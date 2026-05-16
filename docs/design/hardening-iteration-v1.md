# 技术方案：硬化迭代 v1（hardening-iteration-v1）

| 项 | 值 |
|---|---|
| Feature | `hardening-iteration-v1` |
| 版本 | v1.0 |
| 日期 | 2026-05-13 |
| 关联 PRD | 内部驱动 / 无单独 PRD（基于审查报告与既有 design doc 回归补齐） |
| 关联测试用例 | [../test-cases/hardening-iteration-v1.md](../test-cases/hardening-iteration-v1.md)（P0 落地时建） |
| 触发 | 2026-05-13 全仓 4 路并行审查（Web / 数据 / 多租户 / Grep）综述报告 |
| 工程原则 | [../engineering-principles.md](../engineering-principles.md) v1.0 — 复用优先 L0-L4 阶梯 |
| 上游约束 | [product-architecture-optimization-instructions.md](product-architecture-optimization-instructions.md) — 数据分层（private / shared / audit）|

---

## 0. 总定位

### 0.1 本迭代的性质

2026-05-13 全仓审查列出 **9 Critical + 16 High + 大量 Medium** 问题。逐条溯源后，定性如下：

| 类别 | 数量占比 | 性质 |
|---|---|---|
| 回归补齐 | ~70% | [multi-tenant.md](multi-tenant.md) §5.1 已声明 `Flask-WTF` 依赖、§5.5 定义 `@admin_required`，但**代码层从未真正接入 CSRF / 漏装 `@admin_required` 在 `/api/settings` 与 `/api/scheduler/start`**。`alert_history.user_id` 列在 `p0a_data_partition.py` 已加但写入端不传值 → 列恒为 NULL |
| 新发现 | ~30% | screener v1/v2/v3 三套并存且都在被入口引用；`backtest.py` 与 `backtester.py` 字段+口径不一致；v3 guru 缓存调用 `LocalCache.set(..., ttl=...)` 不存在的形参 → 全部静默失效；LocalCache 未知 category 退化为永久 TTL |

**结论**：本迭代核心是**把既有 design doc 的约束执行到位** + **修复版本演进遗留垃圾**，不是发明新设计。这与 [engineering-principles.md](../engineering-principles.md) §4 「反模式」一致 —— 自写越少越好。

### 0.2 优先级原则（与上游对齐）

遵循 [product-architecture-optimization-instructions.md §0](product-architecture-optimization-instructions.md)：

> 先安全与可用 → 再多租户契约 → 再数据可信度 → 最后架构治理。

---

## 1. 目标 / 非目标 / 不动清单

### 1.1 目标（DoD）

1. **9 Critical 全部修复**且 [`validation/cross_user_access.py`](../../stock_trading_system/validation/cross_user_access.py) + [`validation/invariants.py`](../../stock_trading_system/validation/invariants.py) 测试矩阵覆盖
2. **16 High 中 12 条修复**：安全/多租户/数据可信度全闭环；架构治理 4 条（`web/app.py` 拆分 / `analyzer.py` god object / 迁移 runner / Provider 抽象基类）进入 P3-P4
3. **screener v1/v2** 在 web/main/telegram 入口全部替换为 v3；v1/v2 进入 deprecated 但代码保留 2 周
4. **backtest.py 退役**，所有 web 入口走 `backtester.py`，字段/口径统一
5. **多租户契约从约定升级为强制**：`PortfolioManager._user_id()` 拿不到 user_id 直接 `raise`，DB 层 `user_id=None` 不再走"无过滤"分支

### 1.2 非目标

- ❌ 不引入新业务功能（不加新 LLM、不加新数据源、不加新报告类型）
- ❌ 不重构 [`agents/analyzer.py`](../../stock_trading_system/agents/analyzer.py) 967 行 god object（独立迭代）
- ❌ 不改 UI（前端文案 / 布局 / React Island 结构不动）
- ❌ 不改 LLM 子系统、OAuth 子系统（已经做对了）

### 1.3 不动清单（diff 边界）

明确写出避免 PR 失控：

- [`stock_trading_system/auth/`](../../stock_trading_system/auth/) **全部 11 个模块**：bcrypt rounds=12 / Fernet OAuth token 落库 / PKCE / JWKS 验签 / SESSION_VERSION 旋转 — 已通过审查
- OAuth provider 实现（Google / GitHub / Schwab callback 主体逻辑）
- Paper Trade 业务逻辑（不在审查 Critical 范围，仅 P2.6 限定改 Decimal）
- 前端 React Island / vite 配置 / shadcn 组件
- Telegram bot 命令语义（仅加白名单层，不动 `/buy /sell /alert` 语义）
- LLM router / client / TradingAgents monkey-patch（god object 留下个迭代）

---

## 2. 阶段划分（5 Phase / ~6 周）

