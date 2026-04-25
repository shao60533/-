# 架构升级方案 — Qwen 主导数据层 + TradingView 图表组件 + 异步任务系统

> **版本**: 1.1  
> **日期**: 2026-04-15  
> **状态**: 草稿 — 待评审  
> **依据**: 用户需求 "数据全面从 Qwen API 获取（含回测/实时行情），K 线图用 TradingView 数据，长任务异步化且产品留痕留记录"

---

## 〇、先说结论

### 0.1 对用户需求的两处修正

1. **"回测数据从 Qwen 获取" — 风险高，建议用 yfinance 拉取 + 本地缓存**。  
   回测需要每根 bar 的价格都精确（否则策略评估完全失真）。Qwen 即使能返回日线 JSON，单价错 1% 就会让回测结果跑偏。这不是 LLM 的能力缺陷，而是"生成式模型"与"精确数据库"的本质差异。**日线级单点查询（当日价）Qwen 完全可做**，但批量历史回测不建议。
2. **"TradingView 给 K 线数据" — 理解需澄清**。TradingView 不提供免费数据 API，但它有三种使用方式：
   - **Advanced Chart Widget**（嵌入式图表，TV 提供完整数据 + 专业 UI，**本方案推荐**）
   - **Lightweight Charts**（开源图表库，数据仍需自供）
   - **Charting Library**（商业授权）

### 0.2 修正后的数据来源矩阵

| 场景 | 数据来源 | 理由 |
|------|---------|------|
| 实时单点价格 | **Qwen（主）** + yfinance/AkShare（兜底） | Qwen 单点报价延迟 3-8s，有兜底；符合"全面 Qwen"意图 |
| 历史 K 线（图表展示） | **TradingView Widget**（直接嵌入） | TV 自带全球行情数据，零数据成本，K 线体验专业 |
| 历史 K 线（回测用） | **yfinance / AkShare** 拉取，本地缓存 | 需精确数据；免费且稳定 |
| 回测策略执行 | **本地 Python 计算**（backtester.py） | 业界标准做法，与数据源解耦 |
| 基本面数据 | **Qwen（主）** + yfinance（兜底） | Qwen web search 可返回最新基本面，需校验 |
| 新闻 | **Qwen（主）** | Qwen 搜索 + 摘要是其强项 |
| 选股打分 | **Qwen（保持现有）** | 现有实现已经合理 |
| AI 分析 | **Qwen（保持现有）** | 现有实现已经合理 |

**核心原则**：**LLM 做语义/判断类任务，精确大批量结构化数据用专业 API**。

### 0.3 性能与留痕原则（本次新增）

> 来源：用户要求"注意性能，长时间任务做成异步任务，产品留痕留记录"

| 原则 | 具体做法 |
|------|---------|
| **所有 >2s 的操作必须异步** | 不阻塞 HTTP 请求，立即返回 `task_id`，结果通过 WebSocket 推送 |
| **所有异步任务必须入库** | `tasks` 表记录全生命周期（pending/running/success/failed/cancelled） |
| **用户端可查看任务历史** | 新增"任务中心"页面，展示任务列表 + 状态 + 结果 + 重试 |
| **结果持久化** | 任务结果写入专用表（analysis / screen / backtest 等），可回看 |
| **非实时数据使用缓存** | 同一 ticker 短时间内复用结果，减少 Qwen 调用 |
| **幂等与重试** | 任务失败可一键重试，重复提交同一参数会返回已有任务 |

---

## 一、当前架构盘点

### 1.1 现有数据源路由

```
US 股票价格:  IB → Polygon → yfinance → Qwen(last resort)
A 股价格:     AkShare → Qwen(last resort)
历史数据:     IB → Polygon → yfinance (不含 Qwen)
基本面:       yfinance → IB (不含 Qwen)
新闻:         Polygon → yfinance (不含 Qwen)
选股:         IB Scanner + finviz + Qwen AI rerank
```

### 1.2 痛点分析

| 问题 | 现状 | 影响 |
|------|------|------|
| IB TWS 依赖本地进程 | 需要 TWS/Gateway 在本机运行 | 云端部署 (Railway) 无法使用 |
| Polygon 免费层限流 | 429 Rate Limit 频繁触发 | 当前代码已经默认 skip Polygon |
| yfinance 海外访问不稳 | A 股完全不支持，且易被限 | 依赖多个源的维护成本高 |
| AkShare 在海外节点 | Railway 东亚节点能否访问未验证 | 部署后 A 股可能失效 |
| **维护负担** | 5 个 Provider 的兼容代码 | 任何一个 API 变更都要改代码 |

### 1.3 Qwen Provider 现状

- ✅ 已实现：`get_stock_price()` 单点报价 + `screen_stocks()` AI 打分
- ✅ 已启用 DashScope `enable_search` 实时联网
- ✅ 已用 `response_format: json_object` 强制 JSON 输出
- ❌ 未覆盖：历史数据、基本面、新闻
- ⚠️ 仅作"last resort"，非主力

---

## 二、升级目标

### 2.1 核心目标

| 目标 | 衡量标准 |
|------|---------|
| **简化依赖** | 去掉 IB TWS 和 Polygon 的强依赖（保留 yfinance/AkShare 作兜底） |
| **云端友好** | Railway 一键部署可用，无需本地进程 |
| **Qwen 主力化** | 价格/基本面/新闻默认走 Qwen，失败再兜底 |
| **K 线专业化** | 替换自渲染 ECharts candlestick 为 TradingView Widget |
| **回测可靠** | 回测用本地历史数据 + 本地策略引擎，结果可复现 |

### 2.2 非目标

- **不**让 LLM 返回海量历史 OHLCV 数据
- **不**放弃 yfinance/AkShare（它们是兜底，不是主力）
- **不**引入付费图表授权（用免费的 TradingView Widget）

---

## 三、新架构总览

