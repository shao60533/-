"""Meta Agent — automated prompt evolution for underperforming agents.

Weekly cycle:
  1. Find worst agent by 30-day rolling Sharpe
  2. Collect evidence (worst calls + best agent's prompt for reference)
  3. Generate improved prompt via LLM (MUTATOR_SYSTEM_PROMPT from atlas-elenchus)
  4. Create A/B paper-trade sessions (reuses existing infrastructure)
  5. After ab_test_days, compare Sharpe → activate or retire

Prompt adopted from atlas-elenchus (github.com/leonbreukelman/atlas-elenchus).
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from stock_trading_system.agents.iterative.agent_scorer import AGENT_MAP, AgentScorer
from stock_trading_system.agents.iterative.config import IterationConfig
from stock_trading_system.agents.iterative.prompt_store import PromptStore
from stock_trading_system.utils import get_logger

logger = get_logger("iterative.meta_agent")

# ── MUTATOR_SYSTEM_PROMPT (adopted from atlas-elenchus) ──────────────────────

MUTATOR_SYSTEM_PROMPT = """You are a prompt engineer specializing in financial analysis agent prompts.

You will receive:
1. An agent's current system prompt
2. Its role and recent performance (rolling Sharpe, hit rate, Darwinian weight)
3. Its worst recent calls with actual market outcomes
4. The best-performing agent's prompt for reference

Your job: produce a TARGETED modification to the prompt.

Rules:
- Make ONE focused change, not a complete rewrite
- Preserve the agent's core role and analytical framework
- Add specificity where the prompt is vague
- Add decision criteria where the prompt lacks them
- If the agent has a pattern of false positives, add confirmation requirements
- If the agent misses obvious signals, add detection criteria

