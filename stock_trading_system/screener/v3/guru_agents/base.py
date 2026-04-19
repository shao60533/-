"""Base guru agent interface and GuruSignal Pydantic schema.

All 14 guru agents extend BaseGuruAgent and return GuruSignal via
LangChain's chat.with_structured_output(GuruSignal).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


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


class BaseGuruAgent:
    """Abstract base for all guru agents.

    Subclasses must set class-level metadata and implement evaluate_deep().
    """
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
        """Run deep LLM-powered evaluation.

        Args:
            ticker: Stock symbol.
            full_data: GuruDataBundle as dict.
            context: Must contain 'provider' key for LLM routing.

        Returns:
            GuruSignal with structured analysis.
        """
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
        """Common LLM reasoning via structured output.

        Uses LangChain's with_structured_output(GuruSignal) — no manual
        JSON parsing. LangChain handles retries on malformed output.
        """
        from langchain_core.messages import SystemMessage, HumanMessage

        chat = self._get_chat_model(context)
        structured = chat.with_structured_output(GuruSignal)
        # Qwen requires the word "json" in messages when response_format=json_object
        json_hint = "\n\nPlease respond in valid JSON format matching the GuruSignal schema."
        return structured.invoke([
            SystemMessage(content=system_prompt + json_hint),
            HumanMessage(content=user_prompt),
        ])

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
