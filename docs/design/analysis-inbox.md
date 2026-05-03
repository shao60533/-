# 技术方案：AI 分析 + 分析记录合并 (Analysis Inbox)

| 项 | 值 |
|---|---|
| Feature | `analysis-inbox` |
| 版本 | v1.1 |
| 日期 | 2026-05-02 |
| 关联 | [ui-react-island-regression v1.18 R-fix-12](./ui-react-island-regression.md)（HistoryPage 分页 / 筛选 / 多选对比 / 删除）+ [v1.13 R-fix-7E](./ui-react-island-regression.md)（/analysis 5 卡 + 8 tab + depth）+ [unified-progress v1.0](./unified-progress.md)（per-user task_events 流） |
| 关联测试 | `tests/web/test_history_inbox.py`、`tests/web/test_history_redirect.py`、`tests/frontend/AnalysisInbox.spec.tsx` |

## 1. 背景

当前 AI 分析的用户动线被切到 3 个独立 island，造成 "得跑多个地方查"：

| 路径 | 实现 | 问题 |
|---|---|---|
| `/analysis` 主页 | 表单 + 5 条最近卡（`/api/history?limit=5`） | 5 卡无分页/筛选/操作；运行中 task 不显示 |
| `/analysis/<task_id>` 运行中 | PipelineDAG 跑（`replaceState` 切换 URL）| 离开主页后，想看其它历史得返回 |
| `/analysis/<analysis_id>` 详情 | 完整 8 tab 详情（v1.13 R-fix-7E）| 这是真正的"详情页"，没问题 |
| `/history` 列表 | 完全独立 island（v1.18 R-fix-12G 分页/筛选/对比/删除）| **与 /analysis 主页 5 卡是同一份数据的两套实现** |
| `/tasks` 任务中心 | 含 analysis 类型任务进度 | 用户感觉"还得去那查"——根因：**没有一个页面同时展示运行中 + 已完成** |

**根因**：`analysis_history` 只保存**已完成**行；活跃 task 只在 `tasks` 表。前端两边分别拉，没有合并视图，用户被迫切页。

## 2. 设计目标

1 个主入口（`/analysis`）= 提交表单 + 时间线 Inbox（运行中 + 已完成混合排序）。详情页保持独立路由（深链 / 分享 / SEO 友好）。任务中心**不变**——它本来就是给所有任务类型用的总览，不是 analysis 专属入口。

## 3. 信息架构 + URL 状态机

| URL | 渲染 | 用户动作 |
|---|---|---|
| `/analysis` | `<AnalysisFormHeader>` 表单 + `<AnalysisInbox>` 时间线列表 | 提交新分析 / 浏览历史 / 多选对比 / 收藏 |
| `/analysis/<analysis_id>`（数字 id） | 完整 8 tab 详情（v1.13 + v1.18 现状不变） | 看完整决策、quick-info 三卡、操作按钮 |
| `/analysis/<task_uuid>`（UUID） | **不再使用**（v1.7 引入的运行中视图，v1.0 inbox 后废）→ 301 redirect 到 `/analysis?task=<uuid>` | 主页 anchor 到对应运行中卡 |
| `/history` | **301 redirect → `/analysis`**（query string 透传） | 旧书签兼容 |
| `/tasks` `/tasks/<id>` | **不变**——任务中心保留所有任务类型总览 | 跨类型 task 排查；analysis 任务仍可在此查看（v1.7 [查看结果] 跳 /analysis/<id>） |

旧 URL `/analysis/<task_uuid>` 进入主页后，前端检测 query `task=<uuid>` 自动滚动到对应运行中卡 + 展开。

## 4. 数据合并

### 4.1 `/api/history` 加 `include_running` 参数

```
GET /api/history?
    limit=50&offset=0
    &include_running=true
    &ticker=&signal=&provider=&bookmarked=&created_by=me|all
```

返响应（在 v1.18 R-fix-12F `{items, total, limit, offset}` 基础上扩展）：

```json
{
  "items": [
    {
      "kind": "task",
      "task_id": "uuid-...",
      "ticker": "AAPL",
      "depth": "standard",
      "status": "queued",                  // queued | running | failed | cancelled
      "submitted_at": "2026-05-02 10:15:23",
      "task_started_at": "2026-05-02 10:15:25",
      "progress_pct": 0,
      "error": null,
      "created_by": 1,
      "created_by_name": "alice"
    },
    {
      "kind": "analysis",
      "id": 142, "ticker": "MSFT", "signal": "BUY",
      "created_at": "2026-05-02 10:12:01", "created_by": 1,
      "created_by_name": "alice",
      "provider": "qwen", "model": "qwen-max",
      "duration_sec": 108, "task_id": "uuid-...",
      "depth": "standard", "bookmarked": false
      // 全 v1.18 R-fix-12G LIST_FIELDS 字段
    },
    ...
  ],
  "total": 142,
  "running_total": 2,
  "completed_total": 142,
  "limit": 50,
  "offset": 0
}
```