Output format:
---NEW_PROMPT---
(complete modified prompt)
---END_PROMPT---
---REASONING---
(explanation of what you changed and why, referencing specific bad calls)
"""

# ── Display names for mutation context ───────────────────────────────────────

_AGENT_ROLES: dict[str, str] = {
    "market_analyst":       "Market Analyst (technical indicators & price action)",
    "sentiment_analyst":    "Sentiment Analyst (social media & public sentiment)",
    "news_analyst":         "News Analyst (macro news & company-specific events)",
    "fundamentals_analyst": "Fundamentals Analyst (financial statements & valuation)",
    "bull_researcher":      "Bull Researcher (advocates for buying)",
    "bear_researcher":      "Bear Researcher (advocates for selling)",
    "trader":               "Trader (final transaction proposal)",
}


class MetaAgent:
    """Orchestrates prompt evolution: find worst → mutate → A/B test → settle."""

    def __init__(
        self,
        scorer: AgentScorer,
        prompt_store: PromptStore,
        config: IterationConfig,
        llm_call: callable | None = None,
        session_store: Any | None = None,
    ):
        self._scorer = scorer
        self._prompt_store = prompt_store
        self._config = config
        self._llm_call = llm_call
        self._session_store = session_store

    # ── Weekly mutation run ────────────────────────────────────────────

    def run_weekly(self) -> dict[str, Any]:
        """Execute one mutation cycle.

        Returns a summary dict with keys: worst_agent, best_agent,
        version_id, ab_session_id, baseline_session_id.
        """
        if not self._config.meta.enabled:
            return {"status": "skipped", "reason": "meta.enabled is false"}

        if self._llm_call is None:
            return {"status": "error", "reason": "no LLM callable configured"}

        # Step 1: Find worst and best agents
        metrics = self._scorer.get_all_agent_metrics()
        ranked = sorted(metrics.items(), key=lambda x: x[1]["sharpe"], reverse=True)
        if len(ranked) < 2:
            return {"status": "skipped", "reason": "not enough agent metrics"}

        best_id, best_metrics = ranked[0]
        worst_id, worst_metrics = ranked[-1]

        logger.info("Meta Agent: worst=%s (Sharpe=%.3f), best=%s (Sharpe=%.3f)",
                     worst_id, worst_metrics["sharpe"], best_id, best_metrics["sharpe"])

        # Step 2: Collect evidence
        worst_calls = self._get_worst_calls(worst_id, n=5)
        best_prompt = self._get_current_prompt(best_id)
        worst_prompt = self._get_current_prompt(worst_id)

        # Step 3: Generate improved prompt
        mutation_context = self._build_mutation_context(
            worst_id, worst_metrics, worst_prompt, worst_calls,
            best_id, best_metrics, best_prompt,
        )
        raw_response = self._llm_call(MUTATOR_SYSTEM_PROMPT, mutation_context)
        new_prompt = extract_prompt(raw_response)
        reasoning = extract_reasoning(raw_response)

        if not new_prompt:
            return {"status": "error", "reason": "failed to extract new prompt from LLM response"}

        # Step 4: Determine prompt type based on agent role
        prompt_type = "system_prompt" if worst_id.endswith("_analyst") else "prompt_prefix"

        # Step 5: Save version
        version_id = self._prompt_store.save_version(
            agent_id=worst_id,
            prompt_text=new_prompt,
            prompt_type=prompt_type,
            source="meta_agent",
            reasoning=reasoning,
        )

        # Step 6: Create A/B paper trade sessions (if session_store available)
        ab_session_id = None
        baseline_session_id = None
        if self._session_store:
            try:
                today = datetime.now().strftime("%Y-%m-%d")
                baseline_session_id = self._get_or_create_baseline_session()
                ab_session_id = self._session_store.create_session(
                    name=f"A/B: {worst_id} prompt v{version_id}",
                    mode="live",
                    start_capital=100000,
                    start_date=today,
                    config={"prompt_version_id": version_id, "ab_test": True},
                    auto_track=True,
                )
                self._prompt_store.start_testing(version_id, ab_session_id, baseline_session_id)
            except Exception as e:
                logger.warning("Failed to create A/B sessions: %s", e)

        result = {
            "status": "ok",
            "worst_agent": worst_id,
            "worst_sharpe": worst_metrics["sharpe"],
            "best_agent": best_id,
            "best_sharpe": best_metrics["sharpe"],
            "version_id": version_id,
            "prompt_type": prompt_type,
            "reasoning": reasoning,
            "ab_session_id": ab_session_id,
            "baseline_session_id": baseline_session_id,
        }
        logger.info("Meta Agent mutation complete: %s", result)
        return result

    # ── A/B settlement ────────────────────────────────────────────────

    def settle_ab_tests(self) -> list[dict]:
        """Check all testing versions and settle those past ab_test_days.

        Returns list of settlement results.
        """
        from stock_trading_system.strategy.paper_trader.metrics import compute_session_metrics

        if not self._session_store:
            return []

        testing = self._prompt_store.get_testing_versions()
        results: list[dict] = []

        for version in testing:
            try:
                created = datetime.strptime(version["created_at"], "%Y-%m-%d %H:%M:%S")
            except (ValueError, TypeError):
                continue

            days_elapsed = (datetime.now() - created).days
            if days_elapsed < self._config.meta.ab_test_days:
                continue

            baseline_id = version.get("baseline_session_id")
            test_id = version.get("ab_session_id")
            if not baseline_id or not test_id:
                continue

            # Compute metrics for both sessions (reuse paper trade metrics)
            baseline_trades = self._session_store.list_trades(baseline_id)
            baseline_equity = self._session_store.list_equity(baseline_id)
            test_trades = self._session_store.list_trades(test_id)
            test_equity = self._session_store.list_equity(test_id)

            baseline_metrics = compute_session_metrics(
                baseline_trades, baseline_equity, 100000,
            )
            test_metrics = compute_session_metrics(
                test_trades, test_equity, 100000,
            )

            sharpe_before = baseline_metrics.get("sharpe_ratio", 0)
            sharpe_after = test_metrics.get("sharpe_ratio", 0)

            # atlas-elenchus judgment: sharpe_after > sharpe_before → activate
            self._prompt_store.update_version(
                version["id"],
                sharpe_before=sharpe_before,
                sharpe_after=sharpe_after,
            )

            if sharpe_after > sharpe_before:
                self._prompt_store.activate_version(version["id"])
                decision = "activated"
                logger.info("Prompt v%d activated: Sharpe %.3f → %.3f",
                            version["id"], sharpe_before, sharpe_after)
            else:
                self._prompt_store.retire_version(version["id"])
                decision = "retired"
                logger.info("Prompt v%d retired: no improvement (%.3f → %.3f)",
                            version["id"], sharpe_before, sharpe_after)

            results.append({
                "version_id": version["id"],
                "agent_id": version["agent_id"],
                "decision": decision,
                "sharpe_before": sharpe_before,
                "sharpe_after": sharpe_after,
            })

        return results

    # ── Internal helpers ──────────────────────────────────────────────

    def _get_worst_calls(self, agent_id: str, n: int = 5) -> list[dict]:
        """Get the N worst calls (most wrong direction) for an agent."""
        with self._scorer._get_conn() as conn:
            rows = conn.execute(
                """SELECT ticker, date, signal, return_5d, hit_5d
                   FROM agent_scorecards
                   WHERE agent_id = ? AND return_5d IS NOT NULL AND hit_5d = 0
                   ORDER BY ABS(return_5d) DESC LIMIT ?""",
                (agent_id, n),
            ).fetchall()
        return [dict(r) for r in rows]

    def _get_current_prompt(self, agent_id: str) -> str:
        """Get the active prompt override for an agent, or a placeholder."""
        active = self._prompt_store.get_active_prompt(agent_id)
        if active:
            return active["prompt_text"]
        return f"(default {_AGENT_ROLES.get(agent_id, agent_id)} prompt — no override)"

    def _build_mutation_context(
        self,
        worst_id: str, worst_metrics: dict, worst_prompt: str,
        worst_calls: list[dict],
        best_id: str, best_metrics: dict, best_prompt: str,
    ) -> str:
        calls_text = ""
        for call in worst_calls:
            direction = "correct" if call.get("hit_5d") else "WRONG"
            calls_text += (
                f"  - {call['ticker']} on {call['date']}: "
                f"called {call['signal']}, 5d return was {call.get('return_5d', 'N/A'):.2%} "
                f"({direction})\n"
            )

        return f"""Agent to improve: {_AGENT_ROLES.get(worst_id, worst_id)}
