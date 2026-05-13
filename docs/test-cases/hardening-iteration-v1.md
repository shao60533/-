# 测试用例：硬化迭代 v1（hardening-iteration-v1）

| 项 | 值 |
|---|---|
| Feature | `hardening-iteration-v1` |
| 版本 | v1.0 |
| 日期 | 2026-05-13 |
| 关联设计 | [../design/hardening-iteration-v1.md](../design/hardening-iteration-v1.md) |
| 关联 PRD | 内部驱动 / 无单独 PRD |
| 触发审查项 | 9 Critical + 16 High（2026-05-13 全仓 4 路并行审查） |

## 汇总

| 分类 | Phase | 用例数 |
|---|---|---|
| P0.1 CSRF（Flask-WTF 接入） | P0 | 12 |
| P0.2 漏装的 `@admin_required` | P0 | 6 |
| P0.3 alerts / portfolio owner 强制 | P0 | 12 |
| P0.4 登录 / 注册 / 邀请码限流 | P0 | 8 |
| P0.5 统一错误处理（不再泄栈） | P0 | 5 |
| P1.1 Telegram bot 白名单 | P1 | 8 |
| P1.2 删除 legacy TaskScheduler 跨租户路径 | P1 | 3 |
| P1.3 `_user_id() raise` + DB 层抛错 | P1 | 6 |
| P1.4 `cross_user_access` 矩阵（3 → 12+） | P1 | 14 |
| P1.5 `invariants` 补缺失字段 | P1 | 5 |
| P1.6 `task_manager.created_by` 不再 fallback 字符串 | P1 | 3 |
| P2.1+P2.2 LocalCache ttl 形参 + 未知 category 拒绝 | P2 | 10 |
| P2.3 Pickle → JSON | P2 | 3 |
| P2.4 Qwen prompt 主题表外置 | P2 | 3 |
| P2.5 datetime 时区统一 | P2 | 4 |
| P2.6 Paper Trade Decimal 化 | P2 | 8 |
| P2.7 Polygon 限速锁 + Provider Quote 抽象 | P2 | 5 |
| P3.1 screener v1/v2 → v3 收口 | P3 | 5 |
| P3.2 backtest.py 退役（口径统一） | P3 | 6 |
| P3.3 DataManager → DataRouter 收口 | P3 | 4 |
| P3.4 迁移系统轻量化（applied_migrations 表） | P3 | 6 |
| P3.5 analysis_history schema 统一 + task_events.seq DB 化 | P3 | 5 |
| P3.6 PortfolioDatabase 启用 WAL | P3 | 2 |
| P4 Blueprint 拆分（route parity / middleware） | P4 | 8 |
| E2E：安全端到端 | 跨 Phase | 6 |
| 性能与回归 | 跨 Phase | 4 |
| **合计** | | **151** |

---

## 1. P0.1 CSRF（Flask-WTF 接入）（12）

### 单元：CSRFProtect 初始化（3）

**TC-HD-C1-1**：`create_app()` 调用后，`app.extensions["csrf"]` 存在且类型为 `CSRFProtect`

**TC-HD-C1-2**：`app.config["WTF_CSRF_TIME_LIMIT"]` 设为合理值（≥ 3600s，session 过期前不会被反复挑战）

**TC-HD-C1-3**：`app.config["WTF_CSRF_SSL_STRICT"]` 在生产环境（`debug=False`）为 `True`

### 集成：敏感路由 CSRF 校验（6）

每条用例：无 `X-CSRF-Token` header 的 POST 返回 400，带正确 token 返回 200/正常业务码。

**TC-HD-C1-4**：`POST /api/portfolio/sell`

**TC-HD-C1-5**：`POST /api/alerts/remove`

**TC-HD-C1-6**：`POST /api/settings`

**TC-HD-C1-7**：`POST /api/scheduler/start`

**TC-HD-C1-8**：`POST /api/backtest/run`

**TC-HD-C1-9**：`DELETE /api/portfolio/<ticker>`

### 集成：白名单路由不被校验（3）

每条用例：无 CSRF token 的 POST 仍按业务正常处理。

