"""Base guru agent interface and GuruSignal Pydantic schema.

All 14 guru agents extend BaseGuruAgent and return GuruSignal via
LangChain's chat.with_structured_output(GuruSignal).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from stock_trading_system.utils import get_logger

logger = get_logger("screener.v3.guru_agents")


class SubAnalysis(BaseModel):
    """One dimension of a guru's evaluation (e.g. moat, valuation)."""
    name: str
    score: float = Field(ge=0, le=10)
    details: str


class GuruSignal(BaseModel):
    """Structured output from a guru agent's deep evaluation."""
    guru: str
    ticker: str
    signal: Literal["bullish", "bearish", "neutral"]
    confidence: float = Field(ge=0, le=1)
    reasoning: str
    sub_analyses: list[SubAnalysis]
    key_metrics: dict[str, float] = Field(default_factory=dict)
    total_score: float = Field(ge=0, le=100)


# Explicit JSON example for LLMs that need format guidance (Qwen, etc.)
_GURU_SIGNAL_EXAMPLE = """{
  "guru": "buffett",
  "ticker": "AAPL",
  "signal": "bullish",
  "confidence": 0.85,
  "reasoning": "Strong moat and consistent earnings growth...",
  "sub_analyses": [
    {"name": "fundamental_quality", "score": 8.5, "details": "ROE 25% excellent"},
    {"name": "economic_moat", "score": 7.0, "details": "Brand + ecosystem"}
  ],
  "key_metrics": {"intrinsic_value": 220.0, "margin_of_safety": 0.18},
  "total_score": 82.5
}"""


def _coerce_to_guru_signal(raw: dict, guru_name: str, ticker: str) -> GuruSignal:
    """Tolerant parsing of LLM output that doesn't perfectly match schema.

    Handles common Qwen/Gemini format issues:
    - sub_analyses as dict instead of list
    - key_metrics with string values instead of float
    - signal value outside the enum (e.g. "avoid" → "bearish")
    - missing fields with sensible defaults
    """
    # Fix signal enum
    sig = str(raw.get("signal", "neutral")).lower().strip()
    signal_map = {
        "buy": "bullish", "strong_buy": "bullish", "positive": "bullish",
        "sell": "bearish", "strong_sell": "bearish", "negative": "bearish",
        "avoid": "bearish", "short": "bearish",
        "hold": "neutral", "wait": "neutral",
    }
    if sig not in ("bullish", "bearish", "neutral"):
        sig = signal_map.get(sig, "neutral")

    # Fix confidence
    conf = raw.get("confidence", 0.5)
    try:
        conf = float(conf)
        conf = max(0.0, min(1.0, conf))
    except (TypeError, ValueError):
        conf = 0.5

    # Fix sub_analyses: dict → list
    sa_raw = raw.get("sub_analyses", [])
    sub_analyses = []
    if isinstance(sa_raw, dict):
        for k, v in sa_raw.items():
            if isinstance(v, dict):
                sub_analyses.append(SubAnalysis(
                    name=k, score=min(10, max(0, float(v.get("score", 5)))),
                    details=str(v.get("details", "")),
                ))
            else:
                try:
                    score = float(v)
                except (TypeError, ValueError):
                    score = 5.0
                sub_analyses.append(SubAnalysis(name=k, score=min(10, max(0, score)), details=""))
    elif isinstance(sa_raw, list):
        for item in sa_raw:
            if isinstance(item, dict):
                try:
                    sub_analyses.append(SubAnalysis(**item))
                except Exception:
                    sub_analyses.append(SubAnalysis(
                        name=str(item.get("name", "unknown")),
                        score=min(10, max(0, float(item.get("score", 5)))),
                        details=str(item.get("details", "")),
                    ))

    # Fix key_metrics: filter non-numeric values
    km_raw = raw.get("key_metrics", {})
    key_metrics = {}
    if isinstance(km_raw, dict):
        for k, v in km_raw.items():
            try:
                key_metrics[k] = float(v)
            except (TypeError, ValueError):
                pass  # skip non-numeric entries

    # Fix total_score
    ts = raw.get("total_score", 50)
    try:
        ts = max(0, min(100, float(ts)))
    except (TypeError, ValueError):
        ts = 50.0

    return GuruSignal(
        guru=raw.get("guru", guru_name),
        ticker=raw.get("ticker", ticker),
        signal=sig,
        confidence=conf,
        reasoning=str(raw.get("reasoning", "")),
        sub_analyses=sub_analyses,
        key_metrics=key_metrics,
        total_score=ts,
    )