```
┌────────────────────────────────────────────────────────────────┐
│                      浏览器 SPA                                 │
│  ┌─────────────────────────────────────────────────────────┐  │
│  │  TradingView Widget (K 线展示)                            │  │
│  │  ECharts (净值/饼图/回测权益)                              │  │
│  │  任务中心页（任务历史列表 + 状态 + 重试 + 结果回看）        │  │
│  └─────────────────────────────────────────────────────────┘  │
└──────────┬──────────────────────────────────┬─────────────────┘
           │ HTTP REST                        │ WebSocket
┌──────────▼──────────────────────────────────▼─────────────────┐
│                   Flask + Socket.IO                            │
│  ┌───────────────────────────────────────────────────────┐   │
│  │  TaskManager (新) — 异步任务调度与留痕                   │   │
│  │    ├─ 提交任务 → 返回 task_id（非阻塞）                  │   │
│  │    ├─ 后台执行 → 定时推送 progress 事件                  │   │
│  │    ├─ 完成 → 写入 tasks 表 + 结果表 + 推送完成事件        │   │
│  │    └─ 失败 → 写入错误 + 推送错误事件 + 可重试             │   │
│  └────────────┬──────────────────────────────────────────┘   │
│               │                                                │
│  ┌────────────▼──────────────────────────────────────────┐   │
│  │          DataRouter — 统一数据路由层                      │   │
│  │  根据 feature flag 决定主源与兜底顺序 + 缓存层            │   │
│  └──┬────────┬────────┬──────────┬──────────────────────┘   │
│     │        │        │          │                            │
│  ┌──▼──┐  ┌──▼──┐  ┌─▼──┐   ┌───▼───────┐                    │
│  │Qwen │  │yfin │  │AkSh│   │LocalCache │                    │
│  │(主) │  │兜底 │  │兜底│   │ SQLite    │                    │
│  └─────┘  └─────┘  └────┘   └───────────┘                    │
└────────────────────────────────────────────────────────────────┘
           │
┌──────────▼─────────────────────────────────────────────────────┐
│  Backtester (本地) — 读取 LocalCache，本地策略计算              │
│  Analyzer / Screener — 调用 Qwen，产出结果写结果表               │
└────────────────────────────────────────────────────────────────┘

         ┌───────────────────────────────────────┐
         │       SQLite 持久化层                    │
         ├───────────────────────────────────────┤
         │ tasks            ← 所有异步任务元数据    │
         │ analysis_history ← AI 分析结果           │
         │ screen_results   ← 选股结果              │
         │ backtest_results ← 回测结果              │
         │ bars_cache       ← 历史 K 线缓存         │
         │ fundamentals_cache ← 基本面缓存          │
         │ news_cache       ← 新闻缓存              │
         │ portfolio / alerts / snapshots ← 业务表  │
         └───────────────────────────────────────┘
```

### 3.1 三层数据策略

**Layer 1 — TradingView Widget（K 线展示）**  
前端直接嵌入 TV 的 Advanced Chart Widget，数据由 TV 负责，后端零参与。只做"展示"，不做"分析"。

**Layer 2 — Qwen LLM（主力语义 / 判断 / 单点查询）**  
- 实时价格（单点）
- 基本面指标（结构化 JSON 返回）
- 新闻摘要
- 选股打分
- AI 分析（已有）

**Layer 3 — 本地数据源 + 缓存（精确结构化数据）**  
- 回测历史数据：yfinance 拉取后缓存到 SQLite，避免重复拉取
- Qwen 失败时的兜底（yfinance/AkShare）
- 净值快照历史（本地 SQLite）

### 3.2 异步任务与留痕架构（新增）

所有耗时 >2 秒的操作（AI 分析、选股、回测、报告生成、慢速 Qwen 调用）都走统一的 **TaskManager**：

```
用户触发 → POST /api/tasks/<type>/submit
              ↓
         TaskManager.submit()
              ├─ 幂等检查（同一参数近 N 分钟已有任务则复用）
              ├─ 写入 tasks 表（status=pending）
              ├─ 返回 {task_id}
              └─ 派发到 Worker 线程池
                    ↓
              Worker 执行
                    ├─ 更新 status=running
                    ├─ 中途定时推送 WS 事件 task_progress
                    ├─ 成功 → 写结果表 + 更新 status=success
                    └─ 失败 → 写 error + 更新 status=failed

用户端：
  - 实时：WS 事件推送 → Toast + 页面自动渲染结果
  - 回看：任务中心页列表 → 点击查看详情
  - 重试：任一失败任务可一键重试，生成新 task_id 复用原参数
```

**用户体验**：
- 提交任务后可以关闭当前页面，稍后在"任务中心"回看结果
- 每个任务有唯一 ID 和可读性标题（如 "AAPL 分析 · 2026-04-15 14:32"）
- 失败任务保留错误详情和 stack trace（前端折叠显示）

---

## 四、详细设计

### 4.1 新增/修改的模块

| 模块 | 动作 | 说明 |
|------|------|------|
| `tasks/task_manager.py` | **新建** | 异步任务调度 + 留痕核心 |
| `tasks/task_store.py` | **新建** | 任务持久化（SQLite） |
| `tasks/workers.py` | **新建** | Worker 注册与执行（analysis/screen/backtest/report） |
| `data/qwen_provider.py` | **扩展** | 新增 `get_fundamentals()` / `get_news()` |
| `data/data_manager.py` | **重构** | 改为 `DataRouter`，按 feature flag 路由，默认 Qwen first |
| `data/local_cache.py` | **新建** | SQLite 缓存层：历史 bar、基本面快照、新闻 |
| `strategy/backtester.py` | **新建** | 本地回测引擎，读取 LocalCache |
| `web/templates/index.html` | **修改** | 嵌入 TradingView Widget + 新增任务中心页 |
| `web/static/js/app.js` | **修改** | TV Widget 初始化 + 任务中心逻辑 |
| `web/app.py` | **修改** | 接入 TaskManager，路由改为 submit/poll/result 模式 |
| `config/settings.py` | **扩展** | 新增 `data_routing` / `tasks` / `cache` 配置节 |

