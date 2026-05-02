# 技术方案：任务失败原因可见化

| 项 | 值 |
|---|---|
| Feature | `task-failure-visibility` |
| 版本 | v1.0 |
| 日期 | 2026-05-02 |
| 关联 | [unified-progress.md](unified-progress.md) v1.0（task_failed envelope）+ [analysis-rendering.md](analysis-rendering.md) v1.2（per-tab ErrorBoundary 是「分析渲染」失败兜底，本方案补「任务级」失败兜底）|
| 关联测试 | `tests/web/test_task_detail_failure.py`、`tests/tasks/test_workers_qwen_errors.py`、`tests/frontend/tasks-failure.spec.ts` |

## 1. 背景

用户 2026-05-02 截图反馈：`/tasks/<task_id>` 详情页 AI 分析失败时进度卡片显示红色 100% 进度条 + 「已完成 0/1」，错误区是空白。打开 DevTools 才能拿到真实 `error_message`。

### 1.1 现状审计（事实，已 grep 核实）

| 位置 | 现状 |
|---|---|
| 后端 `task_manager.py:267-276` `_fail()` | 已写入 `error_message` + `error_trace` 到 `tasks` 表，并 emit `task_failed` envelope `{id, error_message}` |
| 后端 `task_manager.py:214` `_on_progress` | 已写入 `progress_step` 到 `tasks` 表 |
| 后端 `app.py:3002-3015` `/api/tasks/<task_id>` | `return jsonify(_sanitize_shared_task(task))` — 不裁剪 `error_trace`，**任何看得到 task 的人**都能拿到 stack trace（含路径/环境变量/可能 key），跨用户存在轻量信息泄露 |
| 前端 `TasksPage.tsx:17-21` `interface Task` | 缺 `error_message / error_trace / progress_step / duration_ms` 四个字段，TS 端无法消费 |
| 前端 `TasksPage.tsx:305` `task_failed` 事件 | 读 `p.error || ""`，**后端从来没有发过 `error` 这个 key**，所以失败事件 meta 永远是空 |
| 前端 `TasksPage.tsx:280-281` 进度条 | `isTerminal` 时一律 `width: 100%`；failed/cancelled 与 success 同处理，进度条满格但完成数还是 `0/1`，显示矛盾 |

### 1.2 根因（一句话）

后端**有数据**，前端**不消费**也**不知道**：字段名错配（`error` vs `error_message`）+ TS 类型缺字段 + 详情页没有 failed 分支渲染。属于纯前端展示链路 bug，**不是**分析管线本身的问题。

## 2. 方案

### 2.1 三层修复（前端 / 后端 / worker 错误包装）

| 层 | 改动 | 边界 |
|---|---|---|
| F-1 前端 Task 类型 | `interface Task` 增 `error_message?: string \| null` / `error_trace?: string \| null` / `progress_step?: string \| null` / `duration_ms?: number \| null` | 全 nullable，老 task 行不带这些字段时不破坏 |
| F-2 前端 failed UI | `task.status === "failed"` 在进度卡片下方渲染 `<Alert variant="error">`，标题「分析失败」，正文 `task.error_message ?? "任务失败，但后端未返回错误详情"`，下方 `<details>` 折叠 `error_trace`（限高 240px + 滚动） | `error_trace` 仅当存在时显示；详情卡片不在 list 视图出现 |
| F-3 前端事件字段 | `task_failed` 读 `p.error_message ?? p.error ?? ""`（保留 `p.error` fallback，老队列里历史 envelope 不破坏）；`analysis_pipeline` 且 `p.type === "pipeline_error"` 时 meta 显示 `p.error \|\| p.message` | 不改 envelope 协议；只兼容读 |
| F-4 前端 failed 进度文案 | failed/cancelled 时进度条颜色保留红/黄，但**不再**显示「已完成 0/1」；改显示「失败于：{task.progress_step \|\| 最近 pipeline step \|\| '分析管线'}」；进度百分比优先用 `task.progress`（后端已存的真实值），不再 isTerminal 一律 100% | success 仍 100%；只改 failed/cancelled 分支 |
| B-1 后端 `_sanitize_shared_task` | 新增 owner/admin 判定：`is_owner_or_admin == False` 时**剥离 `error_trace` 字段**（保留 `error_message`，因为 `error_message` 是用户视角的「失败原因」，`error_trace` 才是含路径/key/env 的开发者信息） | shared_research（analysis/screen/...）非 owner 看共享研究本来就允许，但 trace 不该共享；private types 已 403 不需处理 |
| B-2 后端 `/api/tasks/<task_id>` 响应 | 显式确认返回 `error_message / error_trace / progress_step / duration_ms`（`tm.get` 已经从 store 读 row，store row 已含前三字段）；`duration_ms` 若 store 没有，按 `completed_at - started_at` 现算；缺数据返 null 不返 0 | 不开新端点；只是确认现有 dict shape |
| W-1 AI worker 错误包装 | 在 `analysis` worker 调用 `StockAnalyzer.analyze` 的 try/except 里，按 exception 类型映射可读 `error_message`：<br/>`KeyError("QWEN_API_KEY")` / 缺 key → `"Qwen API Key 未配置"`<br/>HTTP 401/403 from DashScope → `"Qwen 认证失败，请检查 API Key"`<br/>HTTP 404 model not found → `"Qwen 模型不可用：{model}"`<br/>`asyncio.TimeoutError` / requests timeout → `"LLM 请求超时，请稍后重试或切换 quick 深度"`<br/>其它 → `str(e)` 原样<br/>`error_trace` 始终保留原始 traceback | 仅包装 message，不吞 exception，不改控制流；走 `_fail()` 既有路径 |

