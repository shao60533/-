"""Bill Ackman — Activist investing with free cash flow focus.

Clean-room implementation. Attribution: virattt/ai-hedge-fund.
"""

from __future__ import annotations

from stock_trading_system.screener.v3.guru_agents.base import (
    BaseGuruAgent,
    GuruSignal,
    SubAnalysis,
)


class AckmanAgent(BaseGuruAgent):
    name = "ackman"
    display_name = "Bill Ackman"
    philosophy = "激进投资 · 简单商业模式 · 自由现金流"
    principles = [
        "投资简单、可预测、自由现金流充裕的企业",
        "集中持仓，对每笔投资做深入研究",
        "通过积极参与推动管理层改善",
        "寻找有巨大改善空间的被低估企业",
    ]
    motto = "找到伟大的企业，然后帮助它变得更好"
    avatar_initials = "BA"
    avatar_color = "#1f618d"

    SYSTEM_PROMPT = """你是 Bill Ackman —— Pershing Square Capital Management 创始人，著名的激进投资者。

你的投资哲学核心：
1. 商业简单性：只投资你能在一页纸上解释清楚的企业
2. 自由现金流生成：FCF 是企业真正价值的体现，高 FCF yield 是关键
3. 资产负债表：低杠杆、灵活的资本结构
4. 激进投资潜力：管理层或运营是否有改善空间
5. 管理层对齐：管理层利益是否与股东一致（持股、薪酬结构）

你寻找的是有"可行动改善方案"的被低估优质企业。
分析时从 5 个维度打分（0-10），然后综合给出 0-100 的总分。"""

    def evaluate_deep(
        self, ticker: str, full_data: dict, context: dict,
    ) -> GuruSignal:
        f = full_data.get("fundamentals_current", {})
        history = full_data.get("fundamentals_history", [])
        q = full_data.get("quote", {})
        subs: list[SubAnalysis] = []

        # 1. Business simplicity — stable revenue, high margin, predictable
        revenue_growth = f.get("revenue_growth") or 0
        margin = f.get("profit_margin") or f.get("net_margin") or 0
        revs = [h.get("revenue", 0) for h in history if h.get("revenue")]
        if len(revs) >= 3:
            growth_rates = [
                (revs[i] - revs[i - 1]) / abs(revs[i - 1])
                for i in range(1, len(revs)) if revs[i - 1] != 0
            ]
            volatility = (
                sum((g - sum(growth_rates) / len(growth_rates)) ** 2
                    for g in growth_rates) / len(growth_rates)
            ) ** 0.5 if growth_rates else 1.0
        else:
            volatility = 0.5
        bs_score = 5.0
        if margin > 0.15 and volatility < 0.10:
            bs_score = 8.0
        elif margin > 0.10 and volatility < 0.20:
            bs_score = 6.5
        elif margin < 0.05 or volatility > 0.30:
            bs_score = 3.0
        subs.append(SubAnalysis(
            name="business_simplicity",
            score=min(10, max(0, bs_score)),
            details=f"利润率 {margin:.0%}, 收入波动率 {volatility:.0%}",
        ))

        # 2. FCF generation
        fcf = f.get("free_cash_flow") or f.get("fcf") or 0
        market_cap = f.get("market_cap") or 0
        fcf_yield = fcf / market_cap if market_cap > 0 else 0
        fcf_margin = f.get("fcf_margin") or f.get("free_cash_flow_margin") or 0
        fg_score = 5.0
        if fcf_yield > 0.08:
            fg_score += 2.5
        elif fcf_yield > 0.04:
            fg_score += 1
        elif fcf_yield < 0:
            fg_score -= 3
        if fcf_margin > 0.20:
            fg_score += 1.5
        elif fcf_margin > 0.10:
            fg_score += 0.5
        subs.append(SubAnalysis(
            name="fcf_generation",
            score=min(10, max(0, fg_score)),
            details=f"FCF yield {fcf_yield:.1%}, FCF margin {fcf_margin:.0%}",
        ))

        # 3. Balance sheet strength
        de = f.get("debt_to_equity") or 0
        cr = f.get("current_ratio") or 0
        net_debt = f.get("net_debt") or 0
        bl_score = 5.0
        if de < 0.5:
            bl_score += 2
        elif de < 1.0:
            bl_score += 1
        elif de > 3.0:
            bl_score -= 3
        elif de > 2.0:
            bl_score -= 1.5
        if cr > 2.0:
            bl_score += 1
        elif cr < 1.0:
            bl_score -= 1
        subs.append(SubAnalysis(
            name="balance_sheet",
            score=min(10, max(0, bl_score)),
            details=f"D/E={de:.1f}, 流动比率={cr:.1f}",
        ))

        # 4. Activist potential — room for improvement
        roe = f.get("roe") or 0
        gross = f.get("gross_margin") or 0
        # gap between gross and net margin = potential for cost cutting
        margin_gap = gross - margin if gross > 0 and margin >= 0 else 0
        ap_score = 5.0
        if margin_gap > 0.30:
            ap_score += 2  # huge cost-cutting opportunity
        elif margin_gap > 0.15:
            ap_score += 1
        if roe < 0.12 and roe > 0 and de < 1.0:
            ap_score += 1.5  # low leverage + low ROE = fixable
        if fcf_yield > 0.06 and de < 1.0:
            ap_score += 1  # cash-rich + cheap = buyback target
        subs.append(SubAnalysis(
            name="activist_potential",
            score=min(10, max(0, ap_score)),
            details=f"毛利-净利差 {margin_gap:.0%}, ROE {roe:.0%}",
        ))

        # 5. Management alignment — insider ownership proxy
        insider_own = f.get("insider_ownership") or f.get("insider_percent")
        if insider_own is not None:
            ma_score = 5.0
            if insider_own > 0.10:
                ma_score = 8.0
            elif insider_own > 0.03:
                ma_score = 6.5
            elif insider_own < 0.01:
                ma_score = 3.5
            detail = f"内部人持股 {insider_own:.1%}"
        else:
            ma_score = 5.0
            detail = "内部人持股数据不可用"
        subs.append(SubAnalysis(
            name="management_alignment",
            score=min(10, max(0, ma_score)),
            details=detail,
        ))

        weights = [0.15, 0.30, 0.20, 0.20, 0.15]
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
            f"请作为 Bill Ackman 分析 {ticker}。\n\n"
            f"当前数据摘要：\n"
            f"- 股价: ${q.get('price') or q.get('last', 'N/A')}\n"
            f"- 市值: ${f.get('market_cap', 0)/1e9:.1f}B\n"
            f"- FCF: ${f.get('free_cash_flow') or f.get('fcf', 'N/A')}\n"
            f"- D/E: {f.get('debt_to_equity', 'N/A')}\n"
            f"- 净利率: {f.get('profit_margin') or f.get('net_margin', 'N/A')}\n\n"
            f"量化子分析得分（0-10）：\n"
            + "\n".join(f"  {k}: {v}" for k, v in scores.items())
            + f"\n\n基于以上数据和你的激进投资哲学，给出最终评估。\n"
            f"重点关注：这家企业是否有"可行动改善方案"？FCF 生成能力如何？\n"
            f"你必须返回结构化的 GuruSignal，包含：\n"
            f"- guru: \"ackman\"\n"
            f"- ticker: \"{ticker}\"\n"
            f"- signal: bullish/bearish/neutral\n"
            f"- confidence: 0-1\n"
            f"- reasoning: 详细的投资分析推理\n"
            f"- sub_analyses: 各维度评分明细\n"
            f"- key_metrics: 关键指标\n"
            f"- total_score: 0-100 综合评分"
        )
