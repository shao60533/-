"""Stanley Druckenmiller — Macro momentum and asymmetric bets.

Clean-room implementation. Attribution: virattt/ai-hedge-fund.
"""

from __future__ import annotations

from stock_trading_system.screener.v3.guru_agents.base import (
    BaseGuruAgent,
    GuruSignal,
    SubAnalysis,
)


class DruckenmillerAgent(BaseGuruAgent):
    name = "druckenmiller"
    display_name = "Stanley Druckenmiller"
    philosophy = "宏观动量 · 非对称押注 · 趋势跟踪"
    principles = [
        "判断对的时候要大胆下注",
        "关注宏观经济周期和流动性环境",
        "趋势是你的朋友，直到它结束",
        "风险回报比至少 3:1 才值得出手",
    ]
    motto = "保护好资本，然后在大机会出现时全力出击"
    avatar_initials = "SD"
    avatar_color = "#2c3e50"

    SYSTEM_PROMPT = """你是 Stanley Druckenmiller —— 传奇宏观对冲基金经理，30 年无亏损年份的记录保持者。

你的投资哲学核心：
1. 宏观对齐：企业是否处于有利的宏观经济环境中
2. 动量信号：价格和基本面动量是否一致向上
3. 风险回报比：不对称的风险收益是关键，下行有限+上行巨大
4. 仓位规模信号：高信心时集中下注，低信心时轻仓
5. 催化剂时机：催化剂是否即将到来（财报、政策、产品发布）

你不追求精确的底部或顶部，而是在趋势确认后果断行动。
分析时从 5 个维度打分（0-10），然后综合给出 0-100 的总分。"""

    def evaluate_deep(
        self, ticker: str, full_data: dict, context: dict,
    ) -> GuruSignal:
        f = full_data.get("fundamentals_current", {})
        history = full_data.get("fundamentals_history", [])
        q = full_data.get("quote", {})
        technicals = full_data.get("technicals", {})
        subs: list[SubAnalysis] = []

        # 1. Macro alignment — revenue growth + sector momentum
        revenue_growth = f.get("revenue_growth") or 0
        earnings_growth = f.get("earnings_growth") or f.get("eps_growth") or 0
        ma_score = 5.0
        if revenue_growth > 0.15 and earnings_growth > 0.15:
            ma_score = 8.5
        elif revenue_growth > 0.08 and earnings_growth > 0.08:
            ma_score = 7.0
        elif revenue_growth < 0 and earnings_growth < 0:
            ma_score = 2.0
        elif revenue_growth < 0 or earnings_growth < 0:
            ma_score = 3.5
        subs.append(SubAnalysis(
            name="macro_alignment",
            score=min(10, max(0, ma_score)),
            details=f"收入增长 {revenue_growth:.0%}, 盈利增长 {earnings_growth:.0%}",
        ))

        # 2. Momentum signal — price relative to moving averages
        price = q.get("price") or q.get("last") or 0
        ma_50 = technicals.get("sma_50") or q.get("sma_50") or 0
        ma_200 = technicals.get("sma_200") or q.get("sma_200") or 0
        ms_score = 5.0
        if price > 0 and ma_50 > 0 and ma_200 > 0:
            if price > ma_50 > ma_200:
                ms_score = 8.5  # strong uptrend
            elif price > ma_200:
                ms_score = 6.5
            elif price < ma_50 < ma_200:
                ms_score = 2.0  # strong downtrend
            else:
                ms_score = 4.0
            momentum_detail = (
                f"价格=${price:.0f}, MA50=${ma_50:.0f}, MA200=${ma_200:.0f}"
            )
        else:
            momentum_detail = "技术指标数据不足"
        subs.append(SubAnalysis(
            name="momentum_signal",
            score=min(10, max(0, ms_score)),
            details=momentum_detail,
        ))

        # 3. Risk-reward ratio — upside vs downside potential
        pe = f.get("pe") or 0
        high_52w = q.get("52w_high") or q.get("year_high") or q.get("fiftyTwoWeekHigh") or 0
        low_52w = q.get("52w_low") or q.get("year_low") or q.get("fiftyTwoWeekLow") or 0
        if price > 0 and high_52w > 0 and low_52w > 0 and low_52w < high_52w:
            upside = (high_52w - price) / price if price > 0 else 0
            downside = (price - low_52w) / price if price > 0 else 0
            rr_ratio = upside / downside if downside > 0.01 else 10
            rr_score = 5.0
            if rr_ratio > 3:
                rr_score = 9.0
            elif rr_ratio > 2:
                rr_score = 7.0
            elif rr_ratio > 1:
                rr_score = 5.5
            elif rr_ratio < 0.5:
                rr_score = 2.0
            rr_detail = f"上行潜力 {upside:.0%} / 下行风险 {downside:.0%} = {rr_ratio:.1f}x"
        else:
            rr_score = 5.0
            rr_detail = "52 周数据不足"
        subs.append(SubAnalysis(
            name="risk_reward_ratio",
            score=min(10, max(0, rr_score)),
            details=rr_detail,
        ))

        # 4. Position sizing signal — conviction based on multiple factors
        fcf_yield = 0
        fcf = f.get("free_cash_flow") or f.get("fcf") or 0
        market_cap = f.get("market_cap") or 0
        if market_cap > 0:
            fcf_yield = fcf / market_cap
        ps_score = 5.0
        strong_signals = 0
        if revenue_growth > 0.10:
            strong_signals += 1
        if ms_score > 7:
            strong_signals += 1
        if fcf_yield > 0.05:
            strong_signals += 1
        if rr_score > 7:
            strong_signals += 1
        ps_score = 3.0 + strong_signals * 1.75
        subs.append(SubAnalysis(
            name="position_sizing_signal",
            score=min(10, max(0, ps_score)),
            details=f"{strong_signals}/4 强信号确认",
        ))

        # 5. Catalyst timing — upcoming events + earnings surprise potential
        eps_surprise = f.get("earnings_surprise") or f.get("eps_surprise")
        ct_score = 5.0
        if eps_surprise is not None:
            if eps_surprise > 0.10:
                ct_score += 2
            elif eps_surprise > 0:
                ct_score += 1
            elif eps_surprise < -0.10:
                ct_score -= 2
            ct_detail = f"盈利惊喜 {eps_surprise:.0%}"
        else:
            ct_detail = "盈利惊喜数据不可用"
        if revenue_growth > 0.20:
            ct_score += 1  # strong growth = potential positive surprise
        subs.append(SubAnalysis(
            name="catalyst_timing",
            score=min(10, max(0, ct_score)),
            details=ct_detail,
        ))

        weights = [0.20, 0.25, 0.25, 0.15, 0.15]
        total = sum(s.score * w for s, w in zip(subs, weights)) * 10

        scores = {s.name: s.score for s in subs}
        scores["total"] = round(total, 1)

        return self._llm_reason(
            self.SYSTEM_PROMPT,
            self._build_prompt(ticker, full_data, scores),
            ticker, context,
        )

    def _build_prompt(self, ticker: str, data: dict, scores: dict) -> str:
        f = data.get("fundamentals_current", {})
        q = data.get("quote", {})
        return (
            f"请作为 Stanley Druckenmiller 分析 {ticker}。\n\n"
            f"当前数据摘要：\n"
            f"- 股价: ${q.get('price') or q.get('last', 'N/A')}\n"
            f"- 收入增长: {f.get('revenue_growth', 'N/A')}\n"
            f"- 盈利增长: {f.get('earnings_growth', 'N/A')}\n"
            f"- 市值: ${f.get('market_cap', 0)/1e9:.1f}B\n\n"
            f"量化子分析得分（0-10）：\n"
            + "\n".join(f"  {k}: {v}" for k, v in scores.items())
            + f"\n\n基于以上数据和你的宏观动量投资哲学，给出最终评估。\n"
            f"重点关注：宏观环境是否有利？风险回报比是否足够不对称？\n"
            f"你必须返回结构化的 GuruSignal，包含：\n"
            f"- guru: \"druckenmiller\"\n"
            f"- ticker: \"{ticker}\"\n"
            f"- signal: bullish/bearish/neutral\n"
            f"- confidence: 0-1\n"
            f"- reasoning: 详细的宏观+动量分析推理\n"
            f"- sub_analyses: 各维度评分明细\n"
            f"- key_metrics: 关键指标\n"
            f"- total_score: 0-100 综合评分"
        )
