# 技术方案：选股记录与运行入口（Screener History）

| 项 | 值 |
|---|---|
| Feature | `screener-history` |
| 版本 | v1.2 |
| 日期 | 2026-05-02 |
| 关联 | [screener-v3 v1.0](./screener-v3.md)（主体）+ [v1.2](./screener-v3.md) 决策透明化 + [v1.3](./screener-v3.md) 主题污染修复 + [analysis-inbox v1.0](./analysis-inbox.md)（用户体验对照） |
| 关联测试 | `tests/web/test_screen_v3_history.py`、`tests/web/test_screener_v3_running_route.py` |

## 1. 背景

用户报告选股 V3 与分析模块同样的痛点：「记录只能从任务中心查」。Audit：

| 项 | 现状 |
|---|---|
| `/screener-v3` | 仅一个 island；`?result=<task_id>` 切结果视图，否则表单 |
| 历史 API | `list_screen_v2_history` 已有但仅 v2；**v3 版本不存在** |
| 用户访问历史唯一路径 | 任务中心 `/tasks` 找 `type=screen_v3` task |
| 提交后流向 | [ScreenerV3Page.tsx:241](../../stock_trading_system/web/frontend/src/islands/screener-v3/ScreenerV3Page.tsx) `window.location.href = '/tasks/${task_id}'` —— **正是用户抱怨的"只能从任务中心"根因** |
| Sidebar | 仅 1 项 `[选股]`（无独立"选股记录"项） |

## 2. 设计决策：不合并到主页（与 analysis-inbox 对照）

| 维度 | analysis（已合并 inbox v1.0） | screener（本方案）|
|---|---|---|
| 频次 | 高，多并发提交 | 低，1-2 次/天 |
| 表单复杂度 | 紧凑（ticker + depth + radio） | 重（NL 输入 / 14 大师多选 / mode / market / candidate_n / 成本预估面板） |
| 单次耗时 | 30s–5min | 长（agent_rt 15-30 分钟） |
| 结果页复杂度 | 8 tab + 8 Card | v1.2 KPI 6 列 + banner + Top 5 圆桌 + 候选表展开行 |
| 主线动作 | 提交 → 即看 inbox 多任务并存 | 提交 → 配置 → 等结果 → 偶尔回看 |

**结论**：选股表单和结果都太重，不适合学 analysis-inbox 把表单 + 历史合并到 `/screener-v3` 单页（信息过载）；选股频次低，"最近 3 卡"覆盖 80% 复看场景。

## 3. 信息架构：3 入口 + URL 状态机

| URL | 渲染 | 用户动作 |
|---|---|---|
| `/screener-v3` | `<RecentScreensCard>` 顶部 3 卡 + `[查看全部 →]` 链接 + `<ScreenerForm>` 表单 | 跑新一轮 / 快速复看最近 |
| `/screener-v3?prefill=<task_id>` | `<ScreenerForm>` 自动用该 task 的 params_json 预填 | [复制配置重跑] 落地 |
| `/screener-v3?task=<task_id>` | `<ScreenerRunningView>` 在 V3 页内显示 PipelineDAG + 大师并发进度 | 提交后流向（不再跳 `/tasks/<id>`）|
| `/screener-v3?result=<task_id>` | `<ResultsView>`（v1.0 + v1.2 现状不变） | 看结果 |
| `/screener-v3/history` | `<ScreenerHistoryList>` 完整列表（分页 + 筛选 + 多选删除 + 复制配置）| 深度回看 / 对比 / 清理 |
| `/tasks` `/tasks/<id>` | **不变**——任务中心保留所有任务类型总览 | 跨类型 task 排查 |

**Sidebar 不动**——保持 1 项 `[选股]`；"查看全部"作为 V3 主页内链接，符合"低频功能放二级"原则。

## 4. 数据流

### 4.1 `TaskStore.list_screen_v3_history` 新方法

```python
def list_screen_v3_history(self, *, user_id: int,
                             modes: tuple[str, ...] | None = None,
                             markets: tuple[str, ...] | None = None,
                             limit: int = 50, offset: int = 0,
                             include_failed: bool = False) -> tuple[list[dict], int]:
    """Return paginated v3 screening history with parsed metrics.

    Each row already contains lightweight summary fields — no need for
    callers to load the full result_ref payload (they can if they
    need Top-5 ticker list, by hitting /api/screen/v3/results/<task_id>).
    """
    ...
```

