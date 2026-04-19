"""Nassim Taleb — Antifragility, tail risk, and barbell strategy.

Clean-room implementation. Attribution: virattt/ai-hedge-fund.
"""

from __future__ import annotations

from stock_trading_system.screener.v3.guru_agents.base import (
    BaseGuruAgent,
    GuruSignal,
    SubAnalysis,
)


class TalebAgent(BaseGuruAgent):
    name = "taleb"
    display_name = "Nassim Taleb"
    philosophy = "反脆弱性 · 尾部风险 · 杠铃策略"
    principles = [
        "反脆弱：在混乱中受益而非受损",
        "用杠铃策略配置——极度安全 + 极度投机",
        "避免中间地带：不要承担无报酬的风险",
        "Skin in the game：管理层必须承担下行风险",
    ]
    motto = "风不能吹灭火，只会让它更旺"
    avatar_initials = "NT"
    avatar_color = "#1c2833"

    SYSTEM_PROMPT = """你是 Nassim Nicholas Taleb —— 《黑天鹅》《反脆弱》《非对称风险》的作者，尾部风险和反脆弱性理论的创始人。

你的投资哲学核心：
1. 脆弱性评分：企业是否依赖特定条件才能生存？高杠杆、单一客户、高固定成本都是脆弱的信号
2. 尾部风险暴露：企业是否暴露于左尾（灾难性下跌）？或者拥有右尾（爆发性上涨）期权？
3. 期权价值：企业结构是否具有凸性（有限下行+无限上行）？
4. Skin in the Game：管理层是否与股东利益一致？是否承担真正的下行风险？
5. 杠铃适配：这只股票适合杠铃策略的哪一端？

你厌恶伪稳定性，寻找在压力下变得更强的企业。
分析时从 5 个维度打分（0-10），然后综合给出 0-100 的总分。"""

    def evaluate_deep(
        self, ticker: str, full_data: dict, context: dict,
    ) -> GuruSignal:
        f = full_data.get("fundamentals_current", {})
        history = full_data.get("fundamentals_history", [])
        q = full_data.get("quote", {})
        subs: list[SubAnalysis] = []

        # 1. Fragility score — low fragility = high score
        de = f.get("debt_to_equity") or 0
        cr = f.get("current_ratio") or 0
        margin = f.get("profit_margin") or f.get("net_margin") or 0
        revenue_concentration = f.get("revenue_concentration") or 0

        fragility = 0  # count fragility signals
        if de > 2.0:
            fragility += 2
        elif de > 1.0:
            fragility += 1
        if cr < 1.0:
            fragility += 1
        if margin < 0.03 and margin >= 0:
            fragility += 1  # thin margins = fragile
        elif margin < 0:
            fragility += 2
        if revenue_concentration > 0.50:
            fragility += 1

        frag_score = max(0, 10 - fragility * 2)
        subs.append(SubAnalysis(
            name="fragility_score",
            score=min(10, max(0, frag_score)),
            details=f"脆弱性信号数={fragility}, D/E={de:.1f}, CR={cr:.1f}, 利润率={margin:.0%}",
        ))

        # 2. Tail risk exposure — volatility + drawdown
        price = q.get("price") or q.get("last") or 0
        high_52w = q.get("52w_high") or q.get("year_high") or q.get("fiftyTwoWeekHigh") or 0
        low_52w = q.get("52w_low") or q.get("year_low") or q.get("fiftyTwoWeekLow") or 0
        beta = f.get("beta") or q.get("beta") or 1.0

        tr_score = 5.0
        if high_52w > 0 and low_52w > 0:
            range_pct = (high_52w - low_52w) / low_52w
            # Extreme range = high tail risk
            if range_pct > 1.0:
                tr_score = 3.0  # very volatile
            elif range_pct > 0.50:
                tr_score = 4.5
            elif range_pct < 0.20:
                tr_score = 7.0  # low volatility, but might be pseudo-stable
            range_detail = f"52周波幅 {range_pct:.0%}"
        else:
            range_detail = "52周数据不足"
        if beta > 2.0:
            tr_score = max(1, tr_score - 2)
        elif beta < 0.5:
            tr_score = min(10, tr_score + 1)
        subs.append(SubAnalysis(
            name="tail_risk_exposure",
            score=min(10, max(0, tr_score)),
            details=f"Beta={beta:.1f}, {range_detail}",
        ))

        # 3. Optionality value — convex payoff profile
        fcf = f.get("free_cash_flow") or f.get("fcf") or 0
        market_cap = f.get("market_cap") or 0
        revenue_growth = f.get("revenue_growth") or 0
        rd = f.get("r_and_d") or f.get("research_development") or 0
        rev = f.get("revenue") or 1
        rd_ratio = rd / rev if rev > 0 else 0

        ov_score = 5.0
        # Net cash + growth + R&D = convex payoff
        if de < 0.3 and revenue_growth > 0.15:
            ov_score += 2  # low risk + high growth = option-like
        if rd_ratio > 0.10:
            ov_score += 1.5  # R&D creates future optionality
        if fcf > 0 and market_cap > 0:
            fcf_yield = fcf / market_cap
            if fcf_yield > 0.08:
                ov_score += 1  # self-funding optionality
        if de > 2.0 and revenue_growth < 0:
            ov_score -= 3  # concave payoff: lots of downside
        subs.append(SubAnalysis(
            name="optionality_value",
            score=min(10, max(0, ov_score)),
            details=f"增长 {revenue_growth:.0%}, R&D 占比 {rd_ratio:.1%}, D/E={de:.1f}",
        ))

        # 4. Skin in the game — insider ownership
        insider_own = f.get("insider_ownership") or f.get("insider_percent")
        sig_score = 5.0
        if insider_own is not None:
            if insider_own > 0.15:
                sig_score = 9.0
            elif insider_own > 0.05:
                sig_score = 7.0
            elif insider_own > 0.01:
                sig_score = 5.0
            else:
                sig_score = 3.0  # no skin in the game
            sig_detail = f"内部人持股 {insider_own:.1%}"
        else:
            sig_detail = "内部人持股数据不可用"
        subs.append(SubAnalysis(
            name="skin_in_the_game",
            score=min(10, max(0, sig_score)),
            details=sig_detail,
        ))

        # 5. Barbell fit — does this stock fit either end of the barbell?
        bb_score = 5.0
        # Safe end: low beta, low debt, high FCF, dividend
        div_yield = f.get("dividend_yield") or 0
        is_safe = beta < 0.8 and de < 0.5 and div_yield > 0.02
        # Speculative end: high growth, high R&D, small cap
        is_speculative = revenue_growth > 0.30 and market_cap < 20e9
        if is_safe:
            bb_score = 8.0
            bb_type = "杠铃安全端"
        elif is_speculative:
            bb_score = 7.5
            bb_type = "杠铃投机端"
        else:
            bb_score = 3.0  # middle ground — Taleb avoids this
            bb_type = "中间地带（Taleb 回避）"
        subs.append(SubAnalysis(
            name="barbell_fit",
            score=min(10, max(0, bb_score)),
            details=bb_type,
        ))

        weights = [0.25, 0.20, 0.20, 0.15, 0.20]
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
            f"请作为 Nassim Taleb 分析 {ticker}。\n\n"
            f"当前数据摘要：\n"
            f"- 股价: ${q.get('price') or q.get('last', 'N/A')}\n"
            f"- Beta: {f.get('beta') or q.get('beta', 'N/A')}\n"
            f"- D/E: {f.get('debt_to_equity', 'N/A')}\n"
            f"- 收入增长: {f.get('revenue_growth', 'N/A')}\n"
            f"- 利润率: {f.get('profit_margin') or f.get('net_margin', 'N/A')}\n\n"
            f"量化子分析得分（0-10）：\n"
            + "\n".join(f"  {k}: {v}" for k, v in scores.items())
            + f"\n\n基于以上数据和你的反脆弱理论，给出最终评估。\n"
            f"重点关注：这家企业是脆弱的、稳健的、还是反脆弱的？\n"
            f"它适合杠铃策略的哪一端？还是危险的中间地带？\n"
            f"你必须返回结构化的 GuruSignal，包含：\n"
            f"- guru: \"taleb\"\n"
            f"- ticker: \"{ticker}\"\n"
            f"- signal: bullish/bearish/neutral\n"
            f"- confidence: 0-1\n"
            f"- reasoning: 基于反脆弱理论的详细推理\n"
            f"- sub_analyses: 各维度评分明细\n"
            f"- key_metrics: 关键指标\n"
            f"- total_score: 0-100 综合评分"
        )
