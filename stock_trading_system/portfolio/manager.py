"""Portfolio manager - manual entry of positions with real-time P&L calculation."""

import json
import threading
import time as _time
from datetime import datetime
from stock_trading_system.utils.timez import now_local, now_utc, today_str_ny
from pathlib import Path

from stock_trading_system.portfolio.database import PortfolioDatabase
from stock_trading_system.portfolio.models import Position, Transaction, DailySnapshot
from stock_trading_system.data.data_manager import DataManager
from stock_trading_system.utils import get_logger
from stock_trading_system.utils.helpers import detect_market

logger = get_logger("portfolio.manager")


# ── Cross-request user-level holdings cache ─────────────────────────────────
#
# Dashboard first-paint and the /api/portfolio/{allocation,summary,pnl}
# endpoints all derive from get_holdings(). Without a cross-request cache,
# three concurrent requests from a single user trigger three parallel
# provider quote fetches against the same ticker list — on Railway with
# cold Schwab/yfinance connections this was the dominant cause of 30–70s
# /api/portfolio/* timings.
#
# Keyed by user_id only — the cache key changes implicitly when
# add/sell/remove/update_cost call _invalidate_user_holdings_cache(uid).
# Stale entries auto-expire after _HOLDINGS_CACHE_TTL_SEC; a lock guards
# read-modify-write so two threads can't double-fetch on a cache miss.
_HOLDINGS_CACHE_TTL_SEC = 45.0
_HOLDINGS_CACHE: dict[int, tuple[float, list[dict]]] = {}
_HOLDINGS_CACHE_LOCK = threading.Lock()


def _invalidate_user_holdings_cache(user_id: int) -> None:
    """Drop the cached holdings for one user.

    Called from every mutation path (buy / sell / remove / update_cost)
    so the next read sees the new position set without waiting out the
    TTL. Cheap and safe to call when nothing is cached.
    """
    with _HOLDINGS_CACHE_LOCK:
        _HOLDINGS_CACHE.pop(user_id, None)


def _read_user_holdings_cache(user_id: int) -> list[dict] | None:
    """Return cached holdings if fresh; else None and evict the stale entry."""
    with _HOLDINGS_CACHE_LOCK:
        entry = _HOLDINGS_CACHE.get(user_id)
        if entry is None:
            return None
        stored_at, holdings = entry
        if (_time.monotonic() - stored_at) > _HOLDINGS_CACHE_TTL_SEC:
            _HOLDINGS_CACHE.pop(user_id, None)
            return None
        return holdings


def _write_user_holdings_cache(user_id: int, holdings: list[dict]) -> None:
    with _HOLDINGS_CACHE_LOCK:
        _HOLDINGS_CACHE[user_id] = (_time.monotonic(), holdings)


# ── Price-fetch deadline budget ─────────────────────────────────────────────
#
# get_prices_batch (Schwab) and the per-ticker DataManager fallback
# (yfinance) used to run unbounded — when an upstream provider was slow
# this stalled the whole web request for tens of seconds. Each phase now
# runs under a wall-clock cap; whatever fails to come back in time is
# treated as "no quote" and the holding falls back to cost basis with
# price_source="cost" so the row still renders.
_BATCH_QUOTE_TIMEOUT_SEC = 6.0
_FALLBACK_QUOTE_TIMEOUT_SEC = 5.0