返每行字段（轻量 summary）：

```json
{
  "task_id": "uuid-...",
  "created_at": "2026-05-02 14:31:22",
  "completed_at": "2026-05-02 14:33:40",
  "duration_sec": 138,
  "status": "success",                  // success | failed | running
  "title": "V3 选股: 存储龙头股",
  "params": {
    "nl_query": "存储龙头股",
    "market": "us",
    "candidate_n": 20,
    "gurus": ["buffett","graham","munger","lynch"],
    "mode": "agent_rt",
    "with_roundtable": true
  },
  "summary": {
    "candidates_count": 20,
    "avg_score": 65.3,
    "votes": {"bullish": 8, "bearish": 3, "neutral": 9},   // sum across candidates
    "consensus_rate_pct": 65,                              // unanimous + majority / total
    "top3_tickers": ["AMD", "MU", "LRCX"],
    "roundtable_enabled": true,
    "llm_calls": 80,
    "cache_hit_pct": 30
  }
}
```

`summary` 字段从已有的 `payload.candidates` + `payload.metrics`（v1.2 已写入）实时算出——不需要 schema 变更，只是 list 端点提取/聚合。

### 4.2 `/api/screen/v3/history` 新端点

```python
@app.route("/api/screen/v3/history")
@login_required
def api_screen_v3_history():
    modes = request.args.getlist("mode") or None
    markets = request.args.getlist("market") or None
    include_failed = (request.args.get("include_failed") or "").lower() == "true"
    try:
        limit = max(1, min(int(request.args.get("limit", 50)), 200))
        offset = max(0, int(request.args.get("offset", 0)))
    except ValueError:
        return jsonify({"error": "limit/offset must be int"}), 400
    rows, total = _get_task_store().list_screen_v3_history(
        user_id=g.user.id,
        modes=tuple(modes) if modes else None,
        markets=tuple(markets) if markets else None,
        limit=limit, offset=offset,
        include_failed=include_failed,
    )
    return jsonify({"items": rows, "total": total,
                      "limit": limit, "offset": offset})
```

**多租户**：仅返 `created_by == g.user.id` 的 task（与 v1.18 R-fix-12 边界一致）。

### 4.3 `/api/screen/v3/recent` 顶部 3 卡专用端点

可以复用 history endpoint：`GET /api/screen/v3/history?limit=3`。无需新建。

### 4.4 `[复制配置重跑]` 落地路径

不需要新端点 —— 前端拿任意 history row 的 `params` 字段，跳 `/screener-v3?prefill=<task_id>`，主页 `<ScreenerForm>` mount 时检测 query：
1. `apiGet('/api/screen/v3/history?limit=1')` 通过 task_id filter 拉该行（或新增 `/api/screen/v3/history/<task_id>` 单条端点 ~10 LOC）
2. 用 `params.nl_query / market / candidate_n / gurus / mode / with_roundtable` 预填 form state
3. 用户可改后再提交（不强制原参数）

## 5. 前端组件

### 5.1 路由分发（`<ScreenerV3Page>`）

```tsx
export function ScreenerV3Page() {
  const path = window.location.pathname
  const params = new URLSearchParams(window.location.search)

  // 子路由 /screener-v3/history
  if (path.startsWith("/screener-v3/history")) {
    return <ScreenerHistoryList />
  }
  // 4 主页状态
  const taskId = params.get("task")
  const resultId = params.get("result")
  const prefillId = params.get("prefill")

  if (taskId) return <ScreenerRunningView taskId={taskId} />
  if (resultId) return <ResultsView resultId={resultId} />
  return <ScreenerHomeView prefillId={prefillId} />
}

function ScreenerHomeView({ prefillId }: { prefillId: string | null }) {
  return (
    <div className="p-4 md:p-6 max-w-5xl mx-auto space-y-6">
      <RecentScreensCard />
      <ScreenerForm prefillTaskId={prefillId} />
    </div>
  )
}
```

### 5.2 `<RecentScreensCard>` 顶部 3 卡

