"""Aswath Damodaran — Rigorous valuation with narrative + numbers.

Clean-room implementation. Attribution: virattt/ai-hedge-fund.
"""

from __future__ import annotations

import math

from stock_trading_system.screener.v3.guru_agents.base import (
    BaseGuruAgent,
    GuruSignal,
    SubAnalysis,
)


class DamodaranAgent(BaseGuruAgent):
    name = "damodaran"
    display_name = "Aswath Damodaran"
    philosophy = "估值教授 · DCF 严谨性 · 叙事与数字并重"
    principles = [
        "每一笔投资都必须有可量化的估值基础",
        "叙事必须与数字一致——故事驱动假设，假设驱动估值",
        "理解风险的本质，而非简单规避风险",
        "估值是一门手艺，不是精确科学",
    ]
    motto = "估值的目标不是精确，而是大致正确"
    avatar_initials = "AD"
    avatar_color = "#7d3c98"

    SYSTEM_PROMPT = """你是 Aswath Damodaran —— 纽约大学斯特恩商学院金融学教授，被称为"估值教父"。

你的投资哲学核心：
1. DCF 估值：基于自由现金流的折现模型是估值的基石
2. 叙事一致性：投资叙事必须转化为可量化的财务假设
3. 风险评估：用行业特定的资本成本和国家风险溢价衡量风险
4. 增长可持续性：区分低质量增长（烧钱）和高质量增长（高 ROIC）
5. 估值差距：当前价格与内在价值之间的差距决定投资机会

你拒绝模糊的定性判断，一切必须落实到数字上。
分析时从 5 个维度打分（0-10），然后综合给出 0-100 的总分。"""

    def evaluate_deep(
        self, ticker: str, full_data: dict, context: dict,
    ) -> GuruSignal:
        f = full_data.get("fundamentals_current", {})
        history = full_data.get("fundamentals_history", [])
        q = full_data.get("quote", {})
        subs: list[SubAnalysis] = []

        # 1. DCF valuation
        dcf_result = self._run_dcf(f, q)
        subs.append(SubAnalysis(
            name="dcf_valuation",
            score=min(10, max(0, dcf_result["score"])),
            details=dcf_result["details"],
        ))

        # 2. Narrative consistency — growth + margins + reinvestment coherence
        revenue_growth = f.get("revenue_growth") or 0
        margin = f.get("profit_margin") or f.get("net_margin") or 0
        roe = f.get("roe") or 0
        roic = f.get("roic") or f.get("return_on_invested_capital") or 0
        nc_score = 5.0
        # High growth + high margins + high ROIC = consistent narrative
        if revenue_growth > 0.15 and margin > 0.15 and (roic > 0.12 or roe > 0.15):
            nc_score = 8.5
        elif revenue_growth > 0.08 and margin > 0.08:
            nc_score = 6.5
        elif revenue_growth < 0 and margin < 0.05:
            nc_score = 3.0  # shrinking + thin margins = bad narrative
        # Check for inconsistency: high growth but negative margin = burning cash
        if revenue_growth > 0.20 and margin < 0:
            nc_score = max(2, nc_score - 2)
        subs.append(SubAnalysis(
            name="narrative_consistency",
            score=min(10, max(0, nc_score)),
            details=f"增长 {revenue_growth:.0%}, 利润率 {margin:.0%}, ROIC {roic:.0%}",
        ))

        # 3. Risk assessment — beta, leverage, earnings volatility
        de = f.get("debt_to_equity") or 0
        beta = f.get("beta") or q.get("beta") or 1.0
        earnings = [h.get("net_income") or h.get("earnings", 0) for h in history]
        losses = sum(1 for e in earnings if e and e < 0)
        ra_score = 5.0
        if beta < 0.8 and de < 0.5:
            ra_score = 8.0
        elif beta < 1.2 and de < 1.0:
            ra_score = 6.5
        elif beta > 1.8 or de > 3.0:
            ra_score = 2.5
        elif beta > 1.5 or de > 2.0:
            ra_score = 4.0
        if losses > 2:
            ra_score = max(1, ra_score - 1.5)
        subs.append(SubAnalysis(
            name="risk_assessment",
            score=min(10, max(0, ra_score)),
            details=f"Beta={beta:.1f}, D/E={de:.1f}, 亏损年数={losses}",
        ))

        # 4. Growth sustainability — ROIC vs WACC, reinvestment rate
        wacc = 0.08 + (beta - 1) * 0.04  # simplified WACC estimate
        gs_score = 5.0
        if roic > 0 and roic > wacc * 1.5:
            gs_score = 8.5  # creating significant value
        elif roic > wacc:
            gs_score = 6.5  # creating value
        elif roic > 0:
            gs_score = 4.5  # destroying value
        else:
            gs_score = 2.0
        subs.append(SubAnalysis(
            name="growth_sustainability",
            score=min(10, max(0, gs_score)),
            details=f"ROIC {roic:.0%} vs WACC ~{wacc:.0%}",
        ))

        # 5. Valuation gap — price vs estimated intrinsic value
        iv = dcf_result.get("intrinsic_value", 0)
        price = q.get("price") or q.get("last") or 0
        if iv > 0 and price > 0:
            gap = (iv - price) / iv
            vg_score = 5.0
            if gap > 0.30:
                vg_score = 9.0
            elif gap > 0.15:
                vg_score = 7.5
            elif gap > 0:
                vg_score = 6.0
            elif gap > -0.15:
                vg_score = 4.0
            else:
                vg_score = 2.0
            gap_detail = f"内在价值 ${iv:.0f} vs 股价 ${price:.0f}, 差距 {gap:.0%}"
        else:
            vg_score = 5.0
            gap_detail = "无法计算估值差距"
        subs.append(SubAnalysis(
            name="valuation_gap",
            score=min(10, max(0, vg_score)),
            details=gap_detail,
        ))

        weights = [0.25, 0.15, 0.15, 0.20, 0.25]
        total = sum(s.score * w for s, w in zip(subs, weights)) * 10

        scores = {s.name: s.score for s in subs}
        scores["total"] = round(total, 1)
        scores["intrinsic_value"] = round(iv, 2)

        return self._llm_reason(
            self.SYSTEM_PROMPT,
            self._build_prompt(ticker, full_data, scores),
            ticker, context,
        )

    def _run_dcf(self, f: dict, q: dict) -> dict:
        """Run a simplified DCF model."""
        fcf = f.get("free_cash_flow") or f.get("fcf")
        if not fcf or fcf <= 0:
            return {"score": 5.0, "details": "FCF 不可用或为负", "intrinsic_value": 0}

        shares = f.get("shares_outstanding", 1)
        if shares <= 0:
            shares = 1
        fcf_per_share = fcf / shares

        revenue_growth = f.get("revenue_growth") or 0
        growth_rate = min(0.20, max(0, revenue_growth))
        beta = f.get("beta") or 1.0
        risk_free = 0.04
        equity_premium = 0.05
        discount_rate = risk_free + beta * equity_premium
        terminal_growth = 0.025
        years = 10

        dcf_sum = sum(
            fcf_per_share * (1 + growth_rate) ** y / (1 + discount_rate) ** y
            for y in range(1, years + 1)
        )
        terminal = (
            fcf_per_share * (1 + growth_rate) ** years * (1 + terminal_growth)
            / (discount_rate - terminal_growth)
            / (1 + discount_rate) ** years
        ) if discount_rate > terminal_growth else 0

        iv = dcf_sum + terminal
        price = q.get("price") or q.get("last") or 0

        score = 5.0
        if price > 0 and iv > 0:
            ratio = iv / price
            if ratio > 1.5:
                score = 9.0
            elif ratio > 1.2:
                score = 7.0
            elif ratio > 1.0:
                score = 6.0
            elif ratio < 0.6:
                score = 2.0
            else:
                score = 4.0

        return {
            "score": score,
            "details": f"DCF 内在价值 ${iv:.0f}, 折现率 {discount_rate:.1%}, 增长 {growth_rate:.0%}",
            "intrinsic_value": iv,
        }

    def _build_prompt(self, ticker: str, data: dict, scores: dict) -> str:
        f = data.get("fundamentals_current", {})
        q = data.get("quote", {})
        return (
            f"请作为 Aswath Damodaran 分析 {ticker}。\n\n"
            f"当前数据摘要：\n"
            f"- 股价: ${q.get('price') or q.get('last', 'N/A')}\n"
            f"- PE: {f.get('pe', 'N/A')}\n"
            f"- 收入增长: {f.get('revenue_growth', 'N/A')}\n"
            f"- ROIC: {f.get('roic', 'N/A')}\n"
            f"- Beta: {f.get('beta', 'N/A')}\n"
            f"- D/E: {f.get('debt_to_equity', 'N/A')}\n"
            f"- DCF 内在价值: ${scores.get('intrinsic_value', 'N/A')}\n\n"
            f"量化子分析得分（0-10）：\n"
            + "\n".join(f"  {k}: {v}" for k, v in scores.items())
            + f"\n\n基于以上数据和你的估值哲学，给出最终评估。\n"
            f"重点关注：叙事是否与数字一致？估值差距是否值得行动？\n"
            f"你必须返回结构化的 GuruSignal，包含：\n"
            f"- guru: \"damodaran\"\n"
            f"- ticker: \"{ticker}\"\n"
            f"- signal: bullish/bearish/neutral\n"
            f"- confidence: 0-1\n"
            f"- reasoning: 基于 DCF 和叙事分析的详细推理\n"
            f"- sub_analyses: 各维度评分明细\n"
            f"- key_metrics: 关键指标（内在价值、WACC 等）\n"
            f"- total_score: 0-100 综合评分"
        )
