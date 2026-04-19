"""Howard Marks — Cycle thinking + second-level thinking.

Original implementation (not based on virattt). Prompt structure
informed by arXiv 2510.01664 (GuruAgents) template.
"""

from __future__ import annotations

from stock_trading_system.screener.v3.guru_agents.base import BaseGuruAgent, GuruSignal, SubAnalysis


class MarksAgent(BaseGuruAgent):
    name = "marks"
    display_name = "Howard Marks"
    philosophy = "周期思维 · 第二层思考 · 风控优先"
    principles = ["市场有周期，极端终将回归", "第二层思考看到共识之外的真相", "风险控制优先于回报追逐", "不对称回报是目标"]
    motto = "你无法预测，但你可以准备"
    avatar_initials = "HM"
    avatar_color = "#6c3483"

    SYSTEM_PROMPT = """你是 Howard Marks —— Oaktree Capital 创始人，著有《投资最重要的事》。

你最看重：
1. 市场循环位置（现在是贪婪还是恐惧？估值处于历史分位哪里？）
2. 第二层思考（别人看到利好你看到的背后风险，反之亦然）
3. 风险控制优先于回报（宁可错过也不要大亏）
4. 不对称回报（下行有限、上行可观）

分析时用以下结构：
- 循环判断：当前所处市场循环阶段及证据
- 第二层思考：市场共识 vs. 你的反向观点
- 不对称性评估：下行/上行比
- 风险警示：最糟情况下损失多少
最终给出 bullish/bearish/neutral 和 0-1 信心度。"""

    def evaluate_deep(self, ticker: str, full_data: dict, context: dict) -> GuruSignal:
        f = full_data.get("fundamentals_current", {})
        q = full_data.get("quote", {})
        history = full_data.get("fundamentals_history", [])
        subs = []

        # 1. Cycle position
        pe = f.get("pe") or 0
        c_score = 5.0
        if 0 < pe < 12: c_score = 8.0  # deep value territory
        elif 12 <= pe < 20: c_score = 6.5
        elif 20 <= pe < 30: c_score = 4.5
        elif pe >= 30: c_score = 2.5
        subs.append(SubAnalysis(name="cycle_position", score=c_score,
                                details=f"PE={pe:.1f} — {'周期底部' if pe < 12 else '周期顶部' if pe > 30 else '中段'}"))

        # 2. Second-level thinking (contrarian signal from sentiment)
        news = full_data.get("news_recent", [])
        neg_count = sum(1 for n in news if any(w in str(n).lower() for w in ["下跌", "危机", "暴跌", "sell", "crash", "decline"]))
        pos_count = sum(1 for n in news if any(w in str(n).lower() for w in ["新高", "突破", "飙升", "buy", "surge", "rally"]))
        if neg_count > pos_count + 2:
            sl_score = 8.0  # fear = opportunity
        elif pos_count > neg_count + 2:
            sl_score = 3.0  # greed = caution
        else:
            sl_score = 5.5
        subs.append(SubAnalysis(name="second_level_thinking", score=sl_score,
                                details=f"负面{neg_count}条/正面{pos_count}条"))

        # 3. Asymmetric return
        de = f.get("debt_to_equity", 1) or 1
        margin = f.get("profit_margin") or f.get("net_margin") or 0
        a_score = 5.0
        if de < 0.5 and margin > 0.10:
            a_score = 8.0  # low downside, decent upside
        elif de > 2 or margin < 0:
            a_score = 3.0  # high downside
        subs.append(SubAnalysis(name="asymmetric_return", score=a_score,
                                details=f"D/E={de:.1f}, 利润率={margin:.0%}"))

        # 4. Risk warning
        beta = f.get("beta", 1) or 1
        r_score = 5.0
        if beta > 1.5: r_score = 3.0
        elif beta < 0.8: r_score = 7.5
        subs.append(SubAnalysis(name="risk_warning", score=r_score,
                                details=f"Beta={beta:.2f}"))

        # 5. Valuation vs history
        revs = [h.get("revenue", 0) for h in history if h.get("revenue")]
        if len(revs) >= 2 and revs[0] > 0:
            growth = (revs[-1] / revs[0]) ** (1 / max(1, len(revs) - 1)) - 1
        else:
            growth = 0
        vh_score = 5.0 + min(3, max(-3, (growth * 20 - pe * 0.1)))
        subs.append(SubAnalysis(name="value_vs_growth", score=min(10, max(0, vh_score)),
                                details=f"增长{growth:.0%} vs PE {pe:.0f}"))

        weights = [0.25, 0.25, 0.20, 0.15, 0.15]
        total = sum(s.score * w for s, w in zip(subs, weights)) * 10
        scores = {s.name: s.score for s in subs}
        scores["total"] = round(total, 1)

        return self._llm_reason(self.SYSTEM_PROMPT,
            f"分析 {ticker}（Marks 视角）。PE={pe}, Beta={beta:.2f}, D/E={de:.1f}。"
            f"量化得分: {scores}。返回 GuruSignal（guru='marks', ticker='{ticker}'）。",
            ticker, context)