排序：所有行按 `task.created_at` 与 `analysis.created_at` 合并 `DESC`，运行中行不在顶部锁定（按真实时间排序）—— 但**运行中默认全部返回**（不参与 limit），完成行参与 limit/offset。

### 4.2 后端实现路径

[stock_trading_system/portfolio/database.py](../../stock_trading_system/portfolio/database.py) 新方法（不动 v1.18 `list_analysis_history`）：

```python
def list_analysis_history(self, *,
                            ticker=None, signal=None, provider=None,
                            bookmarked_user_id=None, created_by=None,
                            limit=50, offset=0,
                            exclude_task_ids: list[str] | None = None):
    """v1.18 contract preserved; new optional ``exclude_task_ids`` lets the
    inbox view drop completed rows whose underlying task is still being
    streamed in the running half (avoids duplicate cards during the few
    hundred ms between task_completed and DB save)."""
    ...
```

[stock_trading_system/web/app.py](../../stock_trading_system/web/app.py) `/api/history` 重写：

```python
@app.route("/api/history")
@login_required
def api_analysis_history():
    include_running = (request.args.get("include_running") or "").lower() == "true"
    # ... 现有 v1.18 query 解析 ...

    running_items: list[dict] = []
    running_task_ids: set[str] = set()
    if include_running:
        store = _get_task_store()
        # 仅当前用户 + analysis 类型 + 活跃 / 失败 状态
        active_states = ("pending", "running", "failed", "cancelled")
        active = store.list_tasks_by_user_and_type(
            user_id=g.user.id, task_type="analysis",
            statuses=active_states, limit=20,
        )
        for t in active:
            params = json.loads(t.get("params_json") or "{}")
            running_items.append({
                "kind": "task",
                "task_id": t["id"],
                "ticker": (params.get("ticker") or "").upper(),
                "depth": params.get("depth", "standard"),
                "status": t["status"],
                "submitted_at": t.get("created_at"),
                "task_started_at": t.get("started_at"),
                "progress_pct": int(t.get("progress") or 0),
                "error": t.get("error_message"),
                "created_by": t.get("created_by"),
                "created_by_name": "<resolve via user repo cache>",
            })
            running_task_ids.add(t["id"])

    rows, total = db.list_analysis_history(
        ..., limit=limit, offset=offset,
        exclude_task_ids=list(running_task_ids) or None,
    )
    completed_items = [history_list_dto(r, ...) for r in rows]
    completed_items_with_kind = [{**c, "kind": "analysis"} for c in completed_items]

    # Merge sort by created_at DESC. Running items are NOT in offset
    # window — they're always returned in full so the inbox always
    # reflects current state.
    merged = sorted(
        running_items + completed_items_with_kind,
        key=lambda x: x.get("submitted_at") or x.get("created_at") or "",
        reverse=True,
    )

    return jsonify({
        "items": merged,
        "total": total,
        "running_total": len(running_items),
        "completed_total": total,
        "limit": limit, "offset": offset,
    })
```

新方法 `TaskStore.list_tasks_by_user_and_type`：

```python
def list_tasks_by_user_and_type(self, *, user_id: int, task_type: str,
                                  statuses: tuple[str, ...], limit: int = 20):
    placeholders = ",".join("?" * len(statuses))
    sql = (f"SELECT id, type, status, progress, error_message, "
            f"created_at, started_at, completed_at, params_json, created_by "
            f"FROM tasks "
            f"WHERE created_by = ? AND type = ? AND status IN ({placeholders}) "
            f"ORDER BY created_at DESC LIMIT ?")
    with self._lock, self._conn() as conn:
        rows = conn.execute(sql, [int(user_id), task_type, *statuses, int(limit)]).fetchall()
        return [dict(r) for r in rows]
```

### 4.3 `/history` Flask 路由 → 301 redirect