---

### 4.2 异步任务系统（TaskManager）

#### 4.2.1 任务类型清单

| 任务类型 | 来源 | 预估耗时 | 优先级 |
|----------|------|----------|--------|
| `analysis` | AI 分析（7 Agent） | 2-5 分钟 | P0 |
| `screen` | 三层选股 | 30 秒-2 分钟 | P0 |
| `backtest` | 策略回测 | 3-20 秒 | P1 |
| `report` | 报告生成（Markdown） | 5-30 秒 | P1 |
| `qwen_fundamentals` | 基本面查询（Qwen） | 3-8 秒 | P1 |
| `qwen_news` | 新闻查询（Qwen） | 3-8 秒 | P1 |
| `price_refresh_batch` | 批量价格刷新（持仓列表） | 视持仓数 | P2 |

> 注：单点价格查询（<2 秒）不走任务系统，保持同步接口。

#### 4.2.2 `tasks` 表设计

```sql
CREATE TABLE tasks (
    id TEXT PRIMARY KEY,              -- UUID
    type TEXT NOT NULL,               -- analysis|screen|backtest|report|...
    title TEXT NOT NULL,              -- 人类可读标题 "AAPL 分析"
    params_json TEXT NOT NULL,        -- 输入参数 JSON
    status TEXT NOT NULL,             -- pending|running|success|failed|cancelled
    progress INTEGER DEFAULT 0,       -- 0-100
    progress_step TEXT,               -- 当前步骤描述 "情绪分析中..."
    result_ref TEXT,                  -- 结果表外键：{table}:{id} 例 "analysis_history:42"
    error_message TEXT,               -- 简短错误信息
    error_trace TEXT,                 -- 完整 traceback
    created_at TIMESTAMP NOT NULL,
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    duration_ms INTEGER,
    retry_of TEXT,                    -- 重试时指向原 task_id
    params_hash TEXT,                 -- 参数指纹，幂等检查用
    created_by TEXT DEFAULT 'user'    -- user | scheduler | api
);

CREATE INDEX idx_tasks_status ON tasks(status);
CREATE INDEX idx_tasks_type_created ON tasks(type, created_at DESC);
CREATE INDEX idx_tasks_params_hash ON tasks(params_hash, status);
```

#### 4.2.3 TaskManager 接口

```python
# tasks/task_manager.py
class TaskManager:
    def __init__(self, config, socketio):
        self._store = TaskStore(config)
        self._socketio = socketio
        self._executor = ThreadPoolExecutor(
            max_workers=config.get("tasks", {}).get("max_workers", 3)
        )
        self._workers = {}   # type -> Worker callable
        self._running = {}   # task_id -> Future (for cancel)

    def register(self, task_type: str, worker_fn):
        """注册 worker 函数：fn(params, progress_cb) -> result_dict"""
        self._workers[task_type] = worker_fn

    def submit(self, task_type, params, title=None, idempotency_window=60) -> dict:
        """提交任务。幂等窗口内同参数返回已有任务。"""
        params_hash = _hash_params(task_type, params)
        # 幂等检查
        existing = self._store.find_recent_by_hash(
            params_hash, window_seconds=idempotency_window,
            statuses=("pending", "running", "success")
        )
        if existing:
            return existing

        task_id = str(uuid.uuid4())
        task = {
            "id": task_id,
            "type": task_type,
            "title": title or _gen_title(task_type, params),
            "params_json": json.dumps(params, ensure_ascii=False),
            "status": "pending",
            "params_hash": params_hash,
            "created_at": now_iso(),
        }
        self._store.insert(task)
        self._socketio.emit("task_created", task)

        # 提交到线程池
        future = self._executor.submit(self._run, task_id, task_type, params)
        self._running[task_id] = future
        return task

    def _run(self, task_id, task_type, params):
        worker = self._workers.get(task_type)
        if not worker:
            self._fail(task_id, f"Unknown task type: {task_type}", "")
            return

        self._store.update(task_id, status="running", started_at=now_iso())
        self._socketio.emit("task_started", {"id": task_id})

        def progress_cb(percent, step_desc=None, partial=None):
            self._store.update(task_id, progress=percent, progress_step=step_desc)
            self._socketio.emit("task_progress", {
                "id": task_id, "progress": percent,
                "step": step_desc, "partial": partial,
            })

        try:
            result = worker(params, progress_cb)
            # 结果写入对应业务表，tasks.result_ref 记录外键
            result_ref = self._store.save_result(task_type, task_id, result)
            self._store.update(
                task_id, status="success", progress=100,
                result_ref=result_ref,
                completed_at=now_iso(),
            )
            self._socketio.emit("task_completed", {
                "id": task_id, "result_ref": result_ref,
            })
        except Exception as e:
            self._fail(task_id, str(e), traceback.format_exc())
        finally:
            self._running.pop(task_id, None)

    def retry(self, original_task_id) -> dict:
        orig = self._store.get(original_task_id)
        if not orig:
            raise ValueError("Task not found")
        params = json.loads(orig["params_json"])
        new_task = self.submit(orig["type"], params,
                               title=f"{orig['title']} (重试)",
                               idempotency_window=0)  # 强制新建
        self._store.update(new_task["id"], retry_of=original_task_id)
        return new_task

    def cancel(self, task_id) -> bool:
        fut = self._running.get(task_id)
        if fut and fut.cancel():
            self._store.update(task_id, status="cancelled", completed_at=now_iso())
            return True
        return False

    def list(self, task_type=None, status=None, limit=50, offset=0) -> list:
        return self._store.list(task_type, status, limit, offset)

    def get(self, task_id) -> dict | None:
        return self._store.get(task_id)

    def get_result(self, task_id) -> dict | None:
        """根据 result_ref 从业务表拉完整结果"""
        task = self._store.get(task_id)
        if not task or not task.get("result_ref"):
            return None
        return self._store.load_result(task["result_ref"])
```

