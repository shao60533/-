#!/usr/bin/env python
"""LangGraph install-health probe — fails LOUD on a corrupted wheel.

Background: pip wheels for ``langgraph-prebuilt`` have repeatedly
landed on developer / Railway disks with the ``.dist-info`` metadata
present but the actual ``langgraph/prebuilt/`` directory MISSING.
``import langgraph.prebuilt`` then ModuleNotFoundError's at runtime,
masking real config errors with a confusing dependency stack.

This script:
  1. Imports ``langgraph.prebuilt`` and asserts ``ToolNode`` exists.
  2. Imports ``tradingagents.graph.trading_graph`` and asserts
     ``TradingAgentsGraph`` exists.
  3. On any failure, prints the suggested ``pip install
     --force-reinstall --no-cache-dir`` command and exits non-zero.

Hooks:
  * Run pre-deploy in CI / Railway nixpacks ``releaseCommand``.
  * Optional `python scripts/check_langgraph_install.py` smoke
    before ``pytest`` in the project Makefile / dev docs.

Usage:
    python scripts/check_langgraph_install.py
    # exit 0 on healthy install
    # exit 1 on broken install (prints fix command)
"""

from __future__ import annotations

import os
import sys


_FIX = (
    "pip install --force-reinstall --no-cache-dir "
    '"langgraph>=1.1.6,<2" "langgraph-prebuilt>=1.0.9,<2"'
)


def main() -> int:
    """Return 0 on healthy, 1 on broken install."""
    failures: list[str] = []

    # 1. langgraph.prebuilt + ToolNode
    try:
        from langgraph.prebuilt import ToolNode  # noqa: F401
    except Exception as e:  # noqa: BLE001
        failures.append(
            f"langgraph.prebuilt.ToolNode import failed: "
            f"{type(e).__name__}: {e}"
        )

    # 2. tradingagents.graph.trading_graph (depends on langgraph.prebuilt)
    try:
        from tradingagents.graph.trading_graph import (  # noqa: F401
            TradingAgentsGraph,
        )
    except Exception as e:  # noqa: BLE001
        # Skip if tradingagents itself isn't installed (some minimal
        # environments — frontend-only CI, etc — won't have it). The
        # real production path always has tradingagents pulled via
        # requirements.txt, so this branch only fires in local
        # frontend-only checkouts.
        msg = str(e)
        if "tradingagents" in msg.lower() and "no module named" in msg.lower():
            print("[check_langgraph_install] tradingagents not installed "
                  "(skipping TradingAgentsGraph check)", file=sys.stderr)
        else:
            failures.append(
                f"tradingagents.graph.trading_graph import failed: "
                f"{type(e).__name__}: {e}"
            )

    if failures:
        print("=" * 70, file=sys.stderr)
        print("LANGGRAPH INSTALL CHECK FAILED", file=sys.stderr)
        print("=" * 70, file=sys.stderr)
        for f in failures:
            print(f"  ✗ {f}", file=sys.stderr)
        print("", file=sys.stderr)
        print("Likely cause: wheel installed dist-info but missing files",
              file=sys.stderr)
        print(f"on disk (e.g. ``ls $(python -c 'import langgraph; "
              f"print(langgraph.__path__[0])')`` doesn't show "
              f"``prebuilt/``).", file=sys.stderr)
        print("", file=sys.stderr)
        print("Fix:", file=sys.stderr)
        print(f"  {_FIX}", file=sys.stderr)
        print("", file=sys.stderr)
        print("Then re-run this script to verify.", file=sys.stderr)
        print("=" * 70, file=sys.stderr)
        return 1

    print("[check_langgraph_install] OK — langgraph.prebuilt.ToolNode "
          "+ tradingagents.graph.TradingAgentsGraph both import cleanly")
    return 0


if __name__ == "__main__":
    sys.exit(main())