```python
@app.route("/history")
def history_page():
    """v1.0 inbox: bookmarks redirected to the unified /analysis page.

    Query string is preserved so saved /history?ticker=X URLs keep
    working (Inbox uses the same query syntax as v1.18 HistoryPage)."""
    qs = request.query_string.decode() if request.query_string else ""
    target = "/analysis" + (f"?{qs}" if qs else "")
    return redirect(target, code=301)
```

## 5. 前端组件

### 5.1 路由分发

[stock_trading_system/web/frontend/src/islands/analysis/AnalysisPage.tsx](../../stock_trading_system/web/frontend/src/islands/analysis/AnalysisPage.tsx) 顶层改：

```tsx
export function AnalysisPage() {
  const urlId = getIdFromUrl()  // existing
  // /analysis/<numeric-id> → 完整详情页 (不变, v1.13 / v1.18 现状)
  if (urlId && !isTaskId(urlId)) return <AnalysisDetailView ... />
  // /analysis/<task_uuid> → 301 to /analysis?task=<uuid>; 见 §3 URL 状态机
  if (urlId && isTaskId(urlId)) {
    window.history.replaceState(null, "", `/analysis?task=${urlId}`)
  }
  return <AnalysisHomeInbox initialTaskAnchor={urlId && isTaskId(urlId) ? urlId : null} />
}
```

### 5.2 `<AnalysisHomeInbox>` 主组件

```tsx
function AnalysisHomeInbox({ initialTaskAnchor }: { initialTaskAnchor: string | null }) {
  return (
    <div className="p-4 md:p-6 max-w-5xl mx-auto space-y-6">
      <AnalysisFormHeader onSubmitted={(taskId, ticker, depth) => addOptimisticTask(...)} />
      <AnalysisInboxList anchor={initialTaskAnchor} />
    </div>
  )
}
```

### 5.3 `<AnalysisFormHeader>`

紧凑表单（不再占整页）：单行 ticker input + depth chip + Submit。提交后**不跳页**——通过 `onSubmitted` 把新 task 插到 inbox 顶部。复用 v1.13 R-fix-7E DEPTH 选项。

### 5.4 `<AnalysisInboxList>` Inbox 列表

数据流：
- mount 时 `apiGet('/api/history?include_running=true&limit=50&offset=0&...')`
- 对每个 `kind=task` 行 `subscribeTaskStream({taskIds:[task.task_id], onEvent})`
- `task_completed` 事件 → 该 task 行变为 `analysis` 行（用 `result_ref` 解出 analysis_id 后 `apiGet('/api/history/<id>')` 拉详情，替换列表中该项；不再保留 task 卡）
- `task_failed` → 替换为失败卡（保留 ticker / submitted_at + error）
- `task_cancelled` → 替换为取消卡（带 [重试] 按钮）

工具栏（复用 v1.18 R-fix-12G）：scope tab `[全部] [我的]` / 仅收藏 / ticker / signal / provider 服务端 query / 多选对比按钮 / 加载更多。

行渲染按 `kind` 分发：

```tsx
{items.map(row =>
  row.kind === "task"
    ? <RunningRow key={row.task_id} row={row} onComplete={...} onFailure={...} />
    : <CompletedRow key={row.id} row={row}
                     selected={selected.has(row.id)}
                     onToggle={() => toggleSelect(row.id)}
                     onDelete={() => deleteOne(row)}
                     onBookmark={() => toggleBookmark(row)} />
)}
```

### 5.5 `<RunningRow>`（运行中卡）

```tsx
function RunningRow({ row, onComplete, onFailure }: ...) {
  const [collapsed, setCollapsed] = useState(() => isMobileViewport())  // 移动默认折叠

  return (
    <div className="border-b py-3 px-2">
      <div className="flex items-center gap-3">
        <Loader2 className="h-4 w-4 animate-spin text-primary" />
        <span className="font-mono font-semibold">{row.ticker}</span>
        <Badge variant="muted" className="text-[10px]">{DEPTH_LABEL[row.depth]}</Badge>
        <Badge variant="default" className="text-[10px]">运行中</Badge>
        <span className="text-xs text-muted-foreground ml-auto">
          {fmtRelative(row.submitted_at)}
        </span>
        <Button size="sm" variant="ghost" onClick={() => setCollapsed(!collapsed)}>
          {collapsed ? <ChevronRight /> : <ChevronDown />}
        </Button>
        <Button size="sm" variant="ghost" onClick={() => cancelTask(row.task_id)}>
          <X className="h-3.5 w-3.5" />
        </Button>
      </div>
      {!collapsed && (
        <div className="mt-3 pl-6">
          <PipelineDAG taskId={row.task_id}
                        onAllDone={() => fetchAndReplace(row.task_id)} />
        </div>
      )}
      {collapsed && row.progress_pct != null && (
        <div className="pl-6 mt-1">
          <div className="h-1 bg-muted rounded overflow-hidden">
            <div className="h-full bg-primary transition-all"
                 style={{ width: `${row.progress_pct}%` }} />
          </div>
        </div>
      )}
    </div>
  )
}
```