```tsx
function RecentScreensCard() {
  const [items, setItems] = useState<HistoryRow[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    apiGet<{items: HistoryRow[]}>('/api/screen/v3/history?limit=3')
      .then(r => setItems(r.items)).catch(() => {})
      .finally(() => setLoading(false))
  }, [])

  if (!loading && items.length === 0) return null  // 首次用户不展示空卡

  return (
    <Card>
      <CardHeader className="pb-2 flex flex-row items-center justify-between">
        <CardTitle className="text-sm">最近选股</CardTitle>
        <a href="/screener-v3/history" className="text-xs text-primary hover:underline">
          查看全部 →
        </a>
      </CardHeader>
      <CardContent>
        {loading ? (
          <div className="grid gap-3 md:grid-cols-3"><Skeleton className="h-32" /><Skeleton className="h-32" /><Skeleton className="h-32" /></div>
        ) : (
          <div className="grid gap-3 md:grid-cols-3">
            {items.slice(0, 3).map(it => <RecentScreenCard key={it.task_id} row={it} />)}
          </div>
        )}
      </CardContent>
    </Card>
  )
}

function RecentScreenCard({ row }: { row: HistoryRow }) {
  const s = row.summary
  return (
    <Card className="cursor-pointer hover:border-primary/40"
          onClick={() => window.location.href = `/screener-v3?result=${row.task_id}`}>
      <CardContent className="pt-3 space-y-1.5 text-xs">
        <div className="flex items-center justify-between">
          <span className="text-muted-foreground">{fmtRelative(row.created_at)}</span>
          <Badge variant="muted" className="text-[9px]">{modeLabel(row.params.mode)}</Badge>
        </div>
        <div className="font-medium text-sm truncate" title={row.params.nl_query}>
          {row.params.nl_query || `${row.params.market.toUpperCase()} 默认`}
        </div>
        <div className="text-muted-foreground">
          {marketLabel(row.params.market)} · 候选 {s?.candidates_count ?? '?'} · {row.params.gurus.length} 大师
        </div>
        <div className="flex items-center gap-2">
          <span className="font-mono">均分 {s?.avg_score?.toFixed(1) ?? '—'}</span>
          {s?.votes && (
            <span>
              <span className="text-emerald-400">{s.votes.bullish}✓</span>{' '}
              <span className="text-red-400">{s.votes.bearish}✗</span>
            </span>
          )}
        </div>
        <div className="font-mono text-[10px] text-muted-foreground">
          Top: {(s?.top3_tickers ?? []).join(' · ') || '—'}
        </div>
      </CardContent>
    </Card>
  )
}
```

### 5.3 `<ScreenerHistoryList>` 完整列表页

复用 v1.18 R-fix-12G HistoryPage 风格 + 选股专属字段：

```
工具栏: [全部] [我的] · 模式多选(classic/agent/agent_rt) · 市场多选(us/cn/hk) · [包含失败] · [删除/owner]
列表行（折叠）:
  ✓ 2026-05-02 14:31  · 美股 · Agent + RT · 4 大师 · 候选 20 · 均分 65.3 · 看多 8/看空 3 · [查看] [复制配置重跑] [删除/owner]
列表行（展开）:
  Top 5: AMD (59.5/BULL) · MU (58.8/BULL) · LRCX (52.9/SPLIT) · WDC (49.1/HOLD) · DELL (49.1/BULL)
  共识率: 65% · 圆桌: ✓ · 80 LLM call · 命中缓存 30% · 耗时 2m 18s
  NL 查询: "存储龙头股"
  [完整查看 →] [复制配置重跑]
[加载更多 (50/123)]
```

`[复制配置重跑]` 跳 `/screener-v3?prefill=<task_id>`。

### 5.4 `<ScreenerRunningView>` 同页换状态

替代当前提交后跳 `/tasks/<id>` 的行为：

