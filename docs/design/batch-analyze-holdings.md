# 一键持仓分析 — 技术方案

> **版本**: 1.0  
> **日期**: 2026-04-18  
> **状态**: 草稿 — 待评审  
> **依据**: 用户需求"对当前所有持仓执行一键 AI 分析"

---

## 一、问题陈述

当前 AI 分析是**单票操作**：用户在分析页输入一只 ticker → 点击"分析" → 等待 2-5 分钟 → 查看结果。如果持仓 8 只股票，需要重复操作 8 次，每次手动输入 ticker，总耗时 20-40 分钟。

**痛点**：盘前/盘后想快速过一遍所有持仓的 AI 观点，但逐只分析的操作路径太长。

**目标**：一键触发所有持仓的 AI 分析，自动排队执行，逐只完成时实时推送结果。

---

## 二、目标与非目标

### 2.1 目标

| # | 目标 | 衡量 |
|---|------|------|
| G1 | **一键触发** — 用户点一次按钮即可分析全部持仓 | 操作步数 = 1 |
| G2 | **逐只推送** — 每只完成时实时展示结果，无需等全部完成 | 首只结果 2-5 分钟内可见 |
| G3 | **智能跳过** — 近期已分析的 ticker 可选跳过，避免重复浪费 | 可配置跳过窗口 |
| G4 | **容错** — 单只失败不影响其他 ticker 继续 | 失败率 < 总数时批次仍 success |
| G5 | **可追溯** — 批次任务在任务中心可见，关联到每只的分析记录 | task_id 可回看 |

### 2.2 非目标

| # | 不做 | 原因 |
|---|------|------|
| NG1 | 不做批次内并行分析（同时跑 N 只） | 单次 AI 分析已吃满 Qwen/Gemini API 带宽，并行只会触发限流 |
| NG2 | 不做自定义 ticker 列表（用户手选哪几只分析） | 保持简单，"一键 = 全部持仓"；自选可用现有单票分析 |
| NG3 | 不做定时自动批量分析（每天自动跑） | 属于 scheduler 范畴，不在本方案内 |
| NG4 | 不做批次内排序策略（先分析亏损最大的） | 初版按持仓顺序即可，不过度设计 |

---

## 三、用户故事

**US-B.1** 作为投资者，我想在持仓页点击"一键分析全部"，系统自动逐只执行 AI 分析，每完成一只就推送结果卡片，这样我可以边看结果边做决策，不用逐只手动触发。

**US-B.2** 作为投资者，我想在触发批量分析时选择是否跳过最近 N 小时内已分析过的 ticker，这样不浪费时间和 API 成本重复分析。

**US-B.3** 作为投资者，我想在任务中心看到这次批量分析的整体进度（3/8 完成）和每只的状态（成功/失败/跳过），这样我知道还需要等多久。

**US-B.4** 作为投资者，我想在仪表盘也有一个快捷入口触发持仓全量分析，这样不用先切到持仓页。

---

## 四、方案设计

### 4.1 核心思路

引入一个新的任务类型 `batch_analysis`，它是一个**编排任务**（orchestrator）：

```
用户点击"一键分析"
    ↓
POST /api/tasks/submit { type: "batch_analysis", params: {} }
    ↓ (立即返回 batch_task_id)
    
batch_analysis_worker 执行：
    1. 读取当前持仓列表 → [AAPL, TSLA, NVDA, ...]
    2. 对每只 ticker 逐一调用现有 analysis_worker
    3. 每只完成/失败时更新 batch 进度 + 推送 WS 事件
    4. 全部完成后汇总：N 成功 / M 失败 / K 跳过
```

**关键设计**：batch_analysis_worker **不直接调用 analyzer**，而是**为每只 ticker 提交独立的 analysis 子任务**到 TaskManager。这样：
- 每只分析都有独立的 task_id，可在任务中心单独查看
- 每只分析的结果正常写入 `analysis_history`，正常触发 paper_trade 自动追踪
- 复用现有 analysis_worker 的全部逻辑（进度推送、结果持久化、策略建议生成）

### 4.2 执行流程

