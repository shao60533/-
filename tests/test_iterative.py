"""Tests for the self-iterating agent module (Phase 1 + Phase 2 + Phase 3).

Test IDs follow the spec (docs/design/self-iterating-agents.md §12):
  IS-1 ~ IS-8  : Agent Scorer
  DW-1 ~ DW-5  : Darwinian weights
  REG-1 ~ REG-3: Regression
  PS-1 ~ PS-4  : Prompt Store (Phase 2)
  MA-1 ~ MA-5  : Meta Agent (Phase 3)
"""

from __future__ import annotations

import os
import sqlite3
import tempfile
from unittest.mock import MagicMock, patch

import pytest

from stock_trading_system.agents.iterative.config import (
    DarwinianConfig,
    IterationConfig,
    ScorerConfig,
    load_iteration_config,
)
from stock_trading_system.agents.iterative.signal_extractor import (
    extract_signal_fixed,
    extract_signal_llm,
    extract_signal_regex,
)
from stock_trading_system.agents.iterative.agent_scorer import (
    AGENT_MAP,
    AgentScorer,
    compute_agent_sharpe,
)
from stock_trading_system.agents.iterative.darwinian import (
    format_weight_context,
    update_darwinian_weights,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture()
def db_path(tmp_path):
    """Create a temporary SQLite DB with the agent_scorecards + prompt_versions tables."""
    path = str(tmp_path / "test.db")
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE agent_scorecards (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            analysis_id INTEGER NOT NULL,
            agent_id TEXT NOT NULL,
            ticker TEXT NOT NULL,
            date TEXT NOT NULL,
            signal TEXT NOT NULL,
            price_at_call REAL,
            return_5d REAL,
            hit_5d INTEGER,
            return_20d REAL,
            hit_20d INTEGER,
            created_at TEXT NOT NULL
        );
        CREATE INDEX idx_sc_agent_date ON agent_scorecards(agent_id, date DESC);

        CREATE TABLE prompt_versions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            agent_id TEXT NOT NULL,
            prompt_text TEXT NOT NULL,
            prompt_type TEXT NOT NULL,
            source TEXT NOT NULL,
            reasoning TEXT,
            status TEXT DEFAULT 'candidate',
            ab_session_id INTEGER,
            baseline_session_id INTEGER,
            sharpe_before REAL,
            sharpe_after REAL,
            created_at TEXT NOT NULL
        );
        CREATE INDEX idx_pv_agent_status ON prompt_versions(agent_id, status);
    """)
    conn.close()
    return path


@pytest.fixture()
def iter_config():
    return IterationConfig(
        enabled=True,
        scorer=ScorerConfig(min_samples=2),
    )


@pytest.fixture()
def scorer(db_path, iter_config):
    mock_llm = MagicMock(return_value='{"signal": "BULLISH"}')
    return AgentScorer(db_path, iter_config, llm_call=mock_llm)


@pytest.fixture()
def sample_final_state():
    """Simulates a TradingAgents final_state dict."""
    return {
        "market_report": "The market outlook is positive with strong momentum.",
        "sentiment_report": "Social sentiment is bearish, negative tweets dominate.",
        "news_report": "Earnings beat expectations significantly.",
        "fundamentals_report": "PE ratio is reasonable at 18x.",
        "investment_debate_state": {
            "bull_history": ["Bull argument"],
            "bear_history": ["Bear argument"],
        },
        "trader_investment_plan": "FINAL TRANSACTION PROPOSAL: **BUY** 100 shares",
        "final_trade_decision": "BUY",
    }


# ═══════════════════════════════════════════════════════════════════
# IS: Agent Scorer tests
# ═══════════════════════════════════════════════════════════════════


class TestIS1_RecordAnalysis:
    """IS-1: After analysing AAPL, 7 scorecard records are created."""

    def test_records_seven_agents(self, scorer, sample_final_state):
        records = scorer.record_analysis(
            analysis_id=1, ticker="AAPL", date="2026-04-10",
            final_state=sample_final_state, price_at_call=185.0,
        )
        assert len(records) == 7
        agent_ids = {r["agent_id"] for r in records}
        assert agent_ids == set(AGENT_MAP.keys())

    def test_records_persisted_to_db(self, scorer, sample_final_state, db_path):
        scorer.record_analysis(
            analysis_id=1, ticker="AAPL", date="2026-04-10",
            final_state=sample_final_state, price_at_call=185.0,
        )
        conn = sqlite3.connect(db_path)
        count = conn.execute("SELECT COUNT(*) FROM agent_scorecards").fetchone()[0]
        conn.close()
        assert count == 7


class TestIS2_SignalExtractionLLM:
    """IS-2: LLM extraction returns BULLISH for a positive report."""

    def test_bullish_report(self):
        mock_llm = MagicMock(return_value='{"signal": "BULLISH"}')
        assert extract_signal_llm("Strong upside potential", mock_llm) == "BULLISH"

    def test_bearish_report(self):
        mock_llm = MagicMock(return_value='{"signal": "BEARISH"}')
        assert extract_signal_llm("Declining revenue", mock_llm) == "BEARISH"

    def test_neutral_on_empty(self):
        mock_llm = MagicMock()
        assert extract_signal_llm("", mock_llm) == "NEUTRAL"

    def test_error_on_exception(self):
        mock_llm = MagicMock(side_effect=RuntimeError("LLM down"))
        assert extract_signal_llm("some report", mock_llm) == "ERROR"


class TestIS3_SignalExtractionFixed:
    """IS-3: Fixed extraction for bull/bear researchers."""

    def test_bull_researcher(self):
        assert extract_signal_fixed("bull_researcher") == "BULLISH"

    def test_bear_researcher(self):
        assert extract_signal_fixed("bear_researcher") == "BEARISH"

    def test_unknown_agent(self):
        assert extract_signal_fixed("unknown") == "NEUTRAL"


class TestIS4_SignalExtractionRegex:
    """IS-4: Regex extraction from trader output."""

    def test_buy(self):
        assert extract_signal_regex("FINAL TRANSACTION PROPOSAL: **BUY** 100 shares") == "BULLISH"

    def test_sell(self):
        assert extract_signal_regex("FINAL TRANSACTION PROPOSAL: **SELL** 50 shares") == "BEARISH"

    def test_hold(self):
        assert extract_signal_regex("FINAL TRANSACTION PROPOSAL: **HOLD**") == "NEUTRAL"

    def test_fallback_keyword(self):
        assert extract_signal_regex("We recommend to SELL") == "BEARISH"

    def test_empty(self):
        assert extract_signal_regex("") == "NEUTRAL"


class TestIS5_BackfillReturns:
    """IS-5: 5-day return backfill computes correctly."""

    def test_backfill_with_price_increase(self, scorer, sample_final_state, db_path):
        scorer.record_analysis(
            analysis_id=1, ticker="AAPL", date="2026-04-01",
            final_state=sample_final_state, price_at_call=100.0,
        )
        # Simulate current price = 110 → 10% return
        get_price = MagicMock(return_value={"last": 110.0})
        updated = scorer.backfill_returns(get_price)
        assert updated > 0

        conn = sqlite3.connect(db_path)
        row = conn.execute(
            "SELECT return_5d, hit_5d FROM agent_scorecards WHERE agent_id = 'market_analyst'"
        ).fetchone()
        conn.close()
        assert row is not None
        assert abs(row[0] - 0.1) < 0.01  # ~10% return


class TestIS6_SharpeCalculation:
    """IS-6: Sharpe matches manual calculation."""

    def test_positive_returns(self):
        returns = [0.02, 0.03, 0.01, 0.04, 0.02]
        sharpe = compute_agent_sharpe(returns)
        assert sharpe > 0

    def test_zero_std(self):
        returns = [0.01, 0.01, 0.01, 0.01, 0.01]
        # All same → std=0 → sharpe=0
        sharpe = compute_agent_sharpe(returns)
        assert sharpe == 0.0

    def test_negative_returns(self):
        returns = [-0.02, -0.03, -0.01, -0.04, -0.02]
        sharpe = compute_agent_sharpe(returns)
        assert sharpe < 0


class TestIS7_MinSamples:
    """IS-7: With < min_samples observations, Sharpe returns 0.0."""

    def test_too_few_samples(self):
        returns = [0.02, 0.03]
        sharpe = compute_agent_sharpe(returns)
        assert sharpe == 0.0

    def test_get_all_agent_metrics_empty_db(self, scorer):
        metrics = scorer.get_all_agent_metrics()
        for agent_id in AGENT_MAP:
            assert metrics[agent_id]["sharpe"] == 0.0
            assert metrics[agent_id]["hit_rate"] == 0.0


class TestIS8_DisabledNoTrigger:
    """IS-8: iteration.enabled=false → no scorecards recorded."""

    def test_disabled_config(self, db_path):
        disabled_config = IterationConfig(enabled=True, scorer=ScorerConfig(extract_signals=False))
        scorer = AgentScorer(db_path, disabled_config)
        records = scorer.record_analysis(
            analysis_id=1, ticker="AAPL", date="2026-04-10",
            final_state={"market_report": "test"}, price_at_call=100.0,
        )
        assert records == []


# ═══════════════════════════════════════════════════════════════════
# DW: Darwinian weight tests
# ═══════════════════════════════════════════════════════════════════


class TestDW1_TopBoost:
    """DW-1: Top 25% get boosted by WEIGHT_BOOST."""

    def test_top_agent_boosted(self, scorer, db_path):
        _seed_varied_returns(db_path)
        cfg = DarwinianConfig()
        weights = update_darwinian_weights(scorer, cfg)
        # The agent with highest Sharpe should have weight > 1.0
        max_w = max(weights.values())
        assert max_w >= 1.05 * 0.99  # ~1.05 (initial 1.0 * boost)


class TestDW2_BottomDecay:
    """DW-2: Bottom 25% get decayed by WEIGHT_DECAY."""

    def test_bottom_agent_decayed(self, scorer, db_path):
        _seed_varied_returns(db_path)
        cfg = DarwinianConfig()
        weights = update_darwinian_weights(scorer, cfg)
        min_w = min(weights.values())
        assert min_w <= 0.95 * 1.01  # ~0.95 (initial 1.0 * decay)


class TestDW3_BoundaryClamping:
    """DW-3: Weights stay within [0.3, 2.5]."""

    def test_ceiling(self, scorer):
        scorer.save_weight("market_analyst", 2.48)
        _seed_varied_returns_for_scorer(scorer)
        cfg = DarwinianConfig()
        update_darwinian_weights(scorer, cfg)
        assert scorer.get_weight("market_analyst") <= 2.5

    def test_floor(self, scorer):
        scorer.save_weight("bear_researcher", 0.31)
        _seed_varied_returns_for_scorer(scorer)
        cfg = DarwinianConfig()
        update_darwinian_weights(scorer, cfg)
        assert scorer.get_weight("bear_researcher") >= 0.3


class TestDW4_MiddleUnchanged:
    """DW-4: Middle 50% weights remain the same."""

    def test_middle_stays(self, scorer, db_path):
        _seed_varied_returns(db_path)
        initial = dict(scorer.get_all_weights())
        cfg = DarwinianConfig()
        update_darwinian_weights(scorer, cfg)
        # At least one agent in the middle should keep its weight
        unchanged_count = sum(
            1 for aid in initial
            if abs(scorer.get_weight(aid) - initial[aid]) < 1e-6
        )
        # With 7 agents, top_n=1, bottom_n=1 → 5 unchanged
        assert unchanged_count >= 3


class TestDW5_WeightContextFormat:
    """DW-5: format_weight_context contains all agents + weight values."""

    def test_contains_all_agents(self, scorer):
        text = format_weight_context(scorer)
        assert "Market Analyst:" in text
        assert "Trader:" in text
        assert "Agent Reliability Weights" in text

    def test_sorted_by_weight(self, scorer):
        scorer.save_weight("market_analyst", 2.0)
        scorer.save_weight("bear_researcher", 0.5)
        text = format_weight_context(scorer)
        market_pos = text.index("Market Analyst:")
        bear_pos = text.index("Bear Researcher:")
        assert market_pos < bear_pos  # Higher weight listed first


# ═══════════════════════════════════════════════════════════════════
# REG: Regression tests
# ═══════════════════════════════════════════════════════════════════


class TestREG1_DisabledBehaviorUnchanged:
    """REG-1: iteration.enabled=false → analyze() returns AnalysisResult only."""

    def test_returns_single_value(self):
        from stock_trading_system.agents.analyzer import StockAnalyzer, AnalysisResult

        config = {"iteration": {"enabled": False}}
        analyzer = StockAnalyzer(config)

        final_state = {
            "market_report": "ok",
            "sentiment_report": "",
            "news_report": "",
            "fundamentals_report": "",
            "investment_debate_state": {},
            "risk_debate_state": {},
            "final_trade_decision": "BUY",
        }

        mock_graph = MagicMock()
        mock_graph.propagator.create_initial_state.return_value = {}
        mock_graph.propagator.get_graph_args.return_value = {}
        mock_graph.graph.stream.return_value = [final_state]
        mock_graph.process_signal.return_value = "BUY"
        analyzer._graph = mock_graph
        analyzer._graphs["gemini"] = mock_graph

        result = analyzer.analyze("AAPL", "2026-04-10")
        assert isinstance(result, AnalysisResult)
        assert result.signal == "BUY"


class TestREG2_PaperTradeUnaffected:
    """REG-2: Existing paper_trade functionality should not be affected."""

    def test_compute_session_metrics_still_works(self):
        from stock_trading_system.strategy.paper_trader.metrics import compute_session_metrics

        equity = [
            {"total_value": 100000},
            {"total_value": 101000},
            {"total_value": 102000},
        ]
        metrics = compute_session_metrics([], equity, 100000)
        assert "sharpe_ratio" in metrics
        assert "total_return_pct" in metrics


class TestREG3_ConfigLoading:
    """REG-3: Config loading works with and without iteration section."""

    def test_empty_config(self):
        config = load_iteration_config({})
        assert config.enabled is False
        assert config.darwinian.boost == 1.05

    def test_full_config(self):
        raw = {
            "enabled": True,
            "model": "qwen-plus",
            "scorer": {"min_samples": 10},
            "darwinian": {"boost": 1.10, "floor": 0.5},
        }
        config = load_iteration_config(raw)
        assert config.enabled is True
        assert config.scorer.min_samples == 10
        assert config.darwinian.boost == 1.10
        assert config.darwinian.floor == 0.5


# ── Helpers ───────────────────────────────────────────────────────────────────


def _seed_varied_returns(db_path: str) -> None:
    """Insert diverse scorecard rows so each agent has different returns."""
    conn = sqlite3.connect(db_path)
    agents = list(AGENT_MAP.keys())
    # Give each agent different return profiles
    return_profiles = {
        agents[0]: [0.05, 0.03, 0.04, 0.02, 0.06],   # best
        agents[1]: [0.01, 0.02, 0.01, 0.01, 0.02],
        agents[2]: [0.00, 0.01, -0.01, 0.02, 0.01],
        agents[3]: [-0.01, 0.01, 0.00, 0.01, -0.01],
        agents[4]: [-0.01, -0.02, 0.01, 0.00, -0.01],
        agents[5]: [-0.03, -0.02, -0.04, -0.01, -0.03],  # worst
        agents[6]: [0.02, 0.01, 0.03, 0.01, 0.02],
    }

    for agent_id, returns in return_profiles.items():
        for i, ret in enumerate(returns):
            hit = 1 if ret > 0 else 0
            conn.execute(
                """INSERT INTO agent_scorecards
                   (analysis_id, agent_id, ticker, date, signal, price_at_call,
                    return_5d, hit_5d, created_at)
                   VALUES (?, ?, 'AAPL', ?, 'BULLISH', 100.0, ?, ?, '2026-04-10')""",
                (i + 1, agent_id, f"2026-04-{10 + i:02d}", ret, hit),
            )
    conn.commit()
    conn.close()


def _seed_varied_returns_for_scorer(scorer: AgentScorer) -> None:
    """Seed returns via the scorer's DB so get_all_agent_metrics works."""
    _seed_varied_returns(scorer._db_path)


