# 技术方案：多租户（Multi-tenant）

| 项 | 值 |
|---|---|
| Feature | `multi-tenant` |
| 版本 | v1.0 |
| 日期 | 2026-04-19 |
| 关联 PRD | [../prd/multi-tenant.md](../prd/multi-tenant.md) |
| 关联测试用例 | [../test-cases/multi-tenant.md](../test-cases/multi-tenant.md) |

## 1. 目标

见 [PRD §2](../prd/multi-tenant.md#2-目标)。核心四件事：

1. 引入 `users` + `invite_codes` + `user_settings` 三张表 + Flask session 认证
2. 给 6 类私有表加 `user_id` FK；共享表保持不动；审计表 `created_by` 字符串升级为 FK
3. 首次启动自动创建 `admin` 并批量认领老数据
4. 路由层强制 `@login_required` + 私有数据 `WHERE user_id = current_user.id`

## 2. 架构概览

```
                   ┌─────────────────────────────────┐
                   │         Flask App               │
                   │                                 │
 Browser ───cookie─┤  before_request:                │
                   │    - 解析 session → g.user      │
                   │    - 白名单外强制 login         │
                   │    - CSRF 校验 (POST/PUT/DEL)   │
                   │                                 │
                   │  routes/                        │
                   │    auth_routes.py  (new)        │
                   │    settings_routes.py (extend)  │
                   │    existing routes (+ g.user)   │
                   └────────────┬────────────────────┘
                                │
           ┌────────────────────┴────────────────────┐
           ▼                                         ▼
  ┌─────────────────┐                      ┌──────────────────┐
  │  auth/          │                      │  repositories/   │
  │  (new module)   │                      │  (augmented)     │
  │                 │                      │                  │
  │  - password     │                      │  - positions     │
  │  - session      │                      │    (+ user_id)   │
  │  - invite_code  │                      │  - alerts        │
  │  - user_admin   │                      │    (+ user_id)   │
  └────────┬────────┘                      │  - paper         │
           │                               │    (+ user_id)   │
           ▼                               │  - analysis      │
  ┌─────────────────┐                      │    (shared)      │
  │  portfolio.db   │◄─────────────────────┤  - tasks         │
  │                 │                      │    (+ user_id)   │
  │  + users        │                      └──────────────────┘
  │  + invite_codes │
  │  + user_settings│
  │  + (私有表加列) │
  └─────────────────┘
```

## 3. 新表 Schema

### 3.1 `users`

```sql
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    email         TEXT    NOT NULL UNIQUE,
    password_hash TEXT    NOT NULL,         -- bcrypt, rounds=12
    display_name  TEXT    NOT NULL,
    role          TEXT    NOT NULL DEFAULT 'user'   -- 'admin' | 'user'
                          CHECK(role IN ('admin','user')),
    status        TEXT    NOT NULL DEFAULT 'active' -- 'active' | 'deleted'
                          CHECK(status IN ('active','deleted')),
    created_at    TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_login_at TEXT,
    password_reset_token      TEXT,         -- UUID v4, NULL 表未重置
    password_reset_expires_at TEXT          -- ISO 时间，24h 后作废
);

CREATE UNIQUE INDEX IF NOT EXISTS ix_users_email_active
    ON users(email) WHERE status = 'active';
```

- 邮箱小写归一化（写入前 `email.strip().lower()`）
- `display_name` 为空时默认取邮箱 `@` 前部分
- 软删：`status = 'deleted'` 释放邮箱可重用，原数据保留 30 天

### 3.2 `invite_codes`

```sql
CREATE TABLE IF NOT EXISTS invite_codes (
    code        TEXT    PRIMARY KEY,       -- 12 位字母数字
    created_by  INTEGER NOT NULL REFERENCES users(id),
    created_at  TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_at  TEXT,                       -- NULL = 不过期
    used_by     INTEGER REFERENCES users(id),
    used_at     TEXT,
    revoked_at  TEXT
);
```

- 生成：`secrets.token_urlsafe(9)`（约 12 字符）
- 单次使用：`used_by IS NOT NULL` 后不可再兑
- 吊销：`revoked_at` 被设置后兑换请求返回 `invite_revoked`

### 3.3 `user_settings`

```sql
CREATE TABLE IF NOT EXISTS user_settings (
    user_id        INTEGER PRIMARY KEY REFERENCES users(id),
    llm_provider   TEXT,                   -- NULL = 走全局 yaml/legacy
    notify_email   INTEGER DEFAULT 0,      -- 预留
    created_at     TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at     TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
```

## 4. 私有表迁移

对以下表执行 `ADD COLUMN user_id INTEGER REFERENCES users(id)`：

| 表 | 现有位置 | 迁移后默认值（老数据） |
|---|---|---|
| positions | [database.py:45](../../stock_trading_system/portfolio/database.py#L45) | admin.id |
| transactions | [database.py:53](../../stock_trading_system/portfolio/database.py#L53) | admin.id |
| daily_snapshots | [database.py:63](../../stock_trading_system/portfolio/database.py#L63) | admin.id |
| alerts | [database.py:72](../../stock_trading_system/portfolio/database.py#L72) | admin.id |
| alert_history | [database.py:106](../../stock_trading_system/portfolio/database.py#L106) | 通过 alert_id 继承（JOIN 查询） |
| paper_trade_sessions | [session_store.py](../../stock_trading_system/strategy/paper_trader/session_store.py) | admin.id |

**paper_trade 子表**（strategy_events / trades / equity / daily_stats / analysis_tracked）：
- 不加 user_id，统一通过 `session_id → session.user_id` 二跳
- 查询时 JOIN：`WHERE session.user_id = :uid`

### 4.1 索引策略

```sql
-- 新增复合索引（user_id 第一列，后跟最常用过滤列）
CREATE INDEX IF NOT EXISTS ix_positions_user        ON positions(user_id, ticker);
CREATE INDEX IF NOT EXISTS ix_transactions_user     ON transactions(user_id, timestamp DESC);
CREATE INDEX IF NOT EXISTS ix_daily_snapshots_user  ON daily_snapshots(user_id, date DESC);
CREATE INDEX IF NOT EXISTS ix_alerts_user           ON alerts(user_id, ticker);
CREATE INDEX IF NOT EXISTS ix_paper_sessions_user   ON paper_trade_sessions(user_id, created_at DESC);
```

### 4.2 审计表：`tasks` / `screen_results_v2` / `backtest_results`

`tasks.created_by` 目前是字符串占位 `'user'`。升级为 `user_id INTEGER FK`：

```sql
ALTER TABLE tasks RENAME COLUMN created_by TO created_by_legacy;
ALTER TABLE tasks ADD COLUMN created_by INTEGER REFERENCES users(id);
-- 迁移：legacy='user' 的全部 UPDATE SET created_by = admin.id
UPDATE tasks SET created_by = (SELECT id FROM users WHERE email='admin@local')
 WHERE created_by_legacy IS NOT NULL AND created_by IS NULL;
-- 保留 legacy 列 30 天作为回滚依据，Phase 3 再 DROP
CREATE INDEX IF NOT EXISTS ix_tasks_user ON tasks(created_by, created_at DESC);
```

`screen_results_v2` / `backtest_results` 同理（如果当前无 created_by 列则直接 ADD）。

### 4.3 共享表收藏：`analysis_bookmarks`

```sql
CREATE TABLE IF NOT EXISTS analysis_bookmarks (
    user_id       INTEGER NOT NULL REFERENCES users(id),
    analysis_id   INTEGER NOT NULL REFERENCES analysis_history(id),
    bookmarked_at TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    note          TEXT,
    PRIMARY KEY (user_id, analysis_id)
);
```

用户可以给共享分析加个人笔记。

## 5. 认证实现

### 5.1 依赖

```txt
# requirements.txt 追加
bcrypt>=4.1
Flask-WTF>=1.2        # CSRF
```

不引入 Flask-Login，自研轻量中间件（单人项目规模不值得拉 Flask-Login 的生命周期钩子）。

### 5.2 新模块 `stock_trading_system/auth/`

```
stock_trading_system/auth/
├── __init__.py
├── password.py           # bcrypt 包装（hash/verify）
├── session.py            # session 读写、current_user 解析
├── invite.py             # 邀请码生成/兑换/吊销
├── repository.py         # users 表 CRUD
├── decorators.py         # @login_required / @admin_required
└── bootstrap.py          # 首次启动 admin + 老数据迁移
```

### 5.3 `password.py`

```python
import bcrypt

def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode()

def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
```

### 5.4 `session.py`

```python
from flask import session, g
from stock_trading_system.auth.repository import UserRepository

SESSION_KEY = "user_id"
SESSION_VERSION_KEY = "sv"  # 手动失效所有 session：递增该值
CURRENT_SESSION_VERSION = 1

def login_user(user_id: int):
    session.clear()
    session[SESSION_KEY] = user_id
    session[SESSION_VERSION_KEY] = CURRENT_SESSION_VERSION
    session.permanent = True  # 30 天滑动

def logout_user():
    session.clear()

def load_current_user(repo: UserRepository):
    """Called from before_request. Populates g.user or None."""
    g.user = None
    uid = session.get(SESSION_KEY)
    sv = session.get(SESSION_VERSION_KEY)
    if uid is None or sv != CURRENT_SESSION_VERSION:
        return
    user = repo.find_by_id(uid)
    if user and user.status == "active":
        g.user = user
```

### 5.5 `decorators.py`

```python
from functools import wraps
from flask import g, abort, redirect, url_for, request, jsonify

def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if g.get("user") is None:
            if request.path.startswith("/api/"):
                return jsonify({"error": "unauthorized"}), 401
            return redirect(url_for("auth.login", next=request.path))
        return fn(*args, **kwargs)
    return wrapper

def admin_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        u = g.get("user")
        if u is None or u.role != "admin":
            abort(403)
        return fn(*args, **kwargs)
    return wrapper
```

### 5.6 白名单 + `before_request`

```python
PUBLIC_PATHS = {
    "/login", "/register", "/api/auth/login",
    "/api/auth/register", "/health", "/static",
}

@app.before_request
def enforce_auth():
    load_current_user(user_repo)
    if request.path.startswith("/static/"):
        return
    if request.path in PUBLIC_PATHS:
        return
    if g.user is None:
        if request.path.startswith("/api/"):
            return jsonify({"error": "unauthorized"}), 401
        return redirect(url_for("auth.login"))
```

### 5.7 CSRF

用 Flask-WTF 的 `CSRFProtect(app)`，为所有 API 自动校验 `X-CSRFToken` header（前端从 `<meta name="csrf-token">` 读 token，每个 fetch 请求附上）。

```python
from flask_wtf.csrf import CSRFProtect
csrf = CSRFProtect(app)

# /api/auth/login 注册前端时还没 token，豁免
csrf.exempt(auth_routes.api_login)
csrf.exempt(auth_routes.api_register)
```

### 5.8 Session cookie 配置

```python
app.config.update(
    SECRET_KEY=os.environ["FLASK_SECRET_KEY"],   # 必填，启动时校验
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=not app.debug,
    PERMANENT_SESSION_LIFETIME=timedelta(days=30),
)
```

启动时若 `FLASK_SECRET_KEY` 未设置，自动生成一个写到 `~/.stock_trading/flask_secret.key`（600 权限，首次提醒用户备份）。

## 6. API 契约

所有路径 `/api/auth/*` 新增。

### 6.1 `POST /api/auth/register`

Request：
```json
{ "invite_code": "abc123def456", "email": "foo@x.com",
  "password": "…", "display_name": "Foo" }
```

Response 200：`{"user": {"id": 2, "email": "foo@x.com", "role": "user"}}`
响应副作用：自动登录（写 session）。

错误：
- 400 `invite_invalid` / `invite_used` / `invite_expired` / `invite_revoked`
- 400 `email_taken`
- 400 `password_weak`（<8 字符、纯数字、等等）

### 6.2 `POST /api/auth/login`

Request：`{"email":"…","password":"…"}`
Response 200：`{"user":…}` + session cookie
错误：
- 401 `invalid_credentials`（邮箱不存在或密码错，统一文案不区分）
- 429 `rate_limited`（P1）

### 6.3 `POST /api/auth/logout`

登录态下清 session，返回 200。

### 6.4 `POST /api/auth/change-password`

Request：`{"old_password":"…","new_password":"…"}`
401 如 old 错；400 如 new 弱。

### 6.5 `POST /api/auth/reset` （用 token）

Request：`{"token":"<uuid>","new_password":"…"}`
token 不存在/过期/已用 → 400 `reset_invalid`

### 6.6 Admin：`/api/admin/invites`

- `GET` → 列出所有邀请码
- `POST` → 生成新码 `{"expires_in_days": 7}` 可选
- `DELETE /api/admin/invites/<code>` → 吊销

### 6.7 Admin：`/api/admin/users/<id>/reset-token`

生成该用户的重置 token，返回链接。不自动发邮件，admin 自行发。

### 6.8 `/api/settings/llm-provider` 扩展

现有接口（[model-switch](./model-switch.md)）新增：
- 存储位置：`user_settings.llm_provider`（不再写 yaml）
- 优先级：`env > user_settings > global yaml > legacy auto`
- GET 返回多加 `scope: "user" | "global_yaml" | "env" | "legacy"` 字段

## 7. 路由改造清单

Web 路由（[web/app.py](../../stock_trading_system/web/app.py)）约 30 条，逐条清单：

| 路由 | 当前 | 改造 |
|---|---|---|
| `/` | 公开 | `@login_required`；未登录重定向 /login |
| `/login`, `/register` | — | 新建模板 |
| `/api/portfolio/*` | 读全表 | WHERE user_id = g.user.id |
| `/api/alerts/*` | 读全表 | WHERE user_id = g.user.id |
| `/api/paper/*` | 读全表 | JOIN paper_trade_sessions ON user_id |
| `/api/analyze` (trigger) | 无 user 字段 | 创建 task 时 created_by = g.user.id |
| `/api/analysis/<id>` | 读共享 | 只需登录；不过滤 |
| `/api/screen/*` | 读共享 | 同上；创建时 created_by = g.user.id |
| `/api/tasks` | 全列表 | 查询参数 `scope=my|all`，默认 my |
| `/api/tasks/<id>/cancel` | — | 只允许 created_by = self 或 admin |
| `/api/settings/llm-provider` | 写 yaml | 写 user_settings |
| `/api/admin/*` | — | `@admin_required` |

统一规则：**列表型查询默认过滤 user_id；明细型查询按资源类型决定**（私有表要求匹配，共享表只要登录）。

## 8. 迁移脚本

`stock_trading_system/migrations/to_multi_tenant.py`

```python
"""One-shot migration: single-user → multi-tenant.

Usage:
    python -m stock_trading_system.migrations.to_multi_tenant \
           --admin-email admin@local \
           [--admin-password <plain>]   # optional; auto-gen if absent
           [--dry-run]
"""
```

### 执行步骤（全部在一个事务里，出错回滚）

1. **备份**：`shutil.copy(db, db + ".pre-mt.bak")`
2. **检查幂等**：若 `users` 表已存在且有行 → 已迁移，退出
3. **建新表**：users / invite_codes / user_settings / analysis_bookmarks
4. **创建 admin**：生成或接收初始密码（bcrypt hash 后 INSERT）
5. **给私有表加列**：
   - SQLite 不支持 `ADD COLUMN ... REFERENCES`，只能 `ADD COLUMN user_id INTEGER`
   - FK 约束通过应用层 + PRAGMA foreign_keys=ON 强制（新增 write 会校验）
   - 老数据：`UPDATE positions SET user_id = admin.id WHERE user_id IS NULL`（每张私有表一句）
6. **tasks.created_by 字符串 → FK**：按 §4.2
7. **索引**：按 §4.1
8. **校验**：`SELECT COUNT(*) FROM positions WHERE user_id IS NULL` 应为 0（每张私有表 assert）
9. **打印总结**：迁移行数、admin 密码（若自动生成）

### Dry-run

`--dry-run` 打印所有计划 SQL 但不执行。

### 回滚

`shutil.move(db + ".pre-mt.bak", db)` 即可。

## 9. 首次启动检测

`stock_trading_system/auth/bootstrap.py`：

```python
def ensure_multi_tenant_ready(db: PortfolioDatabase) -> None:
    """Called at Flask app creation. Idempotent."""
    if not _has_users_table(db):
        raise RuntimeError(
            "Database not migrated. Run: "
            "python -m stock_trading_system.migrations.to_multi_tenant"
        )
    if _user_count(db) == 0:
        raise RuntimeError(
            "Users table empty. Re-run migration to bootstrap admin."
        )
```

迁移和运行分离，避免生产误触自动建 admin。

## 10. 前端改造

### 10.1 新页面

| 页 | 路径 | 备注 |
|---|---|---|
| 登录 | `/login` | 独立极简模板，不复用主 nav |
| 注册 | `/register` | 同上 |
| 密码重置 | `/reset?token=<uuid>` | 同上 |

### 10.2 Nav 栏改造

```html
<!-- 顶部右侧 -->
<div class="nav-user-menu">
  <span class="nav-user-avatar">{{ user.display_name[0] }}</span>
  <span class="nav-user-email">{{ user.email }}</span>
  <div class="nav-user-dropdown">
    <a href="/settings">设置</a>
    <a href="/admin/invites" v-if="user.is_admin">邀请码</a>
    <a href="#" onclick="logout()">登出</a>
  </div>
</div>
```

### 10.3 任务中心

```html
<div class="tabs-scrollable">   <!-- 复用 mobile-optimization 组件 -->
  <a class="tab active" data-scope="my">我的任务</a>
  <a class="tab" data-scope="all">全部任务</a>
</div>
<div class="task-list" data-scope="my"></div>
```

切换 scope 重新请求 `/api/tasks?scope=my|all`。

### 10.4 分析/选股详情页

结果页头部加一行：

```html
<div class="result-audit">
  <i class="bi bi-person-circle"></i>
  由 <strong>{{ creator.display_name }}</strong>
  在 {{ created_at }} 触发
</div>
```

### 10.5 CSRF token 注入

```html
<meta name="csrf-token" content="{{ csrf_token() }}">
```

全局 fetch wrapper 自动读取并加到 header。

## 11. Model-switch 用户级覆盖

改造 [model-switch](./model-switch.md) 的 resolver：

```python
# stock_trading_system/llm/router.py （修改版）
def get_active_provider(config: dict, user_id: int | None = None) -> Provider:
    # 1. env
    env_val = os.environ.get(ENV_LLM_PROVIDER, "").strip().lower()
    if env_val in VALID_PROVIDERS:
        return env_val

    # 2. user_settings (NEW)
    if user_id is not None:
        us = user_settings_repo.get(user_id)
        if us and us.llm_provider in VALID_PROVIDERS:
            return us.llm_provider

    # 3. global yaml
    cfg_val = (config.get("llm_provider") or "").strip().lower()
    if cfg_val in VALID_PROVIDERS:
        return cfg_val

    # 4. legacy
    return "qwen" if (config.get("qwen") or {}).get("api_key") else "gemini"
```

调用处（analyzer / nl_parser / universe 等）需获得 `user_id` → 从 task 记录（`tasks.created_by`）或 `g.user.id` 取。

**对异步任务**：task 入队时 snapshot user_id 到 task 参数，worker 执行时读该 user_id（避免 worker 拿不到 request context）。

## 12. 实施计划

7 个 Phase，每 Phase 独立 commit。

### Phase 0 —— 依赖 + 配置（~0.5h）
- requirements.txt 加 bcrypt / Flask-WTF
- Flask SECRET_KEY 启动校验 + 自动生成

### Phase 1 —— 新表 + 迁移脚本（~2h）
- 建 users / invite_codes / user_settings / analysis_bookmarks
- 写 to_multi_tenant.py
- Dry-run + 真实运行测试

### Phase 2 —— auth 模块（~2.5h）
- password / session / invite / repository / decorators / bootstrap
- 单元测试覆盖

### Phase 3 —— 路由改造（~3h）
- before_request + CSRF 接入
- 30 条路由逐条加装饰器 + WHERE 过滤
- 审计字段 created_by 填充

### Phase 4 —— 前端登录/注册/Nav（~2.5h）
- /login /register /reset 三模板
- Nav 用户菜单 + 任务中心 tab
- 结果页审计信息条

### Phase 5 —— Model-switch 用户级（~1.5h）
- router 签名加 user_id
- analyzer / screener V2 / nl_parser 传递 user_id
- task 入队 snapshot

### Phase 6 —— 验收（~2h）
- 跑完整测试矩阵（见测试用例）
- 真实模拟 2-3 用户操作
- 更新 changelog

**总计 ~14h**。

## 13. 风险与缓解（细化 PRD §8）

| 风险 | 缓解措施 |
|---|---|
| 迁移脚本 SQLite `ADD COLUMN` 不支持 FK | 只加 INTEGER 列，应用层强制；PRAGMA foreign_keys=ON 新写校验 |
| 忘记给某 API 加 @login_required | before_request 默认要求登录；只有 PUBLIC_PATHS 白名单豁免 → 加错方向是"过度要求登录"，不是"越权" |
| Worker 异步任务拿不到 request context | 任务入队时 snapshot user_id 到 params_json；worker 直接读 |
| bcrypt 在 Railway 部署慢（cost=12 约 200ms） | 登录路径性能够用；超过则降到 cost=10 |
| SQLite 写并发瓶颈加剧 | WAL 模式已启用；多用户场景下继续验证 |
| 管理员忘记邀请码吊销 | 邀请码列表 UI + expires_at 默认 7 天 |
| Admin 被锁出 | 提供 `python -m stock_trading_system.auth.bootstrap reset-admin` 维护命令 |

## 14. 回滚方案

1. 停服务
2. `cp portfolio.db.pre-mt.bak portfolio.db`
3. 回滚代码到迁移前 commit
4. 重启

数据 100% 无损（迁移只 ADD COLUMN / UPDATE，未删任何列/行）。

## 15. 与其他模块的集成摘要

| 模块 | 本方案触及点 |
|---|---|
| [model-switch](./model-switch.md) | router 加 user_id 参数；user_settings.llm_provider 覆盖 yaml |
| [mobile-optimization](./mobile-optimization.md) | Login/Register/Reset 页沿用 `form-row-mobile` + `num-responsive`；Nav dropdown 用 mobile collapse-row |
| [paper-trade](./paper-trade.md) | sessions 加 user_id；全量追踪语义不变（但每用户独立） |
| [batch-analyze-holdings](./batch-analyze-holdings.md) | 批量基于"我的持仓" → 自动变用户级 |
| [self-iterating-agents](./self-iterating-agents.md) | 全局级（admin 开关），不分用户 |

## 16. 版本历史

| 版本 | 日期 | 变更 |
|---|---|---|
| v1.0 | 2026-04-19 | 初版：auth 模块 + 3 张新表 + 12 张表迁移 + Flask session + 邀请码 + 用户级 model-switch + admin 首启迁移 |