```tsx
function ScreenerRunningView({ taskId }: { taskId: string }) {
  const [meta, setMeta] = useState<{title?: string; params?: any} | null>(null)
  const [done, setDone] = useState(false)

  useEffect(() => {
    apiGet<any>(`/api/tasks/${taskId}`).then(setMeta).catch(() => {})
    const sub = subscribeTaskStream({
      taskIds: [taskId],
      onEvent: (env) => {
        if (env.event === "task_completed") {
          setDone(true)
          // smooth transition to result view
          setTimeout(() => window.location.replace(`/screener-v3?result=${taskId}`), 600)
        } else if (env.event === "task_failed") {
          // 留在运行中页, 显示失败 + 跳回表单按钮
          setDone(true)  // sentinel
        }
      },
      onStatusChange: () => {},
    })
    return () => sub.destroy()
  }, [taskId])

  return (
    <div className="p-4 md:p-6 max-w-5xl mx-auto space-y-4">
      <div className="flex items-center gap-3">
        <Button variant="ghost" size="sm"
                onClick={() => window.location.href = "/screener-v3"}>
          <ArrowLeft className="h-4 w-4" />
        </Button>
        <h1 className="text-xl font-bold">选股运行中</h1>
        {meta?.title && <Badge variant="muted">{meta.title}</Badge>}
      </div>
      <PipelineDAG taskId={taskId} />
      {/* 大师并发进度（复用 unified-progress 已有的 guru_unit_done 事件流）*/}
      <GuruParallelProgress taskId={taskId} />
      {!done && (
        <p className="text-xs text-center text-muted-foreground">
          完成后自动跳转到结果页 · 可在 <a href="/tasks" className="underline">任务中心</a> 跨类型查看
        </p>
      )}
    </div>
  )
}
```

`<GuruParallelProgress>` 是新建小组件（~80 LOC），订阅同 task 的 `guru_unit_done` 事件流（unified-progress v1.0 + screener-v3 v1.0 §4.6 已规范），按 (guru, ticker) 矩阵显示进度。

### 5.5 `<ScreenerForm prefillTaskId>` 加预填

当前 [ScreenerForm](../../stock_trading_system/web/frontend/src/islands/screener-v3/ScreenerV3Page.tsx) state 已含 `nl/market/candidateN/mode/selected (Set<guru>)`。新增 useEffect：

```tsx
useEffect(() => {
  if (!prefillTaskId) return
  apiGet<HistoryRow>(`/api/screen/v3/history/${prefillTaskId}`)
    .then(r => {
      if (!r?.params) return
      setNl(r.params.nl_query || "")
      setMarket(r.params.market as Market)
      setCandidateN(r.params.candidate_n)
      setMode(r.params.with_roundtable ? "agent_rt" :
              r.params.mode === "classic" ? "classic" : "agent")
      setSelected(new Set(r.params.gurus || []))
      // 提示 banner
      setPrefillBanner(`已从 ${fmtRelative(r.created_at)} 的运行复制配置`)
    })
    .catch(() => {})
}, [prefillTaskId])
```

提交按钮上方显示 `<Alert variant='info'>已复制配置，可修改后重跑</Alert>`。

### 5.6 提交后流向修正

`stock_trading_system/web/frontend/src/islands/screener-v3/ScreenerV3Page.tsx:241`：
```tsx
// 删除：
window.location.href = `/tasks/${data.task_id}`
// 改为：
window.location.href = `/screener-v3?task=${data.task_id}`
```

任务中心 `/tasks/<id>` 仍可访问（不强制 redirect），保持跨类型排查能力；只是用户主动线不再被迫去那里。

## 6. 实施分期

| 步 | 范围 | 工时 |
|---|---|---|
| 1 | 后端 `TaskStore.list_screen_v3_history` + `get_screen_v3_history_one(task_id, user_id)` | ~1h |
| 2 | 后端 `/api/screen/v3/history` + `/api/screen/v3/history/<task_id>` 端点（含多租户隔离 + 失败状态过滤） | ~30min |
| 3 | 前端 `<RecentScreensCard>` 顶部 3 卡 + `[查看全部 →]` 链接 | ~1h |
| 4 | 前端 `/screener-v3/history` 路由 + `<ScreenerHistoryList>`（复用 v1.18 HistoryPage 工具栏 + 行渲染 + 多选；加 mode/market 筛选 + [复制配置重跑]）| ~2.5h |
| 5 | 前端 `<ScreenerRunningView>` + `<GuruParallelProgress>` + 提交跳 `?task=<id>` | ~1.5h |
| 6 | `<ScreenerForm>` 加 prefillTaskId useEffect + banner 提示 | ~30min |
| 7 | 测试 + npm build | ~1h |
| **合计** | | **~8h** |

## 7. 复用 / 边界

依据 [engineering-principles.md](./engineering-principles.md)：