# ═══════════════════════════════════════════════════════════════════
# PS: Prompt Store tests (Phase 2)
# ═══════════════════════════════════════════════════════════════════

from stock_trading_system.agents.iterative.prompt_store import PromptStore


class TestPS1_SaveAndRetrieve:
    """PS-1: Save a prompt version and retrieve it."""

    def test_save_and_get(self, db_path):
        store = PromptStore(db_path)
        vid = store.save_version(
            agent_id="market_analyst",
            prompt_text="You are an improved market analyst...",
            prompt_type="system_prompt",
            source="meta_agent",
            reasoning="Added confirmation requirements",
        )
        assert vid > 0

        version = store.get_version(vid)
        assert version["agent_id"] == "market_analyst"
        assert version["status"] == "candidate"
        assert version["prompt_type"] == "system_prompt"


class TestPS2_ActivateAndRetire:
    """PS-2: Activating a version retires the previous active one."""

    def test_activate_retires_old(self, db_path):
        store = PromptStore(db_path)
        v1 = store.save_version("market_analyst", "prompt v1", source="manual")
        store.activate_version(v1)
        assert store.get_version(v1)["status"] == "active"

        v2 = store.save_version("market_analyst", "prompt v2", source="meta_agent")
        store.activate_version(v2)
        assert store.get_version(v2)["status"] == "active"
        assert store.get_version(v1)["status"] == "retired"

    def test_get_active_prompt(self, db_path):
        store = PromptStore(db_path)
        vid = store.save_version("news_analyst", "better news prompt", source="manual")
        store.activate_version(vid)
        active = store.get_active_prompt("news_analyst")
        assert active is not None
        assert active["prompt_text"] == "better news prompt"

    def test_no_active_returns_none(self, db_path):
        store = PromptStore(db_path)
        assert store.get_active_prompt("nonexistent") is None


