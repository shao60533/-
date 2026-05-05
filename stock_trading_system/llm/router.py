"""Provider resolution — single source of truth for which LLM is active.

Priority chain:
    1. env LLM_PROVIDER  (deployment override; never persisted)
    2. user_settings.llm_provider (per-user override, if user_id given)
    3. config["llm_provider"] (global yaml setting)
    4. legacy auto-detect:
         - openrouter env present → openrouter (cloud one-env activation)
         - else qwen key present → qwen
         - else → gemini

v1.0 (2026-05-05) added ``openrouter`` as a third provider plus a
*preset pool* layer underneath. ``openrouter`` is special: a single
key unlocks 100+ models, and the user picks which model to use via
``active.deep`` / ``active.quick`` pointers into ``presets[]``.

``resolve_openrouter_model(config, role=...)`` is the single resolver
for that pointer; it never raises and always returns a normalised
preset dict (falls back to a hardcoded safe default when the registry
is empty / corrupt). See ``docs/design/llm-openrouter.md`` for the
rationale.
"""

from __future__ import annotations

import os
from typing import Literal

from stock_trading_system.llm.constants import ENV_LLM_PROVIDER, VALID_PROVIDERS
from stock_trading_system.utils import get_logger

logger = get_logger("llm.router")

Provider = Literal["qwen", "gemini", "openrouter"]


def get_active_provider(config: dict, user_id: int | None = None) -> Provider:
    """Single source of truth. Resolve which LLM provider is active.

    Priority:
        1. env LLM_PROVIDER (deployment override; never persisted)
        2. user_settings.llm_provider (per-user override, if user_id given)
        3. config["llm_provider"] (global yaml setting)
        4. legacy auto-detect:
             - OPENROUTER_API_KEY env or openrouter.api_key set → openrouter
             - qwen.api_key set → qwen
             - fallback → gemini
    """
    # 1. env var
    env_val = os.environ.get(ENV_LLM_PROVIDER, "").strip().lower()
    if env_val in VALID_PROVIDERS:
        return env_val  # type: ignore[return-value]
    if env_val and env_val not in VALID_PROVIDERS:
        logger.warning(
            "Ignoring unknown LLM_PROVIDER=%r (valid: %s)",
            env_val,
            sorted(VALID_PROVIDERS),
        )

    # 2. per-user setting
    if user_id is not None:
        user_provider = _get_user_llm_provider(config, user_id)
        if user_provider and user_provider in VALID_PROVIDERS:
            return user_provider  # type: ignore[return-value]

    # 3. global config
    cfg_val = (config.get("llm_provider") or "").strip().lower()
    if cfg_val in VALID_PROVIDERS:
        return cfg_val  # type: ignore[return-value]
    if cfg_val and cfg_val not in VALID_PROVIDERS:
        logger.warning("Ignoring unknown config.llm_provider=%r", cfg_val)

    # 4. legacy auto-detect — OR first so cloud deploys that only ship
    # ``OPENROUTER_API_KEY`` env light up without any yaml change.
    has_qwen = bool((config.get("qwen") or {}).get("api_key"))
    has_or = bool(
        os.environ.get("OPENROUTER_API_KEY")
        or (config.get("openrouter") or {}).get("api_key")
    )
    if has_or:
        return "openrouter"
    return "qwen" if has_qwen else "gemini"


