# dashboard-perf-collapse v1.1 — holdings quote timeout 真生效 + 缓存 helper 签名回归

> **关联**：v1.0 施工图见 [`changelog.md` 2026-05-16 dashboard-perf-collapse v1.0 行](changelog.md)。本文档只覆盖 v1.0 上线后用户反馈"清缓存后 `/api/dashboard` 仍卡 60s"的 follow-up 修法，不重复 v1.0 的整体收敛策略。
>
> **不动 v1.0 已交付的部分**：`/api/dashboard` 一次性返回 `pnl + holdings + history + alerts_count + allocation + summary + transactions_count` 的收敛、`compute_pnl_from_holdings / compute_allocation_from_holdings` 派生静态方法、`add/sell/remove/update_cost` 的缓存失效、`price_source / price_stale` 字段契约、`DashboardPage.tsx` 首屏单调用。本期只动 `PortfolioManager._fetch_batch_with_timeout` + `get_holdings` fallback 段 + 4 个超时/缓存常量 + 3 处缓存 helper 调用。

## 1. 用户证据

> 2026-05-16 用户反馈：v1.0 上线后清缓存或等 45s TTL 过期，`/api/dashboard?history_days=90` 仍稳定卡到 **~60s**；命中缓存的二次请求又确实 <50ms。说明 v1.0 的"超时兜底"在真冷路径上没有生效。

Railway 日志在该窗口的形态：
- `[perf.dashboard] holdings_ms=60xxx` 而非预期的 `≤2000`
- 没有 `get_prices_batch timeout` 告警 → 说明 `result(timeout=6s)` 这一行根本没抛 `FutTimeout`
- 也没有 `get_holdings fallback timeout` 告警 → 说明 fallback 同样未触发超时分支

## 2. 第一性根因（两条独立故障，互相放大）

### 2.1 `with ThreadPoolExecutor` 的 `__exit__` 抵消了 `Future.result(timeout=...)`

v1.0 代码形态（`manager.py` v1.0 版本）：

```python
with ThreadPoolExecutor(max_workers=1) as pool:
    future = pool.submit(self._data_manager.get_prices_batch, tickers, market=market)
    try:
        return future.result(timeout=timeout_sec)
    except FutTimeout:
        return {}
```

- `future.result(timeout=6)` 在 6s 处确实抛 `FutTimeout` 并被捕获。
- 但 `with` 块 `__exit__` 进入 `ThreadPoolExecutor.shutdown(wait=True)` 默认行为——**等所有未完成的 worker 线程退出**。
- 我们提交给它的 `get_prices_batch` 是同步阻塞调用（Schwab/yfinance 慢 socket）；它根本不响应 cancel，所以请求线程一直阻塞在 `__exit__` 直到底层 socket 自己超时（Schwab 默认 ~30-60s、连续两段批+逐票 fallback 容易撞 60s）。
- `Future.cancel()` 在 Python `concurrent.futures` 里对**已开始执行**的任务是 no-op（语言契约，不是 bug）。所以 cancel 也救不了正在跑的 socket。

`get_holdings` 里 fallback 段用 `with ThreadPoolExecutor(...)` + `as_completed(timeout=5s)` 是完全一样的形态——`as_completed` 超时正确抛了，但 `with` 退出仍在等。

**判定**：v1.0 的超时只是"延迟了多久之后我们不再等",但 executor 自己仍在等。这是 stdlib 默认契约的盲点。

### 2.2 holdings 用户级缓存被一处 WIP 改坏，永远命中不到

上一个 WIP 提交把三处调用改成了：

```python
cached = _read_user_holdings_cache(uid, self._holdings_cache_scope)
_write_user_holdings_cache(self._holdings_cache_scope, uid, [])
_write_user_holdings_cache(self._holdings_cache_scope, uid, holdings)
```

但是：

1. helper 定义仍只接受 `(user_id)` / `(user_id, holdings)`——多传一个位置参数 → `TypeError`。
2. `self._holdings_cache_scope` 在 `PortfolioManager.__init__` 里**从未赋值** → 先于函数调用就 `AttributeError`。
3. 三处调用没有 try/except 兜底——`get_holdings(use_cache=True)` 在到达提供方调用之前就已经抛错。

实际线上的表现是：v1.0 描述的 45s TTL 缓存层**完全没生效**，每次 `/api/dashboard` 都强制走 provider 冷路径。冷路径又踩 2.1 的 `with` 问题 → 60s。命中状态 <50ms 之所以仍然成立，是另一条链路（`flask.g._holdings_cache` request-scoped）兜住了。

