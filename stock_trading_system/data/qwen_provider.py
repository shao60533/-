"""Qwen (通义千问) data provider - last-resort fallback via LLM + web search.

Uses Alibaba DashScope's OpenAI-compatible API. The underlying model performs
a web search (Yahoo Finance / Google Finance / exchange sites) and returns a
structured JSON quote. This is intentionally used as the LAST fallback in the
data chain because each call costs LLM tokens and takes several seconds.

Scope:
- get_stock_price(ticker) — backup real-time quote
- screen_stocks(universe, strategy) — AI-driven ranking of candidates

NOT used for historical bars, fundamentals, or news (other providers cover
those reliably; LLM output for large datasets is unstable).
"""

import json
import re

from stock_trading_system.utils import get_logger

logger = get_logger("data.qwen")


_QUOTE_SYSTEM = (
    "You are a real-time stock quote service. When the user gives a ticker, "
    "use web search to find the latest available market price from reputable "
    "sources (Yahoo Finance, Google Finance, official exchanges, Sina/East "
    "Money for A-shares). Respond with ONLY a JSON object, no prose, no "
    "markdown fences. Schema: "
    '{"ticker":"<upper>","last":<number>,"open":<number|null>,'
    '"high":<number|null>,"low":<number|null>,"prev_close":<number|null>,'
    '"change":<number|null>,"change_pct":<number|null>,"volume":<number|null>,'
    '"currency":"<USD|CNY|HKD|...>","source":"<url or site name>",'
    '"as_of":"<ISO 8601 timestamp or date>"}. '
    'If you cannot find data, respond with {"error":"<short reason>"}.'
)


_SCREEN_SYSTEM = (
    "You are a stock screening assistant. Given a list of candidate tickers "
    "and a strategy (growth / value / momentum / low_volatility), use web "
    "search to gather recent fundamental and price information, then rank "
    "the candidates. Respond with ONLY a JSON object (no prose, no markdown "
    "fences). Schema: "
    '{"picks":[{"ticker":"<upper>","name":"<company>",'
    '"signal":"BUY|HOLD|SELL","score":<0-100>,'
    '"summary":"<one-line rationale>"}]}. '
    "Return at most the requested number of picks, sorted by score descending."
)


_FUNDAMENTALS_SYSTEM = (
    "You are a financial fundamentals service. Given a ticker, use web "
    "search to find the latest fundamental indicators from Yahoo Finance, "
    "East Money (东方财富), or exchange filings. Respond with ONLY a JSON "
    "object, no prose, no markdown fences. Schema: "
    '{"ticker":"<upper>","market_cap":<number|null>,'
    '"pe_ratio":<number|null>,"pb_ratio":<number|null>,'
    '"roe":<number|null>,"gross_margin":<number|null>,'
    '"net_margin":<number|null>,"revenue_growth":<number|null>,'
    '"dividend_yield":<number|null>,"beta":<number|null>,'
    '"week_52_high":<number|null>,"week_52_low":<number|null>,'
    '"eps":<number|null>,"confidence":"high|medium|low",'
    '"as_of":"<ISO date>","source":"<url or site name>"}. '
    "Percentage fields (roe, gross_margin, net_margin, revenue_growth, "
    "dividend_yield) should be expressed as percentages (e.g. 25.3 for "
    "25.3%, NOT 0.253). "
    'If you cannot find reliable data, respond with {"error":"<short reason>"}.'
)


_NEWS_SYSTEM = (
    "You are a financial news service. Given a ticker, use web search to "
    "find the most recent news (last 7 days) from Reuters, Bloomberg, CNBC, "
    "Sina Finance, or East Money. Respond with ONLY a JSON object. Schema: "
    '{"news":[{"title":"<string>","url":"<http(s) url>","date":"<ISO>",'
    '"source":"<site>","summary":"<one-sentence summary>"}]}. '
    "Return at most the requested number of items, sorted by most recent "
    "first. Skip items without a verifiable URL."
)