**TC-HD-C1-10**：`POST /api/auth/login` 接受无 CSRF token 请求（登录前用户没法拿 token）

**TC-HD-C1-11**：`POST /api/auth/register` 同上

**TC-HD-C1-12**：`POST /oauth/google/callback` `/oauth/github/callback` `/oauth/schwab/callback` 同上（第三方 redirect）

---

## 2. P0.2 漏装的 `@admin_required`（6）

每条用例：role=user 账号请求返 403；admin 账号正常 200/业务返回。

**TC-HD-C2-1**：`GET /api/settings` 普通用户 403

**TC-HD-C2-2**：`POST /api/settings` 普通用户 403（防 C3：改 API key 提权）

**TC-HD-C2-3**：`POST /api/scheduler/start` 普通用户 403

**TC-HD-C2-4**：`POST /api/scheduler/stop` 普通用户 403

**TC-HD-C2-5**：`POST /api/scheduler/run-now` 普通用户 403（确认未回归）

**TC-HD-C2-6**：`POST /api/admin/invites` 创建邀请码普通用户 403（确认未回归）

---

## 3. P0.3 alerts / portfolio owner 强制（12）

### `monitor.py` / `database.py` 签名（4）

**TC-HD-C3-1**：`AlertMonitor.remove_alert(alert_id)` 不传 `user_id` 抛 `TypeError`

**TC-HD-C3-2**：`PortfolioDatabase.remove_alert(alert_id, user_id)` 别人的 alert_id rowcount=0 抛 `NotFound`

**TC-HD-C3-3**：`PortfolioDatabase.save_alert_trigger(...)` 不传 `user_id` 抛 `TypeError`

**TC-HD-C3-4**：`PortfolioDatabase.get_alert_history(user_id)` 仅返当前用户的 trigger 行

### IDOR 防御（4）

每条用例：alice 创建资源 → bob 用 alice 的 id 操作 → 返 404（不暴露资源存在）。

**TC-HD-C3-5**：`POST /api/alerts/remove` bob 删 alice 的 alert → 404

**TC-HD-C3-6**：`GET /api/alerts/history` bob 看不到 alice 的 trigger（按 user 过滤）

**TC-HD-C3-7**：`DELETE /api/portfolio/<ticker>` bob 删 alice 的同 ticker → 404（bob 无该持仓）

**TC-HD-C3-8**：`POST /api/portfolio/update_cost` bob 改 alice 的成本 → 404

### 显式 `g.user` 检查（4）

**TC-HD-C3-9**：匿名请求 `/api/alerts/remove` 走 `enforce_auth` 拦截 → 401

**TC-HD-C3-10**：匿名请求 `/api/alerts/history` 同上 → 401

**TC-HD-C3-11**：`alert_history` 写入端必含 `user_id`（grep `save_alert_trigger` 调用，所有调用方都传值）

**TC-HD-C3-12**：`invariants.run_all()` 失败如果存在 `alert_history.user_id IS NULL` 行（联动 P1.5）

---

## 4. P0.4 登录 / 注册 / 邀请码限流（8）

**TC-HD-C4-1**：`POST /api/auth/login` 同 IP 11 次/分钟 → 第 11 次返 429 + `Retry-After`

**TC-HD-C4-2**：`POST /api/auth/login` 同邮箱 6 次/分钟 → 第 6 次返 429（防穷邮箱不变 IP）

**TC-HD-C4-3**：`POST /api/auth/register` 同 IP 6 次/小时 → 429

**TC-HD-C4-4**：`POST /api/auth/invites/validate` 同 IP 21 次/小时 → 429（防邀请码扫码）

**TC-HD-C4-5**：429 响应体含 `{"error": "rate_limited", "retry_after_seconds": <int>}`

**TC-HD-C4-6**：登录成功后不计入失败次数（IP 计数器仅累积失败）

**TC-HD-C4-7**：限流计数器 storage 在进程重启后清零（本期用内存 storage 可接受）

**TC-HD-C4-8**：管理员账号不受 `/api/admin/invites` 路由限流影响（白名单 role=admin）

---

## 5. P0.5 统一错误处理（不再泄栈）（5）

