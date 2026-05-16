"""hardening-iteration-v1 P4 step-1 — route table parity baseline.

P4 splits ``web/app.py`` (4517 lines, 139 routes) into ~11 Blueprints.
The split MUST preserve every (route URL × HTTP method) pair exactly —
a missed route = 404 in production, an added method = silent breakage.

This suite snapshots the current route table (post-P0-P3) so the
follow-up Blueprint-split PR can diff against the same shape. Any
divergence — added route, removed route, method drift — fails this
test loudly during the split work.

Two pieces:

    * ``test_route_table_snapshot_recorded`` — bootstraps the
      production app and records (rule, methods, endpoint) tuples to
      a fixture file under ``tests/web/_fixtures/route_table.json``.
      Failure mode: a route was added/removed without updating the
      fixture. CI fails so the diff is captured intentionally.

    * ``test_no_duplicate_endpoints`` — defensive against the
      Blueprint-split antipattern of registering the same endpoint
      twice (first the old @app.route stays, then the bp version
      lands). Flask raises in this case but the error is easy to
      miss during a 1000-line PR review.

This is a *baseline*, not a *split-time gate*. The fixture is checked
in. When P4 step-2 lands, it compares the bp-served route set against
this fixture; any drift surfaces in CI before merge.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest


FIXTURE = (
    Path(__file__).resolve().parent
    / "_fixtures"
    / "route_table.json"
)


def _current_routes(app) -> list[dict]:
    """Snapshot of every URL rule the live app carries.

    We strip the auto-generated ``static`` route (every Flask app has
    one) so the diff doesn't churn on test-config differences. The
    method set is sorted for deterministic comparison."""
    out: list[dict] = []
    for rule in app.url_map.iter_rules():
        if rule.endpoint == "static":
            continue
        methods = sorted(
            m for m in (rule.methods or set())
            if m not in ("HEAD", "OPTIONS")
        )
        out.append({
            "rule": str(rule),
            "methods": methods,
            "endpoint": rule.endpoint,
        })
    # Sort by (rule, methods) so two snapshots taken in different
    # registration orders compare equal.
    out.sort(key=lambda r: (r["rule"], ",".join(r["methods"])))
    return out


def test_route_table_snapshot_recorded(app_client):
    """Locks the (rule, methods, endpoint) tuples to a checked-in
    fixture. When P4 step-2 lands, the Blueprint-split app must
    produce exactly the same snapshot.

    First-run / regenerate workflow:
        rm tests/web/_fixtures/route_table.json
        pytest tests/web/test_route_parity.py
        git add tests/web/_fixtures/route_table.json
        git commit
    """
    current = _current_routes(app_client["app"])

    if not FIXTURE.exists():
        FIXTURE.parent.mkdir(parents=True, exist_ok=True)
        FIXTURE.write_text(json.dumps(current, indent=2, ensure_ascii=False))
        pytest.fail(
            f"Route-table fixture created at {FIXTURE.relative_to(FIXTURE.parent.parent.parent)}. "
            f"Re-run the suite to verify; commit the fixture."
        )

    expected = json.loads(FIXTURE.read_text(encoding="utf-8"))
    if current != expected:
        # Build a focused diff so reviewers see exactly which routes drifted.
        cur_set = {(r["rule"], tuple(r["methods"])) for r in current}
        exp_set = {(r["rule"], tuple(r["methods"])) for r in expected}
        added = cur_set - exp_set
        removed = exp_set - cur_set
        msg_lines = ["Route table drifted vs the P4-baseline fixture."]
        if added:
            msg_lines.append("ADDED (in code, not in fixture):")
            for rule, methods in sorted(added):
                msg_lines.append(f"  + {rule}  {list(methods)}")
        if removed:
            msg_lines.append("REMOVED (in fixture, not in code):")
            for rule, methods in sorted(removed):
                msg_lines.append(f"  - {rule}  {list(methods)}")
        msg_lines.append(
            "If this drift is intentional, regenerate the fixture: "
            "rm tests/web/_fixtures/route_table.json && pytest "
            "tests/web/test_route_parity.py"
        )
        pytest.fail("\n".join(msg_lines))


# Pre-existing duplicate endpoints in the monolithic web/app.py — each
# of these is registered against two distinct URL rules (e.g. `index`
# is bound to both ``/`` and ``/dashboard``). Flask accepts this; the
# rule URLs differ even when the endpoint name collides. The P4
# Blueprint split needs to either fold these into one rule with a
# redirect, or rename one of the endpoints. Until then this set is the
# known-good baseline so the P4 split can't accidentally ADD new
# duplicates without us seeing it.
_KNOWN_DUPLICATE_ENDPOINTS = frozenset({
    "analysis_page",
    "backtest_page",
    "index",
    "settings_page",
    "tasks_page_react",
    "tasks_v2_redirect",
})


def test_no_new_duplicate_endpoints(app_client):
    """The Blueprint-split antipattern is registering the same endpoint
    twice. Flask accepts the second registration silently as long as
    the URL rules differ; tracking which endpoints are deliberately
    shared between rules lets us spot new ones the split introduces."""
    app = app_client["app"]
    endpoints = [r.endpoint for r in app.url_map.iter_rules()
                 if r.endpoint != "static"]
    dupes = {e for e in endpoints if endpoints.count(e) > 1}
    new_dupes = dupes - _KNOWN_DUPLICATE_ENDPOINTS
    assert not new_dupes, (
        f"new duplicate endpoints not on the baseline list: {sorted(new_dupes)}. "
        f"If intentional, add to _KNOWN_DUPLICATE_ENDPOINTS; if not, dedupe."
    )


def test_no_route_collides_on_rule_and_method(app_client):
    """A (rule, method) pair must resolve to exactly one endpoint.
    Two views on the same path + method = the second silently
    overrides the first in Flask (after a warning)."""
    seen: dict[tuple[str, str], str] = {}
    collisions: list[str] = []
    for rule in app_client["app"].url_map.iter_rules():
        if rule.endpoint == "static":
            continue
        for method in (rule.methods or set()):
            if method in ("HEAD", "OPTIONS"):
                continue
            key = (str(rule), method)
            prior = seen.get(key)
            if prior and prior != rule.endpoint:
                collisions.append(
                    f"{rule} {method} → both '{prior}' and '{rule.endpoint}'"
                )
            seen[key] = rule.endpoint
    assert not collisions, "\n".join(["route collisions:", *collisions])