```
┌─────────────────────────────────────────────────────────────────┐
│ batch_analysis_worker(params, progress_cb)                       │
│                                                                   │
│  1. holdings = get_portfolio().get_holdings()                    │
│     → [{ticker:"AAPL", shares:100, ...}, ...]                   │
│                                                                   │
│  2. 过滤：                                                       │
│     ├─ 排除 shares=0 的空仓                                      │
│     └─ 若 skip_recent_hours > 0：                                │
│        检查 analysis_history 最近 N 小时有无该 ticker 的成功记录   │
│        有 → 标记 skipped，不分析                                  │
│                                                                   │
│  3. 逐只顺序执行（非并行）：                                      │
│     for i, ticker in enumerate(to_analyze):                      │
│       progress_cb(pct, f"正在分析 {ticker} ({i+1}/{total})")     │
│       ┌─────────────────────────────────────────────┐            │
│       │ 直接调用 analysis_worker(                    │            │
│       │   {ticker, date},                           │            │
│       │   sub_progress_cb                           │            │
│       │ )                                           │            │
│       │ → 结果自动写入 analysis_history              │            │
│       │ → 自动触发 paper_trade 追踪                  │            │
│       └─────────────────────────────────────────────┘            │
│       emit WS: batch_analysis_item {                             │
│         batch_task_id, ticker, index, total,                     │
│         status: "success"|"failed"|"skipped",                    │
│         analysis_id, signal, error?                              │
│       }                                                           │
│                                                                   │
│  4. 汇总结果：                                                    │
│     return {                                                      │
│       total, analyzed, succeeded, failed, skipped,               │
│       items: [{ticker, status, analysis_id?, signal?, error?}]   │
│     }                                                             │
└─────────────────────────────────────────────────────────────────┘
```

### 4.3 为什么逐只顺序执行而非并行

| 维度 | 顺序执行 | 并行执行 |
|------|---------|---------|
| API 限流 | 安全，单次分析已用满 7 Agent 管线 | 多只同时跑会触发 Qwen/Gemini 429 |
| 用户体验 | 首只 2-5 分钟出结果，逐只推送 | 全部同时跑，但全部同时延迟增大 |
| 资源占用 | 低（1 个 worker 线程） | 高（N 个 worker 线程） |
| 错误隔离 | 天然隔离，一只失败不影响下一只 | 需额外处理并发错误 |
| 实现复杂度 | 简单 | 需要子任务管理、并发控制 |

**结论**：顺序执行是正确选择。8 只持仓逐只分析约 20-40 分钟，但用户从第一只完成（2-5 分钟）就可以开始看结果。

### 4.4 子任务模式 vs 直接调用

考虑了两种方案：

**方案 A — 提交子任务到 TaskManager**：
- 每只 ticker 创建独立 task_id
- 优点：任务中心可逐只查看；幂等检查自动生效
- 缺点：batch worker 需要等待子任务完成（polling 或 callback）

**方案 B — 直接调用 analysis_worker 函数（选用）**：
- batch worker 内部直接 `analysis_worker(params, sub_progress_cb)`
- 结果正常写入 analysis_history（因为 worker 内部调了 save_analysis）
- 优点：简单直接；无需子任务等待机制
- 缺点：这些分析不会作为独立 task 出现在任务中心（但出现在分析记录中）

**选择方案 B**，理由：
1. 不增加 TaskManager 复杂度（无需父子任务关系）
2. 每只分析的**结果**仍然完整写入 analysis_history，在"分析记录"页正常可查
3. 自动追踪到 paper_trade 的钩子在 batch worker 中手动调用即可
4. 批次整体作为一个 task 出现在任务中心，足够满足可追溯需求

---

## 五、API 设计

### 5.1 新增端点

无需新增 REST 端点。复用现有 `POST /api/tasks/submit`：

```json
POST /api/tasks/submit
{
    "type": "batch_analysis",
    "params": {
        "skip_recent_hours": 4,
        "date": null
    },
    "title": "持仓全量分析"
}
```

**参数说明**：

| 参数 | 类型 | 默认 | 说明 |
|------|------|------|------|
| `skip_recent_hours` | number | 4 | 跳过最近 N 小时内已分析的 ticker。0 = 全部重新分析 |
| `date` | string \| null | null（今天） | 分析日期，透传给每只的 analysis_worker |

### 5.2 WebSocket 事件

复用现有 `task_*` 事件 + 新增 1 个细粒度事件：

| 事件 | 数据 | 时机 |
|------|------|------|
| `task_created` | 标准 task dict | 批次提交 |
| `task_started` | `{id}` | 开始执行 |
| `task_progress` | `{id, progress, step}` | 每只开始/完成时 |
| **`batch_analysis_item`** | 见下 | **每只 ticker 完成时** |
| `task_completed` | `{id, result_ref}` | 全部完成 |
| `task_failed` | `{id, error_message}` | 致命错误（非单只失败） |