Performance: Sharpe={worst_metrics['sharpe']:.3f}, Hit Rate={worst_metrics['hit_rate']:.1%}, Weight={self._scorer.get_weight(worst_id):.2f}

Current prompt:
{worst_prompt}

Worst recent calls:
{calls_text or '  (no data available)'}

Best-performing agent for reference: {_AGENT_ROLES.get(best_id, best_id)}
Performance: Sharpe={best_metrics['sharpe']:.3f}, Hit Rate={best_metrics['hit_rate']:.1%}
Best agent's prompt:
{best_prompt}
"""

    def _get_or_create_baseline_session(self) -> int:
        """Find or create the baseline A/B session."""
        sessions = self._session_store.list_sessions(limit=50)
        for s in sessions:
            config = s.get("config", {})
            if config.get("ab_baseline") and s.get("status") in ("pending", "running"):
                return s["id"]
        # Create a new baseline
        today = datetime.now().strftime("%Y-%m-%d")
        return self._session_store.create_session(
            name="A/B Baseline (default prompts)",
            mode="live",
            start_capital=100000,
            start_date=today,
            config={"ab_baseline": True},
            auto_track=True,
        )


# ── Prompt extraction helpers ─────────────────────────────────────────────────


def extract_prompt(raw: str) -> str | None:
    """Extract the new prompt from LLM response between markers."""
    match = re.search(
        r"---NEW_PROMPT---\s*(.+?)\s*---END_PROMPT---",
        raw, re.DOTALL,
    )
    if match:
        return match.group(1).strip()
    return None


def extract_reasoning(raw: str) -> str | None:
    """Extract the reasoning section from LLM response."""
    match = re.search(
        r"---REASONING---\s*(.+?)(?:---|$)",
        raw, re.DOTALL,
    )
    if match:
        return match.group(1).strip()
    return None