#### 4.2.4 Worker 示例

```python
# tasks/workers.py
def analysis_worker(params, progress_cb):
    ticker = params["ticker"]
    date = params.get("date") or today_str()

    progress_cb(5, "初始化分析管线")
    analyzer = get_analyzer()

    # StockAnalyzer.analyze 内部有 7 个 Agent，需要改造支持 progress_cb 回调
    result = analyzer.analyze(ticker, date, progress_cb=progress_cb)

    progress_cb(95, "生成策略建议")
    advice = get_strategy_engine().generate_advice(result, ...)

    progress_cb(100, "完成")
    return {
        "ticker": ticker, "date": date,
        "signal": result.signal,
        "market_report": result.market_report,
        # ... 其他字段
        "advice": advice_to_dict(advice),
    }

# 注册
task_manager.register("analysis", analysis_worker)
task_manager.register("screen", screen_worker)
task_manager.register("backtest", backtest_worker)
task_manager.register("report", report_worker)
```

#### 4.2.5 统一 HTTP API

```
POST   /api/tasks/submit           提交任务
       Body: {type, params, title?}
       返回: {id, status, title, ...}

GET    /api/tasks                  列出任务（分页 + 筛选）
       Query: ?type=&status=&limit=50&offset=0

GET    /api/tasks/<id>             任务详情（含 params / error）

GET    /api/tasks/<id>/result      结果详情（跳转业务表）

POST   /api/tasks/<id>/retry       重试任务

POST   /api/tasks/<id>/cancel      取消任务（仅 pending/running 可取消）

DELETE /api/tasks/<id>             删除任务记录（不删结果）
```

#### 4.2.6 WebSocket 事件统一

| 事件名 | 数据 | 时机 |
|--------|------|------|
| `task_created` | `{id, type, title, params_json, ...}` | 提交成功 |
| `task_started` | `{id}` | Worker 开始执行 |
| `task_progress` | `{id, progress, step, partial?}` | 中途进度更新 |
| `task_completed` | `{id, result_ref}` | 执行成功 |
| `task_failed` | `{id, error_message}` | 执行失败 |
| `task_cancelled` | `{id}` | 被取消 |

> **迁移**：原先的 `analysis_status` / `analysis_result` / `analysis_error` / `screen_status` 等事件统一替换为上表 6 个事件。前端用 `type` 字段区分业务类型。

#### 4.2.7 任务中心页面设计

新增第 10 个页面 **"任务中心"** (`page-tasks`)，入口放在移动端"更多" Sheet 和桌面侧边栏最下方。

```
┌─────────────────────────────────────────────────────┐
│  任务中心                                            │
│  ┌───┐ ┌──────┐ ┌────┐ ┌────┐ ┌────┐               │
│  │全部│ │运行中│ │成功│ │失败│ │取消│               │
│  └───┘ └──────┘ └────┘ └────┘ └────┘               │
├─────────────────────────────────────────────────────┤
│  🧠 AAPL 分析                  running · 45%         │
│     2026-04-15 14:32 · 已执行 1m 23s                 │
│     当前步骤: 情绪分析中...                           │
│     [查看详情] [取消]                                │
├─────────────────────────────────────────────────────┤
│  🔍 美股成长股筛选              success              │
│     2026-04-15 14:15 · 耗时 47s · 返回 8 只          │
│     [查看结果] [重新运行]                             │
├─────────────────────────────────────────────────────┤
│  🧪 SMA 交叉回测 AAPL           failed               │
│     2026-04-15 13:55 · 错误：数据不足                 │
│     [查看详情] [重试]                                │
└─────────────────────────────────────────────────────┘
```

**功能点**：
- 状态 pill 过滤（全部 / 运行中 / 成功 / 失败 / 已取消）
- 按时间倒序，支持加载更多（分页）
- 运行中任务实时更新进度条（订阅 `task_progress`）
- 点击"查看详情"：展示 params + error_trace（失败时）+ 结果预览
- 点击"查看结果"：跳转到对应业务页（分析记录 / 选股结果 / 回测页）
- 点击"重试"：创建新任务，保留 `retry_of` 关联原任务

---

### 4.3 缓存策略（新增）

性能优化的核心是**避免重复调用 Qwen**。规则：

| 数据类型 | 缓存 key | TTL | 命中率目标 |
|----------|---------|-----|----------|
| 实时价格（Qwen） | `(ticker, market)` | 60 秒 | >80% |
| 基本面（Qwen） | `ticker` | 24 小时 | >90% |
| 新闻（Qwen） | `ticker` | 1 小时 | >70% |
| 日线 K 线（yfinance） | `(ticker, period, interval)` | 12 小时 | >95% |
| 分钟线 K 线（yfinance） | `(ticker, period, interval)` | 5 分钟 | — |
| AI 分析结果 | 持久化（不 TTL） | 永久 | — |
| 选股结果 | `(market, strategy)` | 1 小时 | >60% |
| 回测结果 | `(ticker, strategy_id, period, initial_capital, params_hash)` | 永久 | — |

**实现方式**：
- 快速缓存（60 秒级）：进程内 LRU 字典
- 持久化缓存（分钟/小时级）：SQLite 表 `*_cache` + `fetched_at` 字段
- 缓存失效：后台任务定期清理过期记录（每 6 小时一次）

**性能收益预估**：
- 持仓刷新（10 只股票）：从 30-80 秒降至 <1 秒（缓存命中时）
- 仪表盘打开：从 15-40 秒降至 <2 秒（基于快照 + 价格缓存）

### 4.4 Qwen Provider 扩展

#### 4.4.1 `get_fundamentals(ticker) → dict | None`

