"""Warren Buffett — Value investing with moat analysis.

Clean-room implementation inspired by the virattt/ai-hedge-fund project
(https://github.com/virattt/ai-hedge-fund). Structure, naming, comments,
and prompt text are original. Attribution preserved per engineering principles.

Key analysis dimensions:
1. Fundamental quality (ROE, margins, revenue consistency)
2. Earnings consistency (5-year trend stability)
3. Economic moat (competitive advantage durability)
4. Pricing power (gross margin stability + expansion)
5. Book value growth (compounding shareholder equity)
6. Management quality (capital allocation + FCF generation)
7. Intrinsic value (DCF-based fair value estimate)
8. Margin of safety (discount to intrinsic value)
"""

from __future__ import annotations

import math

from stock_trading_system.screener.v3.guru_agents.base import (
    BaseGuruAgent,
    GuruSignal,
    SubAnalysis,
)


class BuffettAgent(BaseGuruAgent):
    name = "buffett"
    display_name = "Warren Buffett"
    philosophy = "价值投资 · 护城河 · 安全边际"
    # v1.4 reasoning lead — first sentence of ``reasoning`` must conclude
    # on these dimensions (not on theme-fit) so every guru's card reads
    # distinctly in the UI.
    framework_lead = "护城河 / 自由现金流 / 安全边际"
    principles = [
        "寻找具有持久竞争优势的企业",
        "以合理价格购买优秀企业",
        "关注长期自由现金流生成能力",
        "管理层的诚信和能力至关重要",
    ]
    motto = "在别人贪婪时恐惧，在别人恐惧时贪婪"
    avatar_initials = "WB"
    avatar_color = "#1a5276"

    SYSTEM_PROMPT = """你是 Warren Buffett —— 伯克希尔·哈撒韦董事长，当代最伟大的价值投资者。

你的投资哲学核心：
1. 经济护城河：企业必须拥有持久的竞争优势（品牌、网络效应、转换成本、规模经济）
2. 盈利一致性：过去 5 年收入和利润稳定增长，无大幅波动
3. 管理层品质：诚实、节俭、善于资本配置
4. 安全边际：只在价格显著低于内在价值时买入
5. 自由现金流：企业必须是"现金生成机器"
6. 低负债：优先选择负债率低的公司

分析时你会从 8 个维度打分（0-10），然后综合给出 0-100 的总分。
最终输出 bullish / bearish / neutral 和 0-1 信心度。

在本系统中，你的任务不是单独判断一家公司是否优秀，而是判断它是否符合用户指定主题下的投资机会。
如果公司不符合用户主题，应先指出主题不匹配，再按你的投资哲学给出保守结论。
即使公司护城河强，如果它不属于用户指定行业/主题，也不能因为"优秀企业"而给出 bullish。"""

    def evaluate_deep(
        self, ticker: str, full_data: dict, context: dict,
    ) -> GuruSignal:
        fundamentals = full_data.get("fundamentals_current", {})
        history = full_data.get("fundamentals_history", [])
        quote = full_data.get("quote", {})

        sub_analyses = []

        # 1. Fundamental quality
        fund_score = self._analyze_fundamentals(fundamentals)
        sub_analyses.append(fund_score)

        # 2. Earnings consistency
        consistency = self._analyze_consistency(history)
        sub_analyses.append(consistency)

        # 3. Economic moat
        moat = self._analyze_moat(fundamentals)
        sub_analyses.append(moat)

        # 4. Pricing power
        pricing = self._analyze_pricing_power(fundamentals, history)
        sub_analyses.append(pricing)

        # 5. Book value growth
        book = self._analyze_book_value_growth(history)
        sub_analyses.append(book)

        # 6. Management quality
        mgmt = self._analyze_management_quality(fundamentals)
        sub_analyses.append(mgmt)

        # 7. Intrinsic value
        intrinsic = self._calculate_intrinsic_value(fundamentals, quote)
        sub_analyses.append(SubAnalysis(
            name="intrinsic_value",
            score=min(10, max(0, intrinsic.get("score", 5))),
            details=f"DCF 估值 ${intrinsic.get('value', 0):.0f}",
        ))

        # 8. Margin of safety
        mos = self._calculate_margin_of_safety(intrinsic, quote)
        sub_analyses.append(SubAnalysis(
            name="margin_of_safety",
            score=min(10, max(0, mos.get("score", 5))),
            details=f"安全边际 {mos.get('margin', 0):.0%}",
        ))

        # Weighted total
        weights = [0.10, 0.15, 0.20, 0.10, 0.10, 0.10, 0.10, 0.15]
        total = sum(
            s.score * w for s, w in zip(sub_analyses, weights)
        ) * 10  # scale to 0-100

        # Build data summary for LLM reasoning
        scores_summary = {s.name: s.score for s in sub_analyses}
        scores_summary["total"] = round(total, 1)
        scores_summary["intrinsic_value"] = intrinsic.get("value", 0)
        scores_summary["margin_of_safety"] = mos.get("margin", 0)

        user_prompt = self._build_user_prompt(ticker, full_data, scores_summary)
        return self._llm_reason(self.SYSTEM_PROMPT, user_prompt, ticker, context)

    # ── Sub-analysis helpers ──────────────────────────────────────────

    def _analyze_fundamentals(self, f: dict) -> SubAnalysis:
        score = 5.0
        details = []
        roe = f.get("roe")
        if roe is not None:
            if roe > 0.20:
                score += 2
                details.append(f"ROE {roe:.0%} 优秀")
            elif roe > 0.15:
                score += 1
                details.append(f"ROE {roe:.0%} 良好")
            elif roe < 0.08:
                score -= 2
                details.append(f"ROE {roe:.0%} 偏低")

        margin = f.get("profit_margin") or f.get("net_margin")
        if margin is not None:
            if margin > 0.20:
                score += 1.5
                details.append(f"净利率 {margin:.0%} 优秀")
            elif margin < 0.05:
                score -= 1.5
                details.append(f"净利率 {margin:.0%} 偏低")

        return SubAnalysis(
            name="fundamental_quality",
            score=min(10, max(0, score)),
            details="；".join(details) or "数据不足",
        )

    def _analyze_consistency(self, history: list[dict]) -> SubAnalysis:
        if len(history) < 3:
            return SubAnalysis(name="earnings_consistency", score=5.0, details="历史数据不足")
        revenues = [h.get("revenue", 0) for h in history if h.get("revenue")]
        if len(revenues) < 3:
            return SubAnalysis(name="earnings_consistency", score=5.0, details="收入数据不足")
        growth_rates = [
            (revenues[i] - revenues[i - 1]) / abs(revenues[i - 1])
            for i in range(1, len(revenues)) if revenues[i - 1] != 0
        ]
        if not growth_rates:
            return SubAnalysis(name="earnings_consistency", score=5.0, details="无法计算增长率")
        avg_growth = sum(growth_rates) / len(growth_rates)
        volatility = (
            sum((g - avg_growth) ** 2 for g in growth_rates) / len(growth_rates)
        ) ** 0.5
        score = 5.0
        if avg_growth > 0.10:
            score += 2
        elif avg_growth > 0.05:
            score += 1
        elif avg_growth < 0:
            score -= 2
        if volatility < 0.05:
            score += 1.5
        elif volatility > 0.20:
            score -= 1.5
        return SubAnalysis(
            name="earnings_consistency",
            score=min(10, max(0, score)),
            details=f"平均增长 {avg_growth:.1%}，波动率 {volatility:.1%}",
        )

    def _analyze_moat(self, f: dict) -> SubAnalysis:
        score = 5.0
        details = []
        roe = f.get("roe", 0)
        margin = f.get("profit_margin") or f.get("net_margin") or 0
        if roe > 0.20 and margin > 0.15:
            score += 2
            details.append("高 ROE + 高利润率 → 可能有护城河")
        market_cap = f.get("market_cap", 0)
        if market_cap > 100e9:
            score += 1
            details.append("超大型企业，规模优势")
        elif market_cap > 10e9:
            score += 0.5
        return SubAnalysis(
            name="economic_moat",
            score=min(10, max(0, score)),
            details="；".join(details) or "需 LLM 定性判断",
        )

    def _analyze_pricing_power(self, f: dict, history: list[dict]) -> SubAnalysis:
        gross_margins = [h.get("gross_margin", 0) for h in history if h.get("gross_margin")]
        if len(gross_margins) < 2:
            return SubAnalysis(name="pricing_power", score=5.0, details="毛利率数据不足")
        trend = gross_margins[-1] - gross_margins[0]
        avg_gm = sum(gross_margins) / len(gross_margins)
        score = 5.0
        if avg_gm > 0.40:
            score += 2
        if trend > 0:
            score += 1
        elif trend < -0.05:
            score -= 2
        return SubAnalysis(
            name="pricing_power",
            score=min(10, max(0, score)),
            details=f"平均毛利率 {avg_gm:.0%}，趋势 {'↑' if trend > 0 else '↓'}",
        )

    def _analyze_book_value_growth(self, history: list[dict]) -> SubAnalysis:
        bvs = [h.get("book_value_per_share", 0) for h in history if h.get("book_value_per_share")]
        if len(bvs) < 2:
            return SubAnalysis(name="book_value_growth", score=5.0, details="账面价值数据不足")
        cagr = (bvs[-1] / bvs[0]) ** (1 / max(1, len(bvs) - 1)) - 1 if bvs[0] > 0 else 0
        score = 5.0
        if cagr > 0.10:
            score += 2.5
        elif cagr > 0.05:
            score += 1
        elif cagr < 0:
            score -= 2
        return SubAnalysis(
            name="book_value_growth",
            score=min(10, max(0, score)),
            details=f"账面价值 CAGR {cagr:.1%}",
        )

    def _analyze_management_quality(self, f: dict) -> SubAnalysis:
        score = 5.0
        details = []
        fcf_margin = f.get("fcf_margin") or f.get("free_cash_flow_margin")
        if fcf_margin is not None:
            if fcf_margin > 0.15:
                score += 2
                details.append(f"FCF margin {fcf_margin:.0%} 优秀")
            elif fcf_margin < 0:
                score -= 2
                details.append("FCF 为负")
        de = f.get("debt_to_equity")
        if de is not None:
            if de < 0.5:
                score += 1
                details.append(f"低负债 D/E={de:.1f}")
            elif de > 2.0:
                score -= 1.5
                details.append(f"高负债 D/E={de:.1f}")
        return SubAnalysis(
            name="management_quality",
            score=min(10, max(0, score)),
            details="；".join(details) or "数据不足",
        )

    def _calculate_intrinsic_value(self, f: dict, quote: dict) -> dict:
        fcf = f.get("free_cash_flow") or f.get("fcf")
        if not fcf or fcf <= 0:
            return {"value": 0, "score": 5.0}
        shares = f.get("shares_outstanding", 1)
        if shares <= 0:
            shares = 1
        fcf_per_share = fcf / shares
        growth_rate = min(0.15, max(0, f.get("revenue_growth", 0.05)))
        discount_rate = 0.10
        terminal_multiple = 15
        years = 10
        dcf_sum = sum(
            fcf_per_share * (1 + growth_rate) ** y / (1 + discount_rate) ** y
            for y in range(1, years + 1)
        )
        terminal = (fcf_per_share * (1 + growth_rate) ** years * terminal_multiple
                     / (1 + discount_rate) ** years)
        iv = dcf_sum + terminal
        price = quote.get("price") or quote.get("last") or quote.get("close") or 0
        score = 5.0
        if price > 0 and iv > 0:
            ratio = iv / price
            if ratio > 1.3:
                score = 8.0
            elif ratio > 1.0:
                score = 6.5
            elif ratio < 0.7:
                score = 2.0
        return {"value": iv, "score": score}

    def _calculate_margin_of_safety(self, intrinsic: dict, quote: dict) -> dict:
        iv = intrinsic.get("value", 0)
        price = quote.get("price") or quote.get("last") or quote.get("close") or 0
        if iv <= 0 or price <= 0:
            return {"margin": 0, "score": 5.0}
        margin = (iv - price) / iv
        score = 5.0
        if margin > 0.30:
            score = 9.0
        elif margin > 0.15:
            score = 7.0
        elif margin > 0:
            score = 6.0
        elif margin < -0.20:
            score = 2.0
        else:
            score = 4.0
        return {"margin": margin, "score": score}

    def _build_user_prompt(self, ticker: str, data: dict, scores: dict) -> str:
        f = data.get("fundamentals_current", {})
        q = data.get("quote", {})
        return f"""请作为 Warren Buffett 分析 {ticker}。

当前数据摘要：
- 股价: ${q.get('price') or q.get('last', 'N/A')}
- 市值: ${f.get('market_cap', 0)/1e9:.1f}B
- PE: {f.get('pe', 'N/A')}
- ROE: {f.get('roe', 'N/A')}
- 净利率: {f.get('profit_margin') or f.get('net_margin', 'N/A')}
- D/E: {f.get('debt_to_equity', 'N/A')}

量化子分析得分（0-10）：
{chr(10).join(f'  {k}: {v}' for k, v in scores.items())}

基于以上数据和你的投资哲学，给出最终评估。
你必须返回结构化的 GuruSignal，包含：
- guru: "buffett"
- ticker: "{ticker}"
- signal: bullish/bearish/neutral
- confidence: 0-1
- reasoning: 详细的投资分析推理
- sub_analyses: 各维度评分明细
- key_metrics: 关键指标（intrinsic_value, margin_of_safety 等）
- total_score: 0-100 综合评分"""
