"""Mohnish Pabrai — Dhandho framework with low-risk high-uncertainty.

Clean-room implementation. Attribution: virattt/ai-hedge-fund.
"""

from __future__ import annotations

from stock_trading_system.screener.v3.guru_agents.base import (
    BaseGuruAgent,
    GuruSignal,
    SubAnalysis,
)


class PabraiAgent(BaseGuruAgent):
    name = "pabrai"
    display_name = "Mohnish Pabrai"
    philosophy = "克隆策略 · 低风险高不确定性 · Dhandho 框架"
    framework_lead = "Dhandho / 低风险高回报 / clone 复制"
    anti_patterns = [
        "估值偏离 P/FCF 合理范围（> 15x）—— Dhandho 框架要求低估值入场。",
        "业务难以理解（多 segment 或新兴技术）—— 我只 clone 我能完全理解的生意。",
        "已有大量明星投资者退出（13F 显示 5+ tier-1 投资者减仓）—— 警示信号。",
    ]
    decision_style = [
        "我会问：'是不是 heads I win, tails I don't lose much？下行 < 30%，上行 > 100%。'",
        "我会问：'这是不是 spawn 项目（小钱大潜力）？早期 sizing 小但允许加仓。'",
        "我会问：'有没有成功的商业模式可以 clone？模仿胜过创新。'",
    ]
    evidence_demands = (
        "reasoning 第二段必须引用: P/FCF / 下行测算（多少损失上限）/ "
        "上行测算（5 年 IRR）/ 业务可重复性（是否有同类成功案例）。"
    )
    principles = [
        "Dhandho：低风险、高不确定性、高回报的投资",
        "克隆优秀投资者的持仓和思路",
        "寻找 Heads I win, tails I don't lose much 的机会",
        "简单的商业模式，由诚实的人经营",
    ]
    motto = "少量投注，大量收获，偶尔下注"
    avatar_initials = "MP"
    avatar_color = "#d35400"

    SYSTEM_PROMPT = """你是 Mohnish Pabrai —— Pabrai Investment Funds 创始人，Dhandho 投资框架的倡导者。

你的投资哲学核心：
1. 下行保护：最差情况下损失有限（Heads I win, tails I don't lose much）
2. 上行期权性：最好情况下收益巨大，存在多个正面催化剂
3. 商业简单性：只投资你能在两分钟内解释清楚的生意
4. 管理层品质：寻找由老板型经营者（owner-operator）运营的企业
5. 复制验证：其他聪明的投资者是否也在持有？（克隆策略）

你寻找的是"Dhandho"——用最小的风险获取最大的收益。
分析时从 5 个维度打分（0-10），然后综合给出 0-100 的总分。"""

    def evaluate_deep(
        self, ticker: str, full_data: dict, context: dict,
    ) -> GuruSignal:
        f = full_data.get("fundamentals_current", {})
        history = full_data.get("fundamentals_history", [])
        q = full_data.get("quote", {})
        subs: list[SubAnalysis] = []

        # 1. Downside protection — valuation floor + balance sheet
        pe = f.get("pe") or 0
        pb = f.get("pb") or 0
        de = f.get("debt_to_equity") or 0
        cr = f.get("current_ratio") or 0
        dp_score = 5.0
        if 0 < pe < 12 and de < 0.5:
            dp_score = 9.0
        elif 0 < pe < 15 and de < 1.0:
            dp_score = 7.0
        elif pe > 30 or de > 2.0:
            dp_score = 3.0
        if 0 < pb < 1.0:
            dp_score = min(10, dp_score + 1)
        if cr > 2.0:
            dp_score = min(10, dp_score + 0.5)
        subs.append(SubAnalysis(
            name="downside_protection",
            score=min(10, max(0, dp_score)),
            details=f"PE={pe:.1f}, PB={pb:.1f}, D/E={de:.1f}, CR={cr:.1f}",
        ))

        # 2. Upside optionality — growth potential + multiple expansion room
        revenue_growth = f.get("revenue_growth") or 0
        earnings_growth = f.get("earnings_growth") or f.get("eps_growth") or 0
        market_cap = f.get("market_cap") or 0
        uo_score = 5.0
        if revenue_growth > 0.15:
            uo_score += 2
        elif revenue_growth > 0.08:
            uo_score += 1
        if earnings_growth > 0.20:
            uo_score += 1.5
        # Small caps with growth = more optionality
        if market_cap < 10e9 and revenue_growth > 0.10:
            uo_score += 1
        subs.append(SubAnalysis(
            name="upside_optionality",
            score=min(10, max(0, uo_score)),
            details=f"收入增长 {revenue_growth:.0%}, 盈利增长 {earnings_growth:.0%}",
        ))

        # 3. Business simplicity — margin stability + single-business focus
        margins = [h.get("profit_margin") or h.get("net_margin", 0)
                   for h in history if h.get("profit_margin") or h.get("net_margin")]
        margin = f.get("profit_margin") or f.get("net_margin") or 0
        if len(margins) >= 3:
            margin_vol = (
                sum((m - sum(margins) / len(margins)) ** 2 for m in margins)
                / len(margins)
            ) ** 0.5
        else:
            margin_vol = 0.5
        bs_score = 5.0
        if margin > 0.10 and margin_vol < 0.05:
            bs_score = 8.0  # stable, profitable, simple
        elif margin > 0.05 and margin_vol < 0.10:
            bs_score = 6.5
        elif margin < 0:
            bs_score = 2.5
        subs.append(SubAnalysis(
            name="business_simplicity",
            score=min(10, max(0, bs_score)),
            details=f"利润率 {margin:.0%}, 利润率波动 {margin_vol:.0%}",
        ))

        # 4. Management quality — owner-operator proxy
        insider_own = f.get("insider_ownership") or f.get("insider_percent")
        roe = f.get("roe") or 0
        fcf_margin = f.get("fcf_margin") or f.get("free_cash_flow_margin") or 0
        mq_score = 5.0
        if insider_own is not None and insider_own > 0.10:
            mq_score += 2  # owner-operator
        if roe > 0.15:
            mq_score += 1.5
        elif roe < 0.05:
            mq_score -= 1.5
        if fcf_margin > 0.15:
            mq_score += 1
        elif fcf_margin < 0:
            mq_score -= 1.5
        insider_detail = (
            f"内部人持股 {insider_own:.1%}" if insider_own is not None
            else "内部人持股 N/A"
        )
        subs.append(SubAnalysis(
            name="management_quality",
            score=min(10, max(0, mq_score)),
            details=f"ROE {roe:.0%}, {insider_detail}",
        ))

        # 5. Copycat validation — institutional ownership + super-investor overlap
        inst = f.get("institutional_ownership") or f.get("inst_ownership")
        cv_score = 5.0
        if inst is not None:
            if 0.30 < inst < 0.80:
                cv_score = 7.0  # good institutional interest
            elif inst > 0.80:
                cv_score = 5.5  # possibly over-owned
            elif inst < 0.10:
                cv_score = 4.0  # too undiscovered
            cv_detail = f"机构持仓 {inst:.0%}"
        else:
            cv_detail = "机构持仓数据不可用"
        # Low PE + institutional interest = other smart money sees value
        if inst and inst > 0.30 and pe > 0 and pe < 15:
            cv_score = min(10, cv_score + 1)
        subs.append(SubAnalysis(
            name="copycat_validation",
            score=min(10, max(0, cv_score)),
            details=cv_detail,
        ))

        weights = [0.25, 0.20, 0.15, 0.20, 0.20]
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
            f"请作为 Mohnish Pabrai 分析 {ticker}。\n\n"
            f"当前数据摘要：\n"
            f"- 股价: ${q.get('price') or q.get('last', 'N/A')}\n"
            f"- PE: {f.get('pe', 'N/A')}\n"
            f"- PB: {f.get('pb', 'N/A')}\n"
            f"- ROE: {f.get('roe', 'N/A')}\n"
            f"- D/E: {f.get('debt_to_equity', 'N/A')}\n"
            f"- 收入增长: {f.get('revenue_growth', 'N/A')}\n\n"
            f"量化子分析得分（0-10）：\n"
            + "\n".join(f"  {k}: {v}" for k, v in scores.items())
            + f"\n\n基于以上数据和 Dhandho 投资框架，给出最终评估。\n"
            f"重点关注：这是否是一个 'Heads I win, tails I don't lose much' 的机会？\n"
            f"你必须返回结构化的 GuruSignal，包含：\n"
            f"- guru: \"pabrai\"\n"
            f"- ticker: \"{ticker}\"\n"
            f"- signal: bullish/bearish/neutral\n"
            f"- confidence: 0-1\n"
            f"- reasoning: 基于 Dhandho 框架的详细推理\n"
            f"- sub_analyses: 各维度评分明细\n"
            f"- key_metrics: 关键指标\n"
            f"- total_score: 0-100 综合评分"
        )