`isMobileViewport()` 用 `window.matchMedia('(max-width: 575.98px)')`（与 mobile-optimization.md 断点一致）。

### 5.6 `<CompletedRow>`（完成卡）

行 + 展开形态完全复用 v1.18 R-fix-12G HistoryPage 行：
- 折叠：checkbox + ticker + signal Badge + 创建者 + provider/model + 耗时 + bookmark + [查看] [时间线] [导出 MD] + (owner/admin) [删除]
- 展开：trade_decision 摘要（前 400 字）
- 不需要做任何新组件 → 直接抽取 v1.18 HistoryPage 中的行渲染为 `<CompletedRow>` 子组件

### 5.7 `<AnalysisDetailView>`（不变）

`/analysis/<numeric-id>` 路由的完整 8 tab 详情页**完全不动**——v1.13 R-fix-7E + v1.18 R-fix-12B + analysis-rendering v1.0/v1.1 落地后的全部组件保留。Inbox 行点 [查看完整] 跳此页。

### 5.8 Sidebar 导航

[stock_trading_system/web/frontend/src/components/shared/Sidebar.tsx](../../stock_trading_system/web/frontend/src/components/shared/Sidebar.tsx) 删除"分析记录" 菜单项（line 36 桌面 + line 140 移动）：

```tsx
// 删除以下两行
{ label: "分析记录", href: "/history",   icon: <ClockArrowDown className="w-4 h-4" /> },
{ label: "分析记录", href: "/history",   icon: <ClockArrowDown className="w-5 h-5" /> },
```

`/history` 路由保留作 redirect（旧书签 / 外链不破）。

## 6. 提交流程（乐观更新）

```
[用户点 Submit]
    ↓
POST /api/tasks/submit { type: "analysis", params: { ticker, date, depth } }
    ↓
返 { task_id }
    ↓
addOptimisticTask({
  kind: "task", task_id, ticker, depth,
  status: "queued", submitted_at: new Date().toISOString(),
  progress_pct: 0,
})  # 列表顶部立刻插
    ↓
useEffect 订阅该 task_id 的事件流 (subscribeTaskStream)
    ↓
[task_started 事件] → status='running'
[step_done 事件]    → progress_pct 累加
[task_completed]    → 解 result_ref → apiGet /api/history/<analysis_id>
                     → 替换该行为 kind='analysis' 行
[task_failed]       → 替换为失败行
[task_cancelled]    → 替换为取消行
```

提交后清空 ticker input；如用户立刻提交其它 ticker，Inbox 顶部叠加多个运行中条目（按提交时间排序）。

## 7. PipelineDAG inline 模式

复用 v1.17 R-fix-11F 修过的 [PipelineDAG.tsx](../../stock_trading_system/web/frontend/src/components/shared/PipelineDAG.tsx)，无需改组件本身。Inbox 行作为容器：
- 桌面 ≥768px：默认展开，7 节点完整 DAG inline 渲染
- 移动 <576px：默认折叠，仅显示 1px 进度条 + 当前节点 label；点击展开同桌面

## 8. 实施分期

| 步 | 范围 | 工时 |
|---|---|---|
| 1 | 后端 `TaskStore.list_tasks_by_user_and_type` + `/api/history` 加 `include_running` 合并排序 + redirect /history | ~1.5h |
| 2 | 前端 `<AnalysisHomeInbox>` + `<AnalysisFormHeader>` + `<AnalysisInboxList>` 主框架 + 路由分发 | ~2h |
| 3 | `<RunningRow>` inline PipelineDAG + 默认折叠/展开切换 + 取消按钮 | ~1.5h |
| 4 | `<CompletedRow>` 抽取自 v1.18 HistoryPage（行渲染 + 展开摘要 + 操作按钮 + 多选对比） | ~1h |
| 5 | 提交乐观更新 + 订阅事件流 + 完成替换 + 失败/取消行 | ~1.5h |
| 6 | Sidebar 去 "分析记录" 项 + URL deep link `?task=<uuid>` 滚动锚定 | ~30min |
| 7 | 测试 + npm build + 端到端 smoke | ~1h |
| **合计** | | **~9h** |

