"""Configuration management - load YAML config with environment variable overrides."""

import os
from pathlib import Path

import yaml


_config = None
_CONFIG_DIR = Path(__file__).parent
_DEFAULT_CONFIG = _CONFIG_DIR / "default_config.yaml"
_USER_CONFIG = Path.home() / ".stock_trading" / "config.yaml"


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
