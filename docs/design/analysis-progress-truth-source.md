# 技术方案：统一 AI 分析进度真相源

| 项 | 值 |
|---|---|
| Feature | `analysis-progress-truth-source` |
| 版本 | v1.0 |
| 日期 | 2026-05-03 |
| 关联 | [unified-progress.md](unified-progress.md) v1.0（envelope schema + per-user room）+ [analysis-rendering.md](analysis-rendering.md) 系列（OverviewCard / inbox row）+ [task-failure-visibility.md](task-failure-visibility.md) v1.0（task_failed 包装）|
| 关联测试 | `tests/tasks/test_progress_truth_source.py` |

## 1. 背景

用户报告「`/analysis` 列表行显示运行中 15%，旁边 `<PipelineDAG>` 已经全绿；任务详情页又是另一个数」——同一任务的进度显示在 4 处不一致。

### 1.1 现状审计（事实，已 grep 核实）

| 表面 | 数据来源 | 结果 |
|---|---|---|
| `<RunningRow>` 行 `{progress_pct}%` | `/api/history?include_running=true` 拉的 `tasks.progress` 持久值 | 落后；只在重新拉接口时刷新 |
| `<PipelineDAG>` 7 节点 | socket `analysis_pipeline` 事件（live） | 实时但只 7 步颗粒度，与 `progress` 数字不挂钩 |
| `<RunningRow>` 折叠态进度条 | 同 `progress_pct` | 落后 |
| `/tasks/<id>` 详情页 | catch-up `/api/tasks/events` + live `task_progress`（live 实际收不到，见 1.2-c） | 与列表完全不一致 |

### 1.2 根因（grep + reflog 确认）

| 编号 | 现象 | 根因 |
|---|---|---|
| a | live 路径上前端永远收不到 `task_progress/task_completed` | `TaskManager._emit` 广播 raw payload `{id: ...}`，而 `subscribeTaskStream.onAny` 用 `"task_id" in env` 过滤——legacy payload 没顶层 `task_id` 被丢弃，必须依赖 `/api/tasks/events?since=<seq>` 重连回放才看到 |
| b | 即使 envelope 修了，行 pct 只跳 5/85/98 三档 | 分析 worker 只在 analyzer 前后调 `progress_cb(15)` / `(85)` / `(98)`；analyzer 内部 7 步的 `step_done` 事件只发 `analysis_pipeline` 通道，**没桥接到 task_progress**——DAG 一步步推进，行数字纹丝不动 |
| c | DAG 全绿时行 pct 仍卡在 15% | 同 b——`pipeline_done` 没产生 progress_cb；后续 advice/finalize 才跳 |
| d | 任务详情页与列表不一致 | 详情页通过 `subscribeTaskStream` 订阅，与列表订阅同样的事件，但 catch-up 顺序不同 → 字段读取不同 |
| e | `task_progress` 缺 `task_id`/`stage`/`status` | payload 只有 `{id, progress, step, partial}`，前端要凭事件类型猜哪个 task、哪个阶段 |

## 2. 总览

**单一真相源** = TaskManager 广播的 envelope `{task_id, user_id, seq, event, payload, emitted_at}`。
所有表面（行 pct、DAG、详情页、状态 badge）订阅同一份 envelope 流，按 `task_id` 路由进各自的 state。

## 3. 方案（三层）

### 3.1 后端 envelope 修复

| ID | 改动 | 位置 |
|---|---|---|
| B-1 | `TaskManager._emit` 广播 `event_emitter.persist_event` 返回的 envelope，不再发 raw payload | `task_manager.py::_emit` |
| B-2 | `progress_cb(percent, step_desc, partial, *, stage)` 增 `stage` kwarg；`task_progress` payload 暴露 `task_id`/`stage`/`status`；所有 lifecycle 事件 payload 同时带 `id` 和 `task_id`（向后兼容） | `task_manager.py::_run.progress_cb` |
| B-3 | analysis worker `_analysis_progress` 把 `step_done` 映射到 `progress_cb`，pipeline_done 映射到 85% | `workers.py::make_analysis_worker` |

### 3.2 进度百分比映射

| 阶段 | pct | step / stage |
|---|---|---|
| 初始化 | 5 | `init` |
| pipeline_start | 5 | `pipeline_start`（仅 step 文案变化，pct 不动） |
| step_done × 7 | 16 / 28 / 39 / 51 / 62 / 74 / 85 | analyzer step id（`market` / `social` / `news` / `fundamentals` / `debate` / `risk` / `decision`） |
| pipeline_done | 85 | `pipeline_done` |
| 生成个人建议 | 90 | `advice` |
| 整理结果 | 98 | `finalize` |
| 成功 | 100（TaskManager 自动） | — |
| 失败 | 不动（保留最后已知 pct + step），`task_failed` 透出 error_message | — |

公式：`pct_step_done = round(5 + (idx + 1) / 7 * 80)`

### 3.3 前端订阅