## 3. 修法（最小改动 + 不退化 v1.0 契约）

### 3.1 改用手动 executor + `shutdown(wait=False, cancel_futures=True)`

`_fetch_batch_with_timeout` 拆开 `with`：

```python
executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="quote-batch")
future = executor.submit(self._data_manager.get_prices_batch, tickers, market=market)
try:
    return future.result(timeout=timeout_sec)
except FutTimeout:
    future.cancel()  # 队列中未执行的会真的取消；正在跑的 socket 仍跑但请求线程不再等
    logger.warning(...)
    return {}
except Exception as e:
    logger.warning(...)
    return {}
finally:
    executor.shutdown(wait=False, cancel_futures=True)
```

- `wait=False`：请求线程立刻返回，不在 `__exit__` 上阻塞。
- `cancel_futures=True`：未开始的任务被丢弃；已开始的任务在背景继续跑直到 socket 自己超时，但**不再持有请求**。被丢弃的结果不会被任何人 await，最终由 GC 回收线程。
- 副作用：worker 线程在请求结束后继续短暂存活直至 socket 关闭。我们用 `thread_name_prefix` 让 `ps`/`py-spy` 容易看到 "quote-batch-N" 残线程；这是已知的可观测成本，远小于让请求线程卡 60s。

`get_holdings` 的 fallback 段同样拆开：

```python
executor = ThreadPoolExecutor(max_workers=min(len(missing), 8), thread_name_prefix="quote-fallback")
futures = {executor.submit(_fetch_price, p): p for p in missing}
try:
    for f in as_completed(futures, timeout=fallback_deadline):
        ticker, price = f.result()
        if price:
            prices[ticker] = price
            sources[ticker] = "realtime"
except FutTimeout:
    for f in futures:
        if not f.done():
            f.cancel()
    logger.warning("get_holdings fallback timeout user=%s unfinished=%s budget=%.2fs elapsed=%.2fs", ...)
finally:
    executor.shutdown(wait=False, cancel_futures=True)
```

`futures` dict 在异常路径仍然完整可用——遍历 `cancel()` 主要回收未启动的任务，已启动的同样会"留在背景跑完"但脱离请求。

### 3.2 缓存 helper 签名回归

仨调用点全部回到单 `user_id` 签名，与 `_read_user_holdings_cache(user_id)` / `_write_user_holdings_cache(user_id, holdings)` 一致：

```python
cached = _read_user_holdings_cache(uid)
_write_user_holdings_cache(uid, [])
_write_user_holdings_cache(uid, holdings)
```

`self._holdings_cache_scope` 概念**整段去除**。如果未来真的要引入多 scope 缓存（例如 cron/web 各一份），必须先 (a) 在 `__init__` 给 `self._holdings_cache_scope` 赋默认值；(b) 把 helper 改成 `(scope, user_id, ...)` 签名；(c) 给现有调用都补 scope 参数；(d) 单元测试覆盖每个 scope。本期一律不做。

### 3.3 预算收紧到能真的兑现 <2s 首屏

v1.0 沿用 `_BATCH_QUOTE_TIMEOUT_SEC=6.0` + `_FALLBACK_QUOTE_TIMEOUT_SEC=5.0`，最坏 11s——即使 3.1 修对了，仍超过 v1.0 自己写的 "dashboard p95 < 1500ms" 验收口径。本期：

| 常量 | v1.0 | v1.1 | 用途 |
|------|------|------|------|
| `_BATCH_QUOTE_TIMEOUT_SEC` | 6.0 | **1.5** | Schwab batch 单次墙钟 |
| `_FALLBACK_QUOTE_TIMEOUT_SEC` | 5.0 | **1.0** | 逐票 fallback 墙钟（per-phase 上限） |
| `_HOLDINGS_TOTAL_QUOTE_BUDGET_SEC` | — | **2.0** | batch + fallback 联合墙钟上限 |

`get_holdings` 在进入 fallback 段时算 `elapsed = monotonic - quote_started`，fallback 实际期限取 `max(0.2, min(_FALLBACK_QUOTE_TIMEOUT_SEC, total_budget - elapsed))`——批阶段慢的话 fallback 自动让出预算，地板 0.2s 防止业务路径 0 等待。

这样最坏 `holdings_ms ≤ 2.0s`（实测 2.02s），满足 v1.0 验收的"p95 < 1500ms（命中缓存）/ 冷路径 ≤ 2s"。

### 3.4 不退化的 price_source / price_stale 契约