**TC-HD-C5-1**：触发未预期异常的端点（如 mock 一个 raise）→ 500 响应体仅 `{"error":"internal","trace_id":"<hex>"}`

**TC-HD-C5-2**：500 响应体 **不含** `Traceback`、provider 名（`schwab`/`polygon`）、文件路径

**TC-HD-C5-3**：`trace_id` 在 logger 输出中可被 grep 到对应 traceback（关联性）

**TC-HD-C5-4**：grep `web/app.py` 中 `return jsonify({"error": str(e)})` 模式 0 命中

**TC-HD-C5-5**：业务可预期错误（400/401/403/404）保留原 message，不被全局 handler 吞掉

---

## 6. P1.1 Telegram bot 白名单（8）

### 配置加载（2）

**TC-HD-T1-1**：`config.telegram.allowed_chat_ids = []` 时 bot 启动失败 / 拒绝处理任何命令（log warning）

**TC-HD-T1-2**：`config.telegram.user_map = {<chat_id>: <email>}` 时启动后构建 `chat_id → user_id` 映射，邮箱不存在的 chat_id 启动失败 fail-fast

### 授权（4）

**TC-HD-T1-3**：未授权 chat_id 发 `/buy AAPL 100 150` → bot 回 "未授权" 拒绝消息

**TC-HD-T1-4**：未授权 chat_id 发 `/alert AAPL price_above 200` → 同上拒绝

**TC-HD-T1-5**：已授权 chat_id 发 `/buy` 命令 → `pm.add_position(user_id=<resolved>, ...)` 落到对应用户

**TC-HD-T1-6**：已授权 chat_id 发 `/list_alerts` → 仅返自己 user_id 下的 alert（不是 `scope="all"`）

### 回归（2）

**TC-HD-T1-7**：bot 启动配置缺失时不破坏 web/CLI 入口（log warning 但 Flask 正常起）

**TC-HD-T1-8**：grep `monitor.list_alerts(scope="all")` 在 telegram_bot.py 0 命中

---

## 7. P1.2 删除 legacy TaskScheduler 跨租户路径（3）

**TC-HD-T2-1**：grep `_post_market_close` 在 `stock_trading_system/` 0 命中

**TC-HD-T2-2**：`POST /api/scheduler/start` 调用后不再触发 `take_snapshot()` 全租户路径（mock 检查）

**TC-HD-T2-3**：`invariants.py` 加 `daily_snapshots.user_id IS NULL → 0 条` 规则，CI 跑 `validation.run_all` 通过

---

## 8. P1.3 `_user_id() raise` + DB 层抛错（6）

**TC-HD-T3-1**：cron 上下文（无 `flask.g.user`）调 `PortfolioManager._user_id()` 抛 `RuntimeError("missing tenant context")`

**TC-HD-T3-2**：`PortfolioDatabase.get_holdings(user_id=None)` 抛 `RuntimeError`

**TC-HD-T3-3**：`PortfolioDatabase.get_holdings(user_id=None, _admin_scope=True)` 返全租户（admin 显式参数）

**TC-HD-T3-4**：`DailySnapshotScheduler.take_snapshot_all_users()` 通过 `_admin_scope=True` 正常工作

**TC-HD-T3-5**：grep `Optional\[int\]` 在 `database.py` 的 `user_id` 形参上 0 命中

**TC-HD-T3-6**：故意触发匿名路径 → trace_id 出现在 logger，500 响应不泄栈（联动 P0.5）

---

## 9. P1.4 `cross_user_access` 矩阵全覆盖（14）

> CI fixture 自动创建 `(admin@local / alice@test / bob@test)` 三账号。每条用例：alice 创建资源 → bob 操作 → 期望 403/404。