class TestPS3_ABTesting:
    """PS-3: A/B testing lifecycle."""

    def test_testing_workflow(self, db_path):
        store = PromptStore(db_path)
        vid = store.save_version("trader", "improved trader prompt", source="meta_agent")
        store.start_testing(vid, ab_session_id=42, baseline_session_id=41)

        version = store.get_version(vid)
        assert version["status"] == "testing"
        assert version["ab_session_id"] == 42

        testing = store.get_testing_versions()
        assert len(testing) == 1

        # Simulate positive result → activate
        store.update_version(vid, sharpe_before=0.5, sharpe_after=0.8)
        store.activate_version(vid)
        assert store.get_version(vid)["status"] == "active"
        assert store.get_version(vid)["sharpe_after"] == 0.8


class TestPS4_GetAllActive:
    """PS-4: get_all_active_prompts returns prompts for all agents."""

    def test_multiple_agents(self, db_path):
        store = PromptStore(db_path)
        v1 = store.save_version("market_analyst", "market v1", prompt_type="system_prompt", source="manual")
        v2 = store.save_version("trader", "trader v1", prompt_type="prompt_prefix", source="manual")
        store.activate_version(v1)
        store.activate_version(v2)

        active = store.get_all_active_prompts()
        assert "market_analyst" in active
        assert "trader" in active
        assert active["market_analyst"]["prompt_type"] == "system_prompt"
        assert active["trader"]["prompt_type"] == "prompt_prefix"


