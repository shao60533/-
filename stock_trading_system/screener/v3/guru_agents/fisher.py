"""Philip Fisher — Growth investing with qualitative research.

Clean-room implementation. Attribution: virattt/ai-hedge-fund.
"""

from __future__ import annotations

from stock_trading_system.screener.v3.guru_agents.base import (
    BaseGuruAgent,
    GuruSignal,
    SubAnalysis,
)


class FisherAgent(BaseGuruAgent):
    name = "fisher"
    display_name = "Philip Fisher"
    philosophy = "成长投资 · 深度调研 · 管理层品质"
    principles = [
        "投资于研发驱动的优秀企业",
        "通过 scuttlebutt 方法深入了解公司",
        "利润率持续扩张是卓越管理的标志",
        "优秀公司值得长期持有，不要轻易卖出",
    ]
    motto = "不要过分强调多元化"
    avatar_initials = "PF"
    avatar_color = "#2471a3"

    SYSTEM_PROMPT = """你是 Philip Fisher —— 成长投资之父，著有《怎样选择成长股》（Common Stocks and Uncommon Profits）。

你的投资哲学核心：
1. 成长潜力：寻找未来 5-10 年收入能显著增长的企业
2. 研发投入：R&D 占比反映企业对未来的投入决心
3. 利润率趋势：持续改善的利润率表明管理效率在提高
4. 管理层品质：诚信、远见、执行力缺一不可
5. 竞争优势：产品或服务必须有难以复制的差异化

你会使用 scuttlebutt 方法——通过多个信息源交叉验证企业的真实状况。
分析时从 5 个维度打分（0-10），然后综合给出 0-100 的总分。"""

    def evaluate_deep(
        self, ticker: str, full_data: dict, context: dict,
    ) -> GuruSignal:
        f = full_data.get("fundamentals_current", {})
        history = full_data.get("fundamentals_history", [])
        subs: list[SubAnalysis] = []

        # 1. Growth potential — revenue growth trajectory
        revenue_growth = f.get("revenue_growth") or 0
        revs = [h.get("revenue", 0) for h in history if h.get("revenue")]
        if len(revs) >= 2 and revs[0] > 0:
            rev_cagr = (revs[-1] / revs[0]) ** (1 / max(1, len(revs) - 1)) - 1
        else:
            rev_cagr = revenue_growth
        gp_score = 5.0
        if rev_cagr > 0.20:
            gp_score = 9.0
        elif rev_cagr > 0.10:
            gp_score = 7.0
        elif rev_cagr > 0.05:
            gp_score = 6.0
        elif rev_cagr < 0:
            gp_score = 3.0
        subs.append(SubAnalysis(
            name="growth_potential",
            score=min(10, max(0, gp_score)),
            details=f"收入 CAGR {rev_cagr:.0%}，当期增长 {revenue_growth:.0%}",
        ))

        # 2. R&D investment intensity
        rd = f.get("r_and_d") or f.get("research_development") or 0
        rev = f.get("revenue") or 1
        rd_ratio = rd / rev if rev > 0 else 0
        rd_score = 5.0
        if rd_ratio > 0.15:
            rd_score = 9.0
        elif rd_ratio > 0.08:
            rd_score = 7.0
        elif rd_ratio > 0.03:
            rd_score = 5.5
        elif rd_ratio == 0:
            rd_score = 4.0  # some industries don't have R&D
        subs.append(SubAnalysis(
            name="r_and_d_investment",
            score=min(10, max(0, rd_score)),
            details=f"R&D 占收入 {rd_ratio:.1%}",
        ))

        # 3. Profit margin improvement
        margins = [h.get("profit_margin") or h.get("net_margin", 0) for h in history
                   if h.get("profit_margin") or h.get("net_margin")]
        current_margin = f.get("profit_margin") or f.get("net_margin") or 0
        if len(margins) >= 2:
            margin_trend = margins[-1] - margins[0]
            avg_margin = sum(margins) / len(margins)
        else:
            margin_trend = 0
            avg_margin = current_margin
        pm_score = 5.0
        if avg_margin > 0.20:
            pm_score += 2
        elif avg_margin < 0.05:
            pm_score -= 2
        if margin_trend > 0.03:
            pm_score += 1.5
        elif margin_trend < -0.03:
            pm_score -= 1.5
        subs.append(SubAnalysis(
            name="profit_margins",
            score=min(10, max(0, pm_score)),
            details=f"平均利润率 {avg_margin:.0%}，趋势 {'↑' if margin_trend > 0 else '↓'}",
        ))

        # 4. Management quality — proxy via ROE, FCF, capex discipline
        roe = f.get("roe") or 0
        fcf_margin = f.get("fcf_margin") or f.get("free_cash_flow_margin") or 0
        mq_score = 5.0
        if roe > 0.20:
            mq_score += 2
        elif roe < 0.08:
            mq_score -= 2
        if fcf_margin > 0.15:
            mq_score += 1.5
        elif fcf_margin < 0:
            mq_score -= 1.5
        subs.append(SubAnalysis(
            name="management_quality",
            score=min(10, max(0, mq_score)),
            details=f"ROE {roe:.0%}, FCF margin {fcf_margin:.0%}",
        ))

        # 5. Competitive advantage — gross margin + market position
        gross = f.get("gross_margin") or 0
        market_cap = f.get("market_cap") or 0
        ca_score = 5.0
        if gross > 0.60:
            ca_score += 2.5
        elif gross > 0.40:
            ca_score += 1
        elif gross < 0.20:
            ca_score -= 2
        if market_cap > 10e9:
            ca_score += 0.5
        subs.append(SubAnalysis(
            name="competitive_advantage",
            score=min(10, max(0, ca_score)),
            details=f"毛利率 {gross:.0%}, 市值 ${market_cap/1e9:.1f}B",
        ))

        weights = [0.25, 0.15, 0.20, 0.20, 0.20]
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
            f"请作为 Philip Fisher 分析 {ticker}。\n\n"
            f"当前数据摘要：\n"
            f"- 股价: ${q.get('price') or q.get('last', 'N/A')}\n"
            f"- 收入增长: {f.get('revenue_growth', 'N/A')}\n"
            f"- 毛利率: {f.get('gross_margin', 'N/A')}\n"
            f"- ROE: {f.get('roe', 'N/A')}\n"
            f"- 净利率: {f.get('profit_margin') or f.get('net_margin', 'N/A')}\n\n"
            f"量化子分析得分（0-10）：\n"
            + "\n".join(f"  {k}: {v}" for k, v in scores.items())
            + f"\n\n基于以上数据和你的成长投资哲学，给出最终评估。\n"
            f"你必须返回结构化的 GuruSignal，包含：\n"
            f"- guru: \"fisher\"\n"
            f"- ticker: \"{ticker}\"\n"
            f"- signal: bullish/bearish/neutral\n"
            f"- confidence: 0-1\n"
            f"- reasoning: 用 scuttlebutt 方法深度分析的推理\n"
            f"- sub_analyses: 各维度评分明细\n"
            f"- key_metrics: 关键指标\n"
            f"- total_score: 0-100 综合评分"
        )
