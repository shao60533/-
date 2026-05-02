# 技术方案：智能选股 V3 —— 大师 Agent 深度评估

| 项 | 值 |
|---|---|
| Feature | `screener-v3` |
| 版本 | v1.5 |
| 日期 | 2026-05-03 |
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
        total = _weighted_sum([...])

        # 【复用】LangChain 原生 structured output，替代自写 JSON 解析
        # 见 docs/engineering-principles.md §5.1
        chat = get_chat_model(context["provider"])
        structured = chat.with_structured_output(GuruSignal)
        return structured.invoke([
            SystemMessage(content=self.SYSTEM_PROMPT),
            HumanMessage(content=self._build_user_prompt(full_data, {
                "fund": fund_score, "moat": moat, "intrinsic": intrinsic,
                "margin_safety": margin_safety, "total": total,
            })),
        ])  # 返回已填充 GuruSignal，LangChain 自动重试/修正 JSON
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

**【复用】**：`tenacity` 库处理重试退避，替代自写循环（见 [engineering-principles §5.1](../engineering-principles.md#51-screenerv3md--需要修订重点)）。
需在 `requirements.txt` 追加 `tenacity>=9.0`。

```python
# concurrency.py
import asyncio
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from stock_trading_system.screener.v3.gurus_agents.base import BaseGuruAgent

CONCURRENCY = 10

# 复用 tenacity：3 次指数退避 2/4/8s
_llm_retry = retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=2, min=2, max=8),
    retry=retry_if_exception_type(RateLimitError),
    reraise=True,
)

async def run_units(units, on_unit_done, cancel_check):
    """units: list of (guru_agent, ticker, bundle)"""
    sem = asyncio.Semaphore(CONCURRENCY)
    results: list[GuruSignal] = []

    @_llm_retry
    def _invoke(guru, ticker, bundle, ctx):
        return guru.evaluate_deep(ticker, bundle, ctx)  # 内部 structured-output 已处理 JSON 重试

    async def _one(unit):
        guru, ticker, bundle = unit
        async with sem:
            if cancel_check():
                return
            cached = cache.get(ticker, guru.name, today())
            if cached:
                await on_unit_done(guru, ticker, cached, cached=True)
                results.append(cached)
                return
            try:
                sig = await asyncio.to_thread(_invoke, guru, ticker, bundle, ctx)
                cache.set(ticker, guru.name, today(), sig)
                await on_unit_done(guru, ticker, sig, cached=False)
                results.append(sig)
            except Exception as e:
                await on_unit_done(guru, ticker, _error_signal(e))

    await asyncio.gather(*[_one(u) for u in units])
    return results
```

- Semaphore(10) 默认（[PRD 确认](../prd/screener-v3.md)）
- tenacity 处理 rate-limit 退避
- 重试耗尽 → 记 neutral signal，不阻塞其他单元
- 结构化输出层的 JSON 解析异常由 LangChain `with_structured_output` 内部处理

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

**【复用】**：复用 TradingAgents 的辩论图节点作为基底（见 [engineering-principles §5.1](../engineering-principles.md#51-screenerv3md--需要修订重点)）：

| 复用节点 | 位置 | 用途 |
|---|---|---|
| `bull_researcher.py` | `tradingagents/agents/researchers/` | 牛方角色模板 |
| `bear_researcher.py` | 同上 | 熊方角色模板 |
| `conservative_debator.py` | `tradingagents/agents/risk_mgmt/` | 反驳对方论点的模板 |
| `reflection.py` | `tradingagents/graph/` | 共识/分歧判定节点 |

我们**只替换身份 system prompt**（把 "bull researcher" 换成 "as Warren Buffett 看 AAPL"），图结构和状态机零改动。

```python
# roundtable.py
from tradingagents.agents.researchers.bull_researcher import make_bull_researcher
from tradingagents.agents.researchers.bear_researcher import make_bear_researcher
from tradingagents.agents.risk_mgmt.conservative_debator import make_conservative_debator
from tradingagents.graph.reflection import make_reflection_node

async def run_roundtable(
    top5_signals: dict[str, list[GuruSignal]],  # ticker -> signals
    llm_client,
) -> dict[str, RoundtableResult]:
    results = {}
    for ticker, signals in top5_signals.items():
        bullish = [s for s in signals if s.signal == "bullish"]
        bearish = [s for s in signals if s.signal == "bearish"]

        if not bullish or not bearish:
            results[ticker] = _consensus(signals)
            continue

        bull_champion = max(bullish, key=lambda s: s.confidence)
        bear_champion = max(bearish, key=lambda s: s.confidence)

        # 复用 TA 的 bull/bear researcher 作辩论基底；只替换身份 prompt
        bull_node = make_bull_researcher(llm_client, persona=bull_champion.guru)
        bear_node = make_bear_researcher(llm_client, persona=bear_champion.guru)
        rebuttal  = make_conservative_debator(llm_client)  # 轮次 2 的反驳
        judge     = make_reflection_node(llm_client)       # consensus 判定

        # TA 既有状态机驱动这个迷你图（bull → bear → rebuttal → judge）
        state = await _drive_debate_graph(
            ticker, bull_champion, bear_champion,
            bull_node, bear_node, rebuttal, judge,
        )
        results[ticker] = RoundtableResult(
            consensus=[s.guru for s in bullish] if len(bullish) > len(bearish) else [s.guru for s in bearish],
            dissent=[s.guru for s in bearish]  if len(bullish) > len(bearish) else [s.guru for s in bullish],
            split=len(bullish) == len(bearish),
            debate_snippets=state["debate_log"],
        )
    return results
```

**复用收益**：
- `bull/bear_researcher` + `conservative_debator` 的 prompt 框架和 state schema 由 TA 维护，我们零维护
- 当 TA 升级辩论提示工程 → 我们自动受益
- 自写 LOC 从 ~150 降到 ~50（见 [engineering-principles §5.1](../engineering-principles.md#51-screenerv3md--需要修订重点)）

**成本上限**：Top 5 × 每只 ≤ 3 次 LLM ≈ 15 calls，~30-60s（与 PRD 一致）。

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

## 12. 复用 / Reuse

按 [docs/engineering-principles.md](../engineering-principles.md) 约束，本方案的"复用 / 自写"比例清单：

### L0 项目内直接复用

| 模块 | 用途 |
|---|---|
| [screener/v2/nl_parser.py](../../stock_trading_system/screener/v2/nl_parser.py) | NL → FilterSpec（Phase 1）|
| [screener/v2/universe.py](../../stock_trading_system/screener/v2/universe.py) | 股池筛选（Phase 2）|
| [screener/v2/aggregator.py](../../stock_trading_system/screener/v2/aggregator.py) | Signal 聚合（Phase 6）|
| [screener/v2/regime_detector.py](../../stock_trading_system/screener/v2/regime_detector.py) | Regime 权重（Phase 6）|
| [screener/v2/data_helper.py](../../stock_trading_system/screener/v2/data_helper.py) | 基本面拉取；v3 扩展为 `GuruDataBundle`（不新建模块）|
| [data/local_cache.py](../../stock_trading_system/data/local_cache.py) | `(ticker, guru, date)` 缓存（§4.4）|
| [tasks/task_store.py](../../stock_trading_system/tasks/task_store.py) + `workers.py` | 异步任务 + 取消 + 流式推送（§4.7）|
| [llm/router.py](../../stock_trading_system/llm/router.py)（model-switch）| 用户级 provider 解析 |
| [auth/session.py](../../stock_trading_system/auth/session.py)（multi-tenant）| `g.user.id` 注入 |

### L1 依赖库（成熟 pip 包）

| 库 | 用途 | 替代的自写代码 |
|---|---|---|
| `pydantic>=2` | `GuruSignal` 结构化 schema | 自写 dataclass + JSON 校验 |
| `langchain>=0.3`（已装）+ `langchain_openai` / `langchain_google_genai` | **`chat.with_structured_output(GuruSignal)`** 替代自写 `_llm_reason`（§4.1）| 每大师 ~30 LOC × 14 = **~420 LOC** |
| `tenacity>=9.0`（需追加到 requirements）| 指数退避重试装饰器（§4.3）| ~30 LOC 自写循环 |
| `asyncio`（stdlib）| Semaphore(10) + gather | — |

### L2 开源项目（vendor / 思路借鉴）

| 项目 | license | 采取方式 |
|---|---|---|
| [TauricResearch/TradingAgents](https://github.com/TauricResearch/TradingAgents)（已装） | Apache-2.0 | **直接 import** 其 `bull_researcher` / `bear_researcher` / `conservative_debator` / `reflection` 作为 Round-table 辩论图基底（§4.9），仅替换身份 prompt |
| [hengruiyun/AI-Investment-Master](https://github.com/hengruiyun/AI-Investment-Master) | AGPL-3.0 | **仅借鉴思路**：AKShare 数据适配 + 中文 prompt 结构；不 copy 代码（AGPL 传染）|
| [yejining99/GuruAgents (arXiv 2510.01664)](https://github.com/yejining99/GuruAgents) | 学术 | 借鉴 prompt 模板结构，用于 Marks / Dalio 自建 |

### L3 Clean-room 重写

| 项目 | 原因 | 范围 |
|---|---|---|
| [virattt/ai-hedge-fund](https://github.com/virattt/ai-hedge-fund) | **无 LICENSE 文件**，直接 fork/copy 法律风险不明 | 14 大师中的 12 位 —— 读源码作 spec，独立重写子分析逻辑 + prompt，**结构/命名/注释完全原创**。保留 attribution 链接到 virattt 作为灵感致谢。|
| [KRSHH/ritadel](https://github.com/KRSHH/ritadel) | MIT，但其 MIT 无法合法授予从 virattt copy 的部分 | 同上，`round_table.py` 的**思路**借鉴，实现采用 TA 辩论图（上面 L2）|

### L4 必须自写

| 模块 | 行数 | 无替代理由 |
|---|---|---|
| `gurus_agents/marks.py` | ~120 | Howard Marks 专属 prompt（周期判断 + 第二层思考），开源无等价 |
| `gurus_agents/dalio.py` | ~120 | Ray Dalio 四象限判定逻辑，开源无等价 |
| `estimator.py` | ~100 | 成本预估 + 动态校准常量，业务特定 |
| `ScreenerV3Pipeline` 编排 | ~150 | 6 Phase 特有编排（NL → Universe → Threshold → Guru → RT → Aggregate）|
| 预选配置面板 UI | ~200 | 业务特定 UI |

### 汇总

| 来源 | 估算 LOC |
|---|---|
| L0（纯 import）| 0（复用，不增量）|
| L1（依赖库包装）| ~150 |
| L2（TA 节点直接使用）| ~50（适配胶水）|
| L3（clean-room 12 大师）| ~2400（~200 LOC/位 × 12）|
| L4（自写）| ~690 |
| **合计新增** | **~3290 LOC** |
| **若全部自写** | **~4800+ LOC** |
| **节省** | **~31%**（主要来自 structured_output / tenacity / TA 辩论图）|

## 14. v1.2 增量：选股结果决策透明化（用户 2026-05-01 提）

### 14.1 现状诊断

生产截图（智能选股 V3 结果页）：信号列全 `-`、看多/看空 KPI 全 0、大师数都 4（无意义计数）、圆桌辩论看不到。

| 症状 | 根因 |
|---|---|
| 信号列全 `-` | [pipeline.py _aggregate](../../stock_trading_system/screener/v3/pipeline.py) 已计 bullish/bearish/total 但**没把 verdict 写回 candidate.signal** |
| 看多/看空 KPI 全 0 | 前端 `candidates.filter(c => c.signal.includes("bull"))` 命中 0 |
| 圆桌辩论无展示 | (a) 用户截图模式选 `agent`（不带 RT）→ roundtable=None；(b) 即使带 RT，前端只读 `result.roundtable.summary` 一段而非按 ticker 分卡 |
| 信息密度低 | 14 大师 `GuruSignal.reasoning` 完整段未展示（仅 slice 80）；价格/PE/ROE 有 `/api/fundamentals` 缓存但没接入；运行模式（agent / agent_rt / classic）+ LLM call 数 + cache 命中率没顶部 banner |

### 14.2 数据契约扩展

**`RoundtableResult` 已有字段**（roundtable.py，不改）：
```python
@dataclass
class RoundtableResult:
    ticker: str
    consensus: list[str]       # 达成共识的 guru 名单
    dissent: list[str]         # 异议者名单
    split: bool                # True = 看多看空对峙
    debate_snippets: list[str] # ['🟢 lynch: ...', '🔴 burry: ...', '⚖️ 裁判: ...']
```

**`_aggregate` 输出每个 candidate 扩字段**（向后兼容老 schema，仅追加）：

```python
{
  "ticker": "AMD",
  "final_score": 59.5,
  "avg_confidence": 0.82,
  "guru_signals": [...],            # v1.0 已有
  "roundtable": {...},              # v1.0 已有 (Top 5 only)

  # v1.2 新增 ↓
  "signal": "bullish",              # majority verdict: bullish | bearish | neutral | split
  "votes": {"bullish": 4, "bearish": 0, "neutral": 0, "total": 4},
  "consensus": "unanimous",         # unanimous | majority | split
  "confidence_range": {"min": 0.60, "max": 0.92, "avg": 0.82},
  "top_bull_argument": {            # 最高 confidence bull 的 reasoning 段（200 字）
    "guru": "lynch",
    "snippet": "AMD 在 GARP 模型下 PEG 0.7…"
  } | null,
  "top_bear_argument": {...} | null,
}
```

**verdict 计算规则**：
- `bullish > bearish + neutral` → `bullish` + consensus=unanimous
- `bullish > bearish` (过半) → `bullish` + consensus=majority
- `bearish` 同理
- 其它 → `split` 或 `neutral`

`_aggregate` 末尾 sort 之前补一段 ~30 行计算（见 §14.5 实施）。

### 14.3 API 响应扩展

`/api/screen/v3/results/<id>` 顶层 payload 加：

```json
{
  "id": ..., "task_id": ..., "created_at": ..., "params": {...},
  "candidates": [...],
  "roundtable": { "items": [...], "summary": "..." },
  "run_metadata": {
    "mode": "agent_rt" | "agent" | "classic",
    "llm_calls": 80,
    "cache_hit_pct": 30,
    "duration_sec": 138,
    "gurus_used": ["buffett", "graham", "munger", "lynch"],
    "candidates_count": 20,
    "roundtable_enabled": true
  }
}
```

`run_metadata` 字段一部分已经在 `result.metrics`（pipeline.py 输出）—— DTO 重命名 + 透传即可，不需改 pipeline。

### 14.4 前端 4 块视觉（一次落地）

#### 14.4.1 顶部 KPI 扩为 6 列

```
┌候选 20┐ ┌均分 42.5┐ ┌看多 8┐ ┌看空 3┐ ┌中性 9┐ ┌共识率 65%┐
```

- "看多" = `candidates.filter(c.signal == 'bullish' && c.consensus != 'split')`
- "中性" = candidates.filter(c.signal == 'neutral' || c.consensus == 'split')
- "共识率" = `(unanimous 数 + majority 数) / total * 100`

#### 14.4.2 运行模式 banner

`<Card>` 单行，显示 mode chip + LLM call 数 + cache 命中 + 总耗时 + 大师列表（Avatar 链）。

```tsx
<Card><CardContent className="py-3 flex flex-wrap items-center gap-3 text-xs">
  <Badge variant="default">⚡ {modeLabel}</Badge>
  <span>{md.gurus_used.length} 大师</span>
  <span>·</span>
  <span>{md.llm_calls} LLM call</span>
  <span>·</span>
  <span>命中缓存 {md.cache_hit_pct}%</span>
  <span>·</span>
  <span>耗时 {fmtDuration(md.duration_sec)}</span>
  {!md.roundtable_enabled && <Badge variant="muted">无圆桌</Badge>}
</CardContent></Card>
```

#### 14.4.3 Top 5 圆桌辩论独立 grid（仅 agent_rt）

不再合并成一段 `summary`。按 ticker 5 张卡：

```tsx
<div className="grid gap-3 md:grid-cols-2 lg:grid-cols-3">
  {result.roundtable?.items?.map(rt => (
    <Card key={rt.ticker} className={rt.split ? 'border-orange-500/40' : 'border-emerald-500/40'}>
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <CardTitle className="font-mono">{rt.ticker}</CardTitle>
          <Badge variant={rt.split ? 'sell' : 'buy'}>
            {rt.split ? 'CONTESTED' : 'CONSENSUS'}
          </Badge>
        </div>
        <div className="text-xs text-muted-foreground">
          共识 {rt.consensus.length} · 异议 {rt.dissent.length}
        </div>
      </CardHeader>
      <CardContent className="space-y-2">
        {rt.debate_snippets.map((line, i) => {
          const isBull = line.startsWith('🟢')
          const isBear = line.startsWith('🔴')
          const isJudge = line.startsWith('⚖️')
          return (
            <div key={i} className={`text-xs leading-relaxed pl-2 border-l-2 ${
              isBull ? 'border-emerald-500/50' :
              isBear ? 'border-red-500/50' :
              isJudge ? 'border-primary' : 'border-zinc-500/30'
            }`}>{line}</div>
          )
        })}
      </CardContent>
    </Card>
  ))}
</div>
```

#### 14.4.4 候选股票表扩列 + 展开行丰富

桌面表格列：`# / 代码 / 综合分 / 信号 / 投票分布 / 共识度 / 现价 / PE / 操作`

- "投票分布" 列用紧凑条形（绿/灰/红 比例条 + `4✓ 0= 0✗`）
- "共识度" 列用 Badge：unanimous (绿) / majority (黄) / split (红)
- "现价 / PE" 列**懒加载**：当前可见行的 ticker 调 `/api/fundamentals/<ticker>`（同 v1.6 30s LocalCache）；rendering 列空缺时显示 skeleton

**展开行**（同 row 下方 `<tr colSpan={9}>`，不开新页）：
```
AMD — 大师评分详情
┌大师 1───────────┐ ┌大师 2───────────┐ ┌大师 3───────────┐ ┌大师 4───────────┐
│ Lynch (核心)    │ │ Buffett (核心)  │ │ Munger (核心)   │ │ Graham (经典)   │
│ [BULL] conf 92% │ │ [BULL] conf 88% │ │ [HOLD] conf 60% │ │ [BEAR] conf 75% │
│ "AMD 在 GARP    │ │ "护城河成型,    │ │ "周期顶部信号   │ │ "PB 6x 已超出   │
│  模型下 PEG     │ │  数据中心利润   │ │  浮现, 需观察   │ │  我的纪律线…"   │
│  0.7 标准入场…" │ │  双位数增长…"   │ │  毛利率…"       │ │                 │
└─────────────────┘ └─────────────────┘ └─────────────────┘ └─────────────────┘

KPI: 现价 $145 · 200-SMA $138 (+5.0%) · PE 28 · ROE 21% · D/E 65
[→ 跑 AI 分析]  [→ 加观察列表]
```

每张大师卡含：
- 大师名 + tier chip（核心 / 进阶 / 经典）
- signal Badge + confidence 数字
- reasoning 完整段（不再 slice，给最大 240 字 + line-clamp-6）
- philosophy 一行（hover 显示）

底部 KPI 行复用 v1.1 `fmtNum / fmtPct` 工具；操作按钮链到 `/analysis?ticker=AMD` 和 `/api/portfolio/track`。

### 14.5 实施清单

| 步 | 范围 | 工时 |
|---|---|---|
| 1 | 后端 `pipeline._aggregate` 加 verdict 计算 + votes/consensus/confidence_range/top_*_argument | ~1h |
| 2 | API `_normalize_v3_candidates` + `/api/screen/v3/results/<id>` payload 加 `run_metadata` | ~30min |
| 3 | 前端 KPI 6 列 + 运行模式 banner + 工具函数 (fmtDuration / consensusBadge / votesBar) | ~45min |
| 4 | 前端 Top 5 圆桌 grid 组件（按 ticker 卡片化 debate_snippets） | ~45min |
| 5 | 前端表格扩列：投票分布条 + 共识 Badge + 现价/PE 懒加载 | ~1h |
| 6 | 前端展开行：4 张大师卡（reasoning 完整 + tier + philosophy）+ KPI 底栏 + 操作按钮 | ~1h |
| 7 | 测试 + npm build + smoke | ~30min |
| **合计** | | **~5h** |

### 14.6 强约束

- 不许动 `_aggregate` 已有字段（`final_score / avg_confidence / guru_signals / roundtable`）—— 仅追加
- 不许改 `RoundtableResult` dataclass 字段名（前端按现有 `consensus/dissent/split/debate_snippets` 渲染）
- 不许新建独立投票详情页路由 —— 仅展开当前行
- 不许吞异常；fundamentals 加载失败该格显示 "—" 不影响其它列
- 现价/PE 懒加载必须用现有 `/api/fundamentals/<ticker>` 30s LocalCache（v1.6 R-perf），不发明新端点

## 15. v1.5 增量：14 大师 prompt 个性化 + 圆桌 cross-examination

### 15.1 现状诊断

`/screener-v3?result=<id>` 候选展开"大师评分详情"四张大师卡虽 v1.4 加了 `framework_lead` 把首屏文字差异化，但深层问题仍在：

| 问题 | 现状 |
|---|---|
| 14 SYSTEM_PROMPT 同质化模板 | 全部"身份 + 哲学 + N 条原则 + 维度打分"——缺反例（什么我会拒绝）、缺决策对白（我自问什么）、缺数字引用要求 |
| SYSTEM_PROMPT 末尾的主题段 | 与 v1.3 `_build_theme_instruction` Rule 1-9 重复 — 同样话说 2 遍稀释注意力 |
| reasoning 三段缺"反转条件" | 段一/段二/段三 已有，但缺"何种新事实会改变结论"（可证伪条件）|
| 圆桌 1 轮单方主张 | bull → bear → judge，没有 bull 反驳 bear 的轮次，**没有真实辩证** |
| judge prompt 4 题 | 只问主题/龙头/胜方/否定，**不要求 quote 双方最强证据** + 不要求"何种新事实改变结论" |

参考 [analysis-rendering v1.6 OverviewCard](./analysis-rendering.md) 的执行总结结构化思路 + tradingagents 上游 `bull_researcher`/`bear_researcher`/`research_manager` 三 agent 分工的"具体证据 + 可证伪"原则。

### 15.2 设计目标（用户确认）

- 路径 B：结构化重构（不改 schema / pipeline / data，仅 prompt + 拼装）
- 圆桌加 Round 3 bull rebuttal（每 contested ticker 多 1 次 LLM call ~$0.02）
- anti_patterns / decision_style 直接合成符合大师风格的中文版（不引用真实 letter）
- 14 大师全做（一步到位）

### 15.3 BaseGuruAgent 字段升级

`stock_trading_system/screener/v3/guru_agents/base.py`：

```python
class BaseGuruAgent:
    # 已有
    name: str
    display_name: str
    philosophy: str
    principles: list[str] = []
    motto: str = ""
    avatar_initials: str = ""
    avatar_color: str = "#888"
    framework_lead: str = ""    # v1.4

    # v1.5 新增 ────────────────────────────────────────
    anti_patterns: list[str] = []   # 立刻拒绝信号 (3 条)，命中任一应返 bearish/neutral
    decision_style: list[str] = []  # 招牌自问 (2-3 条)，reasoning 段一须融入至少 1 条
    evidence_demands: str = ""      # 强制 quote 哪些 sub_analysis 数字
```

### 15.4 SystemMessage 拼装顺序（追加新块）

`_llm_reason` SystemMessage 组合：
```
1. SYSTEM_PROMPT          # per-guru 身份 + 哲学（删除末尾主题段）
2. anti_pattern_block     # v1.5 新增
3. decision_style_block   # v1.5 新增
4. evidence_demand_block  # v1.5 新增
5. theme_instruction      # v1.3
6. coverage_caveat        # v1.4
7. reasoning_format       # v1.4 升级到 4 段（v1.5）
8. schema_instruction     # v1.0
```

新增 helper：
```python
def _build_anti_pattern_block(anti_patterns: list[str]) -> str:
    if not anti_patterns:
        return ""
    items = "\n".join(f"- {p}" for p in anti_patterns)
    return f"""

你的反例守则（满足任一立刻给 bearish 或 neutral，无论财务多漂亮）：
{items}
若命中任一反例，必须在 reasoning 段三或段四明确指出，并在 sub_analyses
新增一项 {{"name": "anti_pattern_hit", "score": 0-3, "details": "..."}}。
"""


def _build_decision_style_block(decision_style: list[str]) -> str:
    if not decision_style:
        return ""
    items = "\n".join(f"- {s}" for s in decision_style)
    return f"""

你的决策对白（在 reasoning 段一中至少融入一条，用引号包起来如 "我会问自己：…"）：
{items}
"""


def _build_evidence_demand_block(evidence_demands: str) -> str:
    if not (evidence_demands or "").strip():
        return ""
    return f"""

证据要求：{evidence_demands.strip()}
若关键数字缺失，请在 sub_analyses 中新增 {{"name": "evidence_gap", "score": 0-3, "details": "缺什么"}}，
不要凭空编造数字；reasoning 段二明确指出"基于现有数据 X，但缺乏 Y"。
"""
```

### 15.5 reasoning 三段升级到四段

`_build_reasoning_format_instruction` 改为：
```
段一(必须): 框架结论（基于 {framework_lead}）+ 至少融入 1 条招牌自问。
段二(必须): 引用 sub_analyses 中的具体数字（按 evidence_demands）。
段三(必须): 主要风险 / 反方观点（含 anti_pattern 命中提示，若有）。
段四(必须): "何种新事实会改变我的结论" —— 1 句话明确说出 1-2 个可观察的反转条件
            （如 "若下季度 ROE 跌破 15%，我会转 neutral"；"若行业新进入者拿走 5% 份额，护城河结论作废"）。
```
全文 280-540 字（4 段比 3 段允许略长）。

### 15.6 14 大师内容（v1.5 合成版）

每位大师追加 `anti_patterns` (3 条) / `decision_style` (2-3 条) / `evidence_demands` (1 段)。完整内容见 §15.10 附录。摘要：

| Guru | framework_lead (v1.4 已有) | anti_patterns 摘要 | decision_style 摘要 |
|---|---|---|---|
| Buffett | 护城河 / 自由现金流 / 安全边际 | 看不懂的科技 / PE>25 / 管理层吹回购但 ROIC 5 年没改善 | 持有 10 年 / 纽交所关 10 年 / 5 年后护城河更宽窄 |
| Graham | 估值 (PE/PB/NCAV) / 资产负债安全 / 安全边际 | PE>15 / PB>1.5 / 当前流动比<1.5 / 长期债>NCAV | 安全边际≥33% / 防御型还是进取型 / 价格 vs 清算价值 |
| Lynch | 成长阶段分类 / PEG / 散户可理解性 | 看不懂的赛道 / 故事股缺 EPS / 多元恶化 | 10 岁孩子能懂吗 / 哪个成长阶段 / PEG<1 |
| Munger | 商业质量 / 持久竞争优势 / 复杂度规避 | 多 segment 各自需 PhD / 激励错配 / 行业内长期低 ROIC | invert always invert / lollapalooza 叠加 / 复利+长跑 |
| Fisher | 15 questions / scuttlebutt / 长期持有 | scuttlebutt 客户负面 / 短期主义管理层 / 产品周期已过顶 | 15 questions 大半 yes / R&D 出新品 / 信任并放权 |
| Burry | 深度价值 / 数据驱动 / 隐藏资产 | 估值溢价 / 一致看多 / 无 hidden asset 或催化剂 | 自己读 10-K / 远低于隐藏价值 / 寻找市场误解 |
| Ackman | 集中持仓 / 优质企业 / 激进改善 | 资本结构无杠杆 / ROIC 已极高 / 结构性衰退 | 5%+ 集中下注吗 / 我能影响管理层做什么 / 风险报酬 3:1 |
| Wood | 颠覆性创新 / 5 平台 / 长曲线 | 成熟行业优胜者 / EV/EBITDA 高+收入<25% / 无 S 曲线迹象 | 5 平台之一 / 5 年 30%+ CAGR 路径 / 定义新市场 |
| Druckenmiller | 宏观 / 趋势 / 仓位管理 | 宏观逆风 / 主回撤期反向 / 缺催化剂 | 宏观对齐 / 加仓 catalyst 是 / 错了何时止损 |
| Damodaran | DCF / 故事 vs 数字 / 透明假设 | 故事数字不一致 / 隐藏 leverage / WACC 假设过松 | 故事数字一致 / DCF 压力测试 / 估值过程可重现 |
| Pabrai | Dhandho / 低风险高回报 / clone | 估值偏离 / 难理解 / 大量明星投资者退出 | heads i win tails i don't lose / spawn 项目 / clone 成功模式 |
| Taleb | 反脆弱 / 黑天鹅 / 期权性 | 短期低波动+隐藏尾部 / 收入单一来源 / 杠杆放大左尾 | 反脆弱（波动后变强）/ 凸性（损失有限收益无限）/ 避免 fragile |
| Marks | 周期 / 第二层思考 / 风险定价 | 一致看好 / 情绪极度乐观 / 风险溢价偏低 | 周期位置 / 第二层思考市场已知什么 / 风险定价是否充分 |
| Dalio | 原则 / 经济机器 / 全天候 | 与大周期逆向 / 缺多元化对冲 / 高度依赖单一环境 | 哪种宏观会赢/输 / 每种 outcome 压力测试 / 全天候多元化 |

完整文案附录见 §15.10。

### 15.7 删除 SYSTEM_PROMPT 末尾的主题段

每位大师 SYSTEM_PROMPT 末尾的形如以下三句删除（与 `_build_theme_instruction` Rule 1-9 重复）：
```
在本系统中，你的任务不是单独判断一家公司是否优秀，而是判断它是否符合用户指定主题下的投资机会。
如果公司不符合用户主题，应先指出主题不匹配，再按你的投资哲学给出保守结论。
即使公司护城河强，如果它不属于用户指定行业/主题，也不能因为"优秀企业"而给出 bullish。
```

### 15.8 圆桌 cross-examination 三轮 + LLM 裁判强化

`stock_trading_system/screener/v3/roundtable.py`：

```python
def _build_debate_prompt(
    guru_name: str, ticker: str, signal: GuruSignal, role: str,
    query: str = "", spec: dict | None = None,
    opponent_signal: GuruSignal | None = None,
) -> str:
    """v1.5: cross-examination 模式。

    Round 1 (bull, opponent_signal=bear_champion 已知):
        必须 quote 自己 sub_analyses 中至少 1 个具体数字
        + 必须指认对方 reasoning 中**最弱**的一条论据并预留反驳空间
        + 不能跑题到泛公司讨论

    Round 2 (bear, opponent_signal=bull_champion):
        必须 quote 自己 sub_analyses 中至少 1 个具体数字
        + 必须 cross-examine Bull Round 1 引用的具体数字（"你引用的 ROE 22% 我有不同看法因为..."）

    Round 3 (bull rebuttal, role="bull_rebuttal"):
        限 200 字
        必须正面回应 Round 2 的 cross-examination —— 不能跑题到新论点
        必须最后一句明确表态："我维持 bullish"或"我承认 bear 的某点正确，下调到 neutral"
    """
    ...
```

```python
def _build_judge_prompts(
    bull_champion: GuruSignal, bear_champion: GuruSignal,
    bull_rebuttal: str | None,  # v1.5 新增
    query: str = "", spec: dict | None = None,
) -> tuple[str, str]:
    """v1.5: 5 项验收 + 反转条件，禁止"双方都有道理"模糊裁决。

    judge_system 强制输出 5 项:
      1. 主题契合度 (0-10) —— 必须 quote sub_analyses[theme_fit].score
      2. 龙头属性 (是 / 否 / 部分) —— 必须给理由 1 句
      3. 多空胜方 + 胜方最强 1 条数字证据 (verbatim quote 双方 reasoning)
      4. 何种新事实会改变结论 (1-2 个可观察反转条件)
      5. 1 句话最终裁决 (禁止"双方都有道理"模糊措辞)
      限 350 字。
    """
```

`run_roundtable` 在 Round 2 之后、judge 之前，新增 Round 3：
```python
# Round 3 — Bull rebuttal: 强制回应 bear cross-examination
bull_rebuttal_prompt = _build_debate_prompt(
    bull_champion.guru, ticker, bull_champion, "bull_rebuttal",
    query=query, spec=spec, opponent_signal=bear_champion,
)
bull_rebuttal_text: str = ""
if llm_call:
    try:
        bull_rebuttal_text = llm_call(
            f"你是 {bull_champion.guru}，正在反驳对方质疑。",
            bull_rebuttal_prompt,
        )
        snippets.append(f"🟢 {bull_champion.guru} (反驳): {bull_rebuttal_text[:250]}")
    except Exception as e:
        snippets.append(f"🟢 {bull_champion.guru} (反驳): 反驳失败 ({e})")
```

成本：每 contested ticker（v1.4 之后只有 split 才走辩论）多 1 次 quick_think_llm call ≈ $0.01-0.02。Top 5 全 contested 时 +$0.05-0.10。

### 15.9 不动（强约束）

- `GuruSignal` Pydantic schema（含 `signal/confidence/reasoning/sub_analyses/key_metrics/total_score`）
- `RoundtableResult` dataclass（含 `consensus/dissent/split/debate_snippets`）
- `_enforce_theme_fit` / `_aggregate` / `concurrency.run_guru_units` / data bundles
- `pipeline.py` / `cache.py` / `estimator.py`
- 前端任何文件（ResultsView / GuruParallelProgress / ScreenerV3Progress）
- DB schema / API 端点 / TaskStore
- v1.3 主题污染防御（theme_instruction Rule 1-9 / theme_universe / cloud carve-out）
- v1.4 8 处契约缺口修复（classic 模式 / cancel / trigger 校验 / cache stats / real roundtable / unit lifecycle / consensus / data bundle）

### 15.10 14 大师完整 anti_patterns / decision_style / evidence_demands 附录

#### Buffett
```python
anti_patterns = [
    "10 岁孩子无法用一句话解释这家公司在做什么 —— 我会跳过。",
    "估值溢价超过 5 年盈利平均的 25 倍，即使公司是好生意。",
    "管理层在年报中频繁吹嘘资本动作（回购/收购）但 5 年期 ROIC 没改善。",
]
decision_style = [
    "我会问：'我愿意以这个价格买下整家公司并持有 10 年吗？'犹豫则跳过。",
    "我会问：'若纽交所明天关闭 10 年，我还安心持有吗？'",
    "我会问：'5 年后这家公司的护城河会比现在更宽还是更窄？'",
]
evidence_demands = (
    "reasoning 第二段必须引用以下具体数字: ROE 5 年中位数 / "
    "FCF margin / 净负债率（debt_to_equity）/ 收益的稳定性（vs 行业波动）。"
)
```

#### Graham
```python
anti_patterns = [
    "PE 超过 15 或 PB 超过 1.5 —— 即便是稳健成长股，也已超出我的纪律线。",
    "当前流动比率低于 1.5 或长期债务超过净流动资产 —— 财务安全不足。",
    "5 年中有任意 1 年的盈利亏损 —— 一致性失败，不进入选股池。",
]
decision_style = [
    "我会问：'当前价格相对清算价值还有多少安全边际？至少 33% 才下手。'",
    "我会问：'这只股票适合防御型还是进取型投资者？我心中的客户是哪类？'",
    "我会问：'如果市场明天闭市 10 年，靠资产负债表能不能扛过去？'",
]
evidence_demands = (
    "reasoning 第二段必须引用以下数字: PE / PB / 当前流动比率 / "
    "长期债务 vs 净流动资产 / NCAV (流动资产 - 全部负债)。"
)
```

#### Lynch
```python
anti_patterns = [
    "我无法用 2 分钟（two-minute drill）向妻子或邻居解释清楚的赛道或商业模式 —— 不进入名单。",
    "故事很热闹但 5 年 EPS 增长低于 15% —— 故事股不属于我的能力圈。",
    "公司开始'多元恶化'(diworsification) —— 进入与核心业务无关的高风险并购。",
)
decision_style = [
    "我会问：'10 岁孩子能听懂这家公司在做什么吗？听不懂我跳过。'",
    "我会问：'这家公司处在哪个成长阶段——slow grower / stalwart / fast grower / cyclical / asset play / turnaround？'",
    "我会问：'PEG 是否小于 1？高 PE 配高增长才是合理的，否则就是高估。'",
]
evidence_demands = (
    "reasoning 第二段必须引用以下数字: PEG / EPS 5 年增长率 / "
    "营收增长（同店或客户增长）/ 业务一句话描述（必须出现在 reasoning 中）。"
)
```

#### Munger
```python
anti_patterns = [
    "商业模式有多个 segment 各自需要 PhD 才能理解 —— 复杂度过载，跳过。",
    "管理层激励错配信号（如管理层股权占比极低同时频繁套现）—— 利益不对齐。",
    "行业内长期低 ROIC（< 8% 持续 5 年以上）—— 结构性差生意，不值得花脑力。",
]
decision_style = [
    "我会反向思考：'怎样让这笔投资亏钱？把所有失败路径列出来，再看哪条概率最高。'(Invert, always invert)",
    "我会找 lollapalooza effect：'是否有多个独立的力量同时叠加把这家公司推向胜利？'",
    "我会问：'我能不能耐心持有 20 年看复利发酵？短期价格我从不操心。'",
]
evidence_demands = (
    "reasoning 第二段必须引用: ROIC 5 年趋势 / 行业内 ROIC 排名 / "
    "收入集中度（前 3 客户占比）/ 商业模式复杂度评估。"
)
```

#### Fisher
```python
anti_patterns = [
    "scuttlebutt（侧面尽调）显示客户对产品/服务持续负面 —— 一线信号比报表更可靠。",
    "管理层只关注下季度业绩，没有长期 R&D 投入或新产品迭代计划。",
    "公司核心产品已过生命周期顶峰且无新品矩阵接续 —— 增长动力枯竭。",
]
decision_style = [
    "我会问：'对我的 15 questions 至少有 12 个是 yes 吗？少于 12 我跳过。'",
    "我会问：'公司 R&D / 营收占比 vs 行业是否领先？是否在出新产品？'",
    "我会问：'高层是否信任并放权给一线管理者？官僚化的公司无法持续创新。'",
]
evidence_demands = (
    "reasoning 第二段必须引用: R&D / 营收占比 / 营收增长 5 年 / "
    "毛利率 vs 行业中位数 / 行业地位（前 3 / 前 10）。"
)
```

#### Burry
```python
anti_patterns = [
    "估值溢价（PE 高于行业中位数 30%+）—— 我从不付溢价。",
    "卖方一致看多 + 媒体一致追捧 —— 共识太强意味着错误定价的反方。",
    "找不到隐藏价值或反向催化剂（hidden asset, spinoff, distressed debt 等）—— 没有 edge 不下手。",
]
decision_style = [
    "我会自己读 10-K 至少 2 遍，不信卖方报告 —— 数字不会骗人。",
    "我会问：'当前价格远低于我看到的隐藏价值多少倍？至少 2x 才下手。'",
    "我会问：'市场对这家公司的误解在哪？我看到了别人看不到什么？'",
]
evidence_demands = (
    "reasoning 第二段必须引用: book_value / EV/EBITDA / "
    "hidden asset 描述（spinoff / 不动产 / 子公司隐藏估值）/ 卖空利率。"
)
```

#### Ackman
```python
anti_patterns = [
    "资本结构不允许激进改善（如已有强势创始人股权不释放，小股东无杠杆）—— 我无法行动。",
    "ROIC 已经极高（> 25%）且无明显改善空间 —— 我没有 alpha 来源。",
    "商业模式有结构性衰退（如线下零售被电商持续蚕食）—— 我不做衰退行业。",
]
decision_style = [
    "我会问：'这是不是一个值得集中下注 5%+ 仓位的优质标的？'",
    "我会问：'如果我能进入董事会影响管理层，我会做什么改变？这些改变能创造多少价值？'",
    "我会问：'风险报酬比是否至少 3:1？下行明确受限，上行 50%+。'",
]
evidence_demands = (
    "reasoning 第二段必须引用: ROIC / 改善空间（vs 行业最佳）/ "
    "资本结构灵活性（杠杆余地、股权可激活度）/ 5 年 IRR 测算。"
)
```

#### Wood
```python
anti_patterns = [
    "业务模式属于成熟行业的优胜者（如银行、传统制造）—— 没有颠覆潜力，不进入 ARK 名单。",
    "EV/EBITDA 高但收入增长低于 25% —— 高估值无法被高增长支撑。",
    "看不到 S 曲线的迹象（创新指标 / 用户增长 / 渗透率提升曲线）—— 不是颠覆者。",
]
decision_style = [
    "我会问：'这家公司是否落在 5 大颠覆平台之一（基因 / AI / 能源储存 / 区块链 / 机器人）？'",
    "我会问：'未来 5 年 30%+ CAGR 的路径是否清晰？TAM 是否足够大？'",
    "我会问：'这家公司是否在定义一个全新市场，而不只是抢现有蛋糕？'",
]
evidence_demands = (
    "reasoning 第二段必须引用: 收入 CAGR (3-5 年) / TAM 估算 / "
    "R&D / 营收 / 创新指标（专利、用户增长、渗透率）。"
)
```

#### Druckenmiller
```python
anti_patterns = [
    "宏观环境逆风（利率上行、流动性收紧、政策风险）—— 即便公司基本面好我也不下手。",
    "股票处于主要回撤期（>20%）且无明显催化剂转向 —— 不接飞刀。",
    "缺乏明确的 catalyst 触发我的仓位 —— 我从不'希望式持有'。",
]
decision_style = [
    "我会问：'当前宏观环境支持这个仓位吗？利率 / 流动性 / 政策三条线一致吗？'",
    "我会问：'什么 catalyst 会让我加仓 50%？没有清晰答案我不进场。'",
    "我会问：'如果我错了，何时止损？大胆下注但永远准备改变主意。'",
]
evidence_demands = (
    "reasoning 第二段必须引用: 宏观对齐度（利率/流动性/政策）/ "
    "相对强弱（vs SPX 或行业 ETF）/ 期权 IV / 流动性指标。"
)
```

#### Damodaran
```python
anti_patterns = [
    "公司故事和财务数字明显不一致（如 dreaming narrative 但增长不到 5%）—— 估值假设站不住。",
    "隐藏杠杆（off-balance-sheet debt / lease commitments）未被市场充分定价。",
    "DCF 关键假设（WACC / terminal growth）过于乐观，压力测试下立刻崩。",
]
decision_style = [
    "我会问：'故事和数字一致吗？dreaming narrative 必须有相应增长支撑，否则只是想象。'",
    "我会问：'我的 DCF 假设是否经得起压力测试？terminal growth 高于 GDP 增速我会警惕。'",
    "我会问：'我的估值过程是否透明且可重现？任何人按我的假设算都得相同答案？'",
]
evidence_demands = (
    "reasoning 第二段必须引用: WACC / terminal growth / "
    "FCF yield / DCF base/bull/bear 三档估值结果。"
)
```

#### Pabrai
```python
anti_patterns = [
    "估值偏离 P/FCF 合理范围（> 15x）—— Dhandho 框架要求低估值入场。",
    "业务难以理解（多 segment 或新兴技术）—— 我只 clone 我能完全理解的生意。",
    "已有大量明星投资者退出（13F 显示 5+ tier-1 投资者减仓）—— 警示信号。",
]
decision_style = [
    "我会问：'是不是 heads I win, tails I don't lose much？下行 < 30%，上行 > 100%。'",
    "我会问：'这是不是 spawn 项目（小钱大潜力）？早期 sizing 小但允许加仓。'",
    "我会问：'有没有成功的商业模式可以 clone？模仿胜过创新。'",
]
evidence_demands = (
    "reasoning 第二段必须引用: P/FCF / 下行测算（多少损失上限）/ "
    "上行测算（5 年 IRR）/ 业务可重复性（是否有同类成功案例）。"
)
```

#### Taleb
```python
anti_patterns = [
    "短期波动率低但隐藏尾部风险（如某地缘 / 监管事件能击穿 50%）—— fragile 类。",
    "收入依赖单一来源（前 1 客户 > 30% 或单一国家 > 70%）—— 抗冲击能力不足。",
    "高杠杆放大左尾（debt/equity > 1 且现金流不稳）—— 一次黑天鹅就清零。",
]
decision_style = [
    "我会问：'这投资是否反脆弱？短期波动后它是变弱还是变强？'",
    "我会问：'是否提供凸性（convexity）？损失有限，但收益无上限或非常大？'",
    "我会问：'我是否避免了 fragile 类（隐藏负面 skew、leverage 放大）？'",
]
evidence_demands = (
    "reasoning 第二段必须引用: max drawdown 5 年 / 收入集中度（前 3 客户/区域）/ "
    "leverage 倍数 / 期权类 upside 是否存在。"
)
```

#### Marks
```python
anti_patterns = [
    "市场一致看好（卖方 buy 评级 > 80% + 媒体追捧）—— 第二层思考说我应该警觉。",
    "投资者情绪极度乐观（VIX 低位 + IPO 火爆 + 散户活跃）—— 周期顶部信号。",
    "风险溢价偏低（高收益债 spread vs 国债 < 历史 25 分位）—— 风险定价不充分。",
]
decision_style = [
    "我会问：'当前周期处于哪个位置？bottom 我激进，top 我退场。'",
    "我会问：'第二层思考——市场已经知道什么？我看到的是新信息还是共识？'",
    "我会问：'风险定价是否充分？补偿是否匹配我承担的风险？'",
]
evidence_demands = (
    "reasoning 第二段必须引用: PE 相对历史百分位 / 风险溢价（vs 国债）/ "
    "投资者情绪指标（VIX、AAII bull/bear）/ 当前周期位置评估。"
)
```

#### Dalio
```python
anti_patterns = [
    "与大债务周期逆向（如长债务周期顶部加杠杆 / 通缩期持有名义资产）。",
    "组合缺乏多元化对冲（all-in 单一资产类别 / 单一宏观环境）。",
    "高度依赖某种环境（如低利率 / 高增长）才能成立 —— 环境转换就崩盘。",
]
decision_style = [
    "我会问：'这投资在哪种宏观环境会赢（增长高 vs 低、通胀高 vs 低 4 象限）？哪种环境会输？'",
    "我会问：'我对每种 outcome 都做了 stress test 吗？没有备份计划不下手。'",
    "我会问：'在全天候组合中这个标的扮演什么角色？分散还是放大现有暴露？'",
]
evidence_demands = (
    "reasoning 第二段必须引用: 宏观环境契合度（增长 + 通胀 4 象限定位）/ "
    "利率敏感性 / 通胀敏感性 / 与组合现有持仓的相关性。"
)
```

### 15.11 实施清单

| 步 | 范围 | 工时 |
|---|---|---|
| 1 | `base.py` 加 3 字段 + 3 helper + `_llm_reason` 拼装 + reasoning 三段→四段 | ~45min |
| 2 | 14 大师文件追加 3 字段 + 删除 SYSTEM_PROMPT 末尾主题段 | ~2h |
| 3 | `roundtable._build_debate_prompt` 升级（加 opponent_signal 参数 + cross-examination 模式） | ~30min |
| 4 | `roundtable._build_judge_prompts` 升级（5 项验收 + 反转条件） | ~20min |
| 5 | `roundtable.run_roundtable` 加 Round 3 bull rebuttal | ~30min |
| 6 | 测试：`test_v15_prompt_blocks.py` 12 case + `test_roundtable_cross_examination.py` 6 case + `test_guru_signal_uniqueness.py` 更新（验首屏 reasoning 含招牌自问） | ~1h |
| **合计** | | **~5h** |

### 15.12 验收

```bash
pytest tests/screener/v3/ -q  # 含 v1.4 165 case + v1.5 新增 18 case 全绿
npm run build  # 前端无变化但应仍通
```

实测：
1. 跑一次 V3 选股（agent_rt 模式 + Top 5 全 contested），观察任一展开行 4 张大师卡：
   - reasoning 段一含招牌自问（带引号）
   - reasoning 段二引用具体数字（PE / ROE / PEG 等按大师不同）
   - reasoning 段四明确 1-2 个反转条件
   - sub_analyses 含 `theme_fit` + 可能 `anti_pattern_hit` / `evidence_gap`
2. 圆桌 grid 中任一 contested 卡的 debate_snippets 有 3 条 + 裁判：
   - 🟢 bull 主张
   - 🔴 bear cross-examine（quote 数字）
   - 🟢 bull rebuttal（明确表态维持/下调）
   - ⚖️ 裁判 5 项裁决（含反转条件）

## 13. 版本历史

| 版本 | 日期 | 变更 |
|---|---|---|
| v1.0 | 2026-04-19 | 初版：新建 `screener/v3/` + 14 大师 agent（12 清洁重写 + 2 自建）+ 并发缓存流式 + 预选面板 + 成本预估 + 圆桌辩论 + 经典模式兼容保留 |
| v1.1 | 2026-04-19 | 复用审计修订（依据 [engineering-principles.md](../engineering-principles.md) §5.1）：§4.1 改用 `ChatOpenAI.with_structured_output()`；§4.3 改用 `tenacity` 重试；§4.9 复用 TradingAgents 辩论图节点；新增 §12 复用清单（自写 LOC 减 ~31%）|
| v1.2 | 2026-05-01 | 选股结果决策透明化（用户 2026-05-01 提，~5h）：现状信号列 `-` / 看多看空 KPI 全 0 / 大师数都是 4 / 圆桌辩论看不到。后端 `_aggregate` 加 verdict 计算（bullish/bearish/neutral/split）+ votes 计数 + consensus chip + confidence_range + top_bull/bear_argument；payload 加 `run_metadata` (mode/llm_calls/cache_hit_pct/duration/gurus_used)。前端 4 块视觉：(1) KPI 扩 6 列（候选/均分/看多/看空/中性/共识率）；(2) 运行模式 banner（mode chip + LLM call + cache 命中 + 耗时 + 大师 Avatar）；(3) Top 5 圆桌独立 grid 按 ticker 卡片化（debate_snippets 按 🟢🔴⚖️ 分色边框）；(4) 候选表扩列（投票分布条 + 共识 Badge + 现价/PE 懒加载）+ 展开行 4 大师卡（完整 reasoning + tier + philosophy）+ KPI 底栏 + 跳 AI 分析 / 观察列表按钮。复用 `/api/fundamentals/<ticker>` 30s LocalCache（v1.6 R-perf）；不动 `RoundtableResult` dataclass / `_aggregate` 已有字段。|
| v1.3 | 2026-05-02 | 选股主题污染修复（联动 [screener-v2.md](./screener-v2.md) v1.2，~3h）：`存储龙头股` 等主题查询在 v3 链路漏掉主题约束 → BRK-B/JPM/V/MA/UNH/WMT/PG broad-market 蓝筹混入。三层防御：(A) `BaseGuruAgent._build_theme_instruction(query, spec)` 渲染 query + filter_spec 进 SystemMessage + theme_fit SubAnalysis 强制 + broad-market 黑名单 + required pure-play (MU/WDC/STX/SNDK) + cloud carve-out；4 个具体 guru 调用签名加 `nl_query`/`filter_spec` 透传；(B) `_enforce_theme_fit(signal, context)` 后处理：theme_fit<4 score≤60 + bullish→neutral；theme_fit<2 score≤45 + bullish→bearish；(C) `roundtable._build_debate_prompt` 加 query/spec + 3 个 theme-fit 强制问题；(D) `ScreenerV3Pipeline._get_candidates` 异常路径走 v2 `theme_fallback_universe`。**不动** 14 大师 prompt、aggregator 字段、RoundtableResult dataclass。|
| v1.4 | 2026-05-03 | **8 处契约缺口修复（用户 2026-05-03 提，~6h）**：v1.0–v1.3 之后审计仍剩 8 个 P1/P2 缺口。线性根因：(1) `_run_classic_mode` 只 `return {results: []}` —— **classic 模式选股永远空结果**；(2) `cancel_check` 只在 phase 边界检查，已派单的 unit 无视取消、用户点停止后任务最终 status=success（payload 里 status=cancelled 但 TaskManager 不识别）；(3) `/api/screen/v3/trigger` 只查 `gurus_required`，**接受任意未知 guru id**（提交 `["xxx"]` 静默丢弃后空结果，与 1 互相加重）+ candidate_n/mode 也无校验；(4) `metrics.cache_hits` 用 `confidence==0 and "失败" in reasoning` **错把 LLM 失败当 cache hit**——真实 cache hit 与失败 fallback 算不开；(5) `_run_roundtable` 是 inline 模板（共识/异议靠 bullish/bearish 数量比，不调 `roundtable.run_roundtable` 模块函数），**14 大师圆桌辩论 + LLM 裁判从未真正运行**；(6) `concurrency.run_guru_units` 只在结尾 `on_unit_done`，没有 unit_start —— 前端矩阵看不到"运行中"，且 LLM 失败被 `_error_signal` 伪装成 `signal=neutral, confidence=0` 的 done 事件，**failed 状态被吞**；(7) `_aggregate` 把 `n_bull > n_bear + n_neu` 当 unanimous，**neutral 被当成 bullish 反方**——5 中性 + 1 看多变成"unanimous bullish"；(8) `_prepare_data_bundles` 只填 `quote/fundamentals_current`，`fundamentals_history/news_recent` 永远空 → 大师没历史 / 没新闻照样给出"基本面强劲"高分。修复（**复用优先**）：(A) **classic 模式真实复用 V2 阈值链路**——`_run_classic_mode` 直接 `import build_gurus from screener.v2.gurus`，对 candidates 调 V2 `BuffettGuru/GrahamGuru/LynchGuru` 的 `evaluate(ticker, fundamentals, context)` → `GuruMatch.match_pct` 映射成 `GuruSignal(signal/total_score/confidence)` 进入既有 `_aggregate`；不开新 LLM call（V2 评估本就是 threshold-based）。(B) **cancel 真实生效**——pipeline 在每 unit / 每 ticker / 每 phase 边界 `_check_cancelled() raise CancelledError`，concurrency `run_guru_units` 内部循环也加 `cancel_check()`；worker 捕获自定义 `ScreenerCancelled` → 持久化部分结果（已完成 unit）→ raise `_CancelledError` 让 TaskManager 标 `cancelled`；UI `<ScreenerRunningView>` 顶部加 `[停止]` 按钮 → POST `/api/tasks/<task_id>/cancel`；剩余未派单 unit 不再消耗 token，已完成结果在 `?result=<task_id>` 仍可看（partial=true banner）。(C) **trigger 校验**——14 guru 注册表交集 + 未知返 400 `invalid_guru` 列出错误项 + `candidate_n ∈ {10,20,30,50}` + `mode ∈ {classic, agent, agent_rt}` + `with_roundtable ↔ mode==agent_rt` 一致性。(D) **真实 cache 统计**——`run_guru_units` 返 `(signals, RunStats)`：`RunStats(cache_hits, new_calls, failed_units, total_units)`；pipeline.metrics 加 `total_units / new_llm_calls / cache_hits / failed_units`；`/api/screen/v3/results _v3_run_metadata` 用 `new_llm_calls` 替代 legacy `llm_calls`，cache_hit_pct = cache_hits/total_units。(E) **真实 roundtable**——`pipeline._run_roundtable` 改为 `await roundtable.run_roundtable(top_signals, llm_call=judge_llm, on_progress=..., query=..., spec=...)`；LLM 失败时 result 加 `roundtable_status: "fallback"` 字段（前端 banner 提示）；不动 `RoundtableResult` dataclass。(F) **unit 生命周期事件**——`run_guru_units` 在每 unit 进入 `_one` 协程时 emit `guru_unit_start({guru, ticker})`；`_invoke` 三次重试全失败 → emit `guru_unit_failed({guru, ticker, error})` 并把 fallback 标 `cached=False, failed=True`；worker 转发；`<GuruParallelProgress>` 状态机加 `running / done / cached / failed` 4 态颜色。(G) **正确 consensus**——`unanimous` 仅当 `top_count == total`（含 all-neutral）；`majority` = top 票最多但 < total；`split` = 最高票并列（尤其 bullish==bearish）；新增 `tests/screener/v3/test_consensus_edges.py`。(H) **数据包补深度**——`_prepare_data_bundles` 加 `news_recent`（DataRouter `get_news` 5 条头条）+ `price_history_summary`（30/90/180-day return + sma200_distance）+ `sector_industry`（fundamentals.sector / industry）；如 provider 返空，bundle 字段保 `[] / null`，`BaseGuruAgent._llm_reason` 检测空字段 → SystemMessage 追加 "**历史/新闻数据不足，不得仅凭快照下高分**"。**所有改动追加式**——不动 `GuruSignal` dataclass、`/api/screen/v3/results` DTO 已有字段、ResultsView 前端契约。复用：V2 gurus（B/G/L）+ existing `roundtable.run_roundtable` + DataRouter.get_news + TaskManager `_CancelledError`；自写 ~450 LOC（含测试）|
