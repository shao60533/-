"""Base class for investment master / guru philosophies.

Each guru is a rule-based engine (optionally augmented by Qwen judgement)
that scores how well a stock fits their investment philosophy.

Output is a match percentage 0-100 + fit boolean + human-readable reason.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, asdict


@dataclass
class GuruMatch:
    """How well a stock matches a guru's philosophy."""
    match_pct: float              # 0-100
    fit: bool                     # convenience boolean (match_pct >= 70)
    reason: str                   # one-line explanation
    principles_met: list[str]     # which principles matched
    principles_unmet: list[str]   # which didn't

    def to_dict(self) -> dict:
        return asdict(self)


class BaseGuru(ABC):
    """Abstract base for a guru philosophy engine."""
    name: str = "base"             # short id, e.g. "buffett"
    display_name: str = "Base Guru"
    philosophy: str = ""           # short tag, e.g. "价值投资 / 护城河"
    principles: list[str] = []     # key principles, e.g. ["经济护城河", "ROE>15%"]
    motto: str = ""                # quote
    avatar_initials: str = "GG"
    avatar_color: str = "#6b7a99"

    def __init__(self, config: dict):
        self._config = config

    @abstractmethod
    def evaluate(self, ticker: str, fundamentals: dict, context: dict) -> GuruMatch:
        """Evaluate how well `ticker` fits this guru's philosophy."""
        raise NotImplementedError

    def metadata(self) -> dict:
        """Return UI metadata for this guru (for /api/screen/v2/gurus)."""
        return {
            "name": self.name,
            "display_name": self.display_name,
            "philosophy": self.philosophy,
            "principles": self.principles,
            "motto": self.motto,
            "avatar_initials": self.avatar_initials,
            "avatar_color": self.avatar_color,
        }

    @staticmethod
    def make_match(
        met: list[str],
        unmet: list[str],
        reason: str = "",
        bonus: float = 0.0,
    ) -> GuruMatch:
        """Compute match_pct from met/unmet list counts.

        match_pct = (len(met) / (len(met) + len(unmet))) * 100 + bonus (capped 0-100)
        """
        total = len(met) + len(unmet)
        base = (len(met) / total * 100.0) if total > 0 else 0.0
        pct = max(0.0, min(100.0, base + bonus))
        return GuruMatch(
            match_pct=round(pct, 1),
            fit=pct >= 70.0,
            reason=reason or f"符合 {len(met)}/{total} 条原则",
            principles_met=met,
            principles_unmet=unmet,
        )