## 9. 复用 / 边界

依据 [engineering-principles.md](./engineering-principles.md)：

- **L0 项目内**：v1.18 R-fix-12G HistoryPage 行渲染 / 工具栏 / 多选对比逻辑（直接抽取）+ v1.7 R-3.1 PipelineDAG inline 形态 + v1.17 R-fix-11F STAGES 契约 + unified-progress v1.0 SocketIO per-user room + shadcn `Tabs / Card / Badge / Checkbox / Skeleton`
- **L1 库**：`subscribeTaskStream`（已有 lib/socket.ts）+ `apiGet/apiPost/apiDelete`（已有 lib/api.ts）+ `lucide-react` 图标
- **L4 自写**：`<RunningRow>`(~80 LOC) + `<AnalysisFormHeader>` 紧凑版(~50 LOC) + `<AnalysisInboxList>` 容器(~120 LOC) + 后端合并排序逻辑(~60 LOC) ≈ 310 LOC

### 不许动（强约束）

- 不许改 `<AnalysisDetailView>`（/analysis/<numeric-id> 完整 8 tab 详情页保持现状）
- 不许改 `PipelineDAG.tsx`（v1.17 已修对，inline 用法是组件本身已支持的）
- 不许改 `analysis_history` schema / `tasks` schema
- 不许把 analysis 类型 task 从 TasksPage 隐藏 / 过滤（任务中心保留所有类型）
- 不许在 inbox 行内嵌完整 8 tab（保持轻量；想看完整跳详情页）

## 10. 测试

`tests/web/test_history_inbox.py`：
- `test_history_with_running_returns_active_tasks`：alice 有 2 active analysis tasks + 5 完成行 → response `running_total=2`，items 含 2 个 `kind=task`
- `test_history_running_excluded_from_offset`：limit=2 时 running 仍全返，completed 按 offset 切片
- `test_history_running_only_self`：bob 看不到 alice 的 running tasks（task scope 已有 multi-tenant 隔离）
- `test_history_completed_with_recent_task_id_deduped`：刚完成的 task 同时在 tasks（status=success）和 analysis_history 出现 → 仅返 analysis_history 行（exclude_task_ids 生效）

`tests/web/test_history_redirect.py`：
- `test_history_root_redirects_to_analysis`：GET `/history` → 301 + Location `/analysis`
- `test_history_query_string_preserved`：GET `/history?ticker=AAPL&signal=BUY` → 301 + `/analysis?ticker=AAPL&signal=BUY`

`tests/frontend/AnalysisInbox.spec.tsx`（vitest，纯逻辑）：
- 提交后 inbox state 顶部 +1 task 行；ticker input 清空
- 收到 `task_completed` envelope 后该 task 行被替换为 analysis 行
- 收到 `task_failed` 后行变为失败卡 + 保留 ticker + 显示重试

## 11. 风险与缓解

| 风险 | 缓解 |
|---|---|
| 多个并发 task 订阅 SocketIO 事件流量 | 已有 per-user room（unified-progress v1.0），单 socket 多 task 订阅；inbox 卸载时 unsubscribe |
| `tasks.created_by` 缺失（旧 task）| `WHERE created_by IS NOT NULL`；缺 owner 的旧 task 不出现在 inbox（与 v1.18 R-fix-12 多租户边界一致） |
| 运行中卡占垂直空间过大 | 移动端默认折叠；桌面允许折叠 |
| `task_completed` 事件错过（断线/丢包） | 复用 unified-progress catch-up：mount 时 `GET /api/tasks/events?since=<seq>`；inbox 也 5 分钟轮询补救（任一活跃 task 状态 success/failed → 替换） |
| 旧 `/analysis/<task_uuid>` 链接失效 | 前端检测 UUID → `replaceState` 到 `/analysis?task=<uuid>` + Inbox 滚动锚定 |
| `/history` 旧 URL 失效 | 301 redirect 保留 query string |
| 多 task 并发提交导致 LLM cost 失控 | analysis 每股本就便宜（quick~$0.05 / standard~$0.20）；提交按钮在已有 5 个并发 task 时禁用并提示 |

## 12. 与其他模块集成

