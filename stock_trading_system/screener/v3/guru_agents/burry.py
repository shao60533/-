"""Michael Burry — Contrarian deep value with catalyst identification.

Clean-room implementation. Attribution: virattt/ai-hedge-fund.
"""

from __future__ import annotations

from stock_trading_system.screener.v3.guru_agents.base import (
    BaseGuruAgent,
    GuruSignal,
    SubAnalysis,
)


class BurryAgent(BaseGuruAgent):
    name = "burry"
    display_name = "Michael Burry"
    philosophy = "逆向深度价值 · 困境投资 · 催化剂识别"
    framework_lead = "深度价值 / 自己读 10-K / 隐藏资产"
    anti_patterns = [
        "估值溢价（PE 高于行业中位数 30%+）—— 我从不付溢价。",
        "卖方一致看多 + 媒体一致追捧 —— 共识太强意味着错误定价的反方。",
        "找不到隐藏价值或反向催化剂（hidden asset, spinoff, distressed debt 等）—— 没有 edge 不下手。",
    ]
    decision_style = [
        "我会自己读 10-K 至少 2 遍，不信卖方报告 —— 数字不会骗人。",
        "我会问：'当前价格远低于我看到的隐藏价值多少倍？至少 2x 才下手。'",
        "我会问：'市场对这家公司的误解在哪？我看到了别人看不到什么？'",
    ]
    evidence_demands = (
        "reasoning 第二段必须引用: book_value / EV/EBITDA / "
        "hidden asset 描述（spinoff / 不动产 / 子公司隐藏估值）/ 卖空利率。"
    )
    principles = [
        "市场共识往往是错误的，逆向思考是超额收益的来源",
        "深入分析资产负债表，寻找被忽视的资产价值",
        "识别能释放价值的催化剂事件",
        "保持高度集中的投资组合",
    ]
    motto = "我只投资于我深入研究过的东西"
    avatar_initials = "MB"
    avatar_color = "#922b21"

    SYSTEM_PROMPT = """你是 Michael Burry —— Scion Asset Management 创始人，因做空次贷危机而闻名的逆向投资者。

你的投资哲学核心：
1. 深度价值：寻找被市场严重低估的股票，尤其是被主流投资者抛弃的
2. 债务分析：仔细审视资产负债表，关注隐藏的债务风险或资产价值
3. 资产覆盖：清算价值 vs 市值，有形资产的真实价值
4. 逆向指标：市场情绪极端悲观时可能是买入机会
5. 催化剂潜力：什么事件能触发价值重估（管理层变动、拆分、回购等）

你擅长发现市场定价的结构性错误。
分析时从 5 个维度打分（0-10），然后综合给出 0-100 的总分。
最终输出 bullish / bearish / neutral 和 0-1 信心度。"""

    def evaluate_deep(
        self, ticker: str, full_data: dict, context: dict,
    ) -> GuruSignal:
        f = full_data.get("fundamentals_current", {})
        history = full_data.get("fundamentals_history", [])
        q = full_data.get("quote", {})
        subs: list[SubAnalysis] = []

        # 1. Deep value — PE, PB, EV/EBITDA extreme cheapness
        pe = f.get("pe") or 0
        pb = f.get("pb") or 0
        ev_ebitda = f.get("ev_to_ebitda") or f.get("enterprise_value_to_ebitda") or 0
        dv_score = 5.0
        if 0 < pe < 8:
            dv_score += 2
        elif 0 < pe < 12:
            dv_score += 1
        elif pe > 30:
            dv_score -= 2
        if 0 < pb < 0.8:
            dv_score += 2
        elif 0 < pb < 1.2:
            dv_score += 1
        elif pb > 5:
            dv_score -= 1.5
        if 0 < ev_ebitda < 6:
            dv_score += 1
        subs.append(SubAnalysis(
            name="deep_value",
            score=min(10, max(0, dv_score)),
            details=f"PE={pe:.1f}, PB={pb:.1f}, EV/EBITDA={ev_ebitda:.1f}",
        ))

        # 2. Debt analysis — leverage risk
        de = f.get("debt_to_equity") or 0
        interest_coverage = f.get("interest_coverage") or 0
        total_debt = f.get("total_debt") or 0
        total_assets = f.get("total_assets") or 1
        debt_ratio = total_debt / total_assets if total_assets > 0 else 0
        da_score = 5.0
        if de < 0.3:
            da_score += 2
        elif de < 1.0:
            da_score += 1
        elif de > 3.0:
            da_score -= 3
        elif de > 2.0:
            da_score -= 1.5
        if interest_coverage > 5:
            da_score += 1
        elif 0 < interest_coverage < 1.5:
            da_score -= 2
        subs.append(SubAnalysis(
            name="debt_analysis",
            score=min(10, max(0, da_score)),
            details=f"D/E={de:.1f}, 利息覆盖={interest_coverage:.1f}, 负债率={debt_ratio:.0%}",
        ))

        # 3. Asset coverage — tangible book vs market cap
        book_value = f.get("book_value") or f.get("tangible_book_value") or 0
        market_cap = f.get("market_cap") or 0
        if market_cap > 0 and book_value > 0:
            coverage = book_value / market_cap
            ac_score = 5.0
            if coverage > 1.5:
                ac_score = 9.0
            elif coverage > 1.0:
                ac_score = 7.5
            elif coverage > 0.5:
                ac_score = 5.5
            else:
                ac_score = 3.0
        else:
            ac_score = 5.0
            coverage = 0
        subs.append(SubAnalysis(
            name="asset_coverage",
            score=min(10, max(0, ac_score)),
            details=f"有形资产/市值 = {coverage:.2f}",
        ))

        # 4. Contrarian indicator — price decline from highs
        price = q.get("price") or q.get("last") or 0
        high_52w = q.get("52w_high") or q.get("year_high") or q.get("fiftyTwoWeekHigh") or 0
        if high_52w > 0 and price > 0:
            drawdown = (high_52w - price) / high_52w
            ci_score = 5.0
            if drawdown > 0.50:
                ci_score = 9.0  # severely beaten down
            elif drawdown > 0.30:
                ci_score = 7.0
            elif drawdown > 0.15:
                ci_score = 5.5
            elif drawdown < 0.05:
                ci_score = 3.0  # near highs, not contrarian
        else:
            ci_score = 5.0
            drawdown = 0
        subs.append(SubAnalysis(
            name="contrarian_indicator",
            score=min(10, max(0, ci_score)),
            details=f"距52周高点回撤 {drawdown:.0%}",
        ))

        # 5. Catalyst potential — buyback, FCF yield, activist potential
        fcf = f.get("free_cash_flow") or f.get("fcf") or 0
        fcf_yield = fcf / market_cap if market_cap > 0 else 0
        buyback = f.get("share_buyback") or f.get("buyback_yield") or 0
        cp_score = 5.0
        if fcf_yield > 0.10:
            cp_score += 2
        elif fcf_yield > 0.05:
            cp_score += 1
        if buyback > 0:
            cp_score += 1.5
        if drawdown > 0.40 and de < 1.0:
            cp_score += 1  # cheap + clean balance sheet = catalyst magnet
        subs.append(SubAnalysis(
            name="catalyst_potential",
            score=min(10, max(0, cp_score)),
            details=f"FCF 收益率 {fcf_yield:.1%}，回购={buyback or 'N/A'}",
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
            f"请作为 Michael Burry 分析 {ticker}。\n\n"
            f"当前数据摘要：\n"
            f"- 股价: ${q.get('price') or q.get('last', 'N/A')}\n"
            f"- PE: {f.get('pe', 'N/A')}\n"
            f"- PB: {f.get('pb', 'N/A')}\n"
            f"- D/E: {f.get('debt_to_equity', 'N/A')}\n"
            f"- 市值: ${f.get('market_cap', 0)/1e9:.1f}B\n\n"
            f"量化子分析得分（0-10）：\n"
            + "\n".join(f"  {k}: {v}" for k, v in scores.items())
            + f"\n\n基于以上数据和你的逆向投资哲学，给出最终评估。\n"
            f"重点关注：是否存在市场定价的结构性错误？有什么潜在催化剂？\n"
            f"你必须返回结构化的 GuruSignal，包含：\n"
            f"- guru: \"burry\"\n"
            f"- ticker: \"{ticker}\"\n"
            f"- signal: bullish/bearish/neutral\n"
            f"- confidence: 0-1\n"
            f"- reasoning: 详细的逆向分析推理\n"
            f"- sub_analyses: 各维度评分明细\n"
            f"- key_metrics: 关键指标\n"
            f"- total_score: 0-100 综合评分"
        )