**`batch_analysis_item` 事件 payload**：

```json
{
    "batch_task_id": "uuid-xxx",
    "ticker": "AAPL",
    "index": 0,
    "total": 8,
    "status": "success",
    "analysis_id": 42,
    "signal": "BUY",
    "confidence": 78,
    "advice_action": "buy",
    "error": null
}
```

status 取值：`success` | `failed` | `skipped`

### 5.3 返回结果

批次任务完成后，通过 `GET /api/tasks/{id}/result` 获取汇总：

```json
{
    "total": 8,
    "analyzed": 6,
    "succeeded": 5,
    "failed": 1,
    "skipped": 2,
    "duration_ms": 1234000,
    "items": [
        {
            "ticker": "AAPL",
            "status": "success",
            "analysis_id": 42,
            "signal": "BUY",
            "confidence": 78,
            "advice_action": "buy"
        },
        {
            "ticker": "TSLA",
            "status": "skipped",
            "reason": "3 小时前已分析",
            "last_analysis_id": 38,
            "last_signal": "HOLD"
        },
        {
            "ticker": "NVDA",
            "status": "failed",
            "error": "Qwen API timeout"
        }
    ]
}
```

---

## 六、后端实现

### 6.1 Worker 实现

```python
# tasks/workers.py — 新增

def make_batch_analysis_worker(deps: WorkerDeps):
    """批量持仓分析 worker — 逐只顺序执行。"""
    
    analysis_worker_fn = make_analysis_worker(deps)
    
    def worker(params: dict, progress_cb) -> dict:
        skip_hours = params.get("skip_recent_hours", 4)
        date = params.get("date") or today_str()
        
        # 1. 获取持仓列表
        pm = deps.get_portfolio()
        holdings = pm.get_holdings()
        tickers = [h["ticker"] for h in holdings if h.get("shares", 0) > 0]
        
        if not tickers:
            return {"total": 0, "analyzed": 0, "succeeded": 0,
                    "failed": 0, "skipped": 0, "items": []}
        
        # 2. 检查跳过（近期已分析的）
        db = pm.db
        items = []
        to_analyze = []
        
        for ticker in tickers:
            if skip_hours > 0:
                recent = db.get_analysis_history(ticker=ticker, limit=1)
                if recent and _within_hours(recent[0]["created_at"], skip_hours):
                    items.append({
                        "ticker": ticker,
                        "status": "skipped",
                        "reason": f"{skip_hours} 小时内已分析",
                        "last_analysis_id": recent[0]["id"],
                        "last_signal": recent[0].get("signal"),
                    })
                    continue
            to_analyze.append(ticker)
        
        total = len(tickers)
        skipped = len(items)
        succeeded = 0
        failed = 0
        
        progress_cb(5, f"持仓 {total} 只，跳过 {skipped} 只，待分析 {len(to_analyze)} 只")
        
        # 3. 逐只分析
        for i, ticker in enumerate(to_analyze):
            step_label = f"分析 {ticker} ({skipped + i + 1}/{total})"
            progress_cb(_batch_pct(i, len(to_analyze)), step_label)
            
            # 构造子进度回调（映射到 batch 的进度区间）
            def sub_progress(pct, step=None, partial=None,
                             _i=i, _n=len(to_analyze)):
                batch_pct = _batch_pct(_i, _n, sub_pct=pct)
                progress_cb(batch_pct, f"{ticker}: {step or ''}")
            
            try:
                result = analysis_worker_fn(
                    {"ticker": ticker, "date": date},
                    sub_progress
                )
                # result 含 analysis_id, signal 等
                items.append({
                    "ticker": ticker,
                    "status": "success",
                    "analysis_id": result.get("analysis_id"),
                    "signal": result.get("signal"),
                    "confidence": result.get("confidence"),
                    "advice_action": result.get("advice_action"),
                })
                succeeded += 1
            except Exception as e:
                logger.warning("Batch analysis failed for %s: %s", ticker, e)
                items.append({
                    "ticker": ticker,
                    "status": "failed",
                    "error": str(e),
                })
                failed += 1
            
            # 推送单只完成事件
            socketio.emit("batch_analysis_item", {
                "batch_task_id": params.get("_task_id", ""),
                **items[-1],
                "index": skipped + i,
                "total": total,
            })
        
        progress_cb(99, f"完成：{succeeded} 成功，{failed} 失败，{skipped} 跳过")
        
        return {
            "total": total,
            "analyzed": len(to_analyze),
            "succeeded": succeeded,
            "failed": failed,
            "skipped": skipped,
            "items": items,
        }
    
    return worker


def _batch_pct(i: int, n: int, sub_pct: float = 0) -> int:
    """将第 i 只（共 n 只）的子进度映射到 batch 的 5%-99% 区间。"""
    if n == 0:
        return 99
    per_ticker = 94.0 / n  # 5% ~ 99% 的空间
    base = 5 + i * per_ticker
    return int(base + (sub_pct / 100) * per_ticker)


def _within_hours(created_at_str: str, hours: int) -> bool:
    """判断时间戳是否在 N 小时以内。"""
    from datetime import datetime, timedelta
    try:
        created = datetime.fromisoformat(created_at_str.replace("Z", "+00:00"))
        return datetime.now(created.tzinfo or None) - created < timedelta(hours=hours)
    except Exception:
        return False
```