class BaseGuruAgent:
    """Abstract base for all guru agents."""
    name: str = ""
    display_name: str = ""
    philosophy: str = ""
    principles: list[str] = []
    motto: str = ""
    avatar_initials: str = ""
    avatar_color: str = "#888"

    def evaluate_deep(
        self, ticker: str, full_data: dict, context: dict,
    ) -> GuruSignal:
        raise NotImplementedError

    def _get_chat_model(self, context: dict):
        """Get a LangChain chat model for the active provider."""
        provider = context.get("provider", "qwen")
        config = context.get("config", {})

        if provider == "qwen":
            from langchain_openai import ChatOpenAI
            qwen_cfg = config.get("qwen", {})
            return ChatOpenAI(
                model=qwen_cfg.get("model", "qwen-plus"),
                api_key=qwen_cfg.get("api_key", ""),
                base_url=qwen_cfg.get("base_url",
                    "https://dashscope.aliyuncs.com/compatible-mode/v1"),
                timeout=120,
            )
        else:
            from langchain_google_genai import ChatGoogleGenerativeAI
            gemini_cfg = config.get("gemini", {})
            return ChatGoogleGenerativeAI(
                model=gemini_cfg.get("model", "gemini-2.5-flash"),
                google_api_key=gemini_cfg.get("api_key", ""),
                timeout=120,
            )

    def _llm_reason(
        self,
        system_prompt: str,
        user_prompt: str,
        ticker: str,
        context: dict,
    ) -> GuruSignal:
        """Common LLM reasoning with tolerant parsing.

        Strategy:
        1. Try with_structured_output(GuruSignal) first (LangChain native)
        2. On validation error, fall back to raw JSON + _coerce_to_guru_signal
        3. On total failure, return neutral fallback
        """
        from langchain_core.messages import SystemMessage, HumanMessage
        import json

        chat = self._get_chat_model(context)

        # Build messages with explicit schema example
        schema_instruction = (
            f"\n\nYou MUST respond with a valid JSON object matching this exact schema. "
            f"signal MUST be exactly one of: \"bullish\", \"bearish\", \"neutral\". "
            f"sub_analyses MUST be a JSON array (not an object). "
            f"key_metrics values MUST be numbers (not strings like \"N/A\"). "
            f"Use 0.0 for unknown numeric values.\n\n"
            f"Example output:\n{_GURU_SIGNAL_EXAMPLE}"
        )

        messages = [
            SystemMessage(content=system_prompt + schema_instruction),
            HumanMessage(content=user_prompt),
        ]

        # Attempt 1: LangChain structured output
        try:
            structured = chat.with_structured_output(GuruSignal)
            return structured.invoke(messages)
        except Exception as e:
            logger.debug("structured_output failed for %s/%s: %s", self.name, ticker, e)

        # Attempt 2: Raw chat → tolerant parse
        try:
            raw_resp = chat.invoke(messages)
            content = raw_resp.content if hasattr(raw_resp, 'content') else str(raw_resp)

            # Extract JSON from response (may have markdown fences)
            json_str = content
            if "```json" in json_str:
                json_str = json_str.split("```json")[1].split("```")[0]
            elif "```" in json_str:
                json_str = json_str.split("```")[1].split("```")[0]

            raw_dict = json.loads(json_str.strip())
            signal = _coerce_to_guru_signal(raw_dict, self.name, ticker)
            logger.info("Tolerant parse succeeded for %s/%s: %s %.0f%%",
                        self.name, ticker, signal.signal, signal.confidence * 100)
            return signal
        except Exception as e2:
            logger.warning("Both structured and tolerant parse failed for %s/%s: %s",
                           self.name, ticker, e2)
            # Return neutral fallback
            return GuruSignal(
                guru=self.name, ticker=ticker, signal="neutral",
                confidence=0.0, reasoning=f"LLM parsing failed: {e2}",
                sub_analyses=[], key_metrics={}, total_score=0,
            )

    def to_meta(self) -> dict:
        """Return guru metadata for the frontend."""
        return {
            "name": self.name,
            "display_name": self.display_name,
            "philosophy": self.philosophy,
            "principles": self.principles,
            "motto": self.motto,
            "avatar_initials": self.avatar_initials,
            "avatar_color": self.avatar_color,
        }