| TC | 端点 | 期望 |
|---|---|---|
| **TC-HD-T4-1** | `POST /api/alerts/remove` | 404（已在 P0.3 测，此处加入矩阵 fixture） |
| **TC-HD-T4-2** | `GET /api/alerts/history?ticker=AAPL` | 200 但 body 不含 alice 的 trigger 行 |
| **TC-HD-T4-3** | `GET /api/alerts/list` | 200 但 body 不含 alice 的 alert 行 |
| **TC-HD-T4-4** | `DELETE /api/portfolio/<ticker>` | 404 |
| **TC-HD-T4-5** | `POST /api/portfolio/update_cost` | 404 |
| **TC-HD-T4-6** | `POST /api/portfolio/snapshot` | 200（每个用户独立 snapshot），但 alice 的快照不变 |
| **TC-HD-T4-7** | `GET /api/portfolio/history` | 200 但 body 不含 alice 的交易行 |
| **TC-HD-T4-8** | `DELETE /api/analysis/<id>` | 共享数据：alice 创建的 analysis bob 不能删（看 design `created_by` 校验），403 |
| **TC-HD-T4-9** | `DELETE /api/analysis_bookmark/<id>` | 404 |
| **TC-HD-T4-10** | `GET /api/paper/sessions/<alice_session_id>` | 404 |
| **TC-HD-T4-11** | `POST /api/paper/sessions/<alice_session_id>/entry` | 404 |
| **TC-HD-T4-12** | `POST /api/settings` (bob = role=user) | 403（非 admin，联动 P0.2 / C3） |
| **TC-HD-T4-13** | `POST /api/scheduler/start` (bob = role=user) | 403（联动 P0.2 / H1） |
| **TC-HD-T4-14** | `POST /api/tasks/<alice_task_id>/cancel` | 404 |

---

## 10. P1.5 `invariants` 补缺失字段（5）

每条用例：故意写入违反不变式的数据 → `invariants.run_all()` 返非 0 退出码 + 列出违规行数。

**TC-HD-T5-1**：`alert_history.user_id IS NULL` 行存在时失败

**TC-HD-T5-2**：`user_analysis_advice.analysis_id` 不存在于 `analysis_history` 时失败

**TC-HD-T5-3**：`task_events.user_id` 非 INTEGER（字符串 `"user"`）时失败

**TC-HD-T5-4**：`daily_snapshots.user_id IS NULL` 行存在时失败

**TC-HD-T5-5**：`tasks.created_by IS NULL` 行存在时失败

---

## 11. P1.6 `task_manager.created_by` 不再 fallback 字符串（3）

**TC-HD-T6-1**：`TaskManager.submit(..., created_by=None)` 在 `flask.g.user` 缺失时抛 `RuntimeError`

**TC-HD-T6-2**：grep `created_by = "user"` 在 `tasks/task_manager.py` 0 命中

**TC-HD-T6-3**：`task_events.user_id` 全表 INTEGER（pytest 启动前跑 P3.4 迁移）

---

## 12. P2.1 + P2.2 LocalCache ttl 形参 + 未知 category 拒绝（10）

### ttl 形参传递（4）

**TC-HD-D1-1**：`local_cache.set(category, key, value, ttl=60)` 写入后 60s 内 `get` 命中，60s 后 miss

**TC-HD-D1-2**：`local_cache.set(category, key, value)`（ttl=None）走 `_DEFAULT_TTL[category]`

**TC-HD-D1-3**：v3 cache.py 调用 `local_cache.set(..., ttl=...)` 不再抛 `TypeError`（联动 C7）

**TC-HD-D1-4**：v3 guru pipeline 跑两次同 ticker → 第二次 `metrics.cache_hits > 0`

### 未知 category 拒绝（4）

**TC-HD-D2-1**：`local_cache.set("unknown_xyz", key, value)` 默认拒绝写入 + `logger.warning`

**TC-HD-D2-2**：`local_cache.set("unknown_xyz", key, value, ttl=300, unsafe_default=False)` 仍拒绝（unsafe_default 是显式开关）

**TC-HD-D2-3**：`local_cache.set("unknown_xyz", key, value, ttl=300, unsafe_default=True)` 允许写入（dev 场景兜底）

**TC-HD-D2-4**：`_DEFAULT_TTL` 注册表至少含 `regime` `guru_signal_v3` `screen_results` `roundtable` `quote_intraday` 等当前实际在用的 category

### 回归（2）

**TC-HD-D2-5**：grep `Unknown cache category` warning 在 staging 环境冒烟时 0 命中

