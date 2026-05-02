"""Peter Lynch — Growth at a Reasonable Price (GARP).

Clean-room implementation. Attribution: virattt/ai-hedge-fund.
"""

from __future__ import annotations

from stock_trading_system.screener.v3.guru_agents.base import (
    BaseGuruAgent,
    GuruSignal,
    SubAnalysis,
)


class LynchAgent(BaseGuruAgent):
    name = "lynch"
    display_name = "Peter Lynch"
    philosophy = "了解你买的东西 · PEG 估值 · 合理价格的成长股"
    principles = [
        "PEG < 1 是理想目标，< 2 尚可接受",
        "将股票分类：慢速、稳健、快速、周期、困境反转、资产隐蔽",
        "投资你了解的企业",
        "关注内部人士买入行为",
    ]
    motto = "投资你所了解的"
    avatar_initials = "PL"
    avatar_color = "#1e8449"

    SYSTEM_PROMPT = """你是 Peter Lynch —— 富达麦哲伦基金传奇经理，13 年年化 29% 的投资大师。

你的投资哲学核心：
1. PEG 估值：PE / 盈利增长率，PEG < 1 是绝佳机会
2. 股票分类法：将每只股票归入六类之一（慢速增长、稳健增长、快速增长、周期型、困境反转、资产隐蔽型）
3. 盈利增长：关注可持续的盈利增长率，20-25% 最佳
4. 机构持仓：低机构持仓意味着尚未被发现
5. 内部人士行为：管理层买入是强烈信号

分析时从 5 个维度打分（0-10），然后综合给出 0-100 的总分。
最终输出 bullish / bearish / neutral 和 0-1 信心度。

在本系统中，你的任务不是单独判断一家公司是否优秀，而是判断它是否符合用户指定主题下的投资机会。
如果公司不符合用户主题，应先指出主题不匹配，再按你的投资哲学给出保守结论。
"投资你了解的"包括理解该公司是否真正在用户查询的行业中赚钱；主题不匹配应明显扣分。"""

    def evaluate_deep(
        self, ticker: str, full_data: dict, context: dict,
    ) -> GuruSignal:
        f = full_data.get("fundamentals_current", {})
        history = full_data.get("fundamentals_history", [])
        q = full_data.get("quote", {})
        subs: list[SubAnalysis] = []

        # 1. PEG valuation
        pe = f.get("pe") or 0
        earnings_growth = f.get("earnings_growth") or f.get("eps_growth") or 0
        if earnings_growth > 0 and pe > 0:
            peg = pe / (earnings_growth * 100)
        else:
            peg = 0
        peg_score = 5.0
        if 0 < peg < 1.0:
            peg_score = 9.0
        elif 0 < peg < 1.5:
            peg_score = 7.0
        elif 0 < peg < 2.0:
            peg_score = 5.5
        elif peg > 3.0:
            peg_score = 2.0
        elif peg > 2.0:
            peg_score = 3.5
        subs.append(SubAnalysis(
            name="peg_valuation",
            score=min(10, max(0, peg_score)),
            details=f"PE={pe:.1f}, 盈利增长={earnings_growth:.0%}, PEG={peg:.2f}",
        ))

        # 2. Growth classification
        revenue_growth = f.get("revenue_growth") or 0
        if revenue_growth > 0.25:
            classification = "快速增长"
            gc_score = 8.0
        elif revenue_growth > 0.10:
            classification = "稳健增长"
            gc_score = 7.0
        elif revenue_growth > 0:
            classification = "慢速增长"
            gc_score = 5.0
        elif revenue_growth < -0.10:
            classification = "困境反转候选"
            gc_score = 4.0
        else:
            classification = "周期型"
            gc_score = 5.0
        subs.append(SubAnalysis(
            name="growth_classification",
            score=min(10, max(0, gc_score)),
            details=f"收入增长 {revenue_growth:.0%} → {classification}",
        ))

        # 3. Earnings growth trend
        earnings_list = [
            h.get("eps") or h.get("earnings_per_share", 0)
            for h in history if h.get("eps") or h.get("earnings_per_share")
        ]
        if len(earnings_list) >= 2 and earnings_list[0] and earnings_list[0] > 0:
            eps_cagr = (earnings_list[-1] / earnings_list[0]) ** (
                1 / max(1, len(earnings_list) - 1)
            ) - 1
        else:
            eps_cagr = earnings_growth
        eg_score = 5.0
        if eps_cagr > 0.25:
            eg_score = 9.0
        elif eps_cagr > 0.15:
            eg_score = 7.5
        elif eps_cagr > 0.05:
            eg_score = 6.0
        elif eps_cagr < 0:
            eg_score = 3.0
        subs.append(SubAnalysis(
            name="earnings_growth",
            score=min(10, max(0, eg_score)),
            details=f"EPS CAGR {eps_cagr:.0%}",
        ))

        # 4. Institutional ownership — lower is more attractive to Lynch
        inst = f.get("institutional_ownership") or f.get("inst_ownership")
        if inst is not None:
            io_score = 5.0
            if inst < 0.30:
                io_score = 8.0  # under-discovered
            elif inst < 0.60:
                io_score = 6.0
            elif inst > 0.90:
                io_score = 3.0  # over-owned
            detail = f"机构持仓 {inst:.0%}"
        else:
            io_score = 5.0
            detail = "机构持仓数据不可用"
        subs.append(SubAnalysis(
            name="institutional_ownership",
            score=min(10, max(0, io_score)),
            details=detail,
        ))

        # 5. Insider activity
        insider = f.get("insider_buying") or f.get("insider_transactions")
        if insider is not None:
            if insider > 0:
                ia_score = 8.0
                ia_detail = f"内部人净买入 ${insider:,.0f}"
            elif insider < 0:
                ia_score = 3.0
                ia_detail = f"内部人净卖出 ${abs(insider):,.0f}"
            else:
                ia_score = 5.0
                ia_detail = "内部人无交易"
        else:
            ia_score = 5.0
            ia_detail = "内部人交易数据不可用"
        subs.append(SubAnalysis(
            name="insider_activity",
            score=min(10, max(0, ia_score)),
            details=ia_detail,
        ))

        weights = [0.30, 0.15, 0.25, 0.15, 0.15]
        total = sum(s.score * w for s, w in zip(subs, weights)) * 10

        scores = {s.name: s.score for s in subs}
        scores["total"] = round(total, 1)
        scores["peg"] = round(peg, 2)

        return self._llm_reason(
            self.SYSTEM_PROMPT,
            self._build_prompt(ticker, full_data, scores),
            ticker, context,
        )

    def _build_prompt(self, ticker: str, data: dict, scores: dict) -> str:
        f = data.get("fundamentals_current", {})
        q = data.get("quote", {})
        return (
            f"请作为 Peter Lynch 分析 {ticker}。\n\n"
            f"当前数据摘要：\n"
            f"- 股价: ${q.get('price') or q.get('last', 'N/A')}\n"
            f"- PE: {f.get('pe', 'N/A')}\n"
            f"- PEG: {scores.get('peg', 'N/A')}\n"
            f"- 收入增长: {f.get('revenue_growth', 'N/A')}\n"
            f"- 盈利增长: {f.get('earnings_growth', 'N/A')}\n\n"
            f"量化子分析得分（0-10）：\n"
            + "\n".join(f"  {k}: {v}" for k, v in scores.items())
            + f"\n\n基于以上数据和你的投资哲学，给出最终评估。\n"
            f"你必须返回结构化的 GuruSignal，包含：\n"
            f"- guru: \"lynch\"\n"
            f"- ticker: \"{ticker}\"\n"
            f"- signal: bullish/bearish/neutral\n"
            f"- confidence: 0-1\n"
            f"- reasoning: 详细的投资分析推理\n"
            f"- sub_analyses: 各维度评分明细\n"
            f"- key_metrics: 关键指标（PEG, 分类等）\n"
            f"- total_score: 0-100 综合评分"
        )