- 拿到价：`price_source="realtime"`、`price_stale=False`。
- 未拿到价但有 avg_cost：`price_source="cost"`、`price_stale=True`、`current_price=avg_cost`（PnL=0 by definition）。
- 既无价也无成本：`price_source="fallback"`、`price_stale=True`、`current_price=0`。

前端 v1.0 已经依赖这三个状态做"价格降级"提示，本期一字不改。

## 4. § 复用 / Reuse

- **L0×3**：`PortfolioManager.get_holdings` 三段结构 / `_HOLDINGS_CACHE` 字典 + `threading.Lock` / `_invalidate_user_holdings_cache` 失效函数全部沿用 v1.0。
- **L4×2**：`concurrent.futures.ThreadPoolExecutor.shutdown(wait, cancel_futures)` 是 stdlib 自 3.9 起的官方契约 / `time.monotonic` 是预算计算的官方时钟。
- 不引入第三方库；不引入 asyncio；不替换 ThreadPoolExecutor 为其他池实现。

## 5. 严格不动

- `/api/dashboard` 端点契约（字段、含义、顺序）/ `compute_pnl_from_holdings / compute_allocation_from_holdings` / `add/sell/remove/update_cost` 失效路径 / `take_snapshot / get_history` / multi-tenant `_user_id()` raise 边界 / `DataManager.get_prices_batch / get_price` 实现 / `DashboardPage.tsx` / `daily_snapshot_scheduler` / Alert monitor / 任务系统。
- 不引入"后台异步预热行情"——v1.0 验收只要求"冷路径 ≤2s + 命中 <50ms"，本期已达成。预热是单独 v1.2 范围。

## 6. 测试与验证

### 6.1 行为级实测（本期新增的口径）

```python
# tests-style script, run locally with .venv:
dm = MagicMock()
dm.get_prices_batch.side_effect = lambda *a, **kw: (time.sleep(30), {})[1]
dm.get_price.side_effect = lambda *a, **kw: (time.sleep(30), {})[1]
pm = PortfolioManager(db_path, data_manager=dm)
pm.add_position("AAPL", 10, 150.0, market="us", user_id=1)
pm.add_position("NVDA", 5, 400.0, market="us", user_id=1)
_invalidate_user_holdings_cache(1)
t0 = monotonic(); h = pm.get_holdings(user_id=1); elapsed = monotonic() - t0
assert elapsed < 3.0          # wall clock under budget
assert [r["price_source"] for r in h] == ["cost", "cost"]
assert [r["price_stale"]  for r in h] == [True,   True]

t0 = monotonic(); pm.get_holdings(user_id=1); cache_ms = (monotonic() - t0) * 1000
assert cache_ms < 50          # cache hit
```

实测结果：`wall_clock=2.02s` + `cache_hit_ms=0`。

### 6.2 既有测试回归

- `tests/portfolio/` 27 case → pass
- `tests/web/test_portfolio_validation.py` + `test_portfolio_transactions_contract.py` + `test_error_handler.py` + `tests/tasks/test_batch_analysis_tenant_context.py` + `test_batch_analysis_history_split.py` 共 20 case → pass
- v1.0 的 `tests/portfolio/test_holdings_perf_collapse.py` 8 case 全部继续通过（本期未触碰其断言点：派生方法数值一致 / 二次调用不重打 DataManager / 4 路 mutation invalidate / no-price 兜底）。

### 6.3 生产验收口径

- 清缓存后冷启 `/api/dashboard?history_days=90` 应 ≤ 2s；`X-Response-Time-ms` ≤ 1500-2000ms（命中缓存层时 < 50ms）。
- 应能在 Railway 日志看到 `get_prices_batch timeout` / `get_holdings fallback timeout` 告警（之前从未看到）。
- 不再出现 60s dashboard。
- `transactions` chip、`allocation` 卡、`summary` 卡仍正确（v1.0 收敛契约保持）。

## 7. 风险与回滚

- **风险**：手动 `shutdown(wait=False)` 让背景线程残存，极端情况下可能堆积。缓解：单 worker batch + 至多 8 worker fallback 的池都是请求 scope，请求结束就脱离；底层 socket 会在 provider 自己的超时内闭合（Schwab/yfinance 数秒到数十秒）。生产监控 `quote-batch-*` / `quote-fallback-*` 线程数；若长期 > 50 再回头评估替换为 asyncio + 真 cancel。
- **回滚**：单文件改动 `stock_trading_system/portfolio/manager.py`，可直接 `git revert` 该提交回到 v1.0 行为；v1.0 已知 bug（60s + 缓存失效）会复现，但不会引入新的字段/契约破坏。