| 模块 | 关系 |
|---|---|
| [unified-progress](./unified-progress.md) v1.0 | 复用 `task_events` per-user room + catch-up `/api/tasks/events?since=<seq>` |
| [ui-react-island-regression](./ui-react-island-regression.md) v1.13 R-fix-7E | `AnalysisDetailView` 详情页保持不变；v1.18 R-fix-12G HistoryPage 行渲染抽取为 `<CompletedRow>` 子组件 |
| [analysis-rendering](./analysis-rendering.md) v1.0/v1.1 | 详情页 8 tab 渲染契约不变；inbox 行不渲染 rendering（轻量） |
| [model-switch](./model-switch.md) v1.0 | provider/model 字段已在 history list DTO；Inbox 行展示 |
| [paper-trade](./paper-trade.md) v1.3 / v1.15 | inbox 完成行的 [按此建议纸面交易] 按钮跳详情页操作（不在 inbox 行内执行）|
| [tasks 任务中心](./architecture-upgrade.md) | **保持不变**——任务中心是跨类型 task 总览，不是 analysis 专属入口；分析提交不再让用户感觉"得去任务中心查"，因为 inbox 已显示所有运行中分析 |

## 14. v1.3 增量：列表 / 详情 Header signal Badge 统一三态

### 14.1 现状

`/analysis` 列表行 [`<CompletedRow>`](../../stock_trading_system/web/frontend/src/islands/analysis/AnalysisPage.tsx) line 1711 直显原始 `row.signal`：
- LLM 输出可能是 `Hold` / `Overweight` / `Underweight` / `Buy` / `Sell` / `Strong Buy` / `Strong Sell` / `BUY` / `SELL` / `HOLD` / `bullish` / `bearish` / `neutral` 多种形态
- 截图实测：MSFT 显示 "Overweight"，TQQQ 显示 "Hold"，SNDK 显示 "Sell"，NVDA 显示 "Overweight"，SOXL 显示 "Sell" —— 同一列表里 7 档评级混杂三档操作语，用户读起来分不清

详情页 Header [line 1083](../../stock_trading_system/web/frontend/src/islands/analysis/AnalysisPage.tsx) `{canonicalSignal(detail) || "N/A"}` 同样问题：直显原始字符串。

`signalVariant(...)` 已经把所有变体映射到 4 个 Badge color variant (`buy/sell/hold/default`)，但**显示文本**没归一化。

### 14.2 目标

列表行 + 详情 Header 的 signal Badge **文本**统一为三档：`Buy` / `Sell` / `Hold`。

OverviewCard 内 `<RatingBadge rating="Overweight">` 等 7 档**保持不动** —— 那是 LLM 评级（rating）维度，与 signal 列独立显示。

### 14.3 映射规则

| LLM 原始值（任意大小写 / 中文 / 子串） | 三态 |
|---|---|
| `Strong Buy` / `Buy` / `Overweight` / `BUY` / `ADD` / `加仓` / `bullish` / 含 "buy" 子串 | **Buy** |
| `Strong Sell` / `Sell` / `Underweight` / `SELL` / `REDUCE` / `减仓` / `bearish` / 含 "sell" 子串 | **Sell** |
| `Hold` / `HOLD` / `Neutral` / `WAIT` / `中性` / `neutral` / 含 "hold" 或 "neutral" 子串 | **Hold** |
| 其它 / 缺失 / 空白 | **Hold**（保守默认）|

### 14.4 实施

**纯前端单点 helper**（不改 DTO / 不改 DB / 不改 LLM 输出）：

`stock_trading_system/web/frontend/src/islands/analysis/AnalysisPage.tsx` 在 `signalVariant` 旁加 sibling helper：

```tsx
/** v1.3: Unify the long tail of LLM signal strings ("Overweight" /
 *  "Strong Sell" / "BUY" / "bullish" / "Hold" / "Neutral" / 中文 / ...)
 *  into the 3-state user-facing label. RatingBadge inside OverviewCard
 *  preserves the 7-state rating ladder — that's a separate dimension. */
function signalLabel(signal: string | null | undefined): "Buy" | "Sell" | "Hold" {
  const s = (signal ?? "").toLowerCase().trim()
  if (!s) return "Hold"
  // Sell first — "underweight" contains "weight" not "buy", but
  // "overweight" must not match "weight"+"buy" either. Order matters.
  if (s.includes("sell") || s.includes("bearish")
      || s.includes("underweight") || s.includes("减仓")
      || s === "reduce") return "Sell"
  if (s.includes("buy") || s.includes("bullish")
      || s.includes("overweight") || s.includes("加仓")
      || s === "add") return "Buy"
  // Default to Hold for hold / neutral / wait / unknown / empty
  return "Hold"
}
```

调用点（仅 2 处）：

