"""Configuration management - load YAML config with environment variable overrides."""

import os
from pathlib import Path

import yaml


_config = None
_CONFIG_DIR = Path(__file__).parent
_DEFAULT_CONFIG = _CONFIG_DIR / "default_config.yaml"

# User-config location. Overridable via STOCK_CONFIG_DIR so that hosted
# deployments (e.g. Railway with a mounted volume at /data/stock_config) can
# persist API keys / writable settings on a filesystem that survives restarts.
_USER_CONFIG_DIR = Path(
    os.environ.get("STOCK_CONFIG_DIR") or (Path.home() / ".stock_trading")
)
_USER_CONFIG = _USER_CONFIG_DIR / "config.yaml"


def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge override into base."""
    merged = base.copy()
    for key, value in override.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _apply_env_overrides(config: dict) -> dict:
    """Override config values with environment variables.

    Mapping:
        GEMINI_API_KEY        -> config["gemini"]["api_key"]
        GEMINI_MODEL          -> config["gemini"]["model"]
        POLYGON_API_KEY       -> config["polygon"]["api_key"]
        IB_HOST               -> config["ib"]["host"]
        IB_PORT               -> config["ib"]["port"]
        TELEGRAM_BOT_TOKEN    -> config["alerts"]["telegram"]["bot_token"]
        TELEGRAM_CHAT_ID      -> config["alerts"]["telegram"]["chat_id"]
        EMAIL_SMTP_HOST       -> config["alerts"]["email"]["smtp_host"]
        EMAIL_USERNAME        -> config["alerts"]["email"]["username"]
        EMAIL_PASSWORD        -> config["alerts"]["email"]["password"]
        EMAIL_TO              -> config["alerts"]["email"]["to_address"]
    """
    env_map = {
        "GEMINI_API_KEY": ("gemini", "api_key"),
        "GEMINI_MODEL": ("gemini", "model"),
        "POLYGON_API_KEY": ("polygon", "api_key"),
        "DASHSCOPE_API_KEY": ("qwen", "api_key"),
        "QWEN_API_KEY": ("qwen", "api_key"),
        "QWEN_MODEL": ("qwen", "model"),
        "IB_HOST": ("ib", "host"),
        "IB_PORT": ("ib", "port"),
        "TELEGRAM_BOT_TOKEN": ("alerts", "telegram", "bot_token"),
        "TELEGRAM_CHAT_ID": ("alerts", "telegram", "chat_id"),
        "EMAIL_SMTP_HOST": ("alerts", "email", "smtp_host"),
        "EMAIL_USERNAME": ("alerts", "email", "username"),
        "EMAIL_PASSWORD": ("alerts", "email", "password"),
        "EMAIL_TO": ("alerts", "email", "to_address"),
        # Overridable SQLite path — used for PaaS deployments where only a
        # specific mounted volume is writable (e.g. Railway Volume at /data).
        "STOCK_DB_PATH": ("portfolio", "db_path"),
    }

    for env_var, path in env_map.items():
        value = os.environ.get(env_var)
        if value is not None:
            node = config
            for key in path[:-1]:
                node = node.setdefault(key, {})
            # Convert port to int
            if path[-1] == "port":
                value = int(value)
            node[path[-1]] = value

    # Auto-enable Qwen when its API key is provided via env var — setting the
    # env variable is a strong signal of intent, avoids the config.yaml trap.
    if os.environ.get("DASHSCOPE_API_KEY") or os.environ.get("QWEN_API_KEY"):
        config.setdefault("qwen", {})
        if config["qwen"].get("enabled") is not True:
            config["qwen"]["enabled"] = True

    return config


def load_config(config_path: str | None = None) -> dict:
    """Load configuration from YAML files and environment variables.

    Priority: env vars > user config > default config
    """
    global _config

    # Load default config
    with open(_DEFAULT_CONFIG) as f:
        config = yaml.safe_load(f)

    # Merge user config if it exists
    user_path = Path(config_path) if config_path else _USER_CONFIG
    if user_path.exists():
        with open(user_path) as f:
            user_config = yaml.safe_load(f) or {}
        config = _deep_merge(config, user_config)

    # Apply environment variable overrides
    config = _apply_env_overrides(config)

    _config = config
    return config


def get_config() -> dict:
    """Get the loaded configuration. Loads default if not yet loaded."""
    global _config
    if _config is None:
        _config = load_config()
    return _config


# Whitelist of dotted-path keys that the web settings editor is allowed to
# modify. Everything else is rejected to avoid accidental writes to internal
# structures (screener thresholds, report schedules, db paths, etc.).
WRITABLE_SETTING_PATHS: set[str] = {
    "gemini.api_key",
    "gemini.model",
    "gemini.deep_think_model",
    "gemini.thinking_level",
    "polygon.api_key",
    "qwen.enabled",
    "qwen.api_key",
    "qwen.model",
    "qwen.base_url",
    "ib.host",
    "ib.port",
    "ib.client_id",
    "ib.enabled",
    "alerts.check_interval",
    "alerts.telegram.bot_token",
    "alerts.telegram.chat_id",
    "alerts.telegram.enabled",
    "alerts.email.smtp_host",
    "alerts.email.smtp_port",
    "alerts.email.username",
    "alerts.email.password",
    "alerts.email.to_address",
    "alerts.email.enabled",
}


def _coerce_value(path: str, value):
    """Coerce a web-submitted value to the right Python type based on key hints."""
    if value is None:
        return value
    # Booleans
    if path.endswith(".enabled"):
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in ("1", "true", "yes", "on")
    # Integers
    if path.endswith(".port") or path.endswith(".client_id") or path == "alerts.check_interval":
        try:
            return int(value)
        except (TypeError, ValueError):
            return None
    # Everything else → string
    return "" if value is None else str(value)


def save_config(updates: dict) -> dict:
    """Merge *updates* into the user config YAML and reload.

    Simple top-level key merge (used by LLM provider switch API).
    """
    import tempfile, shutil

    _USER_CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    if _USER_CONFIG.exists():
        with open(_USER_CONFIG) as f:
            user_cfg = yaml.safe_load(f) or {}
    else:
        user_cfg = {}

    merged = _deep_merge(user_cfg, updates)

    fd, tmp = tempfile.mkstemp(dir=_USER_CONFIG_DIR, suffix=".yaml")
    try:
        with os.fdopen(fd, "w") as f:
            yaml.dump(merged, f, default_flow_style=False, allow_unicode=True)
        shutil.move(tmp, _USER_CONFIG)
    except Exception:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise

    return load_config()


def update_user_config(updates: dict) -> dict:
    """Write a sub-tree of settings to the user config file.

    `updates` is a flat dict mapping dotted paths (e.g. "gemini.api_key") to
    values. Paths not in WRITABLE_SETTING_PATHS are ignored. Empty-string
    values ARE written (they unset the key, useful for clearing a bad API
    key). The user-config YAML is loaded, merged, written back, and then
    `load_config()` is re-run so the in-memory config reflects the change.

    Returns the newly loaded merged config.
    """
    global _config
    # Read existing user config (not the merged view — we only want to write
    # the values the user has customized, not dump the full defaults).
    user_cfg: dict = {}
    if _USER_CONFIG.exists():
        with open(_USER_CONFIG) as f:
            loaded = yaml.safe_load(f) or {}
            if isinstance(loaded, dict):
                user_cfg = loaded

    applied: list[str] = []
    for raw_path, raw_val in (updates or {}).items():
        if raw_path not in WRITABLE_SETTING_PATHS:
            continue
        val = _coerce_value(raw_path, raw_val)
        if val is None and not raw_path.endswith(".enabled"):
            continue  # Invalid coercion (e.g. port="abc")
        parts = raw_path.split(".")
        node = user_cfg
        for p in parts[:-1]:
            if not isinstance(node.get(p), dict):
                node[p] = {}
            node = node[p]
        node[parts[-1]] = val
        applied.append(raw_path)

    # Ensure parent dir exists, then write.
    _USER_CONFIG.parent.mkdir(parents=True, exist_ok=True)
    with open(_USER_CONFIG, "w") as f:
        yaml.safe_dump(user_cfg, f, sort_keys=False, allow_unicode=True)

    # Reload so the in-memory config reflects the edit immediately.
    _config = None
    new_cfg = load_config()
    new_cfg["_applied_paths"] = applied  # non-persisted metadata for the caller
    return new_cfg