def _get_user_llm_provider(config: dict, user_id: int) -> str | None:
    """Read llm_provider from user_settings table."""
    import sqlite3
    db_path = config.get("portfolio", {}).get("db_path", "data/portfolio.db")
    try:
        conn = sqlite3.connect(db_path)
        row = conn.execute(
            "SELECT llm_provider FROM user_settings WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        conn.close()
        return row[0] if row else None
    except Exception:
        return None


def is_provider_locked_by_env() -> bool:
    """True if LLM_PROVIDER env var is set to a valid value.

    UI disables the switch when locked.
    """
    val = os.environ.get(ENV_LLM_PROVIDER, "").strip().lower()
    return val in VALID_PROVIDERS


def has_provider_key(config: dict, provider: Provider) -> bool:
    """Check if the target provider has an API key configured.

    OpenRouter accepts ``OPENROUTER_API_KEY`` env *or*
    ``openrouter.api_key`` from yaml — env wins for cloud deploys.
    """
    if provider == "qwen":
        return bool((config.get("qwen") or {}).get("api_key"))
    if provider == "gemini":
        return bool((config.get("gemini") or {}).get("api_key"))
    if provider == "openrouter":
        return bool(
            os.environ.get("OPENROUTER_API_KEY")
            or (config.get("openrouter") or {}).get("api_key")
        )
    return False


def resolve_active_model(config: dict, user_id: int | None = None) -> tuple[str | None, str | None]:
    """Return ``(provider, model)`` for the requesting user.

    Resolves the model from the provider-specific config slice — `qwen.model`
    / `gemini.deep_think_model` (or `.model`) / OR active deep preset —
    instead of the historical ``llm.model`` lookup which was always empty
    in practice and produced cache keys like ``"qwen:"`` / ``"gemini:"``.

    For openrouter, the model id is the active *deep* preset's ``model``
    field (the Pro / Gemini-3.1 line). Quick model is reported separately
    by callers that need it (typically ``_build_quick_llm`` flows).
    """
    provider = (
        get_active_provider(config, user_id=user_id)
        if user_id is not None
        else get_active_provider(config)
    )
    if provider == "qwen":
        qwen = config.get("qwen") or {}
        model = qwen.get("deep_think_model") or qwen.get("model")
    elif provider == "gemini":
        gem = config.get("gemini") or {}
        model = gem.get("deep_think_model") or gem.get("model")
    elif provider == "openrouter":
        preset = resolve_openrouter_model(config, role="deep")
        model = preset["model"]
    else:
        model = (config.get("llm") or {}).get("model")
    return provider, model


# ── OpenRouter preset pool resolver ──────────────────────────────────


# Hardcoded fallback so ``resolve_openrouter_model`` never raises even if
# yaml drift wipes the registry. Models picked are *plausible* — they
# don't have to be live, only valid OpenRouter model ids — because this
# branch is a degraded last-resort that ships a working call shape.
_HARDCODED_FALLBACK: dict[str, dict] = {
    "deep": {
        "id": "deepseek-v4-pro-fallback",
        "label": "DeepSeek V4 Pro (fallback)",
        "model": "deepseek/deepseek-v4-pro",
        "role": "deep",
        "provider_order": [],
        "kwargs": {},
    },
    "quick": {
        "id": "deepseek-v4-flash-fallback",
        "label": "DeepSeek V4 Flash (fallback)",
        "model": "deepseek/deepseek-v4-flash",
        "role": "quick",
        "provider_order": [],
        "kwargs": {},
    },
}


def _normalize_preset(p: dict) -> dict:
    """Coerce a preset dict to a stable schema callers can rely on.

    Reads are defensive — yaml may have legacy or partial entries — so
    every consumer (router, ChatModel factory, UI DTO) sees the same
    five fields with the same types.
    """
    return {
        "id":             p.get("id") or "",
        "label":          p.get("label") or p.get("id") or "",
        "model":          p.get("model") or "",
        "role":           p.get("role") or "",
        "provider_order": list(p.get("provider_order") or []),
        "kwargs":         dict(p.get("kwargs") or {}),
    }


def resolve_openrouter_model(
    config: dict,
    *,
    role: str,
    feature: str | None = None,
) -> dict:
    """Resolve the active OR preset for ``(role, feature)``.

    Resolution order:
        1. ``active.overrides[feature]`` — feature-pinned preset
           (v1.0 wires the read path; the UI to set this lands later;
           v1.0 only honors it if explicitly present in yaml).
        2. ``active[role]`` — role default pointer (deep / quick).
        3. First entry in ``presets[]`` whose ``role`` matches
           (``"both"`` is allowed and matches both).
        4. ``_HARDCODED_FALLBACK[role]`` — last resort. Never raises.

    Returns a normalised preset dict (see ``_normalize_preset``).
    """
    or_cfg = config.get("openrouter") or {}
    presets_list = or_cfg.get("presets") or []
    presets = {p["id"]: p for p in presets_list if p.get("id")}
    active = or_cfg.get("active") or {}
    overrides = active.get("overrides") or {}

    # 1. feature-pinned (v1.0 read-only; v1.1 will add UI to set)
    if feature and overrides.get(feature):
        pid = overrides[feature]
        if pid in presets:
            return _normalize_preset(presets[pid])

    # 2. role default
    pid = active.get(role)
    if pid and pid in presets:
        return _normalize_preset(presets[pid])

    # 3. first matching role
    for p in presets_list:
        if p.get("role") in (role, "both"):
            return _normalize_preset(p)

    # 4. hardcoded safe default — keyed by role; quick covers unknown
    # roles so a typo here can never crash the caller.
    return _HARDCODED_FALLBACK.get(role, _HARDCODED_FALLBACK["quick"])