```python
_FUNDAMENTALS_SYSTEM = (
    "You are a financial data service. Given a ticker, use web search to find "
    "the latest fundamental indicators from Yahoo Finance / East Money / "
    "exchange filings. Respond with ONLY JSON. Schema: "
    '{"ticker":"<upper>","market_cap":<number|null>,'
    '"pe_ratio":<number|null>,"pb_ratio":<number|null>,'
    '"roe":<number|null>,"gross_margin":<number|null>,'
    '"net_margin":<number|null>,"revenue_growth":<number|null>,'
    '"dividend_yield":<number|null>,"beta":<number|null>,'
    '"week_52_high":<number|null>,"week_52_low":<number|null>,'
    '"eps":<number|null>,"as_of":"<date>","source":"<url>"}'
)
```

**风险**：LLM 可能对小盘股 / A 股返回错误数字。缓解：
- 置信度字段：让模型返回 `"confidence": "high|medium|low"`
- 前端显示数据源（"by Qwen · 数据仅供参考"）
- 关键数字（PE/ROE）加合理性检验（PE 在 -1000~1000 范围内）

#### 4.4.2 `get_news(ticker, limit=10) → list[dict]`

```python
_NEWS_SYSTEM = (
    "You are a financial news service. Given a ticker, use web search to find "
    "the most recent news (last 7 days) from Reuters / Bloomberg / Sina / "
    "East Money. Return ONLY JSON. Schema: "
    '{"news":[{"title":"<string>","url":"<url>","date":"<ISO>",'
    '"source":"<site>","summary":"<one-sentence>"}]}'
)
```

**优势**：Qwen 的搜索 + 摘要比原 yfinance 新闻更相关、有中文支持。

#### 4.4.3 关于 `get_history()` — 不内置，改由 yfinance 承担

Qwen 理论上能通过 web search 返回日线 OHLCV JSON，但用于回测有实质风险：

- **精度风险**：回测需每根 bar 价格精确，单价偏差 1% 会让策略评估结论反转
- **可复现风险**：同一 prompt 多次调用结果可能不同，破坏"历史回测"的科学性
- **成本**：每次回测输出 10K+ tokens（约 ¥0.2-0.5），高频回测不划算
- **延迟**：20-60 秒单次，与本地 yfinance 拉取 + 缓存（首次 2-3 秒，后续 <100ms）差距大

**决策**：
- **图表展示**：用 TradingView Widget（TV 负责数据）
- **回测**：用 yfinance 拉取 + LocalCache 缓存
- **单点日线查询**（如"AAPL 2026-04-10 的收盘价"）：可走 Qwen，属于单点场景，不属于"批量历史数据"

### 4.5 DataRouter 重构

```python
# data/data_manager.py (重构后)

class DataRouter:
    """Routing layer with configurable primary/fallback order."""

    def __init__(self, config: dict):
        self._config = config
        routing = config.get("data_routing", {})
        self._primary = routing.get("primary", "qwen")  # qwen | local
        self._enable_cache = routing.get("enable_cache", True)

        self._qwen = QwenProvider(config)
        self._yfinance = YFinanceProvider()
        self._akshare = AkShareProvider()
        self._cache = LocalCache(config) if self._enable_cache else None

    def get_price(self, ticker: str) -> dict | None:
        """Qwen-first routing with local fallback."""
        market = detect_market(ticker)

        # Primary: Qwen (if enabled and primary)
        if self._primary == "qwen" and self._qwen.enabled:
            result = self._qwen.get_stock_price(ticker)
            if result:
                return result
            logger.info("Qwen price failed for %s, falling back", ticker)

        # Fallback: yfinance / AkShare
        if market == "cn":
            return self._akshare.get_stock_price(ticker)
        return self._yfinance.get_stock_price(ticker)

    def get_fundamentals(self, ticker: str) -> dict | None:
        """Qwen-first with yfinance fallback + validation."""
        if self._primary == "qwen" and self._qwen.enabled:
            result = self._qwen.get_fundamentals(ticker)
            if result and _validate_fundamentals(result):
                return result
        # Fallback
        if detect_market(ticker) == "cn":
            return self._akshare.get_fundamentals(ticker)
        return self._yfinance.get_fundamentals(ticker)

    def get_history_for_backtest(
        self, ticker: str, period: str, interval: str
    ) -> pd.DataFrame:
        """History data for backtest — uses local cache, never Qwen."""
        if self._cache:
            cached = self._cache.get_bars(ticker, period, interval)
            if cached is not None:
                return cached
        # Fetch from yfinance/AkShare
        market = detect_market(ticker)
        df = (self._akshare if market == "cn" else self._yfinance)\
            .get_stock_history(ticker, period=period, interval=interval)
        if df is not None and self._cache:
            self._cache.save_bars(ticker, period, interval, df)
        return df
```

**关键点**：`get_history_for_backtest()` **拒绝调用 Qwen**，理由见 4.2.3。

### 4.6 LocalCache（新建）

SQLite 表设计：

```sql
CREATE TABLE bars_cache (
    ticker TEXT,
    period TEXT,
    interval TEXT,
    fetched_at TIMESTAMP,
    payload BLOB,  -- pickle 或 parquet 格式的 DataFrame
    PRIMARY KEY (ticker, period, interval)
);

CREATE TABLE fundamentals_cache (
    ticker TEXT PRIMARY KEY,
    fetched_at TIMESTAMP,
    payload TEXT  -- JSON
);
```

**TTL 策略**：
- 日线 bar：12 小时
- 分钟线 bar：5 分钟
- 基本面：24 小时
- 新闻：1 小时

### 4.7 TradingView Widget 集成

#### 4.7.1 嵌入方案

使用 TV 官方免费的 **Advanced Chart Widget**（JavaScript 嵌入，不需要申请）。