### 6.2 注册 Worker

```python
# tasks/workers.py — register_default_workers 中新增
tm.register("batch_analysis", make_batch_analysis_worker(deps))
```

### 6.3 幂等策略

- batch_analysis 的 `params_hash` 基于 `{skip_recent_hours, date}` 计算
- 默认幂等窗口 **300 秒**（5 分钟），因为 batch 执行时间长
- 如果上一轮 batch 仍在 running，新提交会返回已有 task（不重复执行）

在 submit 时指定：

```python
# 前端提交时可附加：
tm.submit("batch_analysis", params, 
          title="持仓全量分析",
          idempotency_window=300)
```

---

## 七、前端实现

### 7.1 入口位置

两个入口，统一调用同一函数：

**入口 1 — 持仓管理页**（主入口）：
- 操作按钮组中新增"一键分析全部"按钮
- 位置：与"买入""卖出""快照"并列

**入口 2 — 仪表盘**（快捷入口）：
- 快捷操作面板中新增"分析全部持仓"入口
- 位置：与"分析""选股""报告"并列

### 7.2 交互流程

```
点击"一键分析全部"
    ↓
弹出确认弹窗：
┌──────────────────────────────────────────┐
│  分析全部持仓                              │
│                                            │
│  当前持仓 8 只股票，预计耗时 20-40 分钟      │
│                                            │
│  ☑ 跳过最近 [4] 小时内已分析的股票          │
│                                            │
│           [取消]       [开始分析]            │
└──────────────────────────────────────────┘
    ↓ 点击"开始分析"
    
POST /api/tasks/submit { type: "batch_analysis", ... }
    ↓ 返回 task_id
    
页面切换到「批量分析进度面板」（覆盖持仓列表区域）：
┌──────────────────────────────────────────────┐
│  持仓全量分析                     [取消] [最小化] │
│  进度：3/8 完成 · 预计剩余 ~15 分钟               │
│  ━━━━━━━━━━━━━━━━░░░░░░░░░░░░░░  37%         │
├──────────────────────────────────────────────┤
│  ✅ AAPL   BUY · 置信度 78%     [查看详情]      │
│  ✅ TSLA   HOLD · 置信度 65%    [查看详情]      │
│  🔄 NVDA   分析中 — 情绪分析...                  │
│  ⏳ MSFT   等待中                                │
│  ⏳ GOOG   等待中                                │
│  ⏳ AMZN   等待中                                │
│  ⏭️ META   已跳过 (2 小时前已分析 · SELL)        │
│  ⏭️ AMD    已跳过 (1 小时前已分析 · BUY)         │
└──────────────────────────────────────────────┘
```

### 7.3 移动端适配

- 确认弹窗改为底部全屏抽屉
- 进度面板为全宽卡片列表，每只 ticker 一张卡
- 卡片内操作按钮（查看详情）全宽

### 7.4 最小化模式

用户可点击"最小化"将进度面板收起为底部浮动条：

```
┌──────────────────────────────────────────────┐
│  🧠 持仓分析中 · 3/8 ━━━━━░░░░░  37%  [展开] │
└──────────────────────────────────────────────┘
```

最小化后用户可继续在其他页面操作，分析在后台继续。

### 7.5 JS 实现要点

