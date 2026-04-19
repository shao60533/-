# 技术方案：统一实时进度系统（后端 + 前端）

| 项 | 值 |
|---|---|
| Feature | `unified-progress` |
| 版本 | v1.0 |
| 日期 | 2026-04-20 |
| 关联测试用例 | [../test-cases/unified-progress.md](../test-cases/unified-progress.md) |
| 跨模块影响 | 11 种异步任务类型 + 5 个前端页面 |

## 1. 目标

把"异步任务 → 进度展示"这条链路**从碎片化升级为统一、实时、可断线续传、按用户隔离**。后端不换技术栈（继续 Flask-SocketIO），前端抽出统一 `ProgressStream` 组件供所有页面复用。

### 1.1 成功指标

| 指标 | 目标 |
|---|---|
| 用户 A 不再收到用户 B 的进度事件 | 100%（per-user room 隔离）|
| 断线重连后恢复完整进度 | 丢包 ≤ 1 个事件 |
| 事件从发生到前端渲染 | ≤ 500ms（本地网络）|
| 所有页面使用同一 ProgressStream 组件 | 5/5 页面覆盖 |
| 空态 / 加载中 / 完成 / 失败 / 取消 5 态视觉一致 | 5/5 态统一 |
| 移动端（≤767.98px）交互无横滑、可见进度条 ≥ 44px 触达 | 100% |

## 2. 现状诊断（已审计，见 §11 原始输出）

**后端**：
- Flask-SocketIO 已接好 [web/app.py:8,16,333](../../stock_trading_system/web/app.py)
- 11 种 worker 统一通过 `task_progress` 事件 emit（`tasks/manager.py:202`），**但 screen_v3 / batch_analysis 绕过抽象直接 `socketio.emit`**
- 事件**全局广播**，无 room 隔离，违反 [multi-tenant](./multi-tenant.md)
- 事件**只在内存流**，无持久化 → 断线即永久丢失

**前端**：
- 任务中心 [app.js:3401](../../stock_trading_system/web/static/js/app.js) `loadTasks()` 只在页面加载时调一次 GET `/api/tasks`
- 各页面的进度渲染散落：任务中心 / batch-分析页 / screener-v3 / backtest 各写各的 handler
- `socket.on('connect')` 无 catch-up 逻辑 → 关浏览器再开就丢
- 无统一视觉规范（进度条、状态 pill、item 列表各写各）

## 3. 方案概览

```
┌───────────── Worker (11 种) ─────────────┐
│  emit_event(task_id, event, payload)     │ ← 统一入口，替代原 socketio.emit()
└────────────┬──────────────────────────────┘
             │
             ▼
┌─ emit_event (task_manager.py 新增) ───────────────────────┐
│  1. 从 task params_json 取 user_id                        │
│  2. 生成 seq（该 task 内递增）                             │
│  3. 包装 envelope {task_id, user_id, seq, event, payload, │
│                    emitted_at}                            │
│  4. INSERT INTO task_events（持久化，支撑 catch-up）      │
│  5. socketio.emit(event, envelope, to=f"user:{user_id}")  │
└────────────┬──────────────────────────────────────────────┘
             │
             ▼ WebSocket (room = user:<uid>)
┌─ ProgressStream (前端统一组件) ───────────────────────────┐
│  subscribe(task_ids, onEvent)                             │
│  on 'connect'    → GET /api/tasks/events?since=<last_seq> │
│                    补齐丢失事件                            │
│  on 'disconnect' → 显示连接中断状态，Socket.IO 自动重连    │
│  on 'reconnect'  → 自动触发 catch-up                      │
│  state: idle | connecting | streaming | stalled | done    │
│                                                           │
│  Render API:                                              │
│    ProgressStream.mount('#container', {                   │
│      taskIds: [...], layout: 'compact'|'detail'|'item',   │
│      onComplete: (task) => ...,                           │
│    })                                                     │
└───────────────────────────────────────────────────────────┘
             │
             ▼ 同一组件在 5 个页面挂载
任务中心 / 分析详情 / screener-v3 详情 / batch 持仓 / backtest
```

## 4. 后端改造（5 步）

### 4.1 新表 `task_events`

