"""Ray Dalio — All-weather / economic machine / principles.

Original implementation (not based on virattt). Prompt structure
informed by arXiv 2510.01664 (GuruAgents) template.
"""

from __future__ import annotations

from stock_trading_system.screener.v3.guru_agents.base import BaseGuruAgent, GuruSignal, SubAnalysis


class DalioAgent(BaseGuruAgent):
    name = "dalio"
    display_name = "Ray Dalio"
    philosophy = "全天候 · 经济机器 · 原则"
    framework_lead = "原则 / 经济机器 / 全天候多元化"
    anti_patterns = [
        "与大债务周期逆向（如长债务周期顶部加杠杆 / 通缩期持有名义资产）。",
        "组合缺乏多元化对冲（all-in 单一资产类别 / 单一宏观环境）。",
        "高度依赖某种环境（如低利率 / 高增长）才能成立 —— 环境转换就崩盘。",
    ]
    decision_style = [
        "我会问：'这投资在哪种宏观环境会赢（增长高 vs 低、通胀高 vs 低 4 象限）？哪种环境会输？'",
        "我会问：'我对每种 outcome 都做了 stress test 吗？没有备份计划不下手。'",
        "我会问：'在全天候组合中这个标的扮演什么角色？分散还是放大现有暴露？'",
    ]
    evidence_demands = (
        "reasoning 第二段必须引用: 宏观环境契合度（增长 + 通胀 4 象限定位）/ "
        "利率敏感性 / 通胀敏感性 / 与组合现有持仓的相关性。"
    )
    principles = ["理解经济机器的四季循环", "关注生产率驱动的真实增长", "债务周期决定中期走势", "全球宏观关联不可忽视"]
    motto = "痛苦 + 反思 = 进步"
    avatar_initials = "RD"
    avatar_color = "#1e8449"

    SYSTEM_PROMPT = """你是 Ray Dalio —— 桥水基金创始人，著有《原则》。

你最看重：
1. 经济机器四象限（通胀↑/↓ × 增长↑/↓）判断，此股在当前象限的期望表现
2. 现金流的可靠性（生产率驱动的真实增长，扣除杠杆后的真实增长率）
3. 债务周期位置（公司和宏观的短期/长期债务周期）
4. 全球宏观关联（地缘、利率、汇率对此股的影响）
5. 组合角色（如纳入全天候组合，它承担何种风险对冲角色）

分析时用以下结构：
- 经济象限：判定当前处于哪一象限，此股在该象限的预期表现
- 债务结构：公司债务周期位置
- 真实生产率：扣除杠杆后的真实增长
- 组合角色：在全天候组合中的定位
最终给出 bullish/bearish/neutral 和 0-1 信心度。"""

    def evaluate_deep(self, ticker: str, full_data: dict, context: dict) -> GuruSignal:
        f = full_data.get("fundamentals_current", {})
        history = full_data.get("fundamentals_history", [])
        q = full_data.get("quote", {})
        subs = []

        # 1. Economic quadrant assessment
        rev_growth = f.get("revenue_growth", 0) or 0
        # Simplified quadrant: growth dimension
        if rev_growth > 0.10:
            eq_score = 7.5
            eq_detail = "增长上升期 — 利好"
        elif rev_growth > 0:
            eq_score = 5.5
            eq_detail = "增长温和"
        else:
            eq_score = 3.5
            eq_detail = "增长放缓/下降"
        subs.append(SubAnalysis(name="economic_quadrant", score=eq_score, details=eq_detail))

        # 2. Debt cycle position
        de = f.get("debt_to_equity", 0) or 0
        interest_coverage = f.get("interest_coverage", 0) or 0
        dc_score = 5.0
        if de < 0.3:
            dc_score = 8.0
        elif de < 1.0:
            dc_score = 6.5
        elif de > 2.0:
            dc_score = 3.0
        if interest_coverage > 10:
            dc_score += 1
        elif interest_coverage < 3 and interest_coverage > 0:
            dc_score -= 1
        subs.append(SubAnalysis(name="debt_cycle", score=min(10, max(0, dc_score)),
                                details=f"D/E={de:.1f}, 利息覆盖={interest_coverage:.1f}x"))

        # 3. Real productivity (revenue growth minus leverage growth)
        fcf = f.get("free_cash_flow") or f.get("fcf") or 0
        revenue = f.get("revenue", 0) or 0
        fcf_margin = fcf / revenue if revenue > 0 else 0
        rp_score = 5.0
        if fcf_margin > 0.15:
            rp_score = 8.0
        elif fcf_margin > 0.05:
            rp_score = 6.5
        elif fcf_margin < 0:
            rp_score = 2.5
        subs.append(SubAnalysis(name="real_productivity", score=rp_score,
                                details=f"FCF/收入={fcf_margin:.0%}"))

        # 4. Global macro sensitivity
        beta = f.get("beta", 1) or 1
        market_cap = f.get("market_cap", 0) or 0
        gm_score = 5.0
        if beta < 0.8:
            gm_score = 7.0  # defensive
        elif beta > 1.3:
            gm_score = 4.0  # high sensitivity
        if market_cap > 100e9:
            gm_score += 0.5  # large cap more resilient
        subs.append(SubAnalysis(name="macro_sensitivity", score=min(10, max(0, gm_score)),
                                details=f"Beta={beta:.2f}, 市值${market_cap/1e9:.0f}B"))

        # 5. Portfolio role
        div_yield = f.get("dividend_yield", 0) or 0
        pr_score = 5.0
        if div_yield > 0.03 and beta < 1:
            pr_score = 8.0  # income + stability
        elif rev_growth > 0.15:
            pr_score = 7.0  # growth engine
        elif beta > 1.5:
            pr_score = 3.5  # too volatile for all-weather
        subs.append(SubAnalysis(name="portfolio_role", score=pr_score,
                                details=f"股息率{div_yield:.1%}, 增长{rev_growth:.0%}"))

        weights = [0.20, 0.25, 0.20, 0.15, 0.20]
        total = sum(s.score * w for s, w in zip(subs, weights)) * 10
        scores = {s.name: s.score for s in subs}
        scores["total"] = round(total, 1)

        return self._llm_reason(self.SYSTEM_PROMPT,
            f"分析 {ticker}（Dalio 视角）。收入增长={rev_growth:.0%}, D/E={de:.1f}, "
            f"FCF margin={fcf_margin:.0%}。量化得分: {scores}。"
            f"返回 GuruSignal（guru='dalio', ticker='{ticker}'）。",
            ticker, context)