```javascript
// app.js 新增

async function runBatchAnalysis() {
    const skipHours = parseInt(document.getElementById('batch-skip-hours').value) || 4;
    
    const resp = await api('/api/tasks/submit', {
        method: 'POST',
        body: JSON.stringify({
            type: 'batch_analysis',
            params: { skip_recent_hours: skipHours },
            title: '持仓全量分析',
        })
    });
    
    const task = await resp.json();
    currentBatchTaskId = task.id;
    showBatchProgressPanel(task);
}

// 监听单只完成事件
socket.on('batch_analysis_item', (data) => {
    if (data.batch_task_id !== currentBatchTaskId) return;
    updateBatchItemCard(data);
    // 如果 status=success，可以用已有 renderAnalysisResultPayload 弹窗查看
});

// 监听整体进度
socket.on('task_progress', (data) => {
    if (data.id !== currentBatchTaskId) return;
    updateBatchProgressBar(data.progress, data.step);
});

// 监听完成
socket.on('task_completed', (data) => {
    if (data.id !== currentBatchTaskId) return;
    finalizeBatchPanel();
    showToast('success', '持仓分析完成', 
              `${batchResult.succeeded} 成功 / ${batchResult.failed} 失败`);
});
```

### 7.6 「查看详情」跳转

每只完成的 ticker 卡片有"查看详情"按钮：
- 点击后打开分析详情弹窗（复用 `openHistoryDetail(analysis_id)`）
- 不离开当前页面，弹窗叠加在进度面板之上

---

## 八、数据模型

### 8.1 不新增表

批次结果写入 `task_results_generic` 表（已有），`result_ref = "task_results_generic:{id}"`。

每只 ticker 的分析结果正常写入 `analysis_history` 表（复用现有逻辑）。

### 8.2 批次结果 JSON 结构

存入 `task_results_generic.result_json`：

```json
{
    "total": 8,
    "analyzed": 6,
    "succeeded": 5,
    "failed": 1,
    "skipped": 2,
    "items": [
        {"ticker": "AAPL", "status": "success", "analysis_id": 42, "signal": "BUY", ...},
        {"ticker": "META", "status": "skipped", "reason": "2 小时前已分析", "last_analysis_id": 38, ...},
        {"ticker": "NVDA", "status": "failed", "error": "Qwen API timeout"}
    ]
}
```

---

## 九、配置

无需新增配置项。使用现有：

```yaml
tasks:
  max_workers: 3      # batch_analysis 占用 1 个 worker 线程
```

注意：batch_analysis 执行期间占用 1 个 worker 线程（内部顺序执行），其余 2 个 worker 可处理其他任务（如用户同时触发选股）。

---

## 十、风险与缓解

| 风险 | 概率 | 影响 | 缓解 |
|------|------|------|------|
| 单只分析 5 分钟 × 8 只 = 40 分钟总耗时 | 高 | 中 | 逐只推送结果，用户无需等全部完成；跳过近期已分析的减少数量 |
| Qwen/Gemini API 在连续调用后限流 | 中 | 高 | 顺序执行天然限速；单只失败不阻塞后续；失败后可重新触发 batch |
| 用户在 batch 进行中关闭页面 | 中 | 低 | batch 是后台 task，不受前端连接影响；重新打开后可从任务中心恢复查看 |
| 持仓数量过多（>20 只） | 低 | 中 | 前端确认弹窗提示预估耗时；设上限 30 只（超出提示） |
| 长时间占用 worker 线程 | 中 | 低 | max_workers=3，batch 占 1 个，还有 2 个可用 |

---

## 十一、实施计划

### Phase 1 — 后端（0.5 天）

| 步骤 | 内容 | 验证 |
|------|------|------|
| 1.1 | 在 `workers.py` 新增 `make_batch_analysis_worker` | 单元测试：mock holdings + mock analysis_worker |
| 1.2 | 注册到 `register_default_workers` | `POST /api/tasks/submit {type:"batch_analysis"}` 返回 task_id |
| 1.3 | 新增 `batch_analysis_item` WS 事件推送 | WS 客户端收到逐只完成事件 |

### Phase 2 — 前端（0.5 天）

| 步骤 | 内容 | 验证 |
|------|------|------|
| 2.1 | 持仓页 + 仪表盘新增"一键分析全部"按钮 | 按钮可见、可点击 |
| 2.2 | 确认弹窗（跳过时间可配） | 弹窗正常弹出、参数可调 |
| 2.3 | 批量分析进度面板（逐只卡片 + 进度条 + 最小化） | WS 事件驱动 UI 更新 |
| 2.4 | "查看详情"跳转到分析详情弹窗 | 点击跳转正常 |
| 2.5 | 移动端适配 | 手机宽度下进度面板正常 |

### Phase 3 — 测试（0.5 天）