### 2.2 不动的强约束

- **不改** `task_failed` envelope 协议（仍 emit `{id, error_message}`）
- **不改** `tasks` 表 schema（`error_message / error_trace / progress_step` 都已存在）
- **不改** unified-progress v1.0 catch-up / per-user room 机制
- **不改** `_check_task_ownership` 现有规则
- **不改** `analysis-rendering.md` v1.2 的 per-tab ErrorBoundary —— 那是「分析成功但单卡渲染失败」的兜底；本方案是「任务失败」的兜底，互不重叠

### 2.3 共享研究边界（重要）

| 字段 | 创建者 | 同租户非创建者（shared_research type） | admin |
|---|---|---|---|
| `error_message` | ✅ | ✅（用户视角失败原因，无敏感信息） | ✅ |
| `error_trace` | ✅ | ❌ **B-1 新增剥离** | ✅ |
| `progress_step` | ✅ | ✅ | ✅ |
| `duration_ms` | ✅ | ✅ | ✅ |

理由：`error_trace` 由 `traceback.format_exc()` 产出，可能含 `/Users/zhixingshao/...` 路径、环境变量值、API Key 片段（如果异常 message 里漏了）。`error_message` 是 worker W-1 包装过的人话，对所有看得到任务的用户都安全。

## 3. 验收

### 3.1 后端

```bash
pytest tests/web/test_task_detail_failure.py tests/tasks/test_workers_qwen_errors.py -q
```

新增 case：
- `test_task_detail_includes_error_message_for_failed`
- `test_task_detail_strips_error_trace_for_non_owner_on_shared_type`
- `test_task_detail_keeps_error_trace_for_owner`
- `test_task_detail_keeps_error_trace_for_admin`
- `test_worker_wraps_qwen_missing_key`
- `test_worker_wraps_qwen_401`
- `test_worker_wraps_model_not_found`
- `test_worker_wraps_timeout`
- `test_worker_preserves_traceback_in_error_trace`

### 3.2 前端

```bash
cd stock_trading_system/web/frontend && npm run build
```

`tsc -b` 全绿（新字段全 optional 不破坏现有调用）；vite 产物 < 既有 chunk + 5KB（仅新增 alert + details 渲染分支）。

### 3.3 手测路径

1. 故意 unset `QWEN_API_KEY` → 提交 AI 分析 → `/tasks/<id>` 应显示「分析失败」+ 「Qwen API Key 未配置」+ 折叠 trace
2. 同上但用非创建者账号访问 → 应显示 `error_message`，但 `<details>` trace 区不出现（或显示「无开发者详情」）
3. 进度文案：failed 状态显示「失败于：market_analyst」（或当时实际 step），不再是「已完成 0/1」

## 4. 实施清单

| 文件 | 改动 | 增 LOC | 删 LOC |
|---|---|---|---|
| `stock_trading_system/web/frontend/src/islands/tasks/TasksPage.tsx` | F-1/F-2/F-3/F-4 | ~80 | ~5 |
| `stock_trading_system/web/app.py` | B-1（`_sanitize_shared_task` 内部）+ B-2（确认 `tm.get` 返回字段） | ~15 | 0 |
| `stock_trading_system/tasks/task_manager.py` | 确认 `_fail()` envelope 已含 `error_message`（无需改），新增 `duration_ms` 计算（如缺） | ~10 | 0 |
| `stock_trading_system/tasks/workers.py`（或对应 analysis worker） | W-1 错误包装 helper | ~50 | 0 |
| `tests/web/test_task_detail_failure.py` | 新建 | ~120 | 0 |
| `tests/tasks/test_workers_qwen_errors.py` | 新建 | ~100 | 0 |

总计 ~375 增 / ~5 删，自写。

## 5. 风险与回滚

- 风险 1：`error_trace` 剥离误伤 admin 调试 —— 已通过 `is_owner_or_admin` 判定保留 admin 全量
- 风险 2：W-1 错误包装匹配过宽误改成功路径 —— 仅在 except 分支生效，不影响主路径
- 回滚：还原 `TasksPage.tsx` + `_sanitize_shared_task` + worker 即可，schema 无变更