- **L0 项目内**：v1.18 R-fix-12G HistoryPage 工具栏 / 行渲染 / 多选对比逻辑（直接抽用） + v1.0 PipelineDAG / unified-progress per-user room + v1.2 ResultsView 不动 + screener-v3 v1.3 主题污染防御不动 + shadcn 组件库
- **L1 库**：`subscribeTaskStream` / `apiGet/apiPost/apiDelete`（已有）
- **L4 自写**：`<RecentScreensCard>` ~120 LOC + `<ScreenerHistoryList>` ~250 LOC（多数复用 HistoryPage） + `<ScreenerRunningView>` ~80 LOC + `<GuruParallelProgress>` ~80 LOC + `list_screen_v3_history` ~70 LOC + 端点 + 路由分发 ≈ ~700 LOC

### 不许动（强约束）

- 不许改 `<ResultsView>`（v1.0 + v1.2 + screener-v3 v1.3 现状）
- 不许改 `<ScreenerForm>` 既有字段 / 提交逻辑（仅追加 prefill useEffect + banner）
- 不许改 `screen_results_v2 / task_results_generic / tasks` schema
- 不许把 screen_v3 类型从 TasksPage 隐藏（任务中心保留所有类型）
- 不许把 `/screener-v3/<task_id>` 老链接改为 redirect（不存在该路由，无需处理）
- 不许在 history list 行内嵌完整结果（保持轻量；想看完整跳 `?result=<task_id>`）

## 8. 测试

`tests/web/test_screen_v3_history.py`：
- `test_history_returns_only_self`：alice 跑 2 次 + bob 跑 1 次 → bob `/api/screen/v3/history` 仅返 1 条
- `test_history_summary_extracted_correctly`：mock task 含 candidates/metrics → response `summary.avg_score / votes / top3_tickers / consensus_rate_pct` 正确
- `test_history_filters_by_mode_and_market`：3 个 task 不同 mode/market → query 多选正确过滤
- `test_history_pagination`：10 条 → limit=3, offset=3 返第 4-6 条
- `test_history_one_endpoint_returns_params`：`/api/screen/v3/history/<task_id>` 返单条 params 完整（用于 prefill）
- `test_history_excludes_running_by_default`：仅 `status=success` 默认；`include_failed=true` 才含 failed/cancelled

`tests/web/test_screener_v3_running_route.py`：
- `test_running_view_renders_for_task_query`：mount `/screener-v3?task=<uuid>` 应渲染 `<ScreenerRunningView>` 不渲染表单（前端 unit test，可用 vitest）
- `test_submit_redirects_to_running_view`：提交 → 应 navigate `/screener-v3?task=<id>`，不再 `/tasks/<id>`

## 9. 风险

| 风险 | 缓解 |
|---|---|
| 长任务（agent_rt 30min）用户离开 V3 页后回来，URL 已是 `/screener-v3?task=<id>` 但任务可能已完成 | `<ScreenerRunningView>` mount 时先 `apiGet('/api/tasks/<id>')` 拿当前状态，若 status=success 立即 `window.location.replace('?result=<id>')`；catch-up 也走 unified-progress 既有 since=<seq> 路径 |
| 用户 prefill 配置但当前 LLM provider 已切换 → 大师列表不一致 | `<ScreenerForm>` prefill 后过滤 `selected` 与当前 `gurus` 列表交集；不存在的大师 banner 提示 |
| 失败 task 在 history 默认不显示 → 用户找不到失败原因 | 工具栏 [包含失败] 默认关 + 任务中心仍可见；prefill 允许从失败 task 重跑（params 仍可用） |
| 顶部 3 卡 `summary` 计算需扫 candidates 数组（20 条） | `list_screen_v3_history` 只取 limit=3，开销极小；如担心可加内存级缓存 |
| `/screener-v3/history` 与主页用同一 island bundle 体积膨胀 | 复用 v1.18 HistoryPage 组件 → 不引入新依赖；如担心可 lazy import HistoryList |

## 10. 与其他模块集成

| 模块 | 关系 |
|---|---|
| [screener-v3](./screener-v3.md) v1.0/v1.2/v1.3 | 主体 V3 引擎、ResultsView、主题污染防御均**保持不变** |
| [analysis-inbox](./analysis-inbox.md) v1.0 | 用户体验对照——本方案明确**不**走 inbox 单页合并路线（理由见 §2） |
| [unified-progress](./unified-progress.md) v1.0 | 复用 `task_events` per-user room + `guru_unit_done` 事件流 + catch-up `/api/tasks/events?since=<seq>` |
| [ui-react-island-regression](./ui-react-island-regression.md) v1.18 R-fix-12G | HistoryPage 行渲染 / 工具栏 / 多选对比逻辑直接抽取复用 |
| [tasks 任务中心](./architecture-upgrade.md) | **保持不变**——跨类型 task 总览，screen_v3 类型 task 仍可见可排查 |

