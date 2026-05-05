"""Structured-summary state machine.

Single source of truth for what ``rendering_status`` means + how to
derive it from a raw extractor output. Lives outside ``extractor.py``
so the worker / backfill task / API DTO can all import the same
classifier without dragging in the LLM dependency.

States:
    success  — at least one tab dict per non-empty source report; ``None``
               only on tabs whose source content was genuinely empty.
    partial  — at least one tab successfully extracted AND at least one
               failed (extracted=None despite source content present).
    failed   — every tab is missing or None despite content being
               present (LLM down, structured-output validation failed,
               etc.).
    empty    — extractor wasn't called at all (skipped on quick depth)
               or rendering input dict is empty/None. Different from
               "failed" because there's nothing to retry against.
    pending  — DB column default. Used while a row sits in the queue
               before the extractor runs (e.g. a fresh row inserted by
               the worker before the post-save hook runs).
"""

from __future__ import annotations

from typing import Any, Iterable


_TAB_KEYS: tuple[str, ...] = (
    "summary", "Market", "Sentiment", "News",
    "Fundamentals", "Investment Debate", "Risk Assessment", "Decision",
)


def _has_content(value: Any) -> bool:
    """A tab counts as ``extracted`` when its value is a non-empty dict
    (the extractor already returns ``None`` for tabs with no source
    text and ``{...}`` for everything else)."""
    return isinstance(value, dict) and bool(value)


def available_tabs(rendering: dict | None) -> list[str]:
    """List of tab keys whose extraction is non-empty. Order matches
    ``_TAB_KEYS`` so the UI renders a stable badge sequence."""
    if not isinstance(rendering, dict):
        return []
    return [k for k in _TAB_KEYS if _has_content(rendering.get(k))]


def classify(
    rendering: dict | None,
    *,
    source_tabs_present: Iterable[str] | None = None,
) -> tuple[str, str | None]:
    """Return ``(status, error_summary)``.

    Parameters
    ----------
    rendering:
        The dict the extractor emitted (or ``None`` / ``{}``). The
        normal v1.6 shape is ``{tab_key: dict|None}``.
    source_tabs_present:
        Optional list of tab keys whose source markdown / state was
        non-empty. When supplied we can distinguish *"failed because
        the LLM didn't return JSON"* (source had content but extracted
        is None) from *"empty because the analyzer didn't write a
        report"* (source itself was empty). When omitted, we assume
        every tab in ``_TAB_KEYS`` had source content — the
        conservative reading for new analyses.
    """
    if not rendering or not isinstance(rendering, dict):
        return "empty", None

    sources = (
        set(source_tabs_present) if source_tabs_present is not None
        else set(_TAB_KEYS)
    )
    extracted = [k for k in _TAB_KEYS if _has_content(rendering.get(k))]
    expected = [k for k in _TAB_KEYS if k in sources]

    # No expected sources at all — nothing to extract from. Classify as
    # ``empty`` rather than ``failed`` so retries don't burn tokens on
    # an empty input.
    if not expected:
        return "empty", None

    # Every expected tab extracted → success.
    missing = [k for k in expected if k not in extracted]
    if not missing:
        return "success", None

    # Some extracted, some missing → partial.
    if extracted:
        # Truncate the missing list so the error column stays small.
        # No report bodies leak; just the structural tab keys.
        return "partial", f"missing tabs: {', '.join(missing)}"

    # Nothing extracted but sources existed → genuine extraction failure.
    return "failed", f"all {len(expected)} tabs failed extraction"