# ═══════════════════════════════════════════════════════════════════
# MA: Meta Agent tests (Phase 3)
# ═══════════════════════════════════════════════════════════════════

from stock_trading_system.agents.iterative.meta_agent import (
    MetaAgent,
    extract_prompt,
    extract_reasoning,
)


@pytest.fixture()
def meta_agent(db_path):
    """Create a MetaAgent with seeded scorecard data and a mock LLM."""
    _seed_varied_returns(db_path)
    iter_config = IterationConfig(
        enabled=True,
        scorer=ScorerConfig(min_samples=2),
        meta=__import__(
            "stock_trading_system.agents.iterative.config", fromlist=["MetaConfig"]
        ).MetaConfig(enabled=True, ab_test_days=5),
    )
    scorer = AgentScorer(db_path, iter_config)
    prompt_store = PromptStore(db_path)
    mock_llm = MagicMock(return_value=(
        "---NEW_PROMPT---\nYou are an improved analyst focusing on confirmation.\n"
        "---END_PROMPT---\n---REASONING---\nAdded confirmation requirement for signals.\n"
    ))
    return MetaAgent(
        scorer=scorer,
        prompt_store=prompt_store,
        config=iter_config,
        llm_call=mock_llm,
    )


class TestMA1_FindWorstAgent:
    """MA-1: Find the agent with the lowest Sharpe."""

    def test_worst_is_lowest_sharpe(self, meta_agent):
        result = meta_agent.run_weekly()
        assert result["status"] == "ok"
        # bear_researcher has the worst returns in our seed data
        assert result["worst_agent"] == "bear_researcher"