详见第十二节测试用例。

---

## 十二、测试用例

### 12.1 后端

| ID | 用例 | 预期 |
|----|------|------|
| BA-1.1 | 3 只持仓，skip_hours=0 | 全部分析，succeeded=3 |
| BA-1.2 | 3 只持仓，其中 1 只 2 小时前已分析，skip_hours=4 | analyzed=2, skipped=1 |
| BA-1.3 | 空持仓 | total=0，立即 success |
| BA-1.4 | 1 只分析失败（mock Qwen 超时） | succeeded=2, failed=1，整体仍 success |
| BA-1.5 | 全部失败 | succeeded=0, failed=3，整体仍 success（非致命错误） |
| BA-1.6 | progress_cb 调用次数 | 至少 1 + N*2 次（开始 + 每只开始/完成） |
| BA-1.7 | 幂等：5 分钟内重复提交 | 返回相同 task_id |
| BA-1.8 | 取消正在执行的 batch | 当前 ticker 完成后停止，已完成的保留 |
| BA-1.9 | analysis_history 写入 | 每只 succeeded 的 ticker 都有 analysis_history 记录 |
| BA-1.10 | paper_trade 自动追踪 | 每只分析结果正常触发追踪钩子 |

### 12.2 前端

| ID | 用例 | 预期 |
|----|------|------|
| BA-2.1 | 持仓页按钮可见 | "一键分析全部"按钮在操作栏 |
| BA-2.2 | 仪表盘快捷入口 | "分析全部持仓"入口可见 |
| BA-2.3 | 确认弹窗展示 | 显示持仓数量 + 预估耗时 + 跳过设置 |
| BA-2.4 | 进度面板渲染 | 每只 ticker 一张卡片，状态实时更新 |
| BA-2.5 | 逐只完成推送 | 收到 `batch_analysis_item` 后卡片状态更新 |
| BA-2.6 | 信号颜色 | BUY 绿色、SELL 红色、HOLD 黄色 |
| BA-2.7 | 跳过状态展示 | 显示"已跳过"+ 上次信号 |
| BA-2.8 | 失败状态展示 | 显示红色错误信息 |
| BA-2.9 | 查看详情跳转 | 点击后弹出分析详情弹窗 |
| BA-2.10 | 最小化/展开 | 浮动进度条 ↔ 完整面板切换 |
| BA-2.11 | 完成后 Toast | "持仓分析完成：5 成功 / 1 失败" |
| BA-2.12 | 空持仓点击 | 提示"暂无持仓，请先添加持仓" |
| BA-2.13 | 移动端确认弹窗 | 底部全屏抽屉 |
| BA-2.14 | 重复点击防护 | 按钮 disabled + 提示"分析进行中" |

### 12.3 集成

| ID | 用例 | 预期 |
|----|------|------|
| BA-3.1 | 端到端：3 只持仓全量分析 | 3 只全部出现在分析记录页 |
| BA-3.2 | 任务中心可见 | 批次任务在任务中心列表中显示 |
| BA-3.3 | 断网重连后查看 | 通过任务中心查看已完成的批次结果 |
| BA-3.4 | batch 执行中触发单只分析 | 两者互不干扰（不同 worker 线程） |

---

## 十三、成本估算

| 持仓数 | 跳过数 | 实际分析数 | 预估耗时 | Qwen 成本 |
|--------|--------|-----------|---------|-----------|
| 5 | 0 | 5 | 10-25 分钟 | ~¥2 |
| 8 | 2 | 6 | 12-30 分钟 | ~¥2.4 |
| 10 | 3 | 7 | 14-35 分钟 | ~¥2.8 |
| 15 | 5 | 10 | 20-50 分钟 | ~¥4 |

单次分析约 ¥0.4（20K tokens × qwen-plus 价格）。跳过机制有效降低成本。

---

*方案 v1.0 结束。请审阅后确认是否可以进入实施阶段。*

---

## 十四、v1.1 前端入口补丁（2026-05-13）

### 14.1 现状

v1.0 设计稿于 2026-04-18 立项，**后端已实装**（[`tasks/workers.py:782 make_batch_analysis_worker`](../../stock_trading_system/tasks/workers.py)，注册名 `batch_analysis`，含跳过近期分析 / 逐只推送 `batch_analysis_item` 事件 / 完整结果汇总），[`TasksPage.tsx`](../../stock_trading_system/web/frontend/src/islands/tasks/TasksPage.tsx) 已识别 `batch_analysis` 任务类型并在事件流中渲染。