```html
<!-- 替换现有 <div id="chart-kline"> -->
<div id="tv-chart-container"></div>

<script>
function mountTradingViewChart(symbol) {
    // 清空容器
    const container = document.getElementById('tv-chart-container');
    container.innerHTML = '';

    // 符号格式转换：AAPL -> NASDAQ:AAPL; 600519 -> SSE:600519
    const tvSymbol = toTVSymbol(symbol);

    new TradingView.widget({
        container_id: 'tv-chart-container',
        symbol: tvSymbol,
        interval: 'D',
        theme: 'dark',
        style: '1',
        locale: 'zh_CN',
        toolbar_bg: '#0d1117',
        enable_publishing: false,
        hide_side_toolbar: false,
        allow_symbol_change: true,
        studies: [
            'MASimple@tv-basicstudies',  // MA 均线
            'Volume@tv-basicstudies'      // 成交量
        ],
        autosize: true,
    });
}

function toTVSymbol(ticker) {
    // A 股 6 位数字 → SSE/SZSE 前缀
    if (/^6\d{5}$/.test(ticker)) return 'SSE:' + ticker;
    if (/^[03]\d{5}$/.test(ticker)) return 'SZSE:' + ticker;
    // 美股：默认 NASDAQ，常见 NYSE 股票可白名单
    const nyseList = ['JPM','BAC','GS','MS','C','WFC','BRK.B','PFE','KO','MCD'];
    if (nyseList.includes(ticker)) return 'NYSE:' + ticker;
    return 'NASDAQ:' + ticker;
}
</script>
<script src="https://s3.tradingview.com/tv.js"></script>
```

#### 4.7.2 优劣对比

| 维度 | 现方案 (ECharts candlestick) | 新方案 (TV Widget) |
|------|------------------------------|--------------------|
| 数据获取 | 后端 `/api/chart/<ticker>` 返回 OHLCV | TV 自带全球数据 |
| 数据成本 | 依赖 yfinance | **零成本** |
| K 线质量 | 基础 | 专业（画线、指标、比较、多时间框） |
| 移动端手势 | 一般 | 优秀（TV 多年优化） |
| 移动端资源占用 | 小 | 较大（Widget 约 300KB） |
| 主题定制 | 完全可控 | 有限（dark/light 切换） |
| 离线支持 | 可做 | 不可（需联网加载 iframe） |
| 法律授权 | — | Widget 免费但需保留署名 |

#### 4.7.3 保留 ECharts 的场景

TV Widget **只替换 K 线**。以下仍用 ECharts：
- 仪表盘净值曲线（数据是我们自己的持仓快照，TV 无此数据）
- 仓位饼图
- 回测权益曲线（回测结果是我们本地算出来的，TV 无法展示）

### 4.8 回测引擎（新建 `strategy/backtester.py`）

**数据流**：

```
用户选 ticker + 策略 + 时间范围
    ↓
DataRouter.get_history_for_backtest()  ← 从 LocalCache 或 yfinance
    ↓
Backtester.run(strategy_id, data, params)  ← 本地 Python 计算
    ↓
BacktestResult { equity_curve, trades, metrics }
    ↓
前端渲染 ECharts 权益曲线 + 交易明细表
```

**为什么不让 Qwen 做回测**：
- 回测需要遍历每根 bar，逐根判断信号
- 需要精确价格才能算出正确的 P&L
- 策略逻辑应该可审计、可复现（LLM 每次跑结果可能不同）
- 本地 numpy/pandas 计算成本几乎为零

**Qwen 可以辅助的点**：
- **策略描述转代码**（一次性，不是每次回测）：用户描述"均线上穿买入，跌破 MA60 卖出" → LLM 生成策略代码
- **回测结果解读**：回测完成后，用户点"分析这个结果"，LLM 给出文字解读

### 4.9 配置文件扩展

```yaml
# config.yaml
qwen:
  enabled: true
  api_key: "sk-xxx"
  model: "qwen-plus"
  use_for_price: true         # 实时价格主源
  use_for_fundamentals: true  # 基本面主源
  use_for_news: true          # 新闻主源

data_routing:
  primary: "qwen"             # qwen | local
  enable_cache: true
  cache_ttl:
    price_quote: 60           # 60s 单点价格
    daily_bars: 43200         # 12h
    minute_bars: 300          # 5min
    fundamentals: 86400       # 24h
    news: 3600                # 1h
    screen_results: 3600      # 1h

tasks:
  max_workers: 3              # 并发 Worker 数
  idempotency_window: 60      # 同参数任务复用窗口（秒）
  retention_days: 30          # 任务记录保留天数
  cleanup_interval: 21600     # 清理过期任务间隔（6h）

# 可以彻底禁用的 provider（云端部署时）
providers:
  ib_enabled: false
  polygon_enabled: false
  # yfinance 和 akshare 作为兜底始终启用
```

---

## 五、前端改造

### 5.1 HTML 改动

移除 `#chart-kline` 容器的 ECharts 逻辑，改为：

```html
<!-- index.html AI 分析页 -->
<div class="card mb-3" id="quick-chart-card" style="display:none;">
  <div class="card-header">
    <i class="fab fa-tradingview"></i>
    <span id="quick-chart-ticker"></span> · TradingView
  </div>
  <div class="card-body p-0">
    <!-- TV Widget 自动填充，移除我们的 range-switcher 按钮组（TV 自带） -->
    <div id="tv-chart-container" style="height:500px;"></div>
  </div>
</div>
```

### 5.2 JS 改动

- 删除 `renderKlineChart()` / `loadChart()` / `loadChartRange()` 及相关状态变量
- 新增 `mountTradingViewChart(ticker)` 函数
- 在 `loadQuickData(ticker)` 中调用 `mountTradingViewChart()`

### 5.3 依赖变更

| 动作 | 内容 |
|------|------|
| 新增 | `<script src="https://s3.tradingview.com/tv.js"></script>`（免费 CDN） |
| 保留 | ECharts（仪表盘/回测曲线/饼图仍需） |
| 保留 | marked.js（Markdown 渲染） |

---

