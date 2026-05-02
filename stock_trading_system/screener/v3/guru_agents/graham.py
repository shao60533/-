"""Benjamin Graham — Deep value / net-net / margin of safety.

Clean-room rewrite. Attribution: virattt/ai-hedge-fund.
"""

from __future__ import annotations

from stock_trading_system.screener.v3.guru_agents.base import BaseGuruAgent, GuruSignal, SubAnalysis


class GrahamAgent(BaseGuruAgent):
    name = "graham"
    display_name = "Benjamin Graham"
    philosophy = "深度价值 · 净净股 · 安全边际之父"
    # v1.4 reasoning lead — see BaseGuruAgent.framework_lead.
    framework_lead = "估值（PE/PB/NCAV）/ 资产负债安全 / 安全边际"
    anti_patterns = [
        "PE 超过 15 或 PB 超过 1.5 —— 即便是稳健成长股，也已超出我的纪律线。",
        "当前流动比率低于 1.5 或长期债务超过净流动资产 —— 财务安全不足。",
        "5 年中有任意 1 年的盈利亏损 —— 一致性失败，不进入选股池。",
    ]
    decision_style = [
        "我会问：'当前价格相对清算价值还有多少安全边际？至少 33% 才下手。'",
        "我会问：'这只股票适合防御型还是进取型投资者？我心中的客户是哪类？'",
        "我会问：'如果市场明天闭市 10 年，靠资产负债表能不能扛过去？'",
    ]
    evidence_demands = (
        "reasoning 第二段必须引用以下数字: PE / PB / 当前流动比率 / "
        "长期债务 vs 净流动资产 / NCAV (流动资产 - 全部负债)。"
    )
    principles = ["以低于清算价值买入", "严格的财务安全标准", "分散化降低风险", "市场先生是仆人不是主人"]
    motto = "投资的秘诀在于安全边际"
    avatar_initials = "BG"
    avatar_color = "#2c3e50"

    SYSTEM_PROMPT = """你是 Benjamin Graham —— 价值投资之父，著有《聪明的投资者》和《证券分析》。
你的核心标准：
1. 净流动资产价值（NCAV）：市值 < 净流动资产 × 2/3
2. 盈利稳定性：过去 5 年无亏损
3. 股息记录：至少连续支付股息
4. PE < 15，PB < 1.5，PE × PB < 22.5
5. 债务安全：流动比率 > 2，长期债务 < 净流动资产
6. 盈利增长：5 年复合增长 > 通胀率
分析时从 6 个维度打分（0-10），然后综合 0-100 总分。

"""

    def evaluate_deep(self, ticker: str, full_data: dict, context: dict) -> GuruSignal:
        f = full_data.get("fundamentals_current", {})
        history = full_data.get("fundamentals_history", [])
        q = full_data.get("quote", {})
        subs = []

        # 1. Valuation (PE, PB, PE×PB)
        pe = f.get("pe") or 0
        pb = f.get("pb") or 0
        v_score = 5.0
        if 0 < pe < 15: v_score += 2
        elif pe > 25: v_score -= 2
        if 0 < pb < 1.5: v_score += 1.5
        elif pb > 3: v_score -= 1.5
        if 0 < pe * pb < 22.5: v_score += 1
        subs.append(SubAnalysis(name="valuation", score=min(10, max(0, v_score)),
                                details=f"PE={pe:.1f}, PB={pb:.1f}"))

        # 2. Earnings stability
        earnings = [h.get("net_income", h.get("earnings", 0)) for h in history]
        losses = sum(1 for e in earnings if e and e < 0)
        e_score = 8.0 if not losses else max(2, 8 - losses * 2)
        subs.append(SubAnalysis(name="earnings_stability", score=min(10, max(0, e_score)),
                                details=f"过去 {len(history)} 年 {losses} 年亏损"))

        # 3. Dividend record
        div_yield = f.get("dividend_yield", 0) or 0
        d_score = 7.0 if div_yield > 0.02 else (5.0 if div_yield > 0 else 3.0)
        subs.append(SubAnalysis(name="dividend_record", score=d_score,
                                details=f"股息率 {div_yield:.1%}"))

        # 4. Financial strength
        cr = f.get("current_ratio", 0) or 0
        de = f.get("debt_to_equity", 0) or 0
        fs = 5.0
        if cr > 2: fs += 2
        elif cr < 1: fs -= 2
        if de < 0.5: fs += 1.5
        elif de > 2: fs -= 1.5
        subs.append(SubAnalysis(name="financial_strength", score=min(10, max(0, fs)),
                                details=f"流动比率 {cr:.1f}, D/E {de:.1f}"))

        # 5. NCAV check
        ncav = f.get("ncav") or f.get("net_current_asset_value")
        price = q.get("price") or q.get("last") or 0
        mc = f.get("market_cap", 0) or 0
        if ncav and mc > 0:
            ratio = ncav / mc if mc else 0
            n_score = 9.0 if ratio > 1.5 else (7.0 if ratio > 1 else 4.0)
        else:
            n_score = 5.0
        subs.append(SubAnalysis(name="ncav", score=n_score, details=f"NCAV/MC={ncav or 'N/A'}"))

        # 6. Earnings growth
        revs = [h.get("revenue", 0) for h in history if h.get("revenue")]
        if len(revs) >= 2 and revs[0] > 0:
            cagr = (revs[-1] / revs[0]) ** (1 / max(1, len(revs) - 1)) - 1
        else:
            cagr = 0
        g_score = 5.0 + min(3, max(-3, cagr * 30))
        subs.append(SubAnalysis(name="earnings_growth", score=min(10, max(0, g_score)),
                                details=f"收入 CAGR {cagr:.1%}"))

        weights = [0.25, 0.15, 0.10, 0.20, 0.15, 0.15]
        total = sum(s.score * w for s, w in zip(subs, weights)) * 10
        scores = {s.name: s.score for s in subs}
        scores["total"] = round(total, 1)

        return self._llm_reason(self.SYSTEM_PROMPT,
            self._build_prompt(ticker, full_data, scores), ticker, context)

    def _build_prompt(self, ticker, data, scores):
        f = data.get("fundamentals_current", {})
        return f"分析 {ticker}（Graham 视角）。PE={f.get('pe','N/A')}, PB={f.get('pb','N/A')}, " \
               f"D/E={f.get('debt_to_equity','N/A')}。量化得分: {scores}。" \
               f"返回 GuruSignal（guru='graham', ticker='{ticker}'）。"