但 **2 项前端入口仍未接通**：

1. **后端 API 路由缺失** —— `/api/batch/analyze` 路由从未实装；worker 注册了但前端无法触发提交（除非走 `/api/tasks/submit` 通用入口）。
2. **首页 gap-note 卡为占位 alert** —— [`HoldingsSection.tsx:111-137`](../../stock_trading_system/web/frontend/src/islands/dashboard/HoldingsSection.tsx) 当前是「产品缺口」黄边提示卡，点击只 `alert("产品缺口：批量分析持仓尚未接入前端入口")`，不是真实触发。

[mobile-ui-v1.3.md](mobile-ui-v1.3.md) R-MUI-02 已把 gap-note 卡放在首页持仓明细上方作为占位，本期把占位换成**真实可用入口**。

### 14.2 修法

#### 14.2.1 后端：新增 `POST /api/batch/analyze` 路由（[`web/app.py`](../../stock_trading_system/web/app.py)，仿照 [`/api/analyze`](../../stock_trading_system/web/app.py#L1603) pattern）

```python
@app.route("/api/batch/analyze", methods=["POST"])
def api_batch_analyze():
    """提交批量持仓分析任务。

    Body (all optional):
        skip_recent_hours: int = 4   # 跳过最近 N 小时已分析的 ticker
        date: str = today            # YYYY-MM-DD
    Returns:
        {task_id, status: "queued", total_holdings, will_skip, will_analyze}
        无持仓时返回 400 {reason: "no_holdings"}
    """
    if g.user is None:
        return jsonify({"error": "unauthorized"}), 401
    data = request.get_json(silent=True) or {}
    skip_hours = int(data.get("skip_recent_hours", 4))
    date = data.get("date") or _today_str()

    # 预检:用户当前持仓
    pm = _get_portfolio_for_user(g.user.id)  # 用现有 helper
    holdings = pm.get_holdings()
    tickers = [h["ticker"] for h in holdings if h.get("shares", 0) > 0]
    if not tickers:
        return jsonify({"reason": "no_holdings",
                        "message": "暂无持仓,请先添加持仓"}), 400

    tm = _get_task_manager()
    task = tm.submit(
        task_type="batch_analysis",
        params={
            "skip_recent_hours": skip_hours,
            "date": date,
            "__user_id__": g.user.id,
        },
        title=f"批量分析持仓 · {len(tickers)} 只",
        created_by=g.user.id,
    )
    return jsonify({
        "task_id": task["id"],
        "status": "queued",
        "total_holdings": len(tickers),
    })
```

**关键约束**：
- 必须登录（与 `/api/analyze` 一致）
- 多租户：用户只能批量分析**自己的**持仓（`g.user.id` 走 `_get_portfolio_for_user`，多租户隔离自动生效）
- 持仓为空时返回 400 而非空跑任务（避免任务中心被无效任务污染）

#### 14.2.2 前端：替换 [`HoldingsSection.tsx`](../../stock_trading_system/web/frontend/src/islands/dashboard/HoldingsSection.tsx) gap-note 卡为真实触发卡

视觉保留黄边 hero accent（仍然标识"重要操作"），删 `Badge variant="outline">产品缺口</Badge>` + 文案改"批量复核所有持仓的最新 AI 观点"：