## 12. v1.2 主页板块顺序对齐 analysis-inbox

### 12.1 现状

[ScreenerV3Page.tsx:69-74](../../stock_trading_system/web/frontend/src/islands/screener-v3/ScreenerV3Page.tsx) 当前实施：
```tsx
function ScreenerHomeView({ prefillId }) {
  return (
    <div ...>
      <RecentScreensCard />     // ← 最近 3 卡在上
      <ScreenerForm ... />      // ← 表单在下
    </div>
  )
}
```

而 [analysis-inbox v1.1 line 478](./analysis-inbox.md) 已实施：发起分析卡在前，分析记录卡在后。两个主入口规则不一致 —— 用户每次切换页面都要适应一次顺序，且**主动作（提交新任务）**应该位于第一屏不需滚动可见。

### 12.2 调整

`<ScreenerHomeView>` 顺序调换：

```tsx
function ScreenerHomeView({ prefillId }) {
  return (
    <div className="p-4 md:p-6 max-w-5xl mx-auto space-y-6">
      <ScreenerForm prefillTaskId={prefillId} />  // ← 表单在上（主动作）
      <RecentScreensCard />                        // ← 最近 3 卡在下（次要）
    </div>
  )
}
```

`<RecentScreensCard>` 内部不变；表单 prefill banner 与 form 字段位置不变。

### 12.3 与 analysis-inbox 对齐的全局规则

凡是「表单 + 历史」混合主页，统一 **表单在上，历史/记录在下**：

| 主页 | 顺序 | 实施位置 |
|---|---|---|
| `/analysis` | `<AnalysisFormHeader>` → `<AnalysisInboxList>` | analysis-inbox v1.1 ✓ |
| `/screener-v3` | `<ScreenerForm>` → `<RecentScreensCard>` | screener-history v1.2（本节）|

理由：
- 主页第一屏应放主动作（提交新任务），不需要滚动可见
- 历史是次要参考，放在下方按时间倒序浏览自然
- 两个入口规则一致，降低用户切换成本

## 11. 版本历史