| ID | 改动 | 位置 |
|---|---|---|
| F-1 | `<PipelineDAG>` 加 `initialSteps` / `onProgress` 两个可选 props | `PipelineDAG.tsx` |
| F-2 | AnalysisPage inbox 维护 `liveProgress: Record<task_id, {pct, step, stage}>` map | `AnalysisPage.tsx::AnalysisHomeInbox` |
| F-3 | `<RunningRow>` 接 `live` prop，渲染 `Math.max(live.pct, row.progress_pct)`、永不回退；折叠态进度条同样消费 `displayedPct` | `AnalysisPage.tsx::RunningRow` |

订阅事件分发：

```text
task_progress       → liveProgress[task_id] = {pct, step, stage}
analysis_pipeline   → step_done: 兜底重算 pct（task_progress 丢包时）
                      pipeline_done: pct≥85, step="整理结果中"
task_completed      → delete liveProgress[task_id] + refreshInbox()
task_failed         → 同上（行翻为失败态后由 /api/history 接管）
task_cancelled      → 同上
```

## 4. 不动的强约束

- 不改 envelope schema（`{task_id, user_id, seq, event, payload, emitted_at}`）
- 不改 unified-progress v1.0 catch-up 协议 / per-user room 机制
- 不改 `analyzer.PIPELINE_STEPS`（7 步顺序）
- 不改 `analysis_pipeline` 事件 payload（仍是 `{type, step, label, index, total, ...}`）
- 不改 task_failed envelope（仍 `{id, task_id, error_message}`）

## 5. 验收

```bash
pytest tests/tasks/test_progress_truth_source.py \
       tests/tasks/test_workers.py \
       tests/tasks/test_task_manager.py \
       tests/tasks/test_workers_qwen_errors.py \
       tests/tasks/test_event_emitter.py -q
# → 79 passed

cd stock_trading_system/web/frontend && npm test
# → 15 passed (4 OverviewCard.executive + 8 AnalysisCards + 3 AnalysisDetailView.order)

cd stock_trading_system/web/frontend && npm run build
# → tsc + vite green
```

### 5.1 新增 case

`tests/tasks/test_progress_truth_source.py`（4 个）：
- `test_emit_broadcasts_unified_envelope`：所有 lifecycle 事件 envelope 顶层有 `task_id`、`event`、`seq`、`emitted_at`、`payload`
- `test_task_progress_envelope_carries_task_id_stage_status`：progress envelope.payload 同时含 `task_id`、`id` 别名、`stage`、`status`、`step`、`progress`
- `test_analyzer_step_done_drives_5_to_85_progress`：7 step_done 事件按 `5+(idx+1)/7*80` 映射，断言 16 / 51 / 85 三个里程碑
- `test_analyzer_step_done_carries_stage_id`：每个 progress_cb 调用都带正确的 stage（`market` / `decision` / `pipeline_done` / `advice` / `finalize`）

### 5.2 手测路径

1. **新开 deep 分析**：`/analysis` 提交 → 列表行无需刷新即可观察 5%→16→28→39→51→62→74→85→90→98→完成；同一行的 DAG 节点同步推进
2. **DAG 与 pct 一致性**：DAG 全绿那一刻，pct 立即 ≥85（来自 `pipeline_done` envelope）；继续 90/98 跟进
3. **断网重连**：拔网线 5 秒重连，列表通过 `/api/tasks/events?since=<seq>` 回放到正确阶段（envelope 流持久化保证幂等）
4. **任务详情页一致**：列表 + `/tasks/<id>` 显示同一 pct + 同一 step 文案

## 6. 实施清单

| 文件 | 改动 | 增 LOC | 删 LOC |
|---|---|---|---|
| `stock_trading_system/tasks/task_manager.py` | B-1 envelope 广播 + B-2 progress_cb stage kwarg | ~50 | ~10 |
| `stock_trading_system/tasks/workers.py` | B-3 analyzer step_done → progress_cb 桥接 | ~40 | ~5 |
| `stock_trading_system/web/frontend/src/components/shared/PipelineDAG.tsx` | F-1 initialSteps + onProgress | ~30 | ~3 |
| `stock_trading_system/web/frontend/src/islands/analysis/AnalysisPage.tsx` | F-2 liveProgress map + F-3 RunningRow live prop | ~85 | ~5 |
| `tests/tasks/test_progress_truth_source.py` | 新建 4 case | ~190 | 0 |
| `tests/tasks/test_task_manager.py` | RecordingSocketIO.by_name 自动 unwrap envelope | ~20 | ~2 |
| `tests/tasks/test_workers.py` | 测试 lambda 加 `**_` 兼容 stage kwarg | ~2 | ~0 |

总计 ~417 增 / ~25 删，自写。

## 7. 风险与回滚

- 风险 1：smart auto-commit 钩子吞掉部分改动 → 已通过实测发现 + c92b641 模式补回（见 task-failure-visibility 提交记录）。本轮已观察到一次相同模式，重做后已修复。
- 风险 2：老订阅者依赖 raw payload 顶层 `id` 字段 → envelope.payload 仍保留 `id` 别名 + 新增 `task_id`，向后兼容。
- 回滚：还原 4 个源文件 + 1 个测试文件即可，schema 无变更。