```tsx
function BatchAnalyzeHoldingsCard({ holdingsCount }: { holdingsCount: number }) {
  const [busy, setBusy] = useState(false)
  const disabled = holdingsCount === 0 || busy

  async function onSubmit() {
    if (disabled) return
    if (!confirm(`确认批量分析当前 ${holdingsCount} 只持仓?\n\n跳过最近 4 小时已分析的 ticker,逐只顺序执行,预计耗时 5-30 分钟。可在任务中心查看进度。`)) return
    setBusy(true)
    try {
      const res = await apiPost<{ task_id: string; total_holdings: number }>(
        "/api/batch/analyze", { skip_recent_hours: 4 },
      )
      toast.success(`已提交批量分析任务（${res.total_holdings} 只持仓）`, {
        action: { label: "查看任务", onClick: () => location.href = `/tasks?focus=${res.task_id}` },
      })
    } catch (e: any) {
      if (e?.body?.reason === "no_holdings") {
        toast.error("暂无持仓,请先添加持仓")
      } else {
        toast.error("提交失败")
      }
    } finally {
      setBusy(false)
    }
  }

  return (
    <Card className="border-[var(--color-accent-yellow)]/40 bg-[var(--color-accent-yellow)]/5">
      <CardContent className="pt-4 space-y-2">
        <div className="flex items-center justify-between gap-2 min-w-0">
          <strong className="text-sm truncate flex items-center gap-1.5">
            <Sparkles className="h-3.5 w-3.5 text-[var(--color-accent-yellow)]" />
            批量分析持仓
          </strong>
          <span className="text-[10px] text-muted-foreground shrink-0">复用 batch_analysis</span>
        </div>
        <p className="text-xs text-muted-foreground break-words">
          一键复核所有持仓的最新 AI 观点。跳过最近 4 小时已分析的 ticker，逐只顺序执行，预计耗时 5-30 分钟。
        </p>
        <div className="flex flex-wrap gap-2 pt-1">
          <Button variant="default" size="sm" onClick={onSubmit} disabled={disabled} data-batch-analyze-trigger>
            {busy ? "提交中..." : holdingsCount === 0 ? "暂无持仓" : `批量分析持仓 (${holdingsCount})`}
          </Button>
          <Button variant="ghost" size="sm" onClick={() => location.href = "/tasks?type=batch_analysis"}>
            查看历史批次
          </Button>
        </div>
      </CardContent>
    </Card>
  )
}
```

**关键点**：
- `holdingsCount === 0` → 按钮 disabled + 文案变 "暂无持仓"（避免提交后 400）
- 提交前 `confirm()` 二次确认（成本 + 时长提示，避免误点）
- 成功后 toast `action: 查看任务` 一键跳转
- `disabled` 与 `busy` 双重防护，防重复点击
- `data-batch-analyze-trigger` 锚点供 Playwright 测试用
- 视觉沿用现有黄边 hero accent，但**移除"产品缺口"badge**（不再是占位）
- 头部加 `<Sparkles>` icon 强化"AI 操作"语义

#### 14.2.3 调用方更新

[`HoldingsSection`](../../stock_trading_system/web/frontend/src/islands/dashboard/HoldingsSection.tsx) 在 render 里把原 gap-note 卡（line 111-137）替换为：

```tsx
<BatchAnalyzeHoldingsCard holdingsCount={holdings.length} />
```

### 14.3 严格不动

- `make_batch_analysis_worker` 内部实现（worker 完全不动）
- `_emit_batch_item` / `batch_analysis_item` 事件 envelope
- `tasks/workers.py` 注册链（`tm.register("batch_analysis", ...)` 已就位）
- [`TasksPage.tsx`](../../stock_trading_system/web/frontend/src/islands/tasks/TasksPage.tsx) 任务渲染逻辑（已识别 batch_analysis type）
- `/api/analyze` 单只分析路径
- 多租户边界（[v1.18 R-fix-12](analysis-inbox.md)）
- 邀请码 / 登录 / OAuth
- HoldingsSection 其余部分（搜索 / 5↔ 全部 / 持仓卡）

### 14.4 测试

后端 `tests/web/test_api_batch_analyze.py`（4 case）：
1. 未登录 → 401
2. 持仓为空 → 400 reason=`no_holdings`
3. 有 3 只持仓 → 200 + task_id + total_holdings=3 + 任务在 TaskManager 队列中
4. 跨用户隔离：alice 提交后任务 created_by=alice.id，bob 看不到

前端 `tests/frontend/dashboard/batch-analyze-card.test.tsx`（5 case）：
1. holdingsCount=0 → 按钮 disabled + 文案 "暂无持仓"
2. holdingsCount=3 → 按钮可点 + 文案 "批量分析持仓 (3)"
3. 点击 → confirm 弹窗 → 取消则不调 API
4. confirm 后 mock fetch 200 → toast.success + action 链接含 task_id
5. mock fetch 400 reason=no_holdings → toast.error 文案 "暂无持仓"

### 14.5 实施顺序

1. 后端 `/api/batch/analyze` 路由 + 4 单测 (~30min)
2. 前端 `<BatchAnalyzeHoldingsCard>` 组件 + 5 vitest case (~45min)
3. 替换 HoldingsSection 旧卡片调用 (~5min)
4. 手动 E2E：dashboard 点按钮 → 确认 → 跳任务中心看到运行中批次任务 (~10min)

**约 ~1.5h 实装 ~150 LOC**（后端 50 / 前端 80 / 测试 40-50 LOC，纯增量，0 schema / 0 worker 改动）。

---

*v1.1 frontend entry patch 设计稿 — 等待确认后开始实施*