| Phase | 周期 | 主题 | 闭环的审查项 | 估算 LOC |
|---|---|---|---|---|
| **P0** | W1 | 安全底座 | C1 C3 C4 C5 C6 / H1 H2 H4 | +200 −50 |
| **P1** | W2 | 多租户契约强制化 | C2 C9 / `alert_history.user_id` / `_user_id() raise` / cross_user_access 矩阵 / invariants 补缺 | +250 −60 |
| **P2** | W3 | 数据可信度 | C7 C8 / H10 H11 / `datetime` 时区 / 金额 Decimal（限 Paper Trade）/ Polygon 限速锁 | +300 −80 |
| **P3** | W4-W5 | 业务版本收敛 | H8 H12 H13 / 迁移 runner / DataManager→DataRouter 收口 / `analysis_history` schema 统一 | +400 −1000 |
| **P4** | W6 | Web 拆分 | `web/app.py` 4517 行按 Blueprint 拆 + 中间件 | 纯搬运 ~−200 |

**净 LOC**：+1150 / −1390 ≈ **−240**。符合 [engineering-principles.md](../engineering-principles.md) §4 「自写越少越好」。

---

## 3. Phase 详细

### 3.1 P0：安全底座（W1）

#### P0.1 [C1] 接入 Flask-WTF CSRFProtect