```sql
CREATE TABLE IF NOT EXISTS task_events (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id    TEXT    NOT NULL REFERENCES tasks(id),
    user_id    INTEGER NOT NULL REFERENCES users(id),
    seq        INTEGER NOT NULL,
    event      TEXT    NOT NULL,           -- 'task_progress' | 'guru_unit_done' | ...
    payload    TEXT    NOT NULL,           -- JSON
    emitted_at TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    UNIQUE (task_id, seq)
);
CREATE INDEX ix_task_events_user_seq ON task_events(user_id, id DESC);
CREATE INDEX ix_task_events_task_seq  ON task_events(task_id, seq);
```

**保留策略**：task 终态（success/failed/cancelled）后 7 天删除（用 `DELETE WHERE task_id IN (SELECT id FROM tasks WHERE status IN (...) AND completed_at < now('-7 days'))`，放进每日清理任务）。短期内（≤ 7 天）事件可无限回溯，足够覆盖用户再次登录的 catch-up。

### 4.2 `emit_event()` 统一入口

```python
# tasks/manager.py —— 新增，替代 _emit
import json
from stock_trading_system.portfolio.database import get_db
from stock_trading_system.web.app import socketio

_seq_lock = threading.Lock()
_seq_cache: dict[str, int] = {}

def emit_event(task_id: str, event: str, payload: dict) -> None:
    """Unified event emission. Persist → room-scoped broadcast."""
    task = task_store.get(task_id)
    if not task:
        return
    user_id = task.created_by  # 已在 multi-tenant 迁移中升级为 FK

    with _seq_lock:
        seq = _seq_cache.get(task_id, 0) + 1
        _seq_cache[task_id] = seq

    envelope = {
        "task_id":    task_id,
        "user_id":    user_id,
        "seq":        seq,
        "event":      event,
        "payload":    payload,
        "emitted_at": _now_iso(),
    }

    # 1. 持久化（同步，保证重连可拉取）
    get_db().execute(
        "INSERT INTO task_events(task_id, user_id, seq, event, payload) "
        "VALUES (?,?,?,?,?)",
        (task_id, user_id, seq, event, json.dumps(payload)),
    )

    # 2. 实时广播到用户 room（仅订阅该 user 的连接能收）
    socketio.emit(event, envelope, to=f"user:{user_id}")
```

**所有 worker 的调用点统一为 `emit_event(task_id, event, payload)`**，不再允许：
- 直接 `socketio.emit(...)`
- 绕过 task_manager 直接导 socketio

现有违规点修复：
- [workers.py:257](../../stock_trading_system/tasks/workers.py)（screen_v3）—— 改走 emit_event
- [workers.py:510-554,577](../../stock_trading_system/tasks/workers.py)（batch_analysis）—— 同上
- [workers.py:268-275](../../stock_trading_system/tasks/workers.py)（guru_unit_done / roundtable_*）—— 同上

### 4.3 Per-user room 隔离

```python
# web/app.py
from flask import g
from flask_socketio import join_room, leave_room

@socketio.on("connect")
def _ws_connect():
    user = getattr(g, "user", None)
    if user is None:
        return False  # 拒绝未登录的 socket 连接
    join_room(f"user:{user.id}")
    # 可选：告知客户端"最新 seq"方便它判断有无丢失
    latest = task_store.get_latest_seq_for_user(user.id)
    socketio.emit("connected", {"latest_seq": latest}, to=request.sid)

@socketio.on("disconnect")
def _ws_disconnect():
    pass  # Flask-SocketIO 自动清理 room membership
```

**安全**：没登录的 WS 连接直接拒绝（返回 False）。覆盖现有 multi-tenant 认证。

### 4.4 Catch-up API

```python
# web/app.py
@app.route("/api/tasks/events", methods=["GET"])
@login_required
def get_events_since():
    """Return events for current user since given seq (per-task)."""
    # 客户端传：task_id=<id>&since=<last_seq>
    # 或：since_map={task_id: last_seq, ...} JSON body for bulk
    task_id = request.args.get("task_id")
    since   = int(request.args.get("since", 0))
    rows = db.fetchall(
        "SELECT seq, event, payload, emitted_at FROM task_events "
        "WHERE task_id=? AND user_id=? AND seq > ? ORDER BY seq",
        (task_id, g.user.id, since),
    )
    return jsonify([{
        "task_id": task_id, "seq": r["seq"], "event": r["event"],
        "payload": json.loads(r["payload"]), "emitted_at": r["emitted_at"],
    } for r in rows])


@app.route("/api/tasks/running", methods=["GET"])
@login_required
def get_running_tasks():
    """For reconnect: what tasks of mine are currently live?"""
    rows = db.fetchall(
        "SELECT id, type, status, progress, params_json, created_at "
        "FROM tasks WHERE created_by=? AND status IN ('pending','running') "
        "ORDER BY created_at DESC",
        (g.user.id,),
    )
    return jsonify([_task_to_dict(r) for r in rows])
```