**TC-HD-D2-6**：旧 category（已注册）写入行为不变（向后兼容）

---

## 13. P2.3 Pickle → JSON（3）

**TC-HD-D3-1**：`local_cache.set(...)` 写入后 SQLite payload 列是合法 JSON 字符串（非 pickle bytes）

**TC-HD-D3-2**：`local_cache.get(...)` 读出与写入对象 deep-equal（含嵌套 dict / list / None）

**TC-HD-D3-3**：grep `pickle.loads\|pickle.load\b` 在 `stock_trading_system/` 0 命中（除 tests/）

---

## 14. P2.4 Qwen prompt 主题表外置（3）

**TC-HD-D4-1**：`config/themes.yaml` 存在且可被 `qwen_provider` 加载

**TC-HD-D4-2**：grep `NEE.*SO.*DUK\|FSLR.*ENPH.*SEDG\|MU.*WDC.*STX` 在 `.py` 文件 0 命中

**TC-HD-D4-3**：`themes.yaml` 中改一个主题的股票列表 → `materialize_universe` 立即生效（无需重启 / 也无热重载，下次进程启动生效，注释里写明）

---

## 15. P2.5 datetime 时区统一（4）

**TC-HD-D5-1**：`utils/timez.now_utc()` 返 tz-aware datetime（`.tzinfo is not None`）

**TC-HD-D5-2**：`utils/timez.now_ny()` 在 UTC 主机上返 ET 时间（手动 mock 系统时钟验证）

**TC-HD-D5-3**：grep `datetime.now()\|datetime.utcnow()` 在 `stock_trading_system/` `.py` 文件 0 命中（除 `utils/timez.py`）

**TC-HD-D5-4**：所有 `*_at` 字段写入 DB 时带时区（UTC ISO 8601 / `+00:00` 后缀）

---

## 16. P2.6 Paper Trade Decimal 化（8）

**TC-HD-D6-1**：`PaperSession.cash` 类型为 `Decimal`

**TC-HD-D6-2**：1000 次 buy/sell 循环后 cash 与解析期望值**完全相等**（不用 `pytest.approx`）

**TC-HD-D6-3**：commission / slippage 字段类型为 `Decimal`

**TC-HD-D6-4**：`(exit_price / entry_price) - 1` 比率仍保留 float（约定见 design §3.3 P2.6）

**TC-HD-D6-5**：feature flag `paper_trade_decimal=false` 时退回 float 路径（向后兼容窗口）

**TC-HD-D6-6**：feature flag `=true` 默认开启后，旧 session 数据自动 `Decimal.from_float()` 平移而非重算（精度无漂移）

**TC-HD-D6-7**：JSON 序列化时 `Decimal` 转字符串而非 float（API 响应不丢精度）

**TC-HD-D6-8**：grep `float(.*price\|float(.*cash\|float(.*pnl` 在 `paper_trader/` 0 命中

---

## 17. P2.7 Polygon 限速锁 + Provider Quote 抽象（5）

**TC-HD-D7-1**：50 并发线程调 `polygon_provider.get_stock_price(...)` 不触发 429（threading.Lock 生效）

**TC-HD-D7-2**：`Quote` Pydantic 模型字段：`last_price: Decimal, as_of_ts: datetime, is_realtime: bool, source: str`

**TC-HD-D7-3**：Polygon 返"前一日收盘"时 Quote 标 `is_realtime=False`（不再冒充实时）

**TC-HD-D7-4**：DataManager 链式回落时 Quote 的 `source` 字段如实标记（`schwab` / `ib` / `polygon` / `yfinance` / `qwen`）

**TC-HD-D7-5**：所有 6 个 provider 都实现 `BaseQuoteProvider`（mypy / `isinstance` 校验）

---

## 18. P3.1 screener v1/v2 → v3 收口（5）

**TC-HD-V1-1**：grep `from stock_trading_system.screener import StockScreener\|from .screener import` 在非 deprecated shim 0 命中

**TC-HD-V1-2**：`web/app.py` `/api/screen/*` 路由调用 v3 pipeline

**TC-HD-V1-3**：`main.py screen` CLI 命令调用 v3 pipeline

