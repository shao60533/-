"""Configuration dataclass for the iteration module."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ScorerConfig:
    extract_signals: bool = True
    backfill_5d: bool = True
    backfill_20d: bool = True
    rolling_window_days: int = 30
    min_samples: int = 5


@dataclass(frozen=True)
class DarwinianConfig:
    enabled: bool = True
    boost: float = 1.05
    decay: float = 0.95
    floor: float = 0.3
    ceiling: float = 2.5


@dataclass(frozen=True)
class MetaConfig:
    enabled: bool = False
    ab_test_days: int = 5
    max_rewrites_per_week: int = 1


@dataclass(frozen=True)
class IterationConfig:
    enabled: bool = False
    # 2026-05-04: switched to qwen3.6-max-preview per default_config.yaml.
    # ``fallback_model`` stays on the stable qwen-plus on purpose —
    # if a preview model 5xx/429s, falling back to another preview
    # defeats the resilience point.
    model: str = "qwen3.6-max-preview"
    fallback_model: str = "qwen-plus"
    scorer: ScorerConfig = field(default_factory=ScorerConfig)
    darwinian: DarwinianConfig = field(default_factory=DarwinianConfig)
    meta: MetaConfig = field(default_factory=MetaConfig)


def load_iteration_config(raw: dict) -> IterationConfig:
    """Build IterationConfig from the ``iteration:`` section of config.yaml."""
    if not raw:
        return IterationConfig()

    scorer_raw = raw.get("scorer", {})
    darwinian_raw = raw.get("darwinian", {})
    meta_raw = raw.get("meta", {})

    return IterationConfig(
        enabled=raw.get("enabled", False),
        model=raw.get("model", "qwen3.6-max-preview"),
        fallback_model=raw.get("fallback_model", "qwen-plus"),
        scorer=ScorerConfig(**{k: v for k, v in scorer_raw.items()
                               if k in ScorerConfig.__dataclass_fields__}),
        darwinian=DarwinianConfig(**{k: v for k, v in darwinian_raw.items()
                                     if k in DarwinianConfig.__dataclass_fields__}),
        meta=MetaConfig(**{k: v for k, v in meta_raw.items()
                           if k in MetaConfig.__dataclass_fields__}),
    )