1. **列表行** [line 1710-1712](../../stock_trading_system/web/frontend/src/islands/analysis/AnalysisPage.tsx)：
   ```tsx
   <Badge variant={signalVariant(row.signal || "")} className="text-[10px]">
     {signalLabel(row.signal)}
   </Badge>
   ```
   `signalVariant(row.signal)` 决定 Badge 颜色（仍接受任意原文输入），`signalLabel(row.signal)` 决定显示文本（必返三态之一）。

2. **详情 Header** [line 1082-1084](../../stock_trading_system/web/frontend/src/islands/analysis/AnalysisPage.tsx)：
   ```tsx
   <Badge variant={signalVariant(canonicalSignal(detail))}>
     {signalLabel(canonicalSignal(detail))}
   </Badge>
   ```

### 14.5 不动

- `OverviewCard` 内 `<RatingBadge rating={...}>` 7 档评级文本（评级维度独立）
- `analysis_history.signal` 列原文（DB 不动）
- `decision_action` 字段语义（v1.20 引入，仍是 Buy/Sell/Hold 三态本身，已合规）
- `signalVariant(...)` 函数（保留作 Badge color 映射）
- `canonicalSignal(...)` 函数（保留作 detail 信号源选择）
- 后端任何 DTO / API / DB
- v1.0 inbox 主体 / v1.1 顺序 / v1.2（如已存在）

### 14.6 测试

新建 `stock_trading_system/web/frontend/src/islands/analysis/__tests__/signal-label.test.tsx`：
```tsx
import { describe, it, expect } from "vitest"
import { signalLabel } from "../AnalysisPage"  // export needed

describe("signalLabel v1.3 tri-state mapping", () => {
  it.each([
    ["Buy",          "Buy"],
    ["Strong Buy",   "Buy"],
    ["Overweight",   "Buy"],
    ["BUY",          "Buy"],
    ["bullish",      "Buy"],
    ["加仓",         "Buy"],
    ["ADD",          "Buy"],
  ])("maps %s → Buy", (raw, expected) => {
    expect(signalLabel(raw)).toBe(expected)
  })

  it.each([
    ["Sell",         "Sell"],
    ["Strong Sell",  "Sell"],
    ["Underweight",  "Sell"],
    ["SELL",         "Sell"],
    ["bearish",      "Sell"],
    ["减仓",         "Sell"],
    ["REDUCE",       "Sell"],
  ])("maps %s → Sell", (raw, expected) => {
    expect(signalLabel(raw)).toBe(expected)
  })

  it.each([
    ["Hold",         "Hold"],
    ["HOLD",         "Hold"],
    ["Neutral",      "Hold"],
    ["neutral",      "Hold"],
    ["WAIT",         "Hold"],
    ["中性",         "Hold"],
    ["",             "Hold"],
    [null,           "Hold"],
    [undefined,      "Hold"],
    ["unknown junk", "Hold"],
  ])("maps %s → Hold (default)", (raw, expected) => {
    expect(signalLabel(raw as string)).toBe(expected)
  })
})
```

需要把 `signalLabel` export（已在 module scope，加 `export function signalLabel(...)`）。

## 13. 版本历史