### 4.5 事件清理

新增 daily 任务 `cleanup_old_task_events`（走现有任务系统 + APScheduler）：

```python
# tasks/workers.py
def make_cleanup_task_events_worker():
    def worker(task):
        deleted = db.execute(
            "DELETE FROM task_events WHERE task_id IN ("
            " SELECT id FROM tasks WHERE status IN ('success','failed','cancelled') "
            " AND completed_at < datetime('now','-7 days'))"
        ).rowcount
        return {"deleted": deleted}
    return worker
```

## 5. 前端改造

前端是本方案的**等量重点**。不只是后端改，UI 层也要统一组件 + 统一视觉。

### 5.1 `ProgressStream` 组件

新建 [static/js/progress_stream.js](../../stock_trading_system/web/static/js/progress_stream.js)：

```js
/**
 * ProgressStream — 统一任务进度流订阅 + 渲染组件
 *
 * Usage:
 *   const stream = ProgressStream.mount('#my-container', {
 *     taskIds: ['uuid-1', 'uuid-2'],
 *     layout: 'compact',      // 'compact' | 'detail' | 'inline-badge'
 *     onEvent: (envelope) => { ... },   // 可选：额外业务逻辑
 *     onComplete: (task) => { navigate(...) },
 *   });
 *   // 外部再订阅：
 *   stream.subscribe('uuid-3');
 *   stream.unsubscribe('uuid-1');
 *   stream.destroy();
 */
class ProgressStream {
  static mount(selector, opts) { /* ... */ }

  constructor(container, opts) {
    this.container  = container;
    this.opts       = opts;
    this.taskIds    = new Set(opts.taskIds || []);
    this.tasks      = new Map();     // taskId -> { meta, events[], lastSeq }
    this.socket     = null;
    this.status     = 'connecting';  // 'connecting' | 'streaming' | 'stalled' | 'disconnected'
    this._render();
    this._connect();
  }

  async _connect() {
    // 复用已有 socketio-client（index.html 已引入）
    this.socket = io({ transports: ['websocket'] });
    this.socket.on('connect',    () => this._onConnect());
    this.socket.on('disconnect', () => this._setStatus('disconnected'));
    this.socket.on('reconnect',  () => this._onConnect());
    // 泛监听所有事件（通过 onAny）
    this.socket.onAny((event, env) => {
      if (!this.taskIds.has(env.task_id)) return;
      this._applyEvent(env);
      opts.onEvent?.(env);
    });
  }

  async _onConnect() {
    this._setStatus('streaming');
    // Catch-up：每个订阅 task 拉 since=<lastSeq>
    for (const taskId of this.taskIds) {
      const lastSeq = this.tasks.get(taskId)?.lastSeq ?? 0;
      const r = await fetch(`/api/tasks/events?task_id=${taskId}&since=${lastSeq}`, {
        headers: { 'X-CSRFToken': csrfToken() }
      });
      const events = await r.json();
      for (const env of events) this._applyEvent(env);
    }
  }

  _applyEvent(env) {
    const entry = this.tasks.get(env.task_id) ?? { events: [], lastSeq: 0 };
    if (env.seq <= entry.lastSeq) return;  // 幂等：忽略已处理的 seq
    entry.events.push(env);
    entry.lastSeq = env.seq;
    this.tasks.set(env.task_id, entry);
    this._render();
    if (env.event === 'task_completed') {
      this.opts.onComplete?.(env.payload);
    }
  }

  _render() { /* 按 opts.layout 渲染 */ }

  subscribe(taskId)   { this.taskIds.add(taskId); this._onConnect(); }
  unsubscribe(taskId) { this.taskIds.delete(taskId); this.tasks.delete(taskId); }
  destroy()           { this.socket?.close(); this.container.innerHTML = ''; }
}
```

### 5.2 三种布局

**`layout: 'compact'`** —— 任务中心列表一行 / persistent bar：