class QwenProvider:
    """Qwen LLM-backed fallback provider using DashScope OpenAI-compatible API."""

    def __init__(self, config: dict):
        qcfg = (config or {}).get("qwen", {}) or {}
        self._enabled = bool(qcfg.get("enabled") and qcfg.get("api_key"))
        self._api_key = qcfg.get("api_key", "")
        self._model = qcfg.get("model", "qwen-plus")
        self._base_url = qcfg.get(
            "base_url", "https://dashscope.aliyuncs.com/compatible-mode/v1"
        )
        self._timeout = float(qcfg.get("timeout", 30))
        self._client = None

    @property
    def enabled(self) -> bool:
        return self._enabled

    # ── Internal ──────────────────────────────────────────────────────────

    def _get_client(self):
        if self._client is None:
            try:
                from openai import OpenAI
            except ImportError as e:
                logger.error("openai SDK not installed: %s", e)
                return None
            self._client = OpenAI(
                api_key=self._api_key,
                base_url=self._base_url,
                timeout=self._timeout,
            )
        return self._client

    def _call(self, system_prompt: str, user_prompt: str) -> dict | None:
        """Invoke the chat completion API and return parsed JSON."""
        if not self._enabled:
            return None
        client = self._get_client()
        if client is None:
            return None

        try:
            resp = client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                response_format={"type": "json_object"},
                temperature=0.1,
                extra_body={"enable_search": True},
            )
        except Exception as e:
            logger.warning("Qwen API call failed: %s", e)
            return None

        try:
            content = resp.choices[0].message.content or ""
        except (AttributeError, IndexError) as e:
            logger.warning("Qwen response has no content: %s", e)
            return None

        return _parse_json(content)

    # ── Public ────────────────────────────────────────────────────────────

    def get_stock_price(self, ticker: str) -> dict | None:
        """Best-effort real-time quote via Qwen + web search."""
        if not self._enabled:
            return None

        data = self._call(
            _QUOTE_SYSTEM,
            f"Give me the latest real-time market quote for ticker {ticker}.",
        )
        if not data or "error" in data:
            if data and data.get("error"):
                logger.info("Qwen quote for %s: %s", ticker, data["error"])
            return None

        last = _to_float(data.get("last"))
        if last is None:
            logger.warning("Qwen returned no usable price for %s: %s", ticker, data)
            return None

        return {
            "ticker": ticker,
            "last": last,
            "open": _to_float(data.get("open")),
            "high": _to_float(data.get("high")),
            "low": _to_float(data.get("low")),
            "close": _to_float(data.get("prev_close")),
            "volume": _to_float(data.get("volume")),
            "change": _to_float(data.get("change")),
            "change_pct": _to_float(data.get("change_pct")),
            "currency": data.get("currency") or "",
            "source": "qwen:" + (data.get("source") or ""),
            "as_of": data.get("as_of") or "",
        }

    def get_fundamentals(self, ticker: str) -> dict | None:
        """Best-effort fundamentals via Qwen + web search.

        Returns a normalized dict (see validators in data.validators)
        or None on any failure. Raw numeric fields are converted via
        _to_float so callers get real numbers, not strings.
        """
        if not self._enabled:
            return None
        ticker = (ticker or "").upper().strip()
        if not ticker:
            return None

        data = self._call(
            _FUNDAMENTALS_SYSTEM,
            f"Give me the latest fundamental indicators for ticker {ticker}.",
        )
        if not data or "error" in data:
            if data and data.get("error"):
                logger.info("Qwen fundamentals for %s: %s", ticker, data["error"])
            return None

        result = {
            "ticker": ticker,
            "market_cap": _to_float(data.get("market_cap")),
            "pe_ratio": _to_float(data.get("pe_ratio")),
            "pb_ratio": _to_float(data.get("pb_ratio")),
            "roe": _to_float(data.get("roe")),
            "gross_margin": _to_float(data.get("gross_margin")),
            "net_margin": _to_float(data.get("net_margin")),
            "revenue_growth": _to_float(data.get("revenue_growth")),
            "dividend_yield": _to_float(data.get("dividend_yield")),
            "beta": _to_float(data.get("beta")),
            "week_52_high": _to_float(data.get("week_52_high")),
            "week_52_low": _to_float(data.get("week_52_low")),
            "eps": _to_float(data.get("eps")),
            "confidence": (data.get("confidence") or "medium").lower(),
            "as_of": data.get("as_of") or "",
            "source": "qwen:" + (data.get("source") or ""),
        }
        return result

    def get_news(self, ticker: str, limit: int = 10) -> list[dict]:
        """Recent news via Qwen + web search.

        Returns a list of dicts with keys: title, url, date, source, summary.
        Empty list on failure. Items without a plausible http(s) URL are
        filtered out to avoid garbage links.
        """
        if not self._enabled:
            return []
        ticker = (ticker or "").upper().strip()
        if not ticker:
            return []

        user_prompt = (
            f"Find the {max(1, int(limit))} most recent news articles about "
            f"ticker {ticker} from the last 7 days."
        )
        data = self._call(_NEWS_SYSTEM, user_prompt)
        if not data:
            return []
        raw = data.get("news") or []
        if not isinstance(raw, list):
            return []

        results: list[dict] = []
        for item in raw[: max(1, int(limit))]:
            if not isinstance(item, dict):
                continue
            url = (item.get("url") or "").strip()
            if not url.startswith(("http://", "https://")):
                continue  # drop unverifiable links
            title = (item.get("title") or "").strip()
            if not title:
                continue
            results.append({
                "title": title,
                "url": url,
                "date": (item.get("date") or "").strip(),
                "source": (item.get("source") or "").strip(),
                "summary": (item.get("summary") or "").strip(),
            })
        return results

    def materialize_universe(
        self,
        criteria=None,
        market: str = "us",
        count: int = 30,
        *,
        spec=None,
    ) -> list[dict]:
        """v1.3+: turn a FilterSpec (or NL criteria blob) into a fresh
        candidate ticker list.

        This is the **input → candidates** entry point used by
        ``UniverseFilter.filter_by_spec`` Layer A. Different intent
        from ``screen_stocks`` (which RANKS pre-supplied candidates).

        Two call shapes (v1.4):
        * ``materialize_universe(spec=FilterSpec(...))`` — preferred.
          Lets the prompt see structured sectors / themes / keywords /
          target_count separately, which produces tighter relevance
          than a flat criteria blob.
        * ``materialize_universe(criteria="natural language", ...)`` —
          legacy. Still supported so older call sites and tests keep
          working; internally we just stuff the string into the user
          prompt verbatim.

        Returns a list of ``{ticker, name?, sector?}`` dicts. Empty
        list on LLM unavailable / parsing failure / no usable picks.
        Uppercases tickers; preserves return order.
        """
        if not self._enabled:
            return []

        # Accept FilterSpec via positional too — convenience for callers
        # that don't bother with the kwarg.
        if spec is None and criteria is not None and not isinstance(criteria, str):
            spec = criteria
            criteria = None

        if spec is not None:
            market = (getattr(spec, "market", None) or market or "us").lower()
            count = count or getattr(spec, "target_count", None) or 30
            criteria = self._spec_to_criteria_blob(spec)
        elif criteria is None:
            return []

        target = max(1, int(count))
        # The system prompt mirrors ``UniverseFilter._llm_universe``
        # generic-fallback wording — same theme-fit / no-mega-cap
        # constraints — so both paths produce comparable lists.
        system = (
            "你是股票候选池生成助手。根据用户筛选条件返回候选股票代码。"
            "必须严格匹配用户主题，不要用泛大盘龙头、知名公司或高市值公司凑数。"
            "如果用户查询包含行业/主题词，只能返回与该主题有直接业务暴露的公司。"
            "「龙头股」表示该主题/行业内部的龙头，不是全市场市值龙头。"
            "中文「电力 / 电力股 / 公用事业」默认指 Utilities sector "
            "（NEE/SO/DUK/AEP/EXC/SRE/PEG/ED/XEL/D），不是泛能源、不是科技。"
            "中文「能源股 / 能源」默认指 Energy sector 油气链 "
            "（XOM/CVX/COP/EOG/SLB/LNG/MPC/PSX）；除非用户明确写「清洁能源」"
            "/「新能源」/「可再生」/「光伏」/「风电」/「储能」，否则不要"
            "把 NEE/FSLR/ENPH 当成默认能源股。"
            "中文「新能源」默认拆解为 EV + 光伏 + 风电 + 储能 + 可再生能源 "
            "（NEE/FSLR/ENPH/SEDG/BEP/CWEN/ARRY/FLNC），禁止混入 "
            "AAPL/BRK-B/V/JPM/META/MSFT/GOOGL 等泛大盘股或纯油气股。"
            "中文「存储」默认指存储芯片/内存/DRAM/NAND/闪存/SSD/HDD/数据存储硬件 "
            "（MU/WDC/STX/SNDK/MRVL/INTC/AMD/NVDA/AVGO）；只有用户明确写"
            "云存储/对象存储 时才把 AMZN/MSFT/GOOGL 视作主题成员。"
            "禁止为强主题查询返回 BRK-B/JPM/V/MA/PG/WMT/UNH 等泛大盘股。"
            f"市场: {market.upper()}。返回 JSON: "
            f"{{\"tickers\": [{{\"ticker\":\"...\", \"name\":\"...\", "
            f"\"sector\":\"...\"}}, ...]}}，不含其他文字。"
            f"目标数量约 {target}；若直接相关股票不足，可以少于目标数量，"
            "**绝对不允许用大盘股凑数**。"
        )
        data = self._call(system, criteria)
        if not data:
            return []
        raw = data.get("tickers") or data.get("stocks") or data.get("picks") or []
        if not isinstance(raw, list):
            return []
        out: list[dict] = []
        for item in raw[: target * 2]:  # cap so a chatty LLM can't blow up
            if isinstance(item, dict):
                t = (item.get("ticker") or item.get("symbol") or "").strip()
                if not t:
                    continue
                out.append({
                    "ticker": t.upper(),
                    "name":   (item.get("name") or "").strip(),
                    "sector": (item.get("sector") or "").strip(),
                })
            elif isinstance(item, str):
                t = item.strip()
                if t:
                    out.append({"ticker": t.upper(), "name": "", "sector": ""})
        return out

    @staticmethod
    def _spec_to_criteria_blob(spec) -> str:
        """v1.4: render a FilterSpec as a structured criteria blob for
        ``materialize_universe``. We keep each parsed dimension on its
        own labelled line so the LLM can ground each axis (sector vs
        theme vs keyword vs numeric criteria) instead of flattening
        them into a single fuzzy string. Used over the legacy ``;``
        joined blob from ``UniverseFilter._spec_to_nl_criteria``.
        """
        lines: list[str] = []
        raw_query = getattr(spec, "raw_query", None)
        if raw_query:
            lines.append(f"用户原始查询: {raw_query}")
        intent = getattr(spec, "intent_summary", None)
        if intent:
            lines.append(f"核心意图: {intent}")
        sectors = getattr(spec, "sectors", None) or []
        if sectors:
            lines.append("行业 (sector): " + ", ".join(sectors))
        themes = getattr(spec, "themes", None) or []
        if themes:
            lines.append("主题 (theme): " + ", ".join(themes))
        kw = getattr(spec, "natural_fallback", None) or []
        if kw:
            lines.append("关键词 (keywords): " + "; ".join(kw))
        excludes = getattr(spec, "exclude_tickers", None) or []
        if excludes:
            lines.append("排除股票: " + ", ".join(excludes))
        crit = getattr(spec, "criteria", None) or {}
        crit_bits: list[str] = []
        if crit.get("min_market_cap"):
            crit_bits.append(f"市值≥{int(crit['min_market_cap']/1e9)}B USD")
        if crit.get("max_pe"):
            crit_bits.append(f"PE≤{crit['max_pe']}")
        if crit.get("min_roe_pct"):
            crit_bits.append(f"ROE≥{crit['min_roe_pct']}%")
        if crit.get("min_revenue_growth_pct"):
            crit_bits.append(f"收入增速≥{crit['min_revenue_growth_pct']}%")
        if crit.get("min_dividend_yield_pct"):
            crit_bits.append(f"股息率≥{crit['min_dividend_yield_pct']}%")
        if crit_bits:
            lines.append("数值约束: " + "; ".join(crit_bits))
        target = getattr(spec, "target_count", None)
        if target:
            lines.append(f"目标候选数量约 {int(target)}")
        return "\n".join(lines) or "大盘优质股票"

    def screen_stocks(
        self,
        candidates: list[str],
        strategy: str = "growth",
        top_n: int = 10,
    ) -> list[dict]:
        """Use Qwen to rank candidate tickers for a given strategy.

        Returns a list of dicts with keys: ticker, name, signal, score, summary.
        Empty list on failure.
        """
        if not self._enabled or not candidates:
            return []

        # Cap input size to keep prompts reasonable
        universe = candidates[: max(top_n * 3, 30)]
        user_prompt = (
            f"Strategy: {strategy}\n"
            f"Candidates ({len(universe)}): {', '.join(universe)}\n"
            f"Please rank and return the top {top_n} picks."
        )

        data = self._call(_SCREEN_SYSTEM, user_prompt)
        if not data:
            return []

        picks = data.get("picks") or []
        if not isinstance(picks, list):
            return []

        results = []
        for p in picks[:top_n]:
            if not isinstance(p, dict):
                continue
            ticker = (p.get("ticker") or "").upper()
            if not ticker:
                continue
            results.append({
                "ticker": ticker,
                "name": p.get("name") or "",
                "signal": (p.get("signal") or "HOLD").upper(),
                "score": _to_float(p.get("score")) or 0,
                "summary": p.get("summary") or "",
            })
        return results


# ── Helpers ───────────────────────────────────────────────────────────────


def _parse_json(text: str) -> dict | None:
    """Parse JSON from LLM output, tolerating markdown fences or extra text."""
    if not text:
        return None
    s = text.strip()
    # Strip common ```json ... ``` fences
    if s.startswith("```"):
        s = re.sub(r"^```(?:json)?\s*", "", s)
        s = re.sub(r"\s*```$", "", s)
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        pass
    # Fallback: extract first balanced JSON object
    match = re.search(r"\{.*\}", s, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass
    return None


def _to_float(v) -> float | None:
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        s = v.strip().replace(",", "").replace("%", "")
        if not s or s.lower() in ("null", "none", "n/a", "--"):
            return None
        try:
            return float(s)
        except ValueError:
            return None
    return None