| 版本 | 日期 | 变更 |
|---|---|---|
| v1.2 | 2026-05-02 | 主页板块顺序对齐 analysis-inbox（用户反馈）：v1.0 `<ScreenerHomeView>` 实施时 `<RecentScreensCard>`（最近 3 卡）在上、`<ScreenerForm>`（表单）在下，与 analysis-inbox v1.1（发起分析在上、记录在下）规则不一致。调整：`ScreenerHomeView` 两块换序为 `<ScreenerForm>` → `<RecentScreensCard>`，主动作（提交新选股）位于第一屏不需滚动可见，最近记录降为下方次要参考。同时确立全局规则：所有「表单 + 历史」混合主页统一 **表单在上、历史在下**（analysis-inbox / screener-history 两个入口对齐）。`<RecentScreensCard>` 内部不变；`<ScreenerForm>` prefill banner 与字段位置不变；其它路由（`?task=` / `?result=` / `/screener-v3/history`）不变。无 schema / API / 后端改动 |
| v1.1 | 2026-05-02 | **运行中视图换 V3 专属进度组件（用户截图反馈）**：v1.0 `<ScreenerRunningView>` 复用 AI 分析的 `<PipelineDAG>` → 渲染出 `技术面 / 情绪面 / 新闻 / 基本面 / 多空辩论 / 风险评估 / 最终决策` 7 节点，**与选股链路无关**，且 agent_rt 模式下圆桌辩论阶段完全不可见。根因（线性）：(a) `PipelineDAG` 内部 `STAGES` 常量硬编码 analyzer 的 7 步 + 仅监听 `analysis_pipeline` 事件，对 V3 的 `bundle_progress / guru_unit_done` 不响应；(b) `ScreenerV3Pipeline` 内 6 phase 没有自己的 stage_start/stage_done 事件；(c) `_run_roundtable` 内置实现（pipeline.py:326）虽然 `roundtable.run_roundtable` 模块函数有 `roundtable_start/done` 事件，但 pipeline 没调它，事件永远不发；(d) worker `_on_progress` 已经准备好转发 `roundtable_start/done`（workers.py:481）但上游不发就空转。方案（**纯增量、不动** 14 大师、aggregator、RoundtableResult、`ResultsView`、screen_v3 schema、unified-progress 协议）：(A) `ScreenerV3Pipeline.run` 在每 phase 头尾发 `screen_v3_stage_start / screen_v3_stage_done` 事件，stage∈{`parse / universe / bundle / guru / roundtable / aggregate`}；`_run_roundtable` 内部按 ticker 进度发 `roundtable_start({tickers})` 一次 + `roundtable_done({ticker, consensus, dissent})` 每 ticker 一次；管线末尾发 `aggregate_done({results_count})`；(B) `workers.py make_screen_v3_worker._on_progress` 加分支转发 `screen_v3_stage_start / screen_v3_stage_done / aggregate_done`；`bundle_progress / guru_unit_done / roundtable_start / roundtable_done` 不变；(C) 前端新建 `components/shared/ScreenerV3Progress.tsx`（独立组件，不复用 `<PipelineDAG>`），STAGES = `[解析条件 / 构建股票池 / 拉取行情 / 大师并行评分 / 圆桌辩论 / 生成结果]`；圆桌阶段仅 `mode === "agent_rt"` 时显示，否则显示 muted "未启用圆桌"；状态机消费 `screen_v3_stage_start/done` 推进 stage 主线，消费 `bundle_progress` 显示 `准备数据 X/Y`，消费 `guru_unit_done` 显示 `Buffett · AAPL ✓`，消费 `roundtable_start/done` 显示圆桌 ticker 进度；socket 断开时每 5s `GET /api/tasks/<task_id>` 兜底 status，terminal 走既有 task_completed 跳转；(D) `<ScreenerRunningView>` 渲染 `<ScreenerV3Progress mode={mode} taskId={taskId} />` + 既有 `<GuruParallelProgress>`（大师矩阵保留作 detail），**移除 `<PipelineDAG>`**；mode 从 task params_json 读（catch-up GET 已返 params_json）。验收：(1) `/screener-v3?task=<id>` 不再出现 "技术面/情绪面/新闻/基本面/风险评估/最终决策" 文字；(2) agent_rt 跑通后进度区看到 "圆桌辩论 ✓"；(3) agent 模式圆桌阶段显示 muted "未启用圆桌"；(4) 大师矩阵保留并实时推进。后端测试 `tests/screener/v3/test_pipeline_progress_events.py`：mock on_progress 收集事件 → assert `screen_v3_stage_start{stage=parse}` + `_done{stage=guru}` + `aggregate_done` 至少一条；mode=agent_rt 时 assert `roundtable_start` 至少一条。**不动** unified-progress per-user room、socket 协议、TaskStore schema |
| v1.0 | 2026-05-02 | 初版：3 入口结构（`/screener-v3` 主页 + `?task=<id>` 运行中视图 + `?result=<id>` 结果视图 + `/screener-v3/history` 完整记录列表 + `?prefill=<id>` 预填表单），不学 analysis-inbox 单页合并；后端 `TaskStore.list_screen_v3_history(user_id, modes, markets, limit, offset, include_failed)` + `get_screen_v3_history_one(task_id, user_id)` 新方法；`/api/screen/v3/history` `/api/screen/v3/history/<task_id>` 新端点（多租户隔离 v1.18 R-fix-12 边界）；前端 `<RecentScreensCard>` 顶部 3 卡 + [查看全部 →] 链接；`<ScreenerHistoryList>` 复用 v1.18 HistoryPage 工具栏/行/多选 + 加 mode/market 多选筛选 + [复制配置重跑] 跳 `?prefill=<task_id>`；`<ScreenerRunningView>` 同页内 PipelineDAG + `<GuruParallelProgress>` 大师并发矩阵 + 完成 replaceState 到 `?result=<task_id>` + 失败留在运行中页带返回；`<ScreenerForm>` 加 `prefillTaskId` useEffect 拉 history one 预填字段 + banner 提示；提交后从 `/tasks/<id>` 改为 `/screener-v3?task=<id>`；Sidebar 不动（不新增"选股记录"项）；`<ResultsView>` v1.0+v1.2+v1.3 / `<ScreenerForm>` 既有字段提交逻辑 / 任务中心 / screen_v3 schema 全部不动。复用 v1.18 HistoryPage ~70% 代码 + unified-progress + shadcn 组件库；自写 ~700 LOC |
