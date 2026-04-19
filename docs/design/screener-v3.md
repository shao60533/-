# 技术方案：智能选股 V3 —— 大师 Agent 深度评估

| 项 | 值 |
|---|---|
| Feature | `screener-v3` |
| 版本 | v1.0 |
| 日期 | 2026-04-19 |
| 关联 PRD | [../prd/screener-v3.md](../prd/screener-v3.md) |
| 关联测试用例 | [../test-cases/screener-v3.md](../test-cases/screener-v3.md) |
| 替代 | [screener-v2.md](./screener-v2.md) v1.1 的 guru 层 |

## 1. 目标

见 [PRD §2](../prd/screener-v3.md#2-目标)。一句话：把 4 位大师的硬阈值脚本升级为 14 位 agent 的深度评估 + 圆桌辩论，**预算可预估、过程可观测、中断可恢复**。

## 2. 架构概览

```
┌───────────────── 预选配置面板 (Front-end) ─────────────────┐
│  大师选择 │ 深度模式 │ 候选数量 │ 成本预估 │ [开始筛选] │
└──────────────────┬────────────────────────────────────────┘
                   │  POST /api/screen/v3/trigger
                   ▼
┌─────────── task_manager.enqueue('screen_v3', params) ───────┐
│  params = { user_id, nl_query, market, candidate_n,          │
│              gurus[], mode, with_roundtable, llm_provider }  │
└──────────────────┬───────────────────────────────────────────┘
                   │
                   ▼
┌────────────── worker: ScreenerV3Pipeline ───────────────────┐
│                                                              │
│  Phase 1  NL Parser            ───┐                          │
│  Phase 2  Universe Filter         │ 复用 v2                 │
│  Phase 3  Threshold Prefilter  ───┘ → candidates (N=20 默认) │
│                                                              │
│  Phase 4  Guru Agents Pool                                   │
│            ├─ Semaphore(10) 并发                             │
│            ├─ 缓存命中 (ticker, guru, date) → 跳过 LLM       │
│            ├─ 每 unit 完成 → WebSocket push + DB 写入        │
│            └─ Cancel flag check 每 unit 前                   │
│                                                              │
│  Phase 5  Round-table Debate (opt, Top 5)                    │
│                                                              │
│  Phase 6  Aggregator + Regime → Top K → screen_results_v2    │
│                                                              │
└────────────────────────────────────────────────────────────────┘
```

## 3. 模块结构

### 3.1 新增模块 `stock_trading_system/screener/v3/`

```
stock_trading_system/screener/v3/
├── __init__.py
├── pipeline.py              # ScreenerV3Pipeline —— 6 Phase 编排
├── gurus_agents/            # 14 位大师 agent
│   ├── __init__.py
│   ├── base.py              # BaseGuruAgent + GuruSignal (Pydantic)
│   ├── buffett.py
│   ├── graham.py
│   ├── munger.py
│   ├── lynch.py
│   ├── fisher.py
│   ├── burry.py
│   ├── ackman.py
│   ├── wood.py
│   ├── druckenmiller.py
│   ├── damodaran.py
│   ├── pabrai.py
│   ├── taleb.py
│   ├── marks.py             # 自建（arXiv 模板）
│   └── dalio.py             # 自建
├── roundtable.py            # Phase 5 辩论
├── estimator.py             # 成本/时长预估
├── cache.py                 # (ticker, guru, date) 缓存读写
├── concurrency.py           # Semaphore + 失败重试
└── stream.py                # WebSocket 事件推送
```

### 3.2 复用 V2 的 5 个模块

| 文件 | 用途 | 改动 |
|---|---|---|
| [v2/nl_parser.py](../../stock_trading_system/screener/v2/nl_parser.py) | NL → FilterSpec | 0（完全复用） |
| [v2/universe.py](../../stock_trading_system/screener/v2/universe.py) | Layer A 股池筛选 | 0 |
| [v2/data_helper.py](../../stock_trading_system/screener/v2/data_helper.py) | 基本面数据拉取 | 可能扩展（大师需要 5 年历史财报） |
| [v2/aggregator.py](../../stock_trading_system/screener/v2/aggregator.py) | Signal 聚合 | 接口不变；内部兼容旧 GuruMatch + 新 GuruSignal |
| [v2/regime_detector.py](../../stock_trading_system/screener/v2/regime_detector.py) | 市场 regime 权重 | 0 |

### 3.3 兼容层：`BaseGuru` 接口保留

现有 `BaseGuru.evaluate(ticker, fundamentals, context) -> GuruMatch` 保留。新增 `BaseGuruAgent.evaluate_deep(ticker, full_data, context) -> GuruSignal`。

```python
# v2 经典阈值模式（保留）
class BuffettGuru(BaseGuru):
    def evaluate(self, ticker, fundamentals, context) -> GuruMatch:
        ...  # 现有 4 条阈值逻辑

# v3 Agent 深度模式（新增）
class BuffettAgent(BaseGuruAgent):
    def evaluate_deep(self, ticker, full_data, context) -> GuruSignal:
        fund_score     = self._analyze_fundamentals(full_data)
        consistency    = self._analyze_consistency(full_data)
        moat           = self._analyze_moat(full_data)
        pricing_power  = self._analyze_pricing_power(full_data)
        book_growth    = self._analyze_book_value_growth(full_data)
        mgmt_quality   = self._analyze_management_quality(full_data)
        intrinsic      = self._calculate_intrinsic_value(full_data)
        margin_safety  = self._calculate_margin_of_safety(intrinsic, full_data)
        # 聚合为 total_score（6-10 子项加权）
        total = _weighted_sum([...])
        # LLM 结构化推理
        signal = self._llm_reason(full_data, {
            "fund": fund_score, "moat": moat, "intrinsic": intrinsic,
            "margin_safety": margin_safety, "total": total,
        })
        return signal  # Pydantic: signal/confidence/reasoning/key_metrics
```

Pipeline 按 `mode` 走不同路径：

```python
if mode == "classic":
    guru_results = [old_guru.evaluate(t, ...) for t in candidates for old_guru in old_gurus]
else:  # "agent" or "agent_with_roundtable"
    guru_results = await self._run_guru_agents_parallel(candidates, selected_gurus)
    if mode == "agent_with_roundtable":
        roundtable = await self._run_roundtable(guru_results, top_5)
```

## 4. 关键设计

### 4.1 BaseGuruAgent & Pydantic 信号

```python
# gurus_agents/base.py
from __future__ import annotations
from pydantic import BaseModel, Field
from typing import Literal

class SubAnalysis(BaseModel):
    name: str
    score: float = Field(ge=0, le=10)
    details: str

class GuruSignal(BaseModel):
    guru: str
    ticker: str
    signal: Literal["bullish", "bearish", "neutral"]
    confidence: float = Field(ge=0, le=1)
    reasoning: str                          # 全文 LLM 推理（持久化）
    sub_analyses: list[SubAnalysis]
    key_metrics: dict[str, float]           # e.g. intrinsic_value, margin_of_safety
    total_score: float = Field(ge=0, le=100)


class BaseGuruAgent:
    name: str                    # 例 "buffett"
    display_name: str            # 例 "Warren Buffett"
    philosophy: str
    principles: list[str]
    motto: str
    avatar_initials: str
    avatar_color: str

    def evaluate_deep(
        self, ticker: str, full_data: dict, context: dict
    ) -> GuruSignal:
        raise NotImplementedError

    def _llm_reason(self, full_data: dict, scores: dict) -> GuruSignal:
        """Common LLM-reasoning helper. Subclasses provide system_prompt."""
        ...
```

### 4.2 大师数据需求升级

V2 的 `data_helper.py` 返回的 fundamentals 是**单期快照**（current ROE / D/E / margin）。V3 大师需要：

| 数据类型 | 用途 | 来源 |
|---|---|---|
| **5 年财报序列**（revenue / earnings / FCF / book value） | 一致性 / 增长分析（Buffett, Lynch） | yfinance `Ticker.financials`、AkShare `stock_financial_report_sina` |
| **分季度现金流**（operating / investing / financing） | 管理质量（Buffett, Munger） | yfinance `cashflow` |
| **债务明细**（短长期债务、利息支出） | 净净股 / Graham | yfinance `balance_sheet` |
| **行业对比数据**（同行 PE / ROE 均值） | 护城河定性（Fisher） | 预计算表或实时聚合 |
| **新闻情绪** | Catalyst / 尾部风险（Ackman, Taleb） | 复用现有 news 管道 |
| **持股变化**（insider buy/sell） | 管理信心（Lynch, Ackman） | yfinance `major_holders`（可选 P1） |

**扩展点**：新建 [v3/data_helper.py](../../stock_trading_system/screener/v3/data_helper.py)，封装 `GuruDataBundle`：

```python
@dataclass
class GuruDataBundle:
    ticker: str
    market: str
    quote: dict                   # current price + market cap
    fundamentals_current: dict    # 当前一期
    fundamentals_history: list[dict]  # 过去 5 年每年
    cashflow_quarterly: list[dict]
    balance_sheet_history: list[dict]
    news_recent: list[dict]       # 近 30 天
    industry_peers: dict          # peer 均值
```

此 bundle 一次性为 14 大师准备，避免重复 I/O。

### 4.3 并发与速率

```python
# concurrency.py
import asyncio
from stock_trading_system.screener.v3.gurus_agents.base import BaseGuruAgent

CONCURRENCY = 10  # Semaphore 上限

async def run_units(units, on_unit_done):
    """units: list of (guru_agent, ticker, bundle)"""
    sem = asyncio.Semaphore(CONCURRENCY)
    results: list[GuruSignal] = []

    async def _one(unit):
        guru, ticker, bundle = unit
        async with sem:
            if cancel_flag.is_set():
                return
            # 先查缓存
            cached = cache.get(ticker, guru.name, today())
            if cached:
                await on_unit_done(guru, ticker, cached, cached=True)
                results.append(cached)
                return
            # 实调
            for attempt in range(3):
                try:
                    sig = await asyncio.to_thread(
                        guru.evaluate_deep, ticker, bundle, ctx,
                    )
                    cache.set(ticker, guru.name, today(), sig)
                    await on_unit_done(guru, ticker, sig, cached=False)
                    results.append(sig)
                    return
                except RateLimitError:
                    await asyncio.sleep(2 ** attempt)
                except Exception as e:
                    if attempt == 2:
                        await on_unit_done(guru, ticker, _error_signal(e))
                        return

    await asyncio.gather(*[_one(u) for u in units])
    return results
```

速率限制：
- Semaphore(10) 是**默认**（[PRD §3.1 配置选项 Q1A](../prd/screener-v3.md) 已确认）
- 出现 rate limit error → 退避 2/4/8s 重试 3 次
- 全部重试失败 → 记错误 signal（signal="neutral", confidence=0, reasoning="LLM failed"），不阻塞其他单元

### 4.4 缓存

```python
# cache.py
from stock_trading_system.data.local_cache import LocalCache

CACHE_CATEGORY = "guru_signal_v3"

def _cache_key(ticker: str, guru: str, date: str) -> str:
    return f"{ticker}:{guru}:{date}"

def get(ticker, guru, date) -> GuruSignal | None:
    raw = LocalCache.get(CACHE_CATEGORY, _cache_key(ticker, guru, date))
    return GuruSignal.model_validate_json(raw) if raw else None

def set(ticker, guru, date, signal: GuruSignal) -> None:
    LocalCache.set(
        CACHE_CATEGORY, _cache_key(ticker, guru, date),
        signal.model_dump_json(),
        ttl=seconds_until_end_of_day(),
    )
```

**TTL**：当日结束自动失效（次日 00:00 新交易日）。

**失效事件**：新大师 prompt 版本发布时（[self-iterating-agents](./self-iterating-agents.md) Meta Agent 产出新 prompt），cache 需清空。在 cache key 加 `prompt_version` 后缀：

```python
_cache_key = f"{ticker}:{guru}:{prompt_version}:{date}"
```

### 4.5 成本/时长预估（Estimator）

```python
# estimator.py

# 平均值基线（首次部署时以小样本跑一轮校准）
AVG_DURATION_PER_CALL_SEC = 5.0  # 一次 LLM 调用平均 5 秒
AVG_TOKENS_IN            = 2000
AVG_TOKENS_OUT           = 500

# Qwen-plus / Gemini 2.5 flash 单价（¥ / 1K token）
PROVIDER_PRICING = {
    "qwen":   {"in": 0.008, "out": 0.020},
    "gemini": {"in": 0.002, "out": 0.006},
}

def estimate(
    num_candidates: int, num_gurus: int,
    with_roundtable: bool, provider: str,
    concurrency: int = 10,
) -> dict:
    # 主评估
    main_calls = num_candidates * num_gurus
    main_duration = (main_calls / concurrency) * AVG_DURATION_PER_CALL_SEC

    # 圆桌：Top 5 × 平均 3 辩论轮（~15 calls 总）
    rt_calls = 15 if with_roundtable else 0
    rt_duration = 60 if with_roundtable else 0

    total_calls = main_calls + rt_calls
    tokens_in  = total_calls * AVG_TOKENS_IN
    tokens_out = total_calls * AVG_TOKENS_OUT

    pricing = PROVIDER_PRICING[provider]
    cost_cny = (tokens_in * pricing["in"] + tokens_out * pricing["out"]) / 1000

    return {
        "llm_calls": total_calls,
        "duration_sec": main_duration + rt_duration,
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "cost_cny": round(cost_cny, 2),
    }
```

**动态校准**：任务开始后，前 5 个 unit 的实际 duration/tokens 用于更新 `AVG_*` 常量（滑动平均，保存在 `kv_cache`），下次预估更准。

### 4.6 流式回显

```python
# stream.py
from stock_trading_system.web.websocket import push_to_task_channel

async def on_unit_done(guru, ticker, signal, cached=False):
    await push_to_task_channel(task_id, {
        "type": "guru_unit_done",
        "guru": guru.name,
        "guru_display": guru.display_name,
        "ticker": ticker,
        "signal": signal.signal,
        "confidence": signal.confidence,
        "reasoning_preview": signal.reasoning[:200],
        "cached": cached,
        "progress": progress_counter.current(),
        "total": progress_counter.total,
    })
```

前端 `/page-tasks` 任务详情页订阅 `ws://host/ws/tasks/<task_id>` 实时更新进度条 + 增量展示结果行。

### 4.7 任务取消

- `task_manager` 现有 `/api/tasks/<id>/cancel` 路由（见 [tasks/store.py](../../stock_trading_system/tasks/task_store.py)）
- Worker 在每个 unit 前检查 `self.task.status == "cancelled"`，命中则跳出
- 已完成单元的结果**不丢弃**，status → `cancelled`（部分完成）
- UI：任务详情页显示"部分完成 - 48/80 大师评估"

### 4.8 结果持久化

现有 `screen_results_v2` 表的 `results_json` 字段是大 JSON blob。V3 扩展结构：

```json
{
  "engine": "v3",
  "mode": "agent_with_roundtable",
  "candidates_count": 20,
  "selected_gurus": ["buffett","graham","munger","lynch"],
  "results": [
    {
      "ticker": "AAPL",
      "final_score": 82.5,
      "regime_adjusted": 80.1,
      "guru_signals": [
        {
          "guru": "buffett",
          "signal": "bullish",
          "confidence": 0.85,
          "reasoning": "...(full text)...",
          "sub_analyses": [ ... ],
          "key_metrics": { "intrinsic_value": 220, "margin_of_safety": 0.18 },
          "total_score": 88
        },
        ...
      ],
      "roundtable": {
        "consensus": ["buffett", "graham"],
        "dissent": ["burry"],
        "debate_snippets": [...]
      }
    },
    ...
  ],
  "metrics": {
    "duration_sec": 248,
    "llm_calls": 83,
    "cache_hits": 17,
    "cost_cny": 1.58
  }
}
```

**每个 (ticker, guru) 也单独写 `kv_cache`** 便于缓存命中查询（§4.4）。

### 4.9 Round-table 辩论

```python
# roundtable.py
async def run_roundtable(
    top5_signals: dict[str, list[GuruSignal]],  # ticker -> signals
    llm_client,
) -> dict[str, RoundtableResult]:
    results = {}
    for ticker, signals in top5_signals.items():
        bullish = [s for s in signals if s.signal == "bullish"]
        bearish = [s for s in signals if s.signal == "bearish"]

        if not bullish or not bearish:
            # 一致看多/看空 → 无需辩论
            results[ticker] = _consensus(signals)
            continue

        # 挑最自信的牛熊各 1 位，互相反驳 2 轮
        bull_champion = max(bullish, key=lambda s: s.confidence)
        bear_champion = max(bearish, key=lambda s: s.confidence)

        debate = await _two_round_debate(
            llm_client, ticker, bull_champion, bear_champion,
        )
        results[ticker] = RoundtableResult(
            consensus=[s.guru for s in bullish] if len(bullish) > len(bearish) else [s.guru for s in bearish],
            dissent=[s.guru for s in bearish] if len(bullish) > len(bearish) else [s.guru for s in bullish],
            split=len(bullish) == len(bearish),
            debate_snippets=debate,
        )
    return results
```

**成本上限**：Top 5 × 每只 ≤ 3 次 LLM ≈ 15 calls，对应 ~30-60s（与 PRD 声明一致）。

### 4.10 Marks / Dalio 自建 prompt

**Howard Marks**（循环思维 / 第二层思考）：

```python
MARKS_SYSTEM_PROMPT = """
你是 Howard Marks —— Oaktree Capital 创始人，著有《投资最重要的事》。
你最看重：
1. 市场循环位置（现在是贪婪还是恐惧？）
2. 第二层思考（别人看到利好你看到的背后风险）
3. 风险控制优先于回报
4. 不对称回报（下行有限、上行可观）

分析这只股票时，用以下结构：
- 循环判断：当前所处市场循环阶段及证据
- 第二层思考：市场共识 vs. 你的反向观点
- 不对称性评估：下行 / 上行比
- 风险警示：最糟情况下损失多少
最终给出 bullish / bearish / neutral 和 0-1 信心度。
"""
```

**Ray Dalio**（全天候 / 桥水原则）：

```python
DALIO_SYSTEM_PROMPT = """
你是 Ray Dalio —— 桥水基金创始人，著有《原则》。
你最看重：
1. 经济机器四季节（通胀上升/下降 × 增长上升/下降）判断
2. 现金流的可靠性（生产率驱动的真实增长）
3. 债务周期位置
4. 全球宏观关联

分析这只股票时，用以下结构：
- 经济象限：现在处于四象限哪一个，此股在该象限的期望表现
- 债务结构：公司债务周期位置
- 真实生产率：扣除杠杆后的真实增长
- 组合角色：如纳入全天候组合，它承担何种风险对冲角色
最终给出 bullish / bearish / neutral 和 0-1 信心度。
"""
```

## 5. API 契约

### 5.1 `POST /api/screen/v3/estimate`

Request：
```json
{
  "nl_query": "AI 方向，PE<30",
  "market": "US",
  "candidate_n": 20,
  "gurus": ["buffett","graham","munger","lynch"],
  "mode": "agent",
  "with_roundtable": false
}
```

Response 200：
```json
{
  "llm_calls": 80,
  "duration_sec": 160,
  "tokens_in": 160000,
  "tokens_out": 40000,
  "cost_cny": 1.52,
  "cache_hits_forecast": 12
}
```

### 5.2 `POST /api/screen/v3/trigger`

Request 同上 + 隐式 `user_id = g.user.id`。

Response 200：
```json
{
  "task_id": "uuid",
  "estimated_duration_sec": 160,
  "estimated_cost_cny": 1.52
}
```

### 5.3 `WS /ws/tasks/<task_id>`

Event types：
```json
{"type":"guru_unit_done", "guru":"buffett", "ticker":"AAPL",
 "signal":"bullish", "confidence":0.85,
 "reasoning_preview":"...", "cached":false,
 "progress":12, "total":80}
{"type":"roundtable_start", "tickers":["AAPL","NVDA","TSLA","MSFT","GOOG"]}
{"type":"roundtable_done", "ticker":"AAPL", "consensus":["buffett","graham"]}
{"type":"task_complete", "result_url":"/api/screen/v3/results/<id>"}
```

### 5.4 `GET /api/screen/v3/results/<id>`

Response：完整 `screen_results_v2.results_json` blob（§4.8 结构）。

## 6. 前端

### 6.1 预选配置面板

新增组件 `ScreenerV3Settings.vue`（或纯 HTML/JS，项目无 framework 偏好）。

```
┌─ 大师选择 (14) ───────── [全选] [推荐 4] [全不选] ─┐
│ ⬤ Buffett   ⬤ Graham   ⬤ Munger   ⬤ Lynch       │
│ ○ Fisher    ○ Burry    ○ Ackman   ○ Wood         │
│ ○ Drucken.  ○ Damodaran ○ Pabrai  ○ Taleb        │
│ ○ Marks     ○ Dalio                               │
├─ 深度模式 ────────────────────────────────────────┤
│ ○ 经典阈值 (秒级)                                 │
│ ⬤ Agent 深度 (LLM 推理)                           │
│ ○ Agent + 圆桌辩论 (最深)                         │
├─ 候选数量 ────────────────────────────────────────┤
│ [10] [20✓] [30] [50]                             │
├─ 预计 ────────────────────────────────────────────┤
│ 80 次 LLM 调用 | ~2.5 分钟 | ¥1.52                │
├───────────────────────────────────────────────────┤
│          [取消]          [开始筛选 ►]             │
└───────────────────────────────────────────────────┘
```

移动端沿用 `form-row-mobile` + `chip-row` + `collapse-row`（见 [mobile-optimization](./mobile-optimization.md)）。

每次选项变化即 debounce 500ms 调用 `/api/screen/v3/estimate` 更新成本。

### 6.2 任务详情页增强

- 顶部进度条：`已完成 48/80 | 缓存命中 17 | 剩余 ~1.5 分钟`
- 下方流式列表：`Buffett × AAPL ✅ bullish 0.85`, `Graham × AAPL 🔄...`
- 可按"按股票分组 / 按大师分组"两种视图切换
- 底部 `[停止任务]` 按钮

### 6.3 结果页

- Top 10 列表，每行：`ticker + final_score + 大师共识摘要`
- 展开：
  - 每位大师的 signal 色块（绿/灰/红）+ confidence bar
  - 点大师名 → 抽屉展示完整 reasoning
  - 圆桌板块：consensus / dissent / debate 片段

## 7. Worker 集成

```python
# tasks/workers.py 新增
def make_screen_v3_worker(db, task_manager):
    def worker(task):
        params = json.loads(task.params_json)
        user_id = params["user_id"]

        # user-level provider 解析（多租户）
        from stock_trading_system.llm.router import get_active_provider
        provider = get_active_provider(load_config(), user_id=user_id)

        pipeline = ScreenerV3Pipeline(
            config=load_config(),
            user_id=user_id,
            provider=provider,
            task_id=task.id,
            cancel_check=lambda: task_manager.is_cancelled(task.id),
        )
        result = asyncio.run(pipeline.run(**params))
        return {
            "engine": "v3",
            **result.to_dict(),
        }
    return worker
```

## 8. 迁移与兼容

### 8.1 数据库

- 不改表结构
- `screen_results_v2.results_json` 加顶层 `engine` 字段区分 v2/v3（老数据默认 v2）

### 8.2 代码

- 保留 `screener/v2/gurus/*.py` 不动（经典模式）
- 新增 `screener/v3/` 整个目录
- 新增 API 路由 `/api/screen/v3/*`；旧 `/api/screen/v2/*` 路径继续工作

### 8.3 前端

- 旧 `page-screener` 界面改造：NL 输入 + 大师选择面板（默认 4 大师勾选，兼容视觉）
- "深度模式"默认 `Agent 深度`（推荐），用户可切经典
- 首次使用 v3 弹一次性 tooltip："大师评估 V3 上线，约 3 分钟产出深度结果"

### 8.4 回滚

- 前端下拉默认切"经典阈值"→ 完全走 v2 代码
- 后端 API 路径 v3 不可达时前端 fallback 回 v2 `/api/screen/v2/trigger`

## 9. 实施计划

7 个 Phase，共约 ~16-20h。

### Phase 0 —— 准备 & 依赖（~1h）
- Pydantic 2 确认已装
- 新建 `screener/v3/` 骨架 + `__init__.py`
- 依赖 LangChain 已满足（项目已在用）

### Phase 1 —— BaseGuruAgent + 1 个标杆大师（Buffett）（~3h）
- `base.py`（接口 + GuruSignal Pydantic）
- `buffett.py` 全量实现（8 子分析 + LLM）
- 单测 10 条覆盖每个子分析

### Phase 2 —— 其余 11 位 virattt 移植大师（~5h）
- 借鉴 virattt 源码**独立重写**（clean-room，避开 license）
- 每位 6-10 子分析
- 每位一个单测文件

### Phase 3 —— Marks / Dalio 自建（~2h）
- 写 system_prompt
- 结构化 key_metrics（循环位置 / 经济象限）
- 单测

### Phase 4 —— Pipeline + 并发 + 缓存 + 流式（~3h）
- `pipeline.py` 6 Phase 编排
- `concurrency.py` Semaphore + 重试
- `cache.py` (ticker, guru, date)
- `stream.py` WebSocket
- `estimator.py` 成本预估 + 动态校准

### Phase 5 —— Round-table（~2h）
- `roundtable.py` 双大师辩论
- consensus/dissent 聚合
- 单测

### Phase 6 —— API + Worker + 前端（~3h）
- `/api/screen/v3/{estimate,trigger,results}` 三路由
- `make_screen_v3_worker`
- 预选面板 HTML/JS
- 任务详情页流式 UI
- 结果页抽屉展示

### Phase 7 —— 验收（~1.5h）
- 跑 test-cases/screener-v3.md 全矩阵
- 真实 2-3 次完整筛选（20 股 × 14 大师 + 圆桌）
- 成本预估与实际对比，校准基线

## 10. 风险与缓解

| 风险 | 缓解 |
|---|---|
| virattt clean-room 重写被指抄袭 | 读源码作 spec，不 copy-paste 代码；独立命名/结构；保留作者 attribution 链接 |
| 14 大师 prompt 质量参差 | 每位独立 prompt 文件；上线后通过 [self-iterating](./self-iterating-agents.md) 持续优化 |
| Qwen rate limit（尤其并发 10） | Semaphore(10) + 指数退避；文档提醒"个人账号建议 5，企业账号 10+" |
| 成本预估偏差大（尤其首次部署） | 动态校准：首 5 单元实际值覆盖常量 |
| 圆桌辩论 LLM 脱离身份 | Prompt 锚定"你是 X"；温度调低；失败降级为无辩论 |
| WebSocket 断线丢消息 | 重连后 `GET /api/tasks/<id>/state` 拉快照补齐 |
| 长时间任务 worker 被系统杀 | 每个 unit 完成立即入库 → 重启任务从未完成 unit 继续（幂等） |
| 14 大师并发对共用 `GuruDataBundle` 并发读 | Bundle 一次性构造后只读；无写冲突 |

## 11. 与其他模块集成

| 模块 | 接口点 |
|---|---|
| [model-switch](./model-switch.md) v1.0 | `llm.router.get_active_provider(config, user_id=user_id)` |
| [multi-tenant](./multi-tenant.md) v1.0 | `task.created_by = g.user.id`；结果共享可见 |
| [mobile-optimization](./mobile-optimization.md) v1.0 | 预选面板沿用 `form-row-mobile` / `chip-row` / `collapse-row` |
| [self-iterating-agents](./self-iterating-agents.md) v3.0 | 每个 GuruSignal 自动写 `agent_scorecards`；14 大师自动获得演化数据源 |
| [paper-trade](./paper-trade.md) v1.2 | V3 产出 Top 10 → auto_track → 纸面交易持续跟踪表现 |
| [batch-analyze-holdings](./batch-analyze-holdings.md) v1.0 | v3 大师池可复用，持仓分析也能走 Agent 模式（v1.1 议题） |

## 12. 版本历史

| 版本 | 日期 | 变更 |
|---|---|---|
| v1.0 | 2026-04-19 | 初版：新建 `screener/v3/` + 14 大师 agent（12 清洁重写 + 2 自建）+ 并发缓存流式 + 预选面板 + 成本预估 + 圆桌辩论 + 经典模式兼容保留 |
