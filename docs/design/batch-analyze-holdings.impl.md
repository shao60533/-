# 实施指令 — 一键持仓分析

> 本文件是给 Claude Code 新会话的实施指令。在新会话中直接说：
> "按照 docs/design/batch-analyze-holdings.impl.md 实施，完成后跑测试"

---

## 上下文

技术方案：`docs/design/batch-analyze-holdings.md`（完整方案，必读）

## 实施范围

### 后端（3 个文件）

1. **`stock_trading_system/tasks/workers.py`**
   - 新增 `make_batch_analysis_worker(deps)` 函数（方案第六节有完整伪代码）
   - 在 `register_default_workers()` 中注册 `tm.register("batch_analysis", make_batch_analysis_worker(deps))`
   - 关键：内部直接调用 `make_analysis_worker(deps)` 返回的函数，逐只顺序执行
   - 关键：每只完成后通过 `deps.get_socketio().emit("batch_analysis_item", {...})` 推送事件

2. **`stock_trading_system/web/app.py`**
   - 无需新增路由（复用 `POST /api/tasks/submit`）
   - 确认 `batch_analysis_item` 事件能正常推送到前端

3. **`stock_trading_system/tasks/task_store.py`**
   - 确认 `save_result` 支持 `batch_analysis` 类型写入 `task_results_generic` 表
   - 若不支持，在 `save_result` 中加一个 fallback 分支

### 前端（3 个文件）

4. **`stock_trading_system/web/templates/index.html`**
   - 持仓页（`#page-portfolio`）操作按钮组新增"一键分析全部"按钮
   - 仪表盘（`#page-dashboard`）快捷操作区新增"分析全部持仓"入口
   - 新增批量分析确认弹窗 modal（含跳过时间设置）
   - 新增批量分析进度面板 HTML 结构（逐只卡片列表 + 进度条 + 最小化按钮）

5. **`stock_trading_system/web/static/js/app.js`**
   - 新增 `runBatchAnalysis()` — 弹确认框 → 提交任务 → 显示进度面板
   - 新增 `socket.on('batch_analysis_item', ...)` — 更新对应 ticker 卡片状态
   - 新增 `updateBatchProgressPanel(data)` — 进度条 + 步骤文字
   - 新增 `minimizeBatchPanel()` / `expandBatchPanel()` — 最小化/展开
   - 复用 `openHistoryDetail(analysis_id)` 做"查看详情"跳转

6. **`stock_trading_system/web/static/css/style.css`**
   - 批量分析进度面板样式（`.batch-progress-panel`）
   - 逐只卡片样式（`.batch-item-card` + 状态色：success/failed/skipped/running/pending）
   - 最小化浮动条样式（`.batch-mini-bar`）

### 测试

7. **`tests/test_batch_analysis.py`**（新建）
   - 测试用例来自方案第十二节 BA-1.1 ~ BA-1.10
   - mock `get_holdings()` 返回 3 只持仓
   - mock `analysis_worker` 返回预设结果（或抛异常测 failed）
   - 验证：返回结构、跳过逻辑、失败容错、progress_cb 调用次数

## 实施顺序

1. 先读完 `docs/design/batch-analyze-holdings.md` 第四~六节
2. 后端 → workers.py → task_store.py 确认 → 跑 `pytest tests/test_batch_analysis.py`
3. 前端 → index.html → app.js → style.css
4. 全量测试 → `pytest tests/ -x` + `node tests/frontend/run.js`（如果存在）

## 完成标准

- [ ] `POST /api/tasks/submit {type:"batch_analysis", params:{skip_recent_hours:4}}` 返回 task_id
- [ ] 3 只 mock 持仓逐只分析完成，结果写入 analysis_history
- [ ] WebSocket 推送 batch_analysis_item 事件（每只一次）
- [ ] 前端持仓页有"一键分析全部"按钮
- [ ] 点击后弹确认框 → 提交 → 进度面板实时更新
- [ ] `pytest tests/test_batch_analysis.py` 全部通过
- [ ] `pytest tests/ -x` 无回归