class PortfolioManager:
    """Portfolio manager with manual position entry and real-time P&L."""

    def __init__(
        self,
        config: dict | str,
        data_manager: DataManager | None = None,
    ):
        """Accepts either a config dict (production path) or a raw db_path
        string (lightweight test/CLI path).

        The string form is used by integration tests that just want to
        exercise add/sell/snapshot flows against a temp SQLite file
        without bootstrapping a full provider config. In that mode we
        still construct a DataManager but with an empty config, so the
        provider fan-out fails fast and ``get_holdings`` falls back to
        ``current_price=0`` instead of trying to hit a real network.
        """
        if isinstance(config, str):
            db_path = config
            self._config = {"portfolio": {"db_path": db_path}}
        else:
            self._config = config
            db_path = config.get("portfolio", {}).get("db_path", "data/portfolio.db")
        self._db = PortfolioDatabase(db_path)
        self._data_manager = data_manager or DataManager(self._config)

    # ── Manual Entry ─────────────────────────────────────────────────────

    def _user_id(self, user_id: int | None = None) -> int:
        """Resolve user_id: explicit param > flask g.user > raise.

        hardening-iteration-v1 P1.3: the legacy ``return None`` branch
        let cron/CLI callers fall into "no tenant filter" mode at the DB
        layer, producing cross-tenant aggregates (snapshots with
        ``user_id=NULL``, alert_history with no owner). Callers in
        non-request contexts (cron / CLI / worker) MUST now pass
        ``user_id=`` explicitly. Admin-only sweeps that legitimately
        span tenants should iterate users and call this per user_id,
        not pass ``None``.
        """
        if user_id is not None:
            return user_id
        try:
            from flask import g, has_request_context
            if has_request_context() and hasattr(g, "user") and g.user:
                return g.user.id
        except ImportError:
            pass
        raise RuntimeError(
            "PortfolioManager: missing tenant context. Pass user_id "
            "explicitly from worker/CLI/cron callers; never rely on "
            "implicit None — see hardening-iteration-v1 P1.3."
        )

    def add_position(
        self,
        ticker: str,
        shares: float,
        price: float,
        market: str | None = None,
        date: str | None = None,
        notes: str = "",
        user_id: int | None = None,
    ):
        """Record a buy and update position."""
        uid = self._user_id(user_id)
        market = market or detect_market(ticker)
        date = date or today_str_ny()
        timestamp = now_utc().strftime("%Y-%m-%d %H:%M:%S")

        txn = Transaction(
            id=None, ticker=ticker, action="buy",
            shares=shares, price=price, timestamp=timestamp, notes=notes, user_id=uid,
        )
        self._db.add_transaction(txn)

        existing = self._db.get_position(ticker, user_id=uid)
        if existing:
            total_cost = existing.shares * existing.avg_cost + shares * price
            new_shares = existing.shares + shares
            new_avg = total_cost / new_shares
            existing.shares = new_shares
            existing.avg_cost = new_avg
            self._db.upsert_position(existing)
        else:
            pos = Position(
                ticker=ticker, market=market,
                shares=shares, avg_cost=price, added_date=date, user_id=uid,
            )
            self._db.upsert_position(pos)

        logger.info("Added: BUY %s %s @ %s (user=%s)", shares, ticker, price, uid)
        _invalidate_user_holdings_cache(uid)

    def sell_position(
        self,
        ticker: str,
        shares: float,
        price: float,
        date: str | None = None,
        notes: str = "",
        user_id: int | None = None,
    ):
        """Record a sell and update position.

        Validates the holding *before* writing the transaction so a sell
        against a non-existent or under-held position raises instead of
        leaving an orphan SELL row in transactions. Web callers
        (``/api/portfolio/sell``) repeat this check at the route layer
        for a 400 with a clean error message; this guard is the
        last-resort defence for non-web callers.
        """
        uid = self._user_id(user_id)
        existing = self._db.get_position(ticker, user_id=uid)
        if existing is None:
            raise ValueError(f"No position to sell for {ticker} (user={uid})")
        if shares > existing.shares + 1e-9:
            raise ValueError(
                f"Sell shares ({shares}) exceeds holding ({existing.shares})"
            )

        timestamp = now_utc().strftime("%Y-%m-%d %H:%M:%S")
        txn = Transaction(
            id=None, ticker=ticker, action="sell",
            shares=shares, price=price, timestamp=timestamp, notes=notes, user_id=uid,
        )
        self._db.add_transaction(txn)

        remaining = existing.shares - shares
        if remaining <= 1e-9:
            self._db.delete_position(ticker, user_id=uid)
            logger.info("Sold all: %s %s @ %s (closed, user=%s)", shares, ticker, price, uid)
        else:
            existing.shares = remaining
            self._db.upsert_position(existing)
            logger.info("Sold: %s %s @ %s (remaining=%s, user=%s)",
                        shares, ticker, price, remaining, uid)
        _invalidate_user_holdings_cache(uid)

    def remove_position(self, ticker: str, user_id: int | None = None):
        """Remove a position entirely without recording a transaction."""
        uid = self._user_id(user_id)
        self._db.delete_position(ticker, user_id=uid)
        logger.info("Removed position: %s (user=%s)", ticker, uid)
        _invalidate_user_holdings_cache(uid)

    def update_cost(self, ticker: str, avg_cost: float, user_id: int | None = None):
        """Manually correct the average cost for a position."""
        uid = self._user_id(user_id)
        existing = self._db.get_position(ticker, user_id=uid)
        if existing:
            existing.avg_cost = avg_cost
            self._db.upsert_position(existing)
            logger.info("Updated avg cost for %s to %s (user=%s)", ticker, avg_cost, uid)
            _invalidate_user_holdings_cache(uid)

    # ── Queries ──────────────────────────────────────────────────────────

    def get_holdings(
        self,
        user_id: int | None = None,
        *,
        use_cache: bool = True,
    ) -> list[dict]:
        """Get all positions with real-time price and P&L.

        Caching layers (newest first):
            1. User-level cross-request cache (45s TTL) keyed by user_id.
               Same user hitting /api/dashboard, /api/portfolio/allocation,
               /api/portfolio/summary back-to-back reuses one snapshot
               instead of triggering N parallel provider fetches.
               Mutations call _invalidate_user_holdings_cache(uid) to
               drop the entry; the TTL is the safety net.
            2. Provider-level: Schwab batch quote for US tickers; misses
               + CN tickers fall back to per-ticker DataManager fetch
               (yfinance + LocalCache 60s).

        Price-fetch is bounded by a wall-clock budget per phase
        (_BATCH_QUOTE_TIMEOUT_SEC + _FALLBACK_QUOTE_TIMEOUT_SEC). Tickers
        with no quote in the window fall back to cost basis and are
        annotated with price_source="cost" and price_stale=True so the
        UI can show a "价格降级" hint instead of pretending the value
        is live.

        Pass use_cache=False from non-web callers that need a fresh
        snapshot (paper-trade snapshotter, cron sweeps).
        """
        uid = self._user_id(user_id)

        if use_cache:
            cached = _read_user_holdings_cache(uid, self._holdings_cache_scope)
            if cached is not None:
                return cached

        from concurrent.futures import (
            ThreadPoolExecutor, TimeoutError as FutTimeout, as_completed,
        )

        positions = self._db.get_all_positions(user_id=uid)
        if not positions:
            if use_cache:
                _write_user_holdings_cache(self._holdings_cache_scope, uid, [])
            return []

        # 1) Schwab batch for US tickers — one network call replaces N
        # calls, capped by _BATCH_QUOTE_TIMEOUT_SEC so an upstream stall
        # can't hold up the whole request.
        prices: dict[str, float] = {}
        sources: dict[str, str] = {}
        us_tickers = [p.ticker for p in positions if p.market == "us"]
        if us_tickers:
            batch = self._fetch_batch_with_timeout(
                us_tickers, market="us",
                timeout_sec=_BATCH_QUOTE_TIMEOUT_SEC,
            )
            for ticker, quote in (batch or {}).items():
                if quote:
                    price = quote.get("last") or quote.get("close") or 0
                    if price:
                        prices[ticker] = price
                        sources[ticker] = "realtime"

        # 2) Whatever the batch missed (and any CN positions) → per-ticker
        # fallback, capped by _FALLBACK_QUOTE_TIMEOUT_SEC across the whole
        # set. as_completed(timeout=...) raises if any future hasn't
        # finished by the deadline — we catch and break so the tickers
        # we *did* get back still land in `prices`.
        missing = [p for p in positions if p.ticker not in prices]
        if missing:
            def _fetch_price(pos):
                try:
                    data = self._data_manager.get_price(pos.ticker, market=pos.market)
                    if data:
                        return pos.ticker, (data.get("last") or data.get("close") or 0)
                    return pos.ticker, 0
                except Exception:  # noqa: BLE001
                    return pos.ticker, 0

            with ThreadPoolExecutor(max_workers=min(len(missing), 8)) as pool:
                futures = {pool.submit(_fetch_price, p): p for p in missing}
                deadline = _time.monotonic() + _FALLBACK_QUOTE_TIMEOUT_SEC
                try:
                    for f in as_completed(
                        futures,
                        timeout=_FALLBACK_QUOTE_TIMEOUT_SEC,
                    ):
                        ticker, price = f.result()
                        if price:
                            prices[ticker] = price
                            sources[ticker] = "realtime"
                        if _time.monotonic() >= deadline:
                            break
                except FutTimeout:
                    logger.warning(
                        "get_holdings fallback timeout user=%s "
                        "missing=%s budget=%ss",
                        uid, [p.ticker for p in missing],
                        _FALLBACK_QUOTE_TIMEOUT_SEC,
                    )

        holdings: list[dict] = []
        for pos in positions:
            if pos.ticker in prices and prices[pos.ticker] > 0:
                current_price = prices[pos.ticker]
                price_source = sources.get(pos.ticker, "realtime")
                price_stale = False
            elif pos.avg_cost > 0:
                # Provider didn't return a price in the deadline — fall back
                # to cost basis so the row still renders. PnL is 0 in this
                # state by definition; the price_stale flag tells the UI.
                current_price = pos.avg_cost
                price_source = "cost"
                price_stale = True
            else:
                current_price = 0
                price_source = "fallback"
                price_stale = True
            pnl = (current_price - pos.avg_cost) * pos.shares
            pnl_pct = ((current_price / pos.avg_cost) - 1) * 100 if pos.avg_cost > 0 else 0

            holdings.append({
                "ticker": pos.ticker,
                "market": pos.market,
                "shares": pos.shares,
                "avg_cost": pos.avg_cost,
                "current_price": current_price,
                "market_value": current_price * pos.shares,
                "cost_basis": pos.avg_cost * pos.shares,
                "pnl": pnl,
                "pnl_pct": pnl_pct,
                "added_date": pos.added_date,
                "price_source": price_source,
                "price_stale": price_stale,
            })

        if use_cache:
            _write_user_holdings_cache(self._holdings_cache_scope, uid, holdings)
        return holdings

    def _fetch_batch_with_timeout(
        self,
        tickers: list[str],
        market: str,
        timeout_sec: float,
    ) -> dict | None:
        """Run get_prices_batch in a worker thread with a hard timeout.

        DataManager.get_prices_batch is synchronous and provider-bound
        (Schwab); when the provider stalls there's no way to interrupt
        the underlying socket from inside the call. Submitting it to a
        ThreadPoolExecutor + Future.result(timeout=...) gives us a wall
        clock cap — on timeout we just abandon the future and return {}
        so callers fall back to per-ticker / cost basis.
        """
        from concurrent.futures import (
            ThreadPoolExecutor, TimeoutError as FutTimeout,
        )
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(
                self._data_manager.get_prices_batch, tickers, market=market,
            )
            try:
                return future.result(timeout=timeout_sec)
            except FutTimeout:
                logger.warning(
                    "get_prices_batch timeout market=%s n_tickers=%s budget=%ss",
                    market, len(tickers), timeout_sec,
                )
                return {}
            except Exception as e:  # noqa: BLE001
                logger.warning("get_prices_batch failed: %s", e)
                return {}

    @staticmethod
    def compute_pnl_from_holdings(holdings: list[dict]) -> dict:
        """Derive portfolio-level P&L from an existing holdings list.

        Cheap-only arithmetic — no provider calls. Used so /api/dashboard
        and other multi-derivation paths don't trigger a second
        get_holdings() (which would either double the latency or — when
        the cache TTL has fired — hit upstream providers twice).
        """
        total_cost = sum(h["cost_basis"] for h in holdings)
        total_value = sum(h["market_value"] for h in holdings)
        total_pnl = total_value - total_cost
        total_pnl_pct = ((total_value / total_cost) - 1) * 100 if total_cost > 0 else 0
        return {
            "total_cost": total_cost,
            "total_value": total_value,
            "total_pnl": total_pnl,
            "total_pnl_pct": total_pnl_pct,
            "positions": len(holdings),
        }

    @staticmethod
    def compute_allocation_from_holdings(holdings: list[dict]) -> list[dict]:
        """Derive position allocation breakdown from an existing holdings list."""
        total_value = sum(h["market_value"] for h in holdings)
        if total_value == 0:
            return []
        return [
            {
                "ticker": h["ticker"],
                "market": h["market"],
                "value": h["market_value"],
                "weight": h["market_value"] / total_value,
            }
            for h in sorted(holdings, key=lambda x: x["market_value"], reverse=True)
        ]

    def get_transactions(self, ticker: str | None = None, user_id: int | None = None) -> list[dict]:
        """Get transaction history."""
        uid = self._user_id(user_id)
        txns = self._db.get_transactions(ticker, user_id=uid)
        return [
            {
                "id": t.id,
                "ticker": t.ticker,
                "action": t.action,
                "shares": t.shares,
                "price": t.price,
                "date": t.timestamp,
                "notes": t.notes,
            }
            for t in txns
        ]

    def get_pnl(self, user_id: int | None = None) -> dict:
        """Get portfolio-level P&L summary."""
        holdings = self.get_holdings(user_id=user_id)
        return self.compute_pnl_from_holdings(holdings)

    def get_allocation(self, user_id: int | None = None) -> list[dict]:
        """Get position allocation breakdown."""
        holdings = self.get_holdings(user_id=user_id)
        return self.compute_allocation_from_holdings(holdings)

    # ── Snapshots ────────────────────────────────────────────────────────

    def take_snapshot(self, user_id: int | None = None):
        """Save a daily portfolio snapshot."""
        uid = self._user_id(user_id)
        holdings = self.get_holdings(user_id=uid)
        pnl = self.get_pnl(user_id=uid)

        snapshot = DailySnapshot(
            date=today_str_ny(),
            total_value=pnl["total_value"],
            total_cost=pnl["total_cost"],
            pnl=pnl["total_pnl"],
            pnl_pct=pnl["total_pnl_pct"],
            positions_json=json.dumps(holdings, default=str),
            user_id=uid,
        )
        self._db.save_snapshot(snapshot)
        logger.info("Snapshot saved for %s (user=%s)", snapshot.date, uid)

    def get_history(
        self,
        days: int | None = 30,
        user_id: int | None = None,
    ) -> list[dict]:
        """Get historical portfolio snapshots.

        Pass ``days=None`` for the entire series since the user's first
        snapshot. The result is ordered ascending so consumers can plot it
        as an equity curve without resorting.
        """
        uid = self._user_id(user_id)
        snapshots = self._db.get_snapshots(days, user_id=uid)
        return [
            {
                "date": s.date,
                "total_value": s.total_value,
                "total_cost": s.total_cost,
                "pnl": s.pnl,
                "pnl_pct": s.pnl_pct,
            }
            for s in snapshots
        ]