```
┌──────────────────────────────────────────────────────────┐
│ [●] 分析 AAPL · 64%                    [停止] [查看详情] │
│    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━                │
└──────────────────────────────────────────────────────────┘
```

**`layout: 'detail'`** —— 任务详情页完整版：

```
┌──────────── analysis #a7f · 运行中 ────────────┐
│ ● 流式连接中                                    │
│                                                 │
│ 当前阶段：fundamentals_agent 正在分析          │
│ ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 64%      │
│                                                 │
│ 已完成 5/8 · 缓存命中 2 · 剩余 ~1.5 min       │
│                                                 │
│ ┌─ 事件流 ───────────────────────────────┐    │
│ │ ✅ market_agent   已完成   3.2s         │    │
│ │ ✅ news_agent     已完成   4.1s  [缓存] │    │
│ │ 🔄 fundamentals   正在分析  ...         │    │
│ │ ⏳ sentiment      排队中               │    │
│ └─────────────────────────────────────────┘    │
│                                                 │
│              [停止]          [查看结果]         │
└─────────────────────────────────────────────────┘
```

**`layout: 'inline-badge'`** —— 嵌在列表行末尾的微型指示：

```
AAPL · 2026-04-20 · 分析中 [●●●○○ 64%]
```

### 5.3 5 态 × 颜色规范

| 状态 | 图标 | 颜色 | 文案 |
|---|---|---|---|
| idle（无订阅）| — | 不渲染 | — |
| connecting | ⏳ 呼吸灯 | `--text-secondary` | "连接中..." |
| streaming | ● 脉冲绿 | `--accent-green` | "实时流" |
| stalled（> 10s 无事件）| ⚠️ | `--accent-yellow` | "进度暂停，尝试恢复..." |
| disconnected | ✕ | `--accent-red` | "连接断开，自动重连中" |

脉冲动画用 CSS keyframe（纯 CSS，无 JS 轮询）。

### 5.4 断线 UX（明确规范）

- **≤ 2 秒自动重连成功**：静默，不打扰用户；仅连接指示点颜色闪一下黄→绿
- **2-10 秒断线**：顶部悄悄 banner `连接中断，正在重连...`
- **> 10 秒仍未连上**：banner 加 `[手动重试]` 按钮
- **重连成功后**：banner 变 `已恢复，补齐 N 个事件`，3 秒后自淡出
- **tab 非活跃时**：浏览器暂停 socket 是正常行为，活跃时自动 catch-up，**不提示用户**

### 5.5 进度条视觉规范

- 进度条：高 4px（桌面）/ 6px（移动，触达友好），底色 `rgba(56,130,255,0.08)`，填充 `var(--accent-blue)` 带 `transition: width 400ms ease-out`
- 完成瞬间：添加 `transform: scaleX(1.02)` 的弹性一下效果（200ms 回弹）
- 失败瞬间：颜色切 `var(--accent-red)` 并轻微震动（CSS `animation: shake 400ms`）
- 不确定进度（如 `total` 未知）：退化为 `indeterminate` 扫光条纹（纯 CSS）

### 5.6 事件流列表视觉

每条事件行复用 [mobile-optimization](./mobile-optimization.md) 的 `.m-card` 风格：

```html
<div class="event-row" data-status="done|running|pending|failed">
  <span class="event-icon">✅</span>
  <span class="event-title">market_agent</span>
  <span class="event-status">已完成</span>
  <span class="event-meta">3.2s · 缓存</span>
</div>
```

- done: 静态绿 ✅
- running: 脉冲 🔄（CSS `animation: spin 2s linear infinite`）
- pending: 灰 ⏳
- failed: 红 ❌ + 点击展开 reasoning

新增事件行从底部淡入（`animation: slide-up 300ms`），旧事件超 10 条折叠（"查看更早的 N 条"展开）。

### 5.7 移动端适配

- ≤575.98px：`detail` 布局折叠到只显示当前阶段 + 进度条，事件流默认折叠（点击展开）
- 进度条高 6px（比桌面粗）；触达区 ≥ 44px
- 断开 banner 使用 `position: fixed; top: 0;` 挂全屏顶（不遮 tabbar）
- 复用 `.tabs-scrollable` / `.collapse-row` / `.chip-row` tokens

### 5.8 5 个页面的集成清单