**TC-HD-V1-4**：`telegram_bot.py` `/screen` 命令调用 v3 pipeline

**TC-HD-V1-5**：v1 / v2 模块顶部 `DeprecationWarning` 触发（pytest -W error::DeprecationWarning 命中）

---

## 19. P3.2 backtest.py 退役（口径统一）（6）

**TC-HD-V2-1**：web 入口（`/api/backtest/run`）与 worker 入口（`make_backtest_worker`）对同一 ticker + 同一策略 + 同一时间窗回测，关键字段（`total_return` / `annualized_return` / `sharpe` / `max_drawdown`）**完全相等到小数点后 4 位**

**TC-HD-V2-2**：返回 dict 同时含 `total_return` 和 `total_return_pct`（兼容字段，UI 不动）

**TC-HD-V2-3**：年化基数统一为 252（grep `* 365 /\|/ 365 *` 在 `strategy/` 0 命中）

**TC-HD-V2-4**：滑点参数化（默认 0.001），非默认值通过 `slippage` 参数传入

**TC-HD-V2-5**：RSI 实现统一为 Wilder EWM（grep `rolling(.*\.mean()\|SMA` 在 RSI 计算中 0 命中）

**TC-HD-V2-6**：`strategy/backtest.py` 仅保留一周 import shim（顶部 `DeprecationWarning + from .backtester import BacktestEngine as Backtester`）

---

## 20. P3.3 DataManager → DataRouter 收口（4）

**TC-HD-V3-1**：`DataManager.get_stock_price(...)` 内部 delegate 到 `DataRouter`（mock DataRouter 检查调用）

**TC-HD-V3-2**：`DataManager` 启动后 IB / Polygon **不**默认 skipped（修复 `_SKIP_THRESHOLD=1` dead code）

**TC-HD-V3-3**：grep `import yfinance\|yf.Ticker\|yf.download` 仅在 `yfinance_provider.py` 命中

**TC-HD-V3-4**：`regime_detector.py` / `data_helper.py` / `backtester.py._default_history_fn` 都改用 `YFinanceProvider`

---

## 21. P3.4 迁移系统轻量化（applied_migrations 表）（6）

**TC-HD-V4-1**：fresh DB 跑全迁移成功，`applied_migrations` 表含 9 行（8 个现有 + `0000_v0_baseline`）

**TC-HD-V4-2**：同一 DB 重复跑迁移幂等（无副作用、无报错、退出码 0）

**TC-HD-V4-3**：缺失 / 跳过 / 顺序错的迁移会触发 fail-fast（CI 检测）

**TC-HD-V4-4**：每个迁移在 docstring 含 `-- DOWN: ...` 注释（人工回滚参考；本期不做自动 down）

**TC-HD-V4-5**：首次接入老 DB 时 `applied_migrations` 空 → 自动把现有 schema 当作 v0 baseline 标记已完成

**TC-HD-V4-6**：迁移过程中断（kill -9）→ 未完成迁移不写入 `applied_migrations`（事务保证）

---

## 22. P3.5 analysis_history schema 统一 + task_events.seq DB 化（5）

**TC-HD-V5-1**：`schema/analysis_history.py` 是唯一 schema 定义源，`portfolio/database.py` 和 `tasks/task_store.py` 都 import 同一个 DDL

**TC-HD-V5-2**：grep `CREATE TABLE.*analysis_history` 在 `database.py` + `task_store.py` 0 命中（仅在 schema/ 命中）

**TC-HD-V5-3**：`event_emitter.append_event(task_id, kind, ...)` 进程重启后追加，seq 继续递增（不从 1 开始）

**TC-HD-V5-4**：grep `_seq_cache` 在 `tasks/event_emitter.py` 0 命中

**TC-HD-V5-5**：并发 50 线程对同 task_id 写事件，无 `INSERT OR IGNORE` 丢事件（每条都落库）

---

## 23. P3.6 PortfolioDatabase 启用 WAL（2）

**TC-HD-V6-1**：`PortfolioDatabase._get_conn()` 返回连接执行 `PRAGMA journal_mode` 返回 `wal`