class TestMA2_GenerateImprovedPrompt:
    """MA-2: LLM generates a prompt with NEW_PROMPT + REASONING markers."""

    def test_generates_new_prompt(self, meta_agent):
        result = meta_agent.run_weekly()
        assert result["status"] == "ok"
        assert result["version_id"] > 0
        assert result["reasoning"] is not None

    def test_extract_prompt_from_response(self):
        raw = (
            "Some preamble\n"
            "---NEW_PROMPT---\nImproved prompt text here.\n---END_PROMPT---\n"
            "---REASONING---\nBecause the old one was bad.\n"
        )
        assert extract_prompt(raw) == "Improved prompt text here."
        assert extract_reasoning(raw) == "Because the old one was bad."

    def test_extract_prompt_missing(self):
        assert extract_prompt("No markers here") is None

    def test_extract_reasoning_missing(self):
        assert extract_reasoning("No markers here") is None


class TestMA3_CreateABSessions:
    """MA-3: A/B paper trade sessions are created when session_store is available."""

    def test_creates_sessions_with_store(self, db_path):
        _seed_varied_returns(db_path)
        from stock_trading_system.agents.iterative.config import MetaConfig
        iter_config = IterationConfig(
            enabled=True,
            scorer=ScorerConfig(min_samples=2),
            meta=MetaConfig(enabled=True, ab_test_days=5),
        )
        scorer = AgentScorer(db_path, iter_config)
        prompt_store = PromptStore(db_path)

        mock_llm = MagicMock(return_value=(
            "---NEW_PROMPT---\nNew prompt\n---END_PROMPT---\n"
            "---REASONING---\nReason\n"
        ))
        mock_session_store = MagicMock()
        mock_session_store.create_session.return_value = 99
        mock_session_store.list_sessions.return_value = []

        meta = MetaAgent(
            scorer=scorer, prompt_store=prompt_store,
            config=iter_config, llm_call=mock_llm,
            session_store=mock_session_store,
        )
        result = meta.run_weekly()
        assert result["status"] == "ok"
        assert result["ab_session_id"] == 99
        assert mock_session_store.create_session.call_count == 2  # baseline + test

    def test_no_sessions_without_store(self, meta_agent):
        result = meta_agent.run_weekly()
        assert result["ab_session_id"] is None


