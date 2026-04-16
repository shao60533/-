"""GuruAgent — aggregates scores from investment master philosophies.

Takes the pre-computed `guru_matches` dict from the Orchestrator and produces
a single 0-100 score reflecting aggregate "master consensus".

This agent is special: it doesn't fetch data itself — it consumes the
per-guru match results already computed in parallel at L4.
"""

from stock_trading_system.screener.v2.agents.base import BaseAgent, AgentScore


class GuruAgent(BaseAgent):
    name = "guru"
    data_source = "qwen"

    def __init__(self, config: dict, data_helper=None):
        super().__init__(config)

    def score(self, ticker: str, context: dict) -> AgentScore:
        guru_matches = (context or {}).get("guru_matches", {}).get(ticker) or {}
        if not guru_matches:
            return self.make_score(50, "大师哲学数据缺失", {})

        # Average match percentage weighted by fit flag
        total_pct = 0.0
        fit_count = 0
        n = 0
        top_fits = []
        top_unfits = []
        for name, match in guru_matches.items():
            pct = match.get("match_pct", 0) if isinstance(match, dict) else getattr(match, "match_pct", 0)
            fit = match.get("fit", False) if isinstance(match, dict) else getattr(match, "fit", False)
            total_pct += pct
            if fit:
                fit_count += 1
                top_fits.append(f"{name}({pct:.0f}%)")
            else:
                top_unfits.append(f"{name}({pct:.0f}%)")
            n += 1

        avg_pct = total_pct / n if n > 0 else 50.0
        fit_bonus = (fit_count / n) * 15 if n > 0 else 0    # +15 if all fit

        score = avg_pct + fit_bonus
        signals = {
            "gurus_fit": fit_count,
            "gurus_total": n,
            "avg_match_pct": round(avg_pct, 1),
        }

        if top_fits:
            rationale = f"大师认可 {fit_count}/{n}: " + " · ".join(top_fits[:3])
        else:
            rationale = f"大师匹配度偏低（平均 {avg_pct:.0f}%）"
        return self.make_score(score, rationale, signals)
