"""Lock the NL parser system prompt rules 9 (Chinese industry word
disambiguation) and 10 (theme-internal "龙头股") into a regression test.

Without these rules, the LLM lets "存储龙头股" project to mega-cap
broad-market names. We don't run the LLM here — we just assert the
prompt itself contains the language and example tickers we depend on,
so a future refactor that "tightens" the prompt can't quietly drop
them."""

from __future__ import annotations

from stock_trading_system.screener.v2 import nl_parser as _np


PROMPT = _np._SYSTEM_PROMPT


def test_prompt_has_storage_disambiguation_rule():
    assert "存储" in PROMPT
    # Must enumerate the storage sub-themes so the model doesn't drift
    # to "cloud storage" by default.
    for kw in ("内存", "DRAM", "NAND", "闪存", "SSD", "HDD"):
        assert kw in PROMPT, f"prompt missing storage keyword {kw!r}"


def test_prompt_forbids_broad_market_padding():
    # The polluters the user explicitly listed in the spec must appear
    # in the prompt as forbidden examples.
    for polluter in ("BRK-B", "JPM", "V", "MA", "UNH", "WMT", "PG"):
        assert polluter in PROMPT, (
            f"prompt should explicitly forbid {polluter} for themed queries"
        )


def test_prompt_carves_out_cloud_storage_explicit_keywords():
    # Cloud-storage carve-out must be explicit so the model only opens
    # AMZN/MSFT/GOOGL when the user wrote 云存储/对象存储/S3.
    for kw in ("云存储", "对象存储", "S3"):
        assert kw in PROMPT, f"prompt missing cloud-storage carve-out {kw!r}"
    for cloud in ("AMZN", "MSFT", "GOOGL"):
        assert cloud in PROMPT


def test_prompt_constrains_leader_keyword_to_user_theme():
    # Rule 10: 龙头 is theme-internal, not market-wide.
    assert "龙头" in PROMPT
    # The exact phrasing matters less than the contract — assert the
    # prompt clearly says "主题或行业内部" so the LLM doesn't free-fall
    # to market-cap leaders.
    assert "主题或行业内部" in PROMPT or "theme" in PROMPT.lower()
