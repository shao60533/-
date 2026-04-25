"""Charlie Munger — Quality investing with mental models.

Clean-room implementation. Attribution: virattt/ai-hedge-fund.
"""

from __future__ import annotations

from stock_trading_system.screener.v3.guru_agents.base import (
    BaseGuruAgent,
    GuruSignal,
    SubAnalysis,
)


class MungerAgent(BaseGuruAgent):
    name = "munger"
    display_name = "Charlie Munger"
    philosophy = "多元思维模型 · 质量优先 · 持久竞争优势"
    principles = [
        "宁愿以合理价格买入优秀企业，也不以便宜价格买入平庸企业",
        "用跨学科思维模型避免认知偏差",
        "寻找具有持久竞争优势的简单企业",
        "避免你不理解的复杂交易",
    ]
    motto = "反过来想，总是反过来想"
    avatar_initials = "CM"
    avatar_color = "#6c3483"

    SYSTEM_PROMPT = """你是 Charlie Munger —— 伯克希尔·哈撒韦副董事长，多元思维模型的倡导者。

你的投资哲学核心：
1. 质量溢价：优秀企业值得支付合理溢价，低质量便宜货是价值陷阱
2. 管理层诚信：只投资由诚实、有能力的人经营的企业
3. 竞争地位：企业必须拥有难以复制的结构性优势
4. 避免复杂性：只投资你能理解的简单商业模式
5. 定价权：伟大的企业拥有提价而不流失客户的能力

分析时从 5 个维度打分（0-10），然后综合给出 0-100 的总分。
最终输出 bullish / bearish / neutral 和 0-1 信心度。
用多元思维模型（心理学、经济学、物理学、生物学）交叉验证你的结论。"""

    def evaluate_deep(
        self, ticker: str, full_data: dict, context: dict,
    ) -> GuruSignal:
        f = full_data.get("fundamentals_current", {})
        history = full_data.get("fundamentals_history", [])
        subs: list[SubAnalysis] = []

        # 1. Quality premium — high ROE + high margins = quality business
        roe = f.get("roe") or 0
        margin = f.get("profit_margin") or f.get("net_margin") or 0
        q_score = 5.0
        if roe > 0.20 and margin > 0.15:
            q_score = 9.0
        elif roe > 0.15 and margin > 0.10:
            q_score = 7.0
        elif roe < 0.08 or margin < 0.03:
            q_score = 3.0
        subs.append(SubAnalysis(
            name="quality_premium",
            score=min(10, max(0, q_score)),
            details=f"ROE {roe:.0%}, 净利率 {margin:.0%}",
        ))

        # 2. Management integrity — low debt, high FCF, sensible capex
        de = f.get("debt_to_equity") or 0
        fcf_margin = f.get("fcf_margin") or f.get("free_cash_flow_margin") or 0
        m_score = 5.0
        if de < 0.5:
            m_score += 1.5
        elif de > 2.0:
            m_score -= 2
        if fcf_margin > 0.15:
            m_score += 2
        elif fcf_margin < 0:
            m_score -= 2
        subs.append(SubAnalysis(
            name="management_integrity",
            score=min(10, max(0, m_score)),
            details=f"D/E {de:.1f}, FCF margin {fcf_margin:.0%}",
        ))

        # 3. Competitive position — margins + scale
        gross = f.get("gross_margin") or 0
        market_cap = f.get("market_cap") or 0
        c_score = 5.0
        if gross > 0.50:
            c_score += 2
        elif gross > 0.30:
            c_score += 1
        elif gross < 0.15:
            c_score -= 2
        if market_cap > 50e9:
            c_score += 1
        subs.append(SubAnalysis(
            name="competitive_position",
            score=min(10, max(0, c_score)),
            details=f"毛利率 {gross:.0%}, 市值 ${market_cap/1e9:.1f}B",
        ))

        # 4. Avoid complexity — penalize highly leveraged or opaque businesses
        complexity_score = 7.0
        if de > 3.0:
            complexity_score -= 3
        if f.get("sector") in ("Financials", "金融"):
            complexity_score -= 1  # inherently complex
        if margin < 0:
            complexity_score -= 2
        subs.append(SubAnalysis(
            name="avoid_complexity",
            score=min(10, max(0, complexity_score)),
            details=f"D/E {de:.1f}, 负利润={'是' if margin < 0 else '否'}",
        ))

        # 5. Pricing power — stable/expanding gross margins over time
        gross_margins = [h.get("gross_margin", 0) for h in history if h.get("gross_margin")]
        if len(gross_margins) >= 2:
            trend = gross_margins[-1] - gross_margins[0]
            avg_gm = sum(gross_margins) / len(gross_margins)
            p_score = 5.0
            if avg_gm > 0.40:
                p_score += 2
            if trend > 0.02:
                p_score += 1.5
            elif trend < -0.05:
                p_score -= 2
        else:
            p_score = 5.0
            avg_gm = gross
            trend = 0
        subs.append(SubAnalysis(
            name="pricing_power",
            score=min(10, max(0, p_score)),
            details=f"平均毛利率 {avg_gm:.0%}, 趋势 {'↑' if trend > 0 else '↓' if trend < 0 else '→'}",
        ))

        weights = [0.25, 0.20, 0.25, 0.10, 0.20]
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
            f"请作为 Charlie Munger 分析 {ticker}。\n\n"
            f"当前数据摘要：\n"
            f"- 股价: ${q.get('price') or q.get('last', 'N/A')}\n"
            f"- ROE: {f.get('roe', 'N/A')}\n"
            f"- 净利率: {f.get('profit_margin') or f.get('net_margin', 'N/A')}\n"
            f"- 毛利率: {f.get('gross_margin', 'N/A')}\n"
            f"- D/E: {f.get('debt_to_equity', 'N/A')}\n\n"
            f"量化子分析得分（0-10）：\n"
            + "\n".join(f"  {k}: {v}" for k, v in scores.items())
            + f"\n\n基于以上数据和你的投资哲学，给出最终评估。\n"
            f"你必须返回结构化的 GuruSignal，包含：\n"
            f"- guru: \"munger\"\n"
            f"- ticker: \"{ticker}\"\n"
            f"- signal: bullish/bearish/neutral\n"
            f"- confidence: 0-1\n"
            f"- reasoning: 用多元思维模型分析的详细推理\n"
            f"- sub_analyses: 各维度评分明细\n"
            f"- key_metrics: 关键指标\n"
            f"- total_score: 0-100 综合评分"
        )