| 页面 | 原有 handler | 改造 | layout |
|---|---|---|---|
| [任务中心](../../stock_trading_system/web/templates/index.html#L1059) | `loadTasks` + socket event | 每行挂 `ProgressStream(compact)`；顶部全局连接指示 | `compact` |
| [分析详情](../../stock_trading_system/web/templates/index.html#L263) | `app.js:624` handleAnalyze | 触发分析后在结果区上方挂 `detail` 组件 | `detail` |
| [screener-v3 任务页](../../stock_trading_system/web/static/js/screener_v3.js) | 自制 guru_unit_done handler | 删除自制，全换 `ProgressStream(detail)`；guru 事件渲染仍走 `onEvent` 回调自定义 item | `detail` + custom item renderer |
| [batch 持仓](../../stock_trading_system/web/static/js/app.js#L4728) | `batch_analysis_item` handler | 删除自制；用 `detail` 模式；每 item 为一行事件 | `detail` |
| [backtest](../../stock_trading_system/web/static/js/app.js#L4165) | 自制进度 | 换 `compact`，结果 ready 后跳结果 tab | `compact` |

### 5.9 辅助 hook：全局连接指示

在 nav 栏右上角加一个 3px 小圆点，状态跟 ProgressStream 全局实例一致：

```
[🏠 仪表盘]  [🧠 分析]  [🎯 选股]  ...    [●] 实时  [👤 admin ▾]
```

点击点 → 展开一个 popover 显示"当前 N 个运行中任务"，跳转到任务中心。

## 6. 事件 envelope 标准 schema

所有事件统一：

```json
{
  "task_id": "uuid",
  "user_id": 42,
  "seq": 17,
  "event": "task_progress | task_completed | task_failed | task_cancelled | guru_unit_done | batch_analysis_item | roundtable_start | roundtable_done | agent_stage_done",
  "payload": { ... task-specific ... },
  "emitted_at": "2026-04-20T10:22:33.456Z"
}
```

**通用事件（所有 task 都会有）**：
- `task_progress` — payload: `{progress: 0-1, current, total, stage, eta_sec}`
- `task_completed` — payload: `{result_ref, duration_ms}`
- `task_failed` — payload: `{error, traceback}`
- `task_cancelled` — payload: `{reason}`

**领域事件**（各业务自定义 payload，但 envelope 同）：
- `guru_unit_done` — screener-v3
- `batch_analysis_item` — batch-analyze-holdings
- `roundtable_start` / `roundtable_done` — screener-v3
- `agent_stage_done` — analysis（每个 TradingAgent 阶段完成）

扩展新事件 = 新字符串，无需改 envelope。

## 7. 复用 / Reuse

遵循 [engineering-principles.md](../engineering-principles.md) L0→L4：

### L0 项目内复用
- [Flask-SocketIO 基础设施](../../stock_trading_system/web/app.py)（连接、emit、room API）全部沿用
- [tasks/manager.py](../../stock_trading_system/tasks/manager.py) `_emit` 内部逻辑保留，外加 DB 持久化 + room
- [mobile-optimization](./mobile-optimization.md) 的 `.m-card` / `.tabs-scrollable` / `.collapse-row` / CSS tokens 直接用
- [multi-tenant](./multi-tenant.md) 的 `@login_required` + `g.user` 决定 room

### L1 依赖库
- **socket.io-client**（前端已装）—— `onAny()` 监听所有事件 + 原生 `reconnect` 事件
- 无需新增 pip 包（server 端 Flask-SocketIO 已满足）

### L2 思路参考
- [GitHub Actions build log](https://github.blog/engineering/) 的 Last-Event-ID 断线续传思路 → 翻译为 `seq + since=<last_seq>`
- [Hasura subscriptions](https://hasura.io/docs/) 的 subscription-id + room 隔离
- [htmx + SSE](https://htmx.org/extensions/sse/) 的极简渲染模型（本项目不换 SSE，仅借鉴 UI 设计）

### L3 Clean-room
无

### L4 必须自写
| 模块 | 行数 | 理由 |
|---|---|---|
| `task_events` 表 + `emit_event()` | ~80 | 本项目特有的"seq + DB 持久化"组合 |
| `ProgressStream` 组件 | ~300 | 业务特定的 3 布局 + 5 态 + 5 页面集成，无等价组件可复用 |
| 5 页面替换散落 handler | ~-200（删多于加）| 纯重构，预计净减少代码 |
| Catch-up API (2 endpoints) | ~30 | 业务特定 |

**净增 ~210 LOC，净减 ~200 LOC 分散代码，总量几乎持平但一致性大幅提升**。

## 8. 迁移 & 回滚

### 8.1 迁移脚本 `migrations/task_events_v1.py`（幂等，支持 `--dry-run`）

```python
1. 备份 portfolio.db → portfolio.db.pre-progress.bak
2. CREATE TABLE task_events（IF NOT EXISTS）
3. CREATE INDEX（IF NOT EXISTS）
4. 无老数据需要回填（历史事件已丢失，接受损失）
5. 打印：表建立 ✓ / 索引 ✓ / 下一步：部署新代码
```

### 8.2 分阶段回滚
按下面 §9 的 5 phase 分别独立 commit → 任何 phase 出问题 `git revert` 该 phase 即可。DB 表新增为幂等 ALTER，回滚不需要 drop。

## 9. 实施计划（5 Phase，独立 commit）

### Phase 1 —— DB 表 + emit_event 入口（~2h）
- 建 task_events 表（幂等迁移）
- 新增 `tasks/manager.py::emit_event()` 统一入口
- 旧 `_emit()` 保留但内部改调 `emit_event`（过渡兼容）
- 单测 covering emit + seq 递增 + 持久化

### Phase 2 —— SocketIO room 隔离 + Catch-up API（~2h）
- `@socketio.on("connect")` 加 `join_room(f"user:{id}")`
- 未登录拒绝连接
- 新增 `GET /api/tasks/events` + `GET /api/tasks/running`
- 集成测：user A 触发任务，user B WS 不收到

### Phase 3 —— 所有 worker 改用 emit_event（~2h）
- screen_v3 / batch_analysis 移除直接 socketio.emit
- 11 种 worker 全扫，确保无遗漏直接调用
- 本地验证：所有任务类型发出的事件都落库 task_events

### Phase 4 —— `ProgressStream` 组件 + 5 页面集成（~4h）
- 新建 `static/js/progress_stream.js`（3 布局 + 5 态 + 断线 UX）
- CSS 样式（进度条 + 事件流 + 5 态色）
- 5 个页面逐个替换原 handler
- Playwright E2E

### Phase 5 —— 清理 + 收尾（~1h）
- 每日 cleanup_old_task_events 任务
- Nav 全局连接指示点
- 移动端断点回归
- 文档 changelog 更新

**总计 ~11h**。

## 10. 风险与缓解

| 风险 | 概率 | 缓解 |
|---|---|---|
| SocketIO room join 与 Flask session 的生命周期不一致 | 中 | `@socketio.on("connect")` 里显式从 session cookie 拿 user_id；cookie 过期时拒绝 |
| 事件持久化成为 hot path 瓶颈 | 低 | SQLite WAL 已开；单用户 ≤ 100 events/min 完全无压力；如果爆表改 async 入库 |
| 旧 `_emit()` 残留调用 | 中 | Phase 3 加 lint rule：`grep 'socketio.emit' stock_trading_system/tasks/ \| wc -l` 必须 0 |
| 前端 ProgressStream 跟散落 handler 同时工作导致双 emit UI | 中 | Phase 4 严格 per-page 切换，同页同时间只能有一种 handler |
| catch-up 在大量事件时慢 | 低 | `since=<seq>` 索引走 `ix_task_events_task_seq`；单任务事件通常 < 200 条 |
| SocketIO 在 Railway / 某些 proxy 下降级到 polling | 中 | transports=['websocket', 'polling'] fallback，polling 性能够用但不要直接禁用 |
| 多标签页同时订阅同一 task，重复渲染 | 低 | 组件幂等；前端 BroadcastChannel（浏览器标签间通信）P1 可选优化 |

## 11. 审计原始输出（附录）

诊断数据见本次 session 子代理审计（2026-04-20）：
- 11 种 task type 全列清单 + file:line
- 无 SSE、无自动轮询、WS 全局广播
- 自定义事件 3 个（guru_unit_done / batch_analysis_item / roundtable_*）
- task_manager `_emit` 被绕过 3 处

## 12. 版本历史

| 版本 | 日期 | 变更 |
|---|---|---|
| v1.0 | 2026-04-20 | 初版：task_events 表 + emit_event 统一入口 + per-user room + 断线续传 catch-up API + ProgressStream 前端组件（3 布局 5 态）+ 5 页面集成清单 + 事件标准 envelope + 5 Phase 实施计划 |
