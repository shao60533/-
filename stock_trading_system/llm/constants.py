"""Constants for the LLM routing layer.

v1.0 (2026-05-05) added ``openrouter`` as a third valid provider — see
``docs/design/llm-openrouter.md`` for the rationale. Adding a provider
here is the single point that unlocks env / yaml / per-user override
acceptance across the whole stack (``router.get_active_provider`` and
``has_provider_key`` both read this set).
"""

VALID_PROVIDERS = frozenset({"qwen", "gemini", "openrouter"})
ENV_LLM_PROVIDER = "LLM_PROVIDER"