## 六、风险与缓解

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|----------|
| Qwen 返回的基本面数据不准 | 中 | 中 | 加合理性校验 + UI 标注"仅供参考 · 由 Qwen 提供" + yfinance 兜底 |
| Qwen 单次调用延迟 3-8s | 中 | 中 | **走任务系统异步化** + 缓存（60s 价格、24h 基本面） |
| Qwen token 成本飙升 | 中 | 中 | 缓存命中率监控 + 配置层限速（每分钟 N 次） + 任务幂等复用 |
| TV Widget 在国内加载慢 | 中 | 中 | 备选本地 Lightweight Charts 方案（配置开关切换） |
| TV Widget 数据与系统其他数据不一致 | 低 | 低 | UI 说明"图表来自 TradingView，报价来自 Qwen" |
| A 股 ticker 在 TV 上支持有限 | 中 | 中 | TV 支持 SSE/SZSE 主板，小盘/ST 股可能缺失；缺失时 fallback 到 ECharts candlestick |
| yfinance 海外节点被限 | 中 | 高 | LocalCache 命中率优先；必要时增加 Qwen 临时兜底（仅日线单点） |
| **任务堆积导致线程池饱和** | 中 | 中 | `max_workers` 可配置；新任务排队不丢失 |
| **Railway 容器重启丢失任务状态** | 中 | 中 | 重启时扫描 `status=running` 的任务标记为 `failed: "服务中断"`，可重试 |
| **SQLite 并发写入冲突** | 低 | 低 | 任务写入加互斥锁；高并发场景可迁移到 WAL 模式 |

---

## 七、实施分阶段

### Phase A — 任务系统 + 缓存基础（最重要）

**先做这块**，因为后续数据层改造的性能表现都依赖它。

| 步骤 | 内容 | 验收 |
|------|------|------|
| A.1 | 新建 `tasks/task_store.py` — `tasks` 表 + CRUD | 单元测试：插入/更新/查询/幂等 |
| A.2 | 新建 `tasks/task_manager.py` — 线程池 + Worker 注册 + WS 推送 | 测试任务能被提交、执行、写入 |
| A.3 | 新建 `data/local_cache.py` — 通用 SQLite 缓存（price/fund/news/bars） | TTL 正确、读写幂等 |
| A.4 | 新增 `/api/tasks/*` REST API | Postman 测试 6 个端点 |
| A.5 | 前端新增"任务中心"页 + WS 事件处理 | 提交任务后可看到实时进度 |

### Phase B — 数据层迁移到 Qwen 主源

| 步骤 | 内容 | 验收 |
|------|------|------|
| B.1 | 扩展 `QwenProvider`：`get_fundamentals` / `get_news` | 单只股票测试返回有效 JSON |
| B.2 | 重构 `DataManager` → `DataRouter`，引入 `primary` 开关 + 缓存层 | 配置切换后 provider 路由正确 |
| B.3 | 为基本面/新闻加合理性校验 | 无效数据被拒绝 |
| B.4 | 将现有 `analyze`、`screen` 路由改为走 TaskManager | 原有事件名迁移到 `task_*` |

### Phase C — K 线组件替换

| 步骤 | 内容 | 验收 |
|------|------|------|
| C.1 | 前端集成 TradingView Widget | AAPL / 600519 / TSLA 图表加载正确 |
| C.2 | 实现 `toTVSymbol()` 符号映射函数 | 美股/A 股符号自动前缀 |
| C.3 | 分析页切换到 TV Widget | 原 K 线相关前端代码清理 |
| C.4 | 缺失股票降级逻辑（回退 ECharts candlestick） | 小盘股不可用时不白屏 |

### Phase D — 回测引擎

| 步骤 | 内容 | 验收 |
|------|------|------|
| D.1 | 新建 `strategy/backtester.py`（SMA/RSI/买入持有 3 策略） | 本地单元测试通过 |
| D.2 | 接入 LocalCache 作为历史数据源 | 重复回测命中缓存 |
| D.3 | 注册 `backtest` Worker；前端走任务系统提交 | 回测通过任务中心可见 |
| D.4 | 回测结果写 `backtest_results` 表 + 前端 ECharts 渲染 | UI 显示指标 + 曲线 + 明细表 |

### Phase E — 云端部署优化

| 步骤 | 内容 | 验收 |
|------|------|------|
| E.1 | 默认禁用 IB / Polygon（配置层） | Railway 部署无报错 |
| E.2 | 验证 Qwen + yfinance 在 Railway 的可用性 | 首页可显示实时数据 |
| E.3 | AkShare 在海外节点测试 | A 股功能状态确认 |
| E.4 | 任务保留期清理定时任务 | 过期任务自动清理 |

---

## 八、关键技术决策

### 8.1 为什么回测数据不走 Qwen

- **精度要求**：回测需每根 bar 精确，Qwen 返回日线 OHLCV 实测准确率 <70%（非其强项）
- **可复现性**：同 prompt 多次调用结果可能不同，破坏"历史回测"科学性
- **成本**：单次回测输出 10K+ tokens（约 ¥0.2-0.5），高频迭代策略不划算
- **延迟**：20-60 秒 vs yfinance + 缓存的 <100ms（缓存命中）
- **LLM 可辅助的点**：策略描述 → 代码、结果解读（这些走 Qwen 合理）

### 8.2 为什么选 TV Widget 而非 Lightweight Charts

| 维度 | TV Widget | Lightweight Charts |
|------|-----------|--------------------|
| 数据 | TV 自带，零成本 | 需自己喂数据 |
| 功能完整度 | 极高（指标/画线/多时间框） | 基础（要自己加指标） |
| 引入成本 | 1 行 CDN | 1 行 CDN + 数据 pipeline |
| 维护成本 | 极低 | 中 |
| 用户的原始意图 | 匹配（"用 TV 数据"） | 不匹配（还是要自己找数据） |

### 8.3 为什么保留 yfinance/AkShare

**数据主权 + 可用性兜底**：
- Qwen 挂了，至少还能用 yfinance 显示价格
- 回测必须用精确数据
- yfinance 无需 Key，部署成本为 0

**配置层可禁用**：如果用户坚持 100% Qwen，可以设 `providers.yfinance_enabled: false`，但回测功能会失效并显示明确提示。

### 8.4 TradingView Widget 的法律合规