| 版本 | 日期 | 变更 |
|---|---|---|
| v1.1 | 2026-05-02 | **顺序修正 + 空态文案 + `/api/tasks/submit` task_id 修复（用户反馈）**：v1.0 三处问题：(1) "分析记录"卡放在"发起分析"卡**上方**，与"先输入再看历史"产品意图相反；(2) 用户提交后"看不到反馈"——经 `git blame + grep` 排查根因不是前端逻辑缺失，而是 `/api/tasks/submit` 返回 `{id, type, title, ...}` 但前端 `AnalysisPage.tsx:320` 的 `if (res.task_id)` 读 `task_id` 字段，**字段名不匹配** → 乐观插入分支永远进不去 → 用户必须手动刷新才能看到 task；同样问题影响 `<ScreenerForm>` 提交跳转（行 333），但那段代码用 `data.task_id && window.location.href`，结果就是不跳；(3) 空态文案 "下方提交一个新分析开始" 与新顺序不再对应。修正：(A) `AnalysisPage` form 视图 children 顺序改为 [标题] → [发起分析] → [分析记录]（卡片 JSX 块直接换序）；(B) 空态文案统一为 "暂无分析记录，提交一个新分析后会在这里显示进度"；(C) **后端 `/api/tasks/submit` 响应体追加 `task_id` 字段**（值=`task["id"]`，原 `task` 全字段保留向后兼容）→ 前端 v1.0 乐观插入逻辑（`handleSubmit` setInbox prepend optimistic row → 订阅 task_events → settled 后 refreshInbox）**真正生效**——AnalysisPage.tsx:320-340 + 387-415 不变；`<ScreenerForm>` 提交跳转 `/screener-v3?task=<id>` 也跟着修。验收：(1) 页面顺序为 标题 → 发起分析 → 分析记录；(2) 提交"开始分析"后下方分析记录**立即**出现 ticker running row（之前要手刷）；(3) 进度条实时；(4) 完成后 row 替换为 completed analysis card；(5) `/history` 重定向不变；后端测试 `tests/web/test_history_inbox.py` 新增 `test_running_row_carries_all_required_fields`（锁字段契约）+ `test_submit_then_inbox_sees_running_row_immediately`（端到端 submit→inbox）。**不动** /api/history 契约、optimistic insert 逻辑、socket 订阅、`<RunningRow>/<CompletedRow>` 实现 |
| v1.0 | 2026-05-02 | 初版：`/analysis` 主页改 Inbox 布局（顶部紧凑表单 + 时间线列表混合运行中 task + 已完成 analysis）；`/history` 路由 301 redirect 到 `/analysis` 保留 query string；Sidebar 去"分析记录"菜单项；`/api/history` 加 `include_running=true` 合并 tasks + analysis_history 按 created_at DESC 排序，`exclude_task_ids` 防 task_completed 与 DB 写入间的瞬时去重；新方法 `TaskStore.list_tasks_by_user_and_type`；前端新增 `<AnalysisHomeInbox> + <AnalysisFormHeader> + <AnalysisInboxList> + <RunningRow>`，行渲染 v1.18 HistoryPage 抽取为 `<CompletedRow>`；提交不跳页，列表顶部乐观插运行中卡，订阅 task_events 流，完成替换为 analysis 行，失败/取消行带重试；运行中行内嵌 PipelineDAG（桌面默认展开，移动默认折叠+进度条）；旧 `/analysis/<task_uuid>` URL `replaceState` 到 `/analysis?task=<uuid>` 滚动锚定；`<AnalysisDetailView>` 完整 8 tab 详情页保持不变（深链 / 分享 / SEO 友好）；任务中心 `/tasks` 不变（跨类型 task 总览，保留所有类型）|
| v1.3 | 2026-05-03 | 列表 / 详情 Header signal Badge 统一三态（用户 2026-05-03 截图反馈）：现状 `/analysis` 列表行 [`AnalysisPage.tsx:1711`](../../stock_trading_system/web/frontend/src/islands/analysis/AnalysisPage.tsx) 直显原始 `row.signal`，截图实测 7 档评级（Hold / Overweight / Sell）混杂三档操作语，用户读不清；详情页 Header line 1083 同样问题。`signalVariant(...)` 已把所有变体映射到 4 个 Badge color variant 但**显示文本**没归一化。方案纯前端单点 helper（不改 DTO/DB/LLM 输出）：(A) 加 `signalLabel(signal): "Buy" \| "Sell" \| "Hold"`，规则 — Strong Buy/Buy/Overweight/BUY/ADD/加仓/bullish/含"buy"子串 → **Buy**；Strong Sell/Sell/Underweight/SELL/REDUCE/减仓/bearish/含"sell"子串 → **Sell**；Hold/HOLD/Neutral/WAIT/中性/neutral/含"hold"或"neutral"子串 → **Hold**；其它/缺失/空白 → **Hold**（保守默认）；Sell 检测顺序优先于 Buy（避免 "underweight" 被 "weight" 误命中其它）；(B) 列表行 Badge 文本 `{row.signal}` → `{signalLabel(row.signal)}`（`signalVariant` 仍接原文决定颜色）；(C) 详情 Header Badge 同样 `{canonicalSignal(detail)}` → `{signalLabel(canonicalSignal(detail))}`；(D) `signalLabel` 加 `export` 关键字以便测试 import。**不动** OverviewCard 内 `<RatingBadge rating>` 7 档评级文本（评级维度独立）/ `analysis_history.signal` DB 列原文 / `decision_action` 字段语义 / `signalVariant` 函数 / `canonicalSignal` 函数 / 后端任何 DTO/API/DB / inbox 主体 + 顺序。新增 `tests/frontend/AnalysisPage/signal-label.test.tsx` 24 case（7 Buy 变体 + 7 Sell 变体 + 10 Hold 变体含 null/undefined/unknown junk）；自写 ~50 LOC（含测试） |
