"""Cathie Wood — Disruptive innovation and exponential growth.

Clean-room implementation. Attribution: virattt/ai-hedge-fund.
"""

from __future__ import annotations

from stock_trading_system.screener.v3.guru_agents.base import (
    BaseGuruAgent,
    GuruSignal,
    SubAnalysis,
)


class WoodAgent(BaseGuruAgent):
    name = "wood"
    display_name = "Cathie Wood"
    philosophy = "颠覆式创新 · 指数级增长 · 未来技术"
    principles = [
        "投资于引领颠覆式创新的平台型企业",
        "关注 5 年后的 TAM 而非当前盈利",
        "技术护城河比财务护城河更重要",
        "在 S 曲线拐点之前布局",
    ]
    motto = "创新解决问题"
    avatar_initials = "CW"
    avatar_color = "#e74c3c"

    SYSTEM_PROMPT = """你是 Cathie Wood —— ARK Invest 创始人兼 CEO，专注于颠覆式创新投资。

你的投资哲学核心：
1. 创新评分：企业是否处于颠覆式创新的核心（AI、基因编辑、区块链、能源存储、机器人）
2. TAM 扩张：目标市场是否在指数级扩大
3. 收入增长轨迹：年收入增长 > 30% 是理想目标
4. 技术护城河：专利、数据优势、网络效应、平台锁定
5. 采用曲线：处于 S 曲线的哪个阶段（早期采用者 vs 大众市场）

你愿意为高增长支付高估值，传统估值指标对颠覆式创新不适用。
分析时从 5 个维度打分（0-10），然后综合给出 0-100 的总分。"""

    def evaluate_deep(
        self, ticker: str, full_data: dict, context: dict,
    ) -> GuruSignal:
        f = full_data.get("fundamentals_current", {})
        history = full_data.get("fundamentals_history", [])
        q = full_data.get("quote", {})
        subs: list[SubAnalysis] = []

        # 1. Innovation score — R&D intensity + sector
        rd = f.get("r_and_d") or f.get("research_development") or 0
        rev = f.get("revenue") or 1
        rd_ratio = rd / rev if rev > 0 else 0
        sector = f.get("sector") or ""
        industry = f.get("industry") or ""
        innovation_keywords = (
            "technology", "biotech", "software", "semiconductor", "ai",
            "artificial intelligence", "cloud", "saas", "ev", "electric",
            "genomic", "blockchain", "robotics", "autonomous",
            "科技", "生物", "软件", "半导体", "人工智能", "云", "电动",
        )
        is_innovative = any(
            kw in sector.lower() or kw in industry.lower()
            for kw in innovation_keywords
        )
        inn_score = 5.0
        if rd_ratio > 0.20:
            inn_score += 3
        elif rd_ratio > 0.10:
            inn_score += 2
        elif rd_ratio > 0.05:
            inn_score += 1
        if is_innovative:
            inn_score += 1.5
        subs.append(SubAnalysis(
            name="innovation_score",
            score=min(10, max(0, inn_score)),
            details=f"R&D 占比 {rd_ratio:.1%}, 行业={industry or sector or 'N/A'}",
        ))

        # 2. TAM expansion — revenue acceleration
        revs = [h.get("revenue", 0) for h in history if h.get("revenue")]
        revenue_growth = f.get("revenue_growth") or 0
        if len(revs) >= 3:
            recent_growth = (revs[-1] / revs[-2] - 1) if revs[-2] > 0 else 0
            older_growth = (revs[-2] / revs[-3] - 1) if len(revs) >= 3 and revs[-3] > 0 else 0
            is_accelerating = recent_growth > older_growth
        else:
            recent_growth = revenue_growth
            is_accelerating = False
        tam_score = 5.0
        if revenue_growth > 0.40:
            tam_score = 9.0
        elif revenue_growth > 0.25:
            tam_score = 7.5
        elif revenue_growth > 0.10:
            tam_score = 5.5
        elif revenue_growth < 0:
            tam_score = 2.0
        if is_accelerating:
            tam_score = min(10, tam_score + 1)
        subs.append(SubAnalysis(
            name="tam_expansion",
            score=min(10, max(0, tam_score)),
            details=f"收入增长 {revenue_growth:.0%}, {'加速中' if is_accelerating else '非加速'}",
        ))

        # 3. Revenue growth trajectory
        if len(revs) >= 2 and revs[0] > 0:
            rev_cagr = (revs[-1] / revs[0]) ** (1 / max(1, len(revs) - 1)) - 1
        else:
            rev_cagr = revenue_growth
        rg_score = 5.0
        if rev_cagr > 0.50:
            rg_score = 10.0
        elif rev_cagr > 0.30:
            rg_score = 8.0
        elif rev_cagr > 0.15:
            rg_score = 6.0
        elif rev_cagr < 0:
            rg_score = 2.0
        subs.append(SubAnalysis(
            name="revenue_growth_trajectory",
            score=min(10, max(0, rg_score)),
            details=f"收入 CAGR {rev_cagr:.0%}",
        ))

        # 4. Technology moat — gross margin as proxy for IP value
        gross = f.get("gross_margin") or 0
        tm_score = 5.0
        if gross > 0.70:
            tm_score = 9.0
        elif gross > 0.50:
            tm_score = 7.0
        elif gross > 0.30:
            tm_score = 5.0
        elif gross < 0.20:
            tm_score = 3.0
        if rd_ratio > 0.15:
            tm_score = min(10, tm_score + 1)
        subs.append(SubAnalysis(
            name="technology_moat",
            score=min(10, max(0, tm_score)),
            details=f"毛利率 {gross:.0%}, R&D 强度 {rd_ratio:.1%}",
        ))

        # 5. Adoption curve — market penetration phase
        market_cap = f.get("market_cap") or 0
        ac_score = 5.0
        if revenue_growth > 0.30 and market_cap < 50e9:
            ac_score = 8.0  # early adoption, high growth, not mega-cap yet
        elif revenue_growth > 0.30 and market_cap < 200e9:
            ac_score = 7.0
        elif revenue_growth > 0.15:
            ac_score = 6.0
        elif revenue_growth < 0.05 and market_cap > 100e9:
            ac_score = 3.0  # mature, slowing
        subs.append(SubAnalysis(
            name="adoption_curve",
            score=min(10, max(0, ac_score)),
            details=f"市值 ${market_cap/1e9:.1f}B, 增长 {revenue_growth:.0%}",
        ))

        weights = [0.25, 0.20, 0.25, 0.15, 0.15]
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
            f"请作为 Cathie Wood 分析 {ticker}。\n\n"
            f"当前数据摘要：\n"
            f"- 股价: ${q.get('price') or q.get('last', 'N/A')}\n"
            f"- 收入增长: {f.get('revenue_growth', 'N/A')}\n"
            f"- 毛利率: {f.get('gross_margin', 'N/A')}\n"
            f"- R&D: {f.get('r_and_d') or f.get('research_development', 'N/A')}\n"
            f"- 行业: {f.get('industry') or f.get('sector', 'N/A')}\n\n"
            f"量化子分析得分（0-10）：\n"
            + "\n".join(f"  {k}: {v}" for k, v in scores.items())
            + f"\n\n基于以上数据和你的颠覆式创新投资哲学，给出最终评估。\n"
            f"重点关注：这家企业是否在颠覆式创新的前沿？5 年后的市场规模会是多大？\n"
            f"你必须返回结构化的 GuruSignal，包含：\n"
            f"- guru: \"wood\"\n"
            f"- ticker: \"{ticker}\"\n"
            f"- signal: bullish/bearish/neutral\n"
            f"- confidence: 0-1\n"
            f"- reasoning: 详细的创新分析推理\n"
            f"- sub_analyses: 各维度评分明细\n"
            f"- key_metrics: 关键指标\n"
            f"- total_score: 0-100 综合评分"
        )