**TC-HD-V6-2**：并发 50 线程读写 `positions` + `alerts` 不出现 `database is locked` 异常

---

## 24. P4 Blueprint 拆分（route parity / middleware）（8）

### Route parity（3）

**TC-HD-W1-1**：拆分前 snapshot `app.url_map`（路由 URL + HTTP method 集合）

**TC-HD-W1-2**：拆分后 `app.url_map` 与 snapshot **集合相等**（不增不减）

**TC-HD-W1-3**：每个 Blueprint 文件 < 600 行（`web/app.py` < 500 行）

### Service 函数单测（3）

**TC-HD-W2-1**：`web/services/portfolio_service._compute_today_pnl(...)` 独立单测（不依赖 Flask 上下文）

**TC-HD-W2-2**：`web/services/tasks_service._check_task_ownership(...)` 独立单测

**TC-HD-W2-3**：`web/services/paper_service._validate_trade(...)` 独立单测

### Middleware（2）

**TC-HD-W3-1**：每个 request 在 `flask.g.trace_id` 上有 hex32 字符串；同一 request 内多次读返回同值

**TC-HD-W3-2**：敏感操作（settings 改 / portfolio sell / alert remove / scheduler start）落到 `audit_log` 表 + 含 `user_id` `trace_id` `path` `body_digest`

---

## 25. E2E：安全端到端（6）

每条 Playwright / pytest-flask 流程化用例。

**TC-HD-E1**：未登录访问 `/dashboard` → 重定向 `/login`，登录后回到 `/dashboard`

**TC-HD-E2**：CSRF 攻击场景：第三方页面 form 自动 POST `/api/portfolio/sell` 携带 cookie → 400（CSRF 失败）

**TC-HD-E3**：IDOR 端到端：alice 登录创建 alert → bob 在另一浏览器登录拿 alert_id 试删 → 404

**TC-HD-E4**：role=user 用户在 Settings 页看不到 `/api/settings` 的 LLM provider 切换按钮（前端 admin gate + 后端 admin gate 双重）

**TC-HD-E5**：登录暴力破解：100 次连续错密码登录 → 第 11 次起返 429

**TC-HD-E6**：Telegram bot 全流程：未授权 chat_id 发命令拒绝 + 已授权 chat_id 命令落到对应 user_id

---

## 26. 性能与回归（4）

**TC-HD-P1**：v3 guru pipeline 跑相同 ticker 两次，**第二次耗时 < 第一次的 30%**（缓存生效，联动 C7）

**TC-HD-P2**：CSRF 接入后 `/api/portfolio/holdings` p95 延迟回归 < 5% 漂移

**TC-HD-P3**：限流（Flask-Limiter）开启后 normal 请求 p95 延迟回归 < 5% 漂移

**TC-HD-P4**：迁移 runner 首次接入老 DB（含 ~1000 行 positions / ~5000 行 transactions）耗时 < 2s

---

## 27. 验证命令

每个 Phase 完成执行：

```bash
# 单元 + 集成
pytest tests/ -x --tb=short

# 不变式
python -m stock_trading_system.validation.run_all
python -m stock_trading_system.validation.invariants
python -m stock_trading_system.validation.cross_user_access

# 签字
python -m stock_trading_system.validation.sign_off

# Phase 4 专用
pytest tests/web/test_route_parity.py
```

CI 任何阶段失败阻断合并。

---

## 28. 版本历史

| 版本 | 日期 | 用例数 | 变更 |
|---|---|---|---|
| v1.0 | 2026-05-13 | 151 | 初版。配套 [design/hardening-iteration-v1.md](../design/hardening-iteration-v1.md) v1.0。覆盖 9 Critical + 16 High。按 5 Phase × 各子项分组：P0 安全底座 43 / P1 多租户契约 39 / P2 数据可信度 33 / P3 业务版本收敛 28 / P4 Blueprint 拆分 8。+ E2E 6 + 性能回归 4。**严格不动**前端 React Island 用例（不在本期覆盖）/ OAuth provider 主体（已通过审查）/ Paper Trade 业务逻辑（仅 P2.6 Decimal 范围）/ analyzer.py god object 用例（独立迭代）。 |
