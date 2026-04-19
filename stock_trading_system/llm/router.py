"""Provider resolution — single source of truth for which LLM is active.

Priority chain:
    1. env LLM_PROVIDER  (deployment override; never persisted)
    2. config["llm_provider"]  (user setting from yaml)
    3. legacy auto-detect: qwen key present → qwen, else gemini
"""

from __future__ import annotations

import os
from typing import Literal

from stock_trading_system.llm.constants import ENV_LLM_PROVIDER, VALID_PROVIDERS
from stock_trading_system.utils import get_logger

logger = get_logger("llm.router")

Provider = Literal["qwen", "gemini"]


def get_active_provider(config: dict, user_id: int | None = None) -> Provider:
    """Single source of truth. Resolve which LLM provider is active.

    Priority:
        1. env LLM_PROVIDER (deployment override; never persisted)
        2. user_settings.llm_provider (per-user override, if user_id given)
        3. config["llm_provider"] (global yaml setting)
        4. legacy auto-detect: qwen key present -> qwen, else gemini
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

    # 4. legacy auto-detect
    has_qwen = bool((config.get("qwen") or {}).get("api_key"))
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
    """Check if the target provider has an API key configured."""
    if provider == "qwen":
        return bool((config.get("qwen") or {}).get("api_key"))
    return bool((config.get("gemini") or {}).get("api_key"))