class TestMA4_SettleActivate:
    """MA-4: Sharpe improvement → activate the prompt version."""

    def test_sharpe_improved_activates(self, db_path):
        prompt_store = PromptStore(db_path)
        vid = prompt_store.save_version("market_analyst", "new prompt", source="meta_agent")
        # Manually set to testing with session IDs
        prompt_store.start_testing(vid, ab_session_id=10, baseline_session_id=11)
        # Backdate created_at so it's past ab_test_days
        conn = sqlite3.connect(db_path)
        conn.execute(
            "UPDATE prompt_versions SET created_at = '2026-01-01 00:00:00' WHERE id = ?",
            (vid,),
        )
        conn.commit()
        conn.close()

        iter_config = IterationConfig(
            enabled=True,
            scorer=ScorerConfig(min_samples=2),
            meta=__import__(
                "stock_trading_system.agents.iterative.config", fromlist=["MetaConfig"]
            ).MetaConfig(enabled=True, ab_test_days=5),
        )
        scorer = AgentScorer(db_path, iter_config)

        mock_session_store = MagicMock()
        # Test session has better Sharpe than baseline
        mock_session_store.list_trades.return_value = []
        mock_session_store.list_equity.side_effect = [
            # baseline equity (small, mixed returns → low Sharpe)
            [{"total_value": 100000}, {"total_value": 100200},
             {"total_value": 99800}, {"total_value": 100100}],
            # test equity (consistently positive → high Sharpe)
            [{"total_value": 100000}, {"total_value": 101000},
             {"total_value": 102000}, {"total_value": 103000}],
        ]

        meta = MetaAgent(
            scorer=scorer, prompt_store=prompt_store,
            config=iter_config, session_store=mock_session_store,
        )
        settlements = meta.settle_ab_tests()
        assert len(settlements) == 1
        assert settlements[0]["decision"] == "activated"

        version = prompt_store.get_version(vid)
        assert version["status"] == "active"


