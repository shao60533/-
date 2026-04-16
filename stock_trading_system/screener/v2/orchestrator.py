"""ScreenerV2 orchestrator — glues together regime, universe, agents, gurus, aggregator.

Run as a TaskManager worker via `screen_v2_worker(params, progress_cb)`.

Flow (see SCREENER_V2_TECH_DESIGN §2.2):
  L1 regime detect
  L2 universe filter
  L3 8 agent parallel score (with shared context)
  L4 guru evaluate (per ticker, per enabled guru)
  L5 aggregate + rank top N
  L6 (optional) multi-perspective debate — Phase 3
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from stock_trading_system.utils import get_logger
from stock_trading_system.screener.v2.regime_detector import RegimeDetector
from stock_trading_system.screener.v2.universe import UniverseFilter
from stock_trading_system.screener.v2.aggregator import Aggregator
from stock_trading_system.screener.v2.data_helper import DataHelper
from stock_trading_system.screener.v2.nl_parser import NLParser, FilterSpec
from stock_trading_system.screener.v2.agents import build_all as build_agents
from stock_trading_system.screener.v2.gurus import build_gurus

logger = get_logger("screener.v2.orchestrator")


class ScreenerV2:
    """Top-level V2 screening orchestrator."""

    def __init__(self, config: dict, local_cache=None):
        self._config = config
        self._cache = local_cache
        self._data = DataHelper(config, local_cache)
        self._regime_detector = RegimeDetector(config, local_cache)
        self._nl_parser = NLParser(config, local_cache)
        self._universe = UniverseFilter(config, data_helper=self._data)
        self._agents = build_agents(config, self._data)
        self._aggregator = Aggregator()

    # ── Public entry ───────────────────────────────────────────────────

    def run(self, params: dict, progress_cb=None) -> dict:
        """Execute one V2 screening run. Returns full result dict."""
        t0 = time.time()
        cb = progress_cb or (lambda *a, **kw: None)

        # L0 — NL parse (new in V1.1)
        nl_query = params.get("nl_query") or ""
        strategy_hint = params.get("strategy") or None
        market_hint = params.get("market") or "us"
        if nl_query.strip():
            cb(3, "AI 解析自然语言查询")
            filter_spec = self._nl_parser.parse(
                nl_query, market_hint=market_hint, strategy_hint=strategy_hint,
            )
        else:
            filter_spec = FilterSpec(
                intent_summary="(未提供 NL 查询，按 market 默认筛选)",
                market=market_hint,
                natural_fallback=[strategy_hint] if strategy_hint else [],
                raw_query="",
            )
        logger.info("FilterSpec: intent='%s' market=%s sectors=%s",
                    filter_spec.intent_summary, filter_spec.market, filter_spec.sectors)

        # L1 — market regime
        cb(8, "市场环境检测")
        regime = self._regime_detector.detect()
        logger.info("Regime: %s (conf=%.2f)", regime.label, regime.confidence)

        # L2 — universe filter (driven by FilterSpec in V1.1)
        max_universe = int(params.get("max_universe", 40))
        cb(12, f"{filter_spec.market.upper()} 宇宙过滤")
        candidates, universe_source = self._universe.filter_by_spec(
            filter_spec, max_universe=max_universe,
        )
        logger.info("Universe (source=%s): %d tickers", universe_source, len(candidates))
        if not candidates:
            return self._empty_result(regime, params, start_ts=t0,
                                       message="宇宙过滤无候选")

        # L3 — 8 agent parallel scoring
        cb(15, f"8 Agent 并行评分（{len(candidates)} 只）")
        ticker_scores = self._parallel_score(candidates, regime, cb)

        # L4 — guru evaluation
        enabled_gurus = params.get("enabled_gurus") or ["buffett", "graham", "lynch", "oneil"]
        cb(82, f"大师哲学匹配（{len(enabled_gurus)} 位）")
        guru_matches = self._score_gurus(candidates, enabled_gurus, regime)

        # Feed guru results into GuruAgent's context so it can aggregate
        guru_context = {"guru_matches": guru_matches}
        for ticker in candidates:
            if ticker in ticker_scores:
                try:
                    guru_score = self._agents["guru"].score(ticker, guru_context)
                    ticker_scores[ticker]["guru"] = guru_score
                except Exception as e:
                    logger.warning("GuruAgent.score(%s) failed: %s", ticker, e)

        # L5 — aggregate + rank
        cb(90, "聚合排名")
        aggregated = {}
        for ticker, agent_scores in ticker_scores.items():
            gurus_for_ticker = guru_matches.get(ticker, {})
            aggregated[ticker] = self._aggregator.aggregate_one(
                agent_scores=agent_scores,
                guru_matches=gurus_for_ticker,
                regime_weights=regime.weights,
                debate_score=None,   # L6 skipped in Phase 1
            )

        final_count = int(params.get("final_count", 5))
        top = self._aggregator.rank(aggregated, top_n=final_count)

        # L5b — enrich with trade plan + name + sector
        cb(95, "生成交易计划")
        top = self._enrich_trade_plan(top)

        duration_ms = int((time.time() - t0) * 1000)
        cb(100, f"完成 · 耗时 {duration_ms/1000:.1f}s")

        return {
            "regime": regime.to_dict(),
            "weights": regime.weights,
            "enabled_gurus": enabled_gurus,
            "filter_spec": filter_spec.to_dict(),
            "universe_source": universe_source,
            "universe_count": len(candidates),
            "scored_count": len(ticker_scores),
            "final_count": len(top),
            "duration_ms": duration_ms,
            "picks": top,
        }

    # ── Internals ──────────────────────────────────────────────────────

    def _parallel_score(self, tickers, regime, cb) -> dict:
        """Run all agents (except 'guru') in parallel per ticker.

        Returns: {ticker -> {agent_name -> AgentScore}}
        """
        # Prepare shared context
        context = {
            "regime_label": regime.label,
            "regime_weights": regime.weights,
        }

        # Build canslim_signals for O'Neil (shared between agents + gurus)
        canslim = self._build_canslim_signals(tickers)
        context["canslim_signals"] = canslim

        results: dict = {t: {} for t in tickers}
        # Agent list excluding guru (guru is computed after gurus)
        agent_names = [n for n in self._agents if n != "guru"]

        # Parallel per agent — each agent scores ALL tickers
        # This allows agent-level caching (e.g. SPY returns fetched once).
        with ThreadPoolExecutor(max_workers=min(len(agent_names), 7)) as pool:
            futures = {
                pool.submit(self._agents[name].score_batch, tickers, context): name
                for name in agent_names
            }
            done = 0
            for f in as_completed(futures):
                name = futures[f]
                try:
                    per_ticker = f.result()
                except Exception as e:
                    logger.error("Agent %s failed batch: %s", name, e)
                    per_ticker = {t: self._agents[name].make_score(0, f"batch error: {e}", {}) for t in tickers}

                for t, s in per_ticker.items():
                    if t in results:
                        results[t][name] = s
                done += 1
                pct = 15 + int(done / len(agent_names) * 65)   # 15→80
                cb(min(pct, 80), f"Agent 完成：{name} ({done}/{len(agent_names)})")
        return results

    def _score_gurus(self, tickers, enabled, regime) -> dict:
        """Compute guru matches for all tickers. Returns {ticker -> {guru_name -> dict}}."""
        gurus = build_gurus(self._config, enabled=enabled)
        if not gurus:
            return {}

        # Fetch fundamentals + CANSLIM signals once
        out: dict = {}
        canslim_signals = self._build_canslim_signals(tickers)
        context = {"regime_label": regime.label, "canslim_signals": canslim_signals}

        for t in tickers:
            fundamentals = self._data.get_fundamentals(t) or {}
            per_guru = {}
            for name, guru in gurus.items():
                try:
                    m = guru.evaluate(t, fundamentals, context)
                    per_guru[name] = m.to_dict()
                except Exception as e:
                    logger.warning("Guru %s for %s failed: %s", name, t, e)
            out[t] = per_guru
        return out

    def _build_canslim_signals(self, tickers) -> dict:
        """Pre-compute N/S/L-style signals used by O'Neil guru."""
        out = {}
        # Fetch SPY once for relative strength check
        try:
            spy_df = self._data.get_bars("SPY", period="6mo", interval="1d")
            spy_6m = self._data.pct_change(spy_df["Close"], 126) if spy_df is not None else None
        except Exception:
            spy_6m = None

        for t in tickers:
            df = self._data.get_bars(t, period="1y", interval="1d")
            if df is None or df.empty:
                out[t] = {}
                continue
            close = df["Close"]
            high_52w = float(close.tail(252).max()) if len(close) >= 252 else float(close.max())
            cur = float(close.iloc[-1])
            near_high = (high_52w - cur) / high_52w < 0.07 if high_52w > 0 else False

            vol_surge = None
            if "Volume" in df and len(df) >= 20:
                avg20 = float(df["Volume"].tail(20).mean())
                today = float(df["Volume"].iloc[-1])
                if avg20 > 0:
                    vol_surge = today / avg20

            rs_leading = False
            stock_6m = self._data.pct_change(close, 126)
            if stock_6m is not None and spy_6m is not None:
                rs_leading = (stock_6m - spy_6m) > 0.10   # outperform SPY by >10% in 6m

            out[t] = {
                "near_52w_high": near_high,
                "volume_surge": vol_surge,
                "rs_leading": rs_leading,
            }
        return out

    def _enrich_trade_plan(self, picks: list[dict]) -> list[dict]:
        """Add trade plan (entry/stop/target/rr) + name/sector to each pick."""
        enriched = []
        for p in picks:
            ticker = p["ticker"]
            f = self._data.get_fundamentals(ticker) or {}
            df = self._data.get_bars(ticker, period="3mo", interval="1d")

            name = f.get("short_name") or ticker
            sector = f.get("sector") or ""

            # Derive trade plan from ATR and recent close
            entry_lo = entry_hi = stop = target = None
            rr = None
            try:
                if df is not None and not df.empty:
                    close = df["Close"]
                    cur = float(close.iloc[-1])
                    # ATR for sizing
                    high = df["High"]; low = df["Low"]
                    tr = (high - low).rolling(14).mean()
                    atr = float(tr.iloc[-1]) if not tr.empty else cur * 0.02

                    entry_lo = round(cur - atr * 0.5, 2)
                    entry_hi = round(cur + atr * 0.3, 2)
                    stop = round(cur - atr * 2.0, 2)
                    target = round(cur + atr * 6.0, 2)
                    if stop > 0 and target > stop:
                        risk = entry_hi - stop
                        reward = target - entry_hi
                        rr = round(reward / risk, 2) if risk > 0 else None
            except Exception as e:
                logger.warning("Trade plan enrich failed for %s: %s", ticker, e)

            # Horizon heuristic based on agent mix
            horizon = self._derive_horizon(p)
            risk_tag = self._derive_risk_tag(p)

            # Build simple bull/bear thesis (Phase 1 simple string concat)
            bull, bear = self._derive_thesis(p)

            enriched.append({
                **p,
                "name": name,
                "sector": sector,
                "horizon": horizon,
                "risk_tag": risk_tag,
                "entry_low": entry_lo,
                "entry_high": entry_hi,
                "stop": stop,
                "target": target,
                "risk_reward": rr,
                "bull_thesis": bull,
                "bear_thesis": bear,
            })
        return enriched

    @staticmethod
    def _derive_horizon(p: dict) -> str:
        agent_scores = p.get("agent_scores", {})
        mom = (agent_scores.get("momentum") or {}).get("score", 50)
        cat = (agent_scores.get("catalyst") or {}).get("score", 50)
        if cat > 75:
            return "1-3 个月"
        if mom > 75:
            return "3-6 个月"
        return "6-12 个月"

    @staticmethod
    def _derive_risk_tag(p: dict) -> str:
        risk_score = (p.get("agent_scores", {}).get("risk") or {}).get("score", 50)
        if risk_score >= 70:
            return "low"
        if risk_score >= 50:
            return "med"
        return "high"

    @staticmethod
    def _derive_thesis(p: dict) -> tuple[str, str]:
        scores = p.get("agent_scores", {})
        strongest = sorted(
            [(n, s.get("score", 0), s.get("rationale", "")) for n, s in scores.items()],
            key=lambda x: -x[1],
        )
        weakest = sorted(
            [(n, s.get("score", 0), s.get("rationale", "")) for n, s in scores.items()],
            key=lambda x: x[1],
        )

        bull_parts = [f"{r[2]}" for r in strongest[:2] if r[2]]
        bear_parts = [f"{r[2]}" for r in weakest[:1] if r[2] and r[1] < 50]

        bull = "；".join(bull_parts) if bull_parts else "综合信号偏多"
        bear = "；".join(bear_parts) if bear_parts else "短期无明显看空信号"
        return bull, bear

    @staticmethod
    def _empty_result(regime, params, start_ts, message=""):
        return {
            "regime": regime.to_dict(),
            "weights": regime.weights,
            "enabled_gurus": params.get("enabled_gurus") or [],
            "universe_count": 0,
            "scored_count": 0,
            "final_count": 0,
            "duration_ms": int((time.time() - start_ts) * 1000),
            "picks": [],
            "message": message,
        }