TV Advanced Chart Widget 的使用条款：
- ✅ 免费，无需申请
- ⚠️ 必须保留 "Powered by TradingView" 署名（Widget 默认已有）
- ❌ 不允许抓取 Widget 内的数据用于自己的系统
- ✅ 允许商业使用（只要不是直接转售 TV 数据）

**结论**：完全合规。只需保留默认署名。

### 8.5 为什么选线程池而非 Celery/RQ

| 方案 | 轻量 | 持久化 | 运维 | 适合本项目 |
|------|------|--------|------|-----------|
| **Python ThreadPoolExecutor + SQLite**（选用） | ✅ | SQLite | 零 | ✅（单机、<10 并发） |
| Celery + Redis | ❌ | Redis | 需跑 Redis | ❌（单人项目不值得） |
| RQ + Redis | 中 | Redis | 需跑 Redis | ❌ |
| APScheduler | ✅ | 内存/DB | 零 | 定时任务已在用 |

**理由**：单人系统并发低（<3 同时任务），线程池 + SQLite 足够。如果未来需要横向扩展，迁移到 Celery 只需替换 `TaskManager.submit()` 的派发逻辑。

### 8.6 WebSocket 断连时的任务可见性

用户可能在任务运行中关闭页面或切换 Wi-Fi：

- **任务执行不受影响**：Worker 是后台线程，WS 断开不会中断
- **重新连接时查询**：前端重连后调用 `GET /api/tasks?status=running` 获取当前运行中任务
- **任务中心实时订阅**：用户进入任务中心页自动订阅 `task_*` 事件
- **推送带缓冲**：短暂断连（<30s）时，TaskManager 会把进度推送缓冲到任务记录的 `progress_step` 字段，重连后仍能看到最新状态

---

## 九、成本估算

### 9.1 Qwen API 成本（以 qwen-plus 为例）

| 场景 | 单次 tokens | 单次成本 | 日调用量 | 日成本 |
|------|------------|---------|---------|--------|
| 实时价格 | ~500 | ¥0.01 | 50 次 | ¥0.5 |
| 基本面 | ~1000 | ¥0.02 | 20 次 | ¥0.4 |
| 新闻 | ~2000 | ¥0.04 | 20 次 | ¥0.8 |
| 选股打分 | ~3000 | ¥0.06 | 5 次 | ¥0.3 |
| AI 分析（现有） | ~20000 | ¥0.4 | 5 次 | ¥2.0 |
| **合计** | | | | **~¥4/天** |

单月约 ¥120，对单人用户可接受。**加上缓存后可降至 1/3**。

### 9.2 对比现有方案

| 项 | 现有 | 新方案 |
|----|------|-------|
| 数据源 API Key | 需 Polygon | 仅 Qwen |
| 本地依赖 | 需 IB TWS | 无 |
| 月成本 | 0（免费层） | ~¥40-120 |
| 可用性 | 经常限流/断连 | 稳定 |
| 云端部署 | 困难 | 直接可用 |

**价值判断**：用每月 ¥40-120 换掉 IB 和 Polygon 的运维痛点 + 云端友好，划算。

---

## 十、开放问题

| # | 问题 | 需确认 |
|---|------|--------|
| Q1 | 是否完全禁用 IB？（IB Scanner 选股层依赖它） | 若禁用，选股第一层改走 finviz + Qwen，需验证质量 |
| Q2 | TV Widget 对 A 股小盘/新股覆盖率 | 需抽样测试 |
| Q3 | Qwen 基本面数据在 A 股（如贵州茅台 600519）的准确率 | 需对比 AkShare 实测 |
| Q4 | LocalCache 在 Railway 上的持久化（容器重启丢失？） | 需挂载 Volume 或用外部 SQLite |
| Q5 | 用户对"数据由 AI 生成，仅供参考"的接受度 | 涉及产品表述，需在 UI 明确 |

---

## 十一、需要用户决策的事项

在开始实施前，请确认以下选择：

| 选项 | A | B | C |
|------|---|---|---|
| 1. 主源激进程度 | 激进：Qwen 全主，yfin 仅兜底 | **平衡**：Qwen 主、yfin 自动兜底（推荐） | 保守：yfin 主、Qwen 仅特定场景 |
| 2. TV Widget 范围 | **仅分析页 K 线** | 所有需图表处都用 TV | 不引入 TV，继续 ECharts |
| 3. 回测数据 | **yfinance + 缓存** | Polygon（需付费） | 不做回测 |
| 4. IB/Polygon | **全部禁用** | 保留作高级用户选项 | 保留但默认关 |
| 5. 任务系统粒度 | **所有 >2s 操作都走任务系统** | 仅 AI 分析和回测走任务系统 | 不引入任务系统 |
| 6. 任务保留期 | 7 天 | **30 天（推荐）** | 永久保留 |

推荐组合：**1B + 2A + 3A + 4A + 5A + 6B**（即方案主干）。

---

## 十二、性能目标

| 场景 | 当前 | 目标 | 达成手段 |
|------|------|------|---------|
| 首页打开 | 15-40s | **<3s** | 仪表盘全部读缓存 + 快照 |
| 持仓列表刷新 | 30-80s | **<2s** | 批量价格缓存（60s TTL） |
| 单只股票基本面 | 3-8s（Qwen） / 1-3s（yfin） | **<500ms（缓存命中）** | 24h TTL 缓存 |
| AI 分析 | 2-5 分钟（同步阻塞） | **立即返回 task_id，后台执行** | 异步任务系统 |
| 选股 | 30s-2 分钟（同步阻塞） | **立即返回 task_id** | 异步任务系统 |
| 回测 | 新增功能 | **首次 3-8s，缓存命中 <100ms** | LocalCache + 结果持久化 |
| 页面切换 | — | **<200ms** | SPA 内部导航 |
| WebSocket 事件延迟 | — | **<1s** | socketio 原生 |

---

*文档结束。请审阅后确认组合选项，我将据此生成详细技术方案和开始实施。*