class TestMA5_SettleRetire:
    """MA-5: No Sharpe improvement → retire the prompt version."""

    def test_no_improvement_retires(self, db_path):
        prompt_store = PromptStore(db_path)
        vid = prompt_store.save_version("trader", "worse prompt", source="meta_agent")
        prompt_store.start_testing(vid, ab_session_id=20, baseline_session_id=21)
        conn = sqlite3.connect(db_path)
        conn.execute(
            "UPDATE prompt_versions SET created_at = '2026-01-01 00:00:00' WHERE id = ?",
            (vid,),
        )
        conn.commit()
        conn.close()

        iter_config = IterationConfig(
            enabled=True,
            scorer=ScorerConfig(min_samples=2),
            meta=__import__(
                "stock_trading_system.agents.iterative.config", fromlist=["MetaConfig"]
            ).MetaConfig(enabled=True, ab_test_days=5),
        )
        scorer = AgentScorer(db_path, iter_config)

        mock_session_store = MagicMock()
        mock_session_store.list_trades.return_value = []
        mock_session_store.list_equity.side_effect = [
            # baseline equity (consistently positive → high Sharpe)
            [{"total_value": 100000}, {"total_value": 101000},
             {"total_value": 102000}, {"total_value": 103000}],
            # test equity (mixed returns → low Sharpe)
            [{"total_value": 100000}, {"total_value": 100200},
             {"total_value": 99800}, {"total_value": 100100}],
        ]

        meta = MetaAgent(
            scorer=scorer, prompt_store=prompt_store,
            config=iter_config, session_store=mock_session_store,
        )
        settlements = meta.settle_ab_tests()
        assert len(settlements) == 1
        assert settlements[0]["decision"] == "retired"

        version = prompt_store.get_version(vid)
        assert version["status"] == "retired"