- **现状**：`requirements.txt:flask-wtf>=1.2` 已依赖；[multi-tenant.md §5.1](multi-tenant.md) 已声明；但 [`web/app.py`](../../stock_trading_system/web/app.py) 全文 grep `CSRFProtect|flask_wtf|csrf_protect` **0 命中**
- **改动**：
  - [`web/app.py:574`](../../stock_trading_system/web/app.py#L574) `create_app` 内加 `csrf = CSRFProtect(app)`
  - [`templates/layout.html:7`](../../stock_trading_system/web/templates/layout.html#L7) 的 meta tag 不改（前端已读 `csrf-token`）
  - 前端 fetch 公共封装（`frontend/src/lib/api.ts` 或等价位置）所有非 GET 自动注入 `X-CSRF-Token`
  - 仅 `/api/auth/login`、`/api/auth/register`、`/oauth/*/callback`、`/api/health` 走 `@csrf.exempt`
- **DoD**：
  - CSRF token 缺失/错误的 POST 返回 400
  - `tests/web/test_csrf.py` 覆盖 5 类敏感路由（settings / portfolio.sell / alerts.remove / scheduler.start / paper.entry）

#### P0.2 [C3 / H1] 漏装的 `@admin_required`

- **现状**：[`auth/decorators.py:22 admin_required`](../../stock_trading_system/auth/decorators.py#L22) 已实现，已用于 6 处（`web/app.py:795,800,809,815,2621,4441`），但漏装在：
- **改动**：
  - [`web/app.py:2654-2782`](../../stock_trading_system/web/app.py#L2654) `/api/settings` GET + POST 加 `@admin_required`
  - [`web/app.py:2630-2650`](../../stock_trading_system/web/app.py#L2630) `/api/scheduler/start` `/api/scheduler/stop` 加 `@admin_required`（同处 2621 `run-now` 已有）
  - 顺手 audit：`update_user_config` / `secret_key` / 任何全局 mutation 路径都该 `@admin_required`
- **DoD**：role=user 账号请求上述端点返回 403；P1.4 的 cross_user_access 测试矩阵覆盖

#### P0.3 [C4 / C5 / C6] alerts / portfolio owner 强制

- **现状**：
  - [`alerts/monitor.py:48`](../../stock_trading_system/alerts/monitor.py#L48) `remove_alert(alert_id)` 不带 user_id
  - [`portfolio/database.py:620-622`](../../stock_trading_system/portfolio/database.py#L620) `DELETE FROM alerts WHERE id = ?` 无 user_id 过滤
  - [`portfolio/database.py:624-633`](../../stock_trading_system/portfolio/database.py#L624) `save_alert_trigger` 不传 user_id（列恒为 NULL）
  - [`portfolio/database.py:635-646`](../../stock_trading_system/portfolio/database.py#L635) `get_alert_history` 不按 user 过滤
  - [`web/app.py:1700-1722, 1519-1599`](../../stock_trading_system/web/app.py#L1700) 多端点缺显式 `g.user` 检查
- **改动**：
  - `monitor.py` / `database.py` 全部接口签名加 `user_id` 必填
  - `delete_position` `delete_alert` 等 rowcount=0 → 返 404 / `NotFound`
  - web 层每端点入口处显式 `if g.user is None: return 401`，调用底层传 `user_id=g.user.id`
  - `save_alert_trigger` 必传 user_id（看 `alerts/monitor.py` 触发处补传）
- **DoD**：cross_user_access.py 测试矩阵补 `alerts.remove` / `alerts.history` / `portfolio.delete` / `portfolio.update_cost` / `portfolio.snapshot` 共 5 条

#### P0.4 [H4] 登录 / 注册 / 邀请码限流

- **改动**：
  - 引入 `Flask-Limiter>=3.5`
  - 默认 `200/day per IP`
  - `/api/auth/login` `10/minute per IP` + `5/minute per email`
  - `/api/auth/register` `5/hour per IP`
  - `/api/auth/invites/validate` `20/hour per IP`
  - 触发返 429 + Retry-After
- **DoD**：`tests/auth/test_rate_limit.py` 覆盖；登录爆破在 60 秒内被锁

#### P0.5 [H2] 统一错误处理 — 不再泄栈

- **现状**：[`web/app.py:957, 1001-1002, 2418, 2456, 2469, 2778, 2832`](../../stock_trading_system/web/app.py#L957) 等共 ~10 处 `return jsonify({"error": str(e)}), 500` 直接把栈/路径/provider 名返客户端
- **改动**：
  - `web/app.py` 注册 `@app.errorhandler(Exception)`：500 仅返 `{"error":"internal","trace_id": "..."}`
  - 内部 `logger.exception("...", extra={"trace_id": trace_id})`
  - 用 `flask.g.trace_id = uuid4().hex` 在 `before_request` 初始化
  - 移除全仓 `str(e)` 在响应体里的模式
- **DoD**：`grep "str(e)" stock_trading_system/web/app.py` 在 `jsonify(...)` 调用里 0 命中

---

### 3.2 P1：多租户契约强制化（W2）

#### P1.1 [C2] Telegram bot 白名单

- **现状**：[`alerts/telegram_bot.py:184-243`](../../stock_trading_system/alerts/telegram_bot.py#L184) 任意 Telegram 用户找到 bot 即可 `/buy /sell /alert`，`pm.add_position(...)` 不传 user_id，落到 "系统级" 持仓（user_id=None）；`monitor.list_alerts(scope="all")` 列全租户告警
- **改动**：
  - `config/default_config.yaml` 加：
    ```yaml
    telegram:
      allowed_chat_ids: []         # 空数组 = 不启用 bot
      user_map: {}                 # {<chat_id>: <user_email>}
    ```
  - bot 启动时把 `user_map` 解析成 `chat_id → user_id`（查 users 表）
  - 每命令前置 `_authorize(update.effective_chat.id) -> user_id`，非白名单返回拒绝消息 + log
  - `pm.add_position(...)` `pm.sell_position(...)` 必传 user_id
  - `monitor.list_alerts(scope="user", user_id=...)`
- **DoD**：`tests/alerts/test_telegram_authz.py` 覆盖未授权 chat_id 拒绝；授权用户操作落到对应 user_id

#### P1.2 [C9] 移除 legacy TaskScheduler 跨租户路径

- **现状**：[`scheduler/task_scheduler.py:106-126`](../../stock_trading_system/scheduler/task_scheduler.py#L106) `_post_market_close` 调 `take_snapshot()` / `daily_report()` 无 user_id，在 cron 上下文 `_user_id()` 解析失败 → 全租户聚合写 `user_id=NULL` 快照
- **改动**：
  - 删除 `_post_market_close` / `_pre_market_open` 内的 snapshot/report 调用（已被 `DailySnapshotScheduler.take_snapshot_all_users` 取代）
  - 评估：是否整体删除 `TaskScheduler.start()` 入口？现有调用方仅 `web/app.py:2630` `/api/scheduler/start`。建议**保留入口但内部直接 delegate 到 `DailySnapshotScheduler`**，避免外部脚本破坏
- **DoD**：`grep "_post_market_close" stock_trading_system/` 0 命中；invariants 加 `daily_snapshots.user_id IS NULL → 0 条`

#### P1.3 多租户契约从约定升级为强制

- **现状**：[`portfolio/manager.py:45-55`](../../stock_trading_system/portfolio/manager.py#L45) `_user_id()` 拿不到 → 静默 `return None`；DB 层 [`database.py:485-498, 513-518`](../../stock_trading_system/portfolio/database.py#L485) `user_id=None` 走"无过滤"分支 = 全表
- **改动**：
  - `_user_id()` 改 `raise RuntimeError("missing tenant context")`
  - `database.py` 所有 `user_id` 参数改为必填位置参数（不再 `Optional[int] = None`）
  - 为允许 admin-only 跨租户读（`daily_snapshot_scheduler.take_snapshot_all_users`）引入显式参数 `_admin_scope=True`：
    ```python
    def get_holdings(self, *, user_id: int | None = None, _admin_scope: bool = False):
        if user_id is None and not _admin_scope:
            raise RuntimeError("missing tenant context")
        # ...
    ```
- **DoD**：故意触发 None 路径返 500（带 trace_id）；`tests/portfolio/test_user_id_required.py` 覆盖

#### P1.4 cross_user_access 测试矩阵全覆盖

- **现状**：[`validation/cross_user_access.py:25-68`](../../stock_trading_system/validation/cross_user_access.py#L25) 只测 3 条（cancel-task / holdings / anon 401）
- **改动**：扩展到 12+ 条：
  - `alerts.remove` `alerts.history` `alerts.list`
  - `portfolio.delete` `portfolio.update_cost` `portfolio.snapshot` `portfolio.history`
  - `analysis.delete` `analysis_bookmark.delete`
  - `paper.read_other` `paper.entry_other`
  - `settings.write`（非 admin） `scheduler.start`（非 admin）
  - `tasks.cancel_other` `watchlist.delete_other`
- CI 自动 provision 一对账号 `(admin@local / alice@test / bob@test)`，不再依赖 `--bob-email`
- **DoD**：所有 12+ 用例返回 403/404；CI 失败阻断合并

#### P1.5 invariants 补缺失字段

- **现状**：[`validation/invariants.py:19-53`](../../stock_trading_system/validation/invariants.py#L19) 仅 10 条
- **改动**：新增：
  - `alert_history.user_id IS NOT NULL`（P0.3 + P1.x 后写入端都填了）
  - `user_analysis_advice.analysis_id` 必须存在于 `analysis_history`
  - `task_events.user_id` 是 INTEGER（不是字符串 `"user"`）
  - `daily_snapshots.user_id IS NOT NULL`
  - `tasks.created_by IS NOT NULL`
- **DoD**：`python -m stock_trading_system.validation.run_all` 全绿

#### P1.6 task_manager.created_by 不再 fallback 字符串

- **现状**：[`tasks/task_manager.py:131-139`](../../stock_trading_system/tasks/task_manager.py#L131) 拿不到 user_id 时 `created_by = "user"` 写库 → `task_events.user_id` 实际是字符串（SQLite 不强类型但语义错），`fix_tasks_orphan_events.py` 正是因此而存在的补丁迁移
- **改动**：拿不到 user_id 改 raise；仅允许 admin 通过显式 `created_by=<admin_id>` 注入
- **DoD**：grep `created_by = "user"` 0 命中；fix_tasks_orphan_events 不再需要

---

### 3.3 P2：数据可信度（W3）

#### P2.1 [C7] LocalCache.set 加 ttl 形参

- **现状**：[`screener/v3/cache.py:51-58`](../../stock_trading_system/screener/v3/cache.py#L51) 调 `local_cache.set(..., ttl=...)`；[`data/local_cache.py:123`](../../stock_trading_system/data/local_cache.py#L123) `def set(self, category, key, value)` **不接 ttl 形参** → 调用抛 `TypeError` 被 `except Exception: logger.debug(...)` 静默吞掉 → 14 guru × N ticker 缓存**全部失效**
- **改动**：
  - `set(self, category, key, value, ttl: Optional[int] = None)`
  - ttl=None 走 `_DEFAULT_TTL.get(category)` 默认；ttl 显式传 → 覆盖
- **DoD**：v3 guru cache 命中率 > 0；`tests/data/test_local_cache_ttl.py` 覆盖

#### P2.2 [C8] 未知 category 拒绝写入

- **现状**：[`data/local_cache.py:92-95`](../../stock_trading_system/data/local_cache.py#L92) 未知 category → ttl=None → "无 TTL" = 永不过期。实际有 `regime` `guru_signal_v3` `screen_results` `roundtable` 等多个未注册 category 在写入
- **改动**：
  - 未知 category 默认拒绝写入 + `logger.warning`
  - 除非显式 `unsafe_default_ttl=...` 参数（用于 dev / 临时实验）
  - 把当前所有触发 warning 的 category 显式登记到 `_DEFAULT_TTL`
- **DoD**：`_DEFAULT_TTL` 包含完整 category 注册表；grep `Unknown cache category` 在生产日志 0 命中

#### P2.3 [H10] Pickle → JSON

- **现状**：[`data/local_cache.py:115`](../../stock_trading_system/data/local_cache.py#L115) `pickle.loads(row["payload"])` 从 SQLite 缓存读出反序列化 → 任何能写 DB 文件的途径都是 RCE 面
- **改动**：
  - 改 `json.loads`；DataFrame 用 parquet/CSV 写到独立 dir 或 base64 编码
  - 旧 pickle 数据走一次 drop（缓存可重建，不可逆但可接受）
  - 迁移脚本 `migrations/cache_pickle_to_json.py`
- **DoD**：`grep "pickle.loads\|pickle.load" stock_trading_system/` 0 命中（除 tests）

#### P2.4 [H11] Qwen prompt 主题表外置

- **现状**：[`data/qwen_provider.py:323-340`](../../stock_trading_system/data/qwen_provider.py#L323) 长篇 system prompt 硬编码数十只股票（NEE/SO/DUK/FSLR/ENPH/SEDG/MU/WDC/STX 等）
- **改动**：
  - 新建 `stock_trading_system/config/themes.yaml`：
    ```yaml
    themes:
      utilities: [NEE, SO, DUK, AEP, ...]
      solar: [FSLR, ENPH, SEDG, ...]
      semiconductors: [MU, WDC, STX, ...]
    ```
  - `qwen_provider.materialize_universe` 改读 yaml + prompt 通用化
- **DoD**：grep `NEE/SO/DUK\|FSLR/ENPH\|MU/WDC/STX` 在 .py 文件 0 命中

#### P2.5 datetime 时区统一

- **现状**：全仓 53 处 `datetime.now()` 无时区 + 7 处 `datetime.utcnow()`（Py3.12 deprecated）
- **改动**：
  - 新建 [`utils/timez.py`](../../stock_trading_system/utils/timez.py)（~30 LOC）：
    ```python
    NY = ZoneInfo("America/New_York")
    UTC = timezone.utc
    def now_utc() -> datetime: return datetime.now(UTC)
    def now_ny() -> datetime:  return datetime.now(NY)
    def today_str_ny() -> str: return now_ny().strftime("%Y-%m-%d")
    ```
  - 全仓 53 处 `datetime.now()` 改为显式 `now_utc()` / `now_ny()`
  - 7 处 `datetime.utcnow()` 改 `now_utc()`
- **DoD**：`grep "datetime.now()\|datetime.utcnow()" stock_trading_system/ --include="*.py" -E` 仅在 `utils/timez.py` 自身命中

#### P2.6 金额 Decimal 化（限 Paper Trade）

- **现状**：[`strategy/strategy_engine.py:71-72`](../../stock_trading_system/strategy/strategy_engine.py#L71)、[`strategy/backtest.py:213`](../../stock_trading_system/strategy/backtest.py#L213)、[`strategy/paper_trader/simulator.py:378`](../../stock_trading_system/strategy/paper_trader/simulator.py#L378)、[`session_store.py:486`](../../stock_trading_system/strategy/paper_trader/session_store.py#L486) 全用 float
- **范围**：本期**仅 Paper Trade 子系统**（账户余额、PnL、commission、滑点字段）。持仓和 web 展示口径**不动**
- **改动**：
  - `simulator.py:378` `int(target_dollars // entry_price)` → `Decimal` 路径
  - 累加类字段（cash / equity / realized_pnl）改 `Decimal`
  - 比率（`pct_change` / `weight` / `(exit/entry)-1`）保留 float
- **DoD**：`tests/strategy/test_paper_decimal.py` 跑 1000 次买卖循环，cash 最终值与解析期望值**完全相等**（不用 approx）

#### P2.7 Polygon 限速加锁 + Provider Quote 抽象

- **现状**：
  - [`polygon_provider.py:33-38`](../../stock_trading_system/data/polygon_provider.py#L33) `self._last_call` 无锁
  - 所有 `get_stock_price` 返 `dict | None` 字段命名/语义不齐（Polygon 把"前一日收盘"塞进 `last` 字段冒充实时）
- **改动**：
  - `polygon_provider.py` 加 `threading.Lock`
  - 新建 `data/quote.py`：`class Quote(BaseModel)` 字段 `last_price: Decimal, as_of_ts: datetime, is_realtime: bool, source: str`
  - 各 provider `get_stock_price` 返 `Quote`；caller 改用 schema 字段（最小改动：DataManager 再 `.dict()` 兼容旧 caller，留一周后清理）
- **DoD**：多线程 50 并发 Polygon 调用不触发 429；DataManager 链式回落 `is_realtime` 字段如实标记

---

### 3.4 P3：业务版本收敛（W4-W5）

#### P3.1 [H12] screener v1/v2 → v3 收口

- **现状**：
  - v1 ([`screener/screener.py`](../../stock_trading_system/screener/screener.py)) 被 [`web/app.py:72`](../../stock_trading_system/web/app.py#L72) + [`alerts/telegram_bot.py:288`](../../stock_trading_system/alerts/telegram_bot.py#L288) + [`main.py:68`](../../stock_trading_system/main.py#L68) 引用
  - v2 ([`screener/v2/__init__.py`](../../stock_trading_system/screener/v2/__init__.py)) 在 [`tasks/workers.py:712,1214`](../../stock_trading_system/tasks/workers.py#L712) 引用
  - v3 ([`screener/v3/pipeline.py:645`](../../stock_trading_system/screener/v3/pipeline.py#L645)) 在 worker 引用
- **改动**：
  - 把 v3 pipeline 提取一个 sync wrapper（worker 已用 async 模式，CLI/web 同步入口需要）
  - 替换 3 处 v1 引用 → v3 sync wrapper
  - workers v2 引用 → v3
  - v1/v2 文件保留代码 2 周（顶部加 `DeprecationWarning`），P4 末删除
- **DoD**：grep `from stock_trading_system.screener import\|from .screener import\|screener_v2` 命中只在 deprecated shim

#### P3.2 [H13] backtest.py 退役

- **现状**：[`strategy/backtest.py`](../../stock_trading_system/strategy/backtest.py)（web 入口 `web/app.py:2789,2806`）与 [`strategy/backtester.py`](../../stock_trading_system/strategy/backtester.py)（worker 入口 `tasks/workers.py:738`）字段名（`total_return_pct` vs `total_return`）、年化口径（252 vs 365）、滑点（1% vs 0）、RSI 实现（Wilder EWM vs SMA）**全部不一致**
- **改动**：
  - 选 `backtester.py BacktestEngine` 为主线（可注入 history_fn，更解耦）
  - 字段别名兼容：返回 dict 同时含 `total_return` 和 `total_return_pct`（UI 不动）
  - 滑点参数化：默认 0.001，UI 不暴露（除非 admin）
  - 年化统一 252（交易日）
  - `web/app.py:2789,2806` 替换为 `BacktestEngine`
  - 删除 `strategy/backtest.py`（保留 import shim 1 周）
- **DoD**：web 入口与 worker 入口对同一组样本回测，数字一致到小数点后 4 位；`tests/strategy/test_backtest_parity.py` 覆盖

#### P3.3 [H8] DataManager → DataRouter 单一出入口

- **现状**：
  - [`DataManager`](../../stock_trading_system/data/data_manager.py)（链式回落 + 60s 价格 cache）和 [`DataRouter`](../../stock_trading_system/data/data_router.py)（capability matrix + LocalCache）并存
  - [`data_manager.py:25,52,54-55`](../../stock_trading_system/data/data_manager.py#L25) `_SKIP_THRESHOLD=1` + 启动 `_fail_count={"ib":1,"polygon":1}` → IB/Polygon 永远 skip
  - 多模块直接调 `yfinance`（[`regime_detector.py:81`](../../stock_trading_system/screener/v2/regime_detector.py#L81)、[`data_helper.py:31,54`](../../stock_trading_system/screener/v2/data_helper.py#L31)、[`backtester.py:35`](../../stock_trading_system/strategy/backtester.py#L35) `_default_history_fn`）
- **改动**：
  - `DataManager` 内部 delegate 给 `DataRouter`（保留公共 API `get_stock_price()`）
  - 删除 `_fail_count` / `_SKIP_THRESHOLD` 自实现熔断
  - 修复 `_SKIP_THRESHOLD=1` 启动即 skip 的 dead code
  - 全仓直调 `yfinance` 收口到 `YFinanceProvider`
- **DoD**：grep `import yfinance\|yf.Ticker\|yf.download` 仅在 `yfinance_provider.py` 命中

#### P3.4 迁移系统轻量化

- **现状**：8 个迁移无版本表 / 无统一 runner / 无回滚；`fix_strategy_event_analysis_id` / `fix_tasks_orphan_events` 这两个"补丁迁移"暗示之前出过数据污染却没自动重放
- **改动**：
  - 新建 [`migrations/_runner.py`](../../stock_trading_system/migrations/_runner.py)（~80 LOC）：
    ```python
    # applied_migrations(name TEXT PK, applied_at TEXT, checksum TEXT)
    # 启动时按 alphabetical 顺序跑未执行的迁移
    ```
  - 现有 8 个迁移文件加 `@migration("0001_to_multi_tenant")` 类装饰器（或保持原函数 + 文件名映射）
  - 首次接入老 DB：`applied_migrations` 表空时把现有 schema 当作"v0 baseline"，标 P0a 之前的迁移都已应用
- **DoD**：fresh DB 跑全迁移成功；同一 DB 重复跑迁移幂等（无副作用、无报错）

#### P3.5 analysis_history schema 统一 + task_events.seq DB 化

- **现状**：
  - [`portfolio/database.py:157-209`](../../stock_trading_system/portfolio/database.py#L157) 和 [`tasks/task_store.py:549-611`](../../stock_trading_system/tasks/task_store.py#L549) 各自 `CREATE TABLE IF NOT EXISTS analysis_history` 且基础 DDL 不一致（task_store 缺 `rendering_status/error/generated_at`）
  - [`tasks/event_emitter.py:22-23, 102-122`](../../stock_trading_system/tasks/event_emitter.py#L22) `_seq_cache` 内存重启清零 → 与 DB 历史 (task_id, 1) 冲突 → INSERT OR IGNORE 静默丢
- **改动**：
  - 抽 `schema/analysis_history.py` 单文件，两边 import
  - `event_emitter` 取 seq 改 DB `SELECT MAX(seq)+1 WHERE task_id=?`（加事务 + 唯一索引乐观写入）
- **DoD**：重启进程后追加事件 seq 连续；`tests/tasks/test_event_seq_after_restart.py` 覆盖

#### P3.6 PortfolioDatabase 启用 WAL + busy_timeout

- **现状**：[`portfolio/database.py:91-94`](../../stock_trading_system/portfolio/database.py#L91) 无 PRAGMA，与 [`task_store.py:118-123`](../../stock_trading_system/tasks/task_store.py#L118)（WAL + 10s timeout）共库
- **改动**：`PortfolioDatabase._get_conn` 加 `PRAGMA busy_timeout=5000` `PRAGMA journal_mode=WAL`
- **DoD**：并发 50 写不再出现 `database is locked`

---

### 3.5 P4：Web/App.py 拆分（W6）

#### P4.1 按域拆 Blueprint

把 4517 行单文件拆成 ~11 个 Blueprint，每个 < 600 行：

| Blueprint 文件 | 路由数 | 取自 app.py |
|---|---|---|
| `web/blueprints/auth_bp.py` | 8 | `/login` `/register` `/api/auth/*` |
| `web/blueprints/oauth_bp.py` | 10 | `/oauth/google/*` `/oauth/github/*` `/oauth/schwab/*` |
| `web/blueprints/portfolio_bp.py` | 12 | `/api/portfolio/*` |
| `web/blueprints/alerts_bp.py` | 6 | `/api/alerts/*` |
| `web/blueprints/tasks_bp.py` | 10 | `/api/tasks/*` |
| `web/blueprints/screener_bp.py` | 8 | `/api/screen/v3/*` |
| `web/blueprints/analysis_bp.py` | 12 | `/api/analysis/*` `/api/advice/*` |
| `web/blueprints/backtest_bp.py` | 4 | `/api/backtest/*` |
| `web/blueprints/paper_bp.py` | 15 | `/api/paper/*` |
| `web/blueprints/settings_bp.py` | 6 | `/api/settings/*` |
| `web/blueprints/admin_bp.py` | 10 | `/api/admin/*` `/api/scheduler/*` |
| `web/socket_handlers.py` | - | socketio handlers |

#### P4.2 闭包提到 services

`_compute_today_pnl` / `_check_task_ownership` / `_sanitize_shared_task` / `_render_analysis_markdown` / `_validate_trade` 等 [`web/app.py`](../../stock_trading_system/web/app.py) 内闭包提到 `web/services/`，独立可单测。

#### P4.3 中间件

- `web/middleware/request_id.py` — `before_request` 生成 trace_id
- `web/middleware/audit.py` — 敏感操作（settings 改 / portfolio sell / alert remove / scheduler start）写入 `audit_log` 表

#### DoD（P4）

- `web/app.py` < 500 行（仅剩 `create_app()` + Blueprint 注册 + 全局 hook）
- 所有 service 函数有 unit test
- 路由 URL + HTTP method + 行为 100% 不变（`tests/web/test_route_parity.py` 拆分前 snapshot 全部路由表，拆分后断言完全一致）

---

## 4. § 复用 / Reuse

### 4.1 L0 — 项目内复用（最高优先级）

- [`auth/decorators.py:22 admin_required`](../../stock_trading_system/auth/decorators.py#L22) → P0.2 直接挂上即可
- [`auth/repository.py`](../../stock_trading_system/auth/repository.py) / [`auth/session.py`](../../stock_trading_system/auth/session.py) → P1.x 多租户契约的现成基础设施
- [`validation/cross_user_access.py`](../../stock_trading_system/validation/cross_user_access.py) → P1.4 扩矩阵不另起
- [`validation/invariants.py`](../../stock_trading_system/validation/invariants.py) → P1.5 加 3-5 条不变式
- [`tasks/task_store.py:118 PRAGMA WAL+timeout`](../../stock_trading_system/tasks/task_store.py#L118) → P3.6 抄到 `PortfolioDatabase`
- [`screener/v3/pipeline.py`](../../stock_trading_system/screener/v3/pipeline.py) → P3.1 直接作为统一入口
- [`strategy/backtester.py BacktestEngine`](../../stock_trading_system/strategy/backtester.py) → P3.2 替换 `Backtester`
- [`scheduler/daily_snapshot_scheduler.py`](../../stock_trading_system/scheduler/daily_snapshot_scheduler.py) → P1.2 已经是 take_snapshot_all_users 正确路径

### 4.2 L1 — 依赖库

- `Flask-WTF>=1.2`（`requirements.txt` **已依赖、未接入**）→ P0.1 CSRFProtect，**0 新依赖**
- `Flask-Limiter>=3.5` → P0.4 限流，省自写 ~80 LOC（参考 [engineering-principles.md §4](../engineering-principles.md) 反模式「写个轻量 retry 装饰器」）
- `pydantic>=2`（已依赖）→ P2.7 `Quote` 抽象模型
- `tenacity>=8`（已依赖，agents 已用）→ P3.x Schwab/Polygon retry/backoff
- `zoneinfo`（stdlib）→ P2.5 `utils/timez.py`
- `decimal.Decimal`（stdlib）→ P2.6 金额，无新依赖
- `email-validator`（[multi-tenant.md 审计矩阵建议加但未加](../engineering-principles.md#52-multi-tenantmd--基本合理小改进)）→ 顺手加入

### 4.3 L2/L3 — 开源参考

- **迁移 runner**（P3.4）：参考 [yoyo-migrations](https://github.com/lovedaybrooke/yoyo) 的最小设计思路（version table + applied checksums），**不直接 vendor**（项目规模不需要）→ clean-room ~80 LOC
- **Audit middleware**（P4.3）：检索未发现 Flask 通用且足够轻量的方案；自写 ~50 LOC

### 4.4 L4 — 自写（必要且无替代）

| 模块 | LOC | 无替代的理由 |
|---|---|---|
| P0.5 统一 error_handler + trace_id | ~50 | 业务专有日志关联 |
| P1.1 Telegram `chat_id → user_id` | ~80 | 业务专有授权层 |
| P1.3 `_user_id() raise` + DB 层抛错 | ~30 | 业务专有契约 |
| P2.4 `themes.yaml` loader | ~50（其中 5 LOC 代码 + 200 行配置）| 业务数据 |
| P2.5 `utils/timez.py` | ~30 | zoneinfo 标准库包装，业务专有 alias |
| P2.6 Paper Trade Decimal 化 | ~150 | 业务专有 |
| P3.4 迁移 runner | ~80 | 见上 |
| P4 Blueprint 拆分 + audit middleware | ~纯搬运 +50 中间件 | 业务专有 |

**自写代码总计**：~520 LOC 新 + 删除 ~1390 LOC（v1/v2 screener、backtest.py、Pickle 路径、fallback 兜底、duplicate analysis_history schema）。**净 -870 LOC**。

---

## 5. 测试 / 验证

### 5.1 新增测试文件

| 文件 | 关联 Phase | 用例数（估） |
|---|---|---|
| `tests/web/test_csrf.py` | P0.1 | 12 |
| `tests/web/test_admin_routes.py` | P0.2 | 6 |
| `tests/auth/test_rate_limit.py` | P0.4 | 8 |
| `tests/web/test_error_handler.py` | P0.5 | 5 |
| `tests/alerts/test_telegram_authz.py` | P1.1 | 8 |
| `tests/portfolio/test_user_id_required.py` | P1.3 | 6 |
| `tests/data/test_local_cache_ttl.py` | P2.1 P2.2 | 10 |
| `tests/strategy/test_paper_decimal.py` | P2.6 | 8 |
| `tests/strategy/test_backtest_parity.py` | P3.2 | 6 |
| `tests/data/test_yf_chokepoint.py` | P3.3 | 4 |
| `tests/tasks/test_event_seq_after_restart.py` | P3.5 | 4 |
| `tests/web/test_route_parity.py` | P4 | 5 |

合计约 **82 新增 case**。

### 5.2 扩充已有测试

- [`validation/cross_user_access.py`](../../stock_trading_system/validation/cross_user_access.py) 从 3 条扩到 **12+** 条（P1.4）
- [`validation/invariants.py`](../../stock_trading_system/validation/invariants.py) 加 **5** 条不变式（P1.5）

### 5.3 每个 Phase 完成跑

```bash
pytest tests/ -x --tb=short
python -m stock_trading_system.validation.run_all
python -m stock_trading_system.validation.sign_off
```

---

## 6. Rollout / 回滚

### 6.1 灰度

- **P0 / P1**：合主线（修漏洞优先级最高）
- **P2.6 Decimal 化**：feature flag `paper_trade_decimal=true`，先 dogfood 1 周再默认开
- **P3.1 / P3.2**：deprecated shim 保留 2 周
- **P4**：单独长分支，全测试通过 + 真机 dogfood 后合并

### 6.2 回滚

- P0 / P1 SQL 变更走 P3.4 迁移系统（每条带 down SQL 注释）
- P2.3 Pickle → JSON：旧缓存丢失可接受（自动重建）
- P3 v1/v2/backtest.py deprecated shim 是 2 周回滚窗口

### 6.3 commit 规范

每个 Phase 至少分 5-8 个独立 commit，每个 commit 满足：
- 单一职责，diff < 200 行
- commit message 含"修复了哪条审查项 (C# / H#)"
- 当前主分支历史几乎全是 `wip: claude session snapshot`，**本迭代要打破这个 anti-pattern**

---

## 7. 风险

| 风险 | 概率 | 影响 | 缓解 |
|---|---|---|---|
| CSRF 接入后前端漏掉 token | 中 | 用户操作报 400 | tests/web/test_csrf.py 覆盖所有非 GET；前端 fetch 公共封装统一注入 |
| `_user_id() raise` 暴露隐藏 None 路径 | 中 | 异常率短期上升 | 灰度先 staging 跑 24h；trace_id 易定位 |
| screener v1/v2 删除丢失隐藏入口 | 低 | 某调用方 ImportError | deprecated shim 2 周；P3.1 grep 全仓引用清单 |
| 迁移 runner 接入老 DB 不兼容 | 中 | 启动失败 | 首次跑 `applied_migrations` 空时把现有 schema 当 v0 baseline 标记已完成 |
| Decimal 化引入 round-trip 精度差 | 低 | 测试断言失败 | 限定 Paper Trade；旧 float 用 `Decimal.from_float()` 平移而非重算 |
| Blueprint 拆分漏路由 | 中 | 404 | `test_route_parity.py` snapshot + diff |
| 异步任务 worker 内仍有 datetime.now() | 低 | 时区错乱不易察觉 | P2.5 用 `ruff` 规则禁止 raw `datetime.now()`（pre-commit）|

---

## 8. 配套文档落地

| 文档 | 动作 | 时机 |
|---|---|---|
| [test-cases/hardening-iteration-v1.md](../test-cases/hardening-iteration-v1.md) | 新建（约 82 单测 + 5 E2E + 12 cross_user_access 矩阵）| P0 开工前 |
| [design/changelog.md](changelog.md) | 加 v1.0 条目 | 本文件落地时同步 |
| [test-cases/changelog.md](../test-cases/changelog.md) | 加测试用例条目 | test-cases 文档落地时同步 |
| [README.md](../README.md) | 更新「功能演进时间线」 | P4 完成时 |
| [multi-tenant.md](multi-tenant.md) | 加 v1.1 addendum：补充"CSRF / @admin_required 已在 hardening-iteration-v1 落实" | P0 完成时 |
| [engineering-principles.md](../engineering-principles.md) | 加 v1.1 审计矩阵条目：审计 hardening-iteration-v1 的复用比例 | P4 完成时 |

---

## 9. 版本历史

| 版本 | 日期 | 变更 |
|---|---|---|
| v1.0 | 2026-05-13 | 初版。基于 2026-05-13 全仓 4 路并行审查（Web/数据/多租户/Grep）的 9 Critical + 16 High 起 5-Phase 迭代。约 70% 内容是对 [multi-tenant.md](multi-tenant.md) / [product-architecture-optimization-instructions.md](product-architecture-optimization-instructions.md) 的回归补齐。预计净 LOC -870，自写比例约 ~520/(520+1390)=27%。复用阶梯 L0×8 + L1×7 + L2×1 + L4×8。|
