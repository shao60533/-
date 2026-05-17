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

## 15. v1.3 增量：结果页头部合并 + 圆桌/大师中文化 + 股票名称暴露（用户 2026-05-17 提）

### 15.1 现状诊断（v1.2 在生产用一段时间后的反馈）

| 症状 | 根因 |
|---|---|
| 结果页顶部"七卡视觉"（标题行 1 + 6 个 `<Stat>` KPI 卡） | [stat.tsx:17](../../stock_trading_system/web/frontend/src/components/ui/stat.tsx#L17) `<Stat>` 内部就是 `<Card>`，v1.2 §14.4.1 用 6 个 `<Stat>` 排列 = 视觉上 6 张独立卡片，加上未包裹的 header row，整页头部占用过高 |
| 圆桌辩论 verdict `CONSENSUS` / `CONTESTED` 是英文 | v1.2 §14.4.3 落地代码 [`ScreenerV3Page.tsx`](../../stock_trading_system/web/frontend/src/islands/screener-v3/ScreenerV3Page.tsx) 直接用了 spec 草案中的英文 badge 标签，没本地化 |
| 14 大师 signal 是 `BULLISH` / `BEARISH` / `NEUTRAL`（来自 `(s.signal).toUpperCase()`） | v1.0 GuruSignal `signal` 字段是英文枚举（bullish/bearish/neutral），前端直接 `.toUpperCase()` 透传，没在表示层抽象成中文 |
| 候选/圆桌/展开卡都只显示 ticker code（如 `AMD` / `601318`） | v1.2 设计聚焦数据透明化，假设用户认得代码；A 股六位数字与美股缩写混合，新用户/移动端用户识别成本高。`/api/fundamentals/<ticker>` 已返 `short_name` 但 v1.2 仅在 KPI 底栏展示 |

### 15.2 设计约束

**复用优先**：
- 股票名称走已有的 `/api/fundamentals/<ticker>` `short_name` 字段（v1.2 已经在每个候选 ticker 上调用并缓存到 `funds` state）。**不发明新端点、不引入新缓存**
- 三档 signal 仍由后端 `_derive_candidate_signal` / `GuruSignal.signal` 提供（bullish / bearish / neutral / buy / sell / hold 兼容），**前端仅在表示层映射成中文**
- "共识 / 不共识"二值仍由 `RoundtableResult.split: bool` 决定，**不改后端契约**

**不动清单**：
- 后端 `_aggregate` / `RoundtableResult` / API DTO（v1.2 §14.6 已声明的强约束继续生效）
- v1.2 已有的 `signalBadge()` 颜色映射 / `consensusBadge()` / `VotesBar` / `CandidateExpanded` 整体结构
- 桌面表格的 8 列布局（投票分布 / 共识度 / 现价 / PE 列保留）

### 15.3 前端 4 项变更

#### 15.3.1 顶部 7 卡 → 1 卡合并

把原本独立的"返回 + 标题 + 日期"flex 行 + 6 个 `<Stat>` KPI tile 合并到**一个** `<Card>`：

```tsx
<Card>
  <CardHeader>
    <div className="flex items-center gap-3 flex-wrap min-w-0">
      <Button variant="ghost" size="sm" onClick={...}><ArrowLeft /></Button>
      <h1 className="text-xl font-bold truncate min-w-0 flex-1">选股结果</h1>
      <Badge variant="muted" className="shrink-0">{created_at}</Badge>
    </div>
  </CardHeader>
  <CardContent>
    <div className="grid grid-cols-3 md:grid-cols-6 gap-3 grid-collapse-mobile">
      <SummaryKpi label="候选数" value={...} />
      <SummaryKpi label="平均分" value={...} />
      <SummaryKpi label="看多"   value={...} tone="bull" />
      <SummaryKpi label="看空"   value={...} tone="bear" />
      <SummaryKpi label="中性"   value={...} />
      <SummaryKpi label="共识率" value={...} />
    </div>
  </CardContent>
</Card>
```

新建 `SummaryKpi` 替代 `<Stat>`：纯 div（label + value），不嵌套 Card；`tone="bull" | "bear" | "neutral"` 决定数值颜色（绿/红/默认），label 沿用 `<Stat>` 的 `uppercase tracking-wider text-muted` 风格。

栅格 `grid-cols-3 md:grid-cols-6 grid-collapse-mobile`：
- ≥768px（md）：一行 6 列
- 576–767px（小平板）：两行各 3 列（v1.2 是 2 行 + 2 行 + 2 行各 2 列，现在更扁平）
- ≤575.98px（手机）：[`styles/index.css:151`](../../stock_trading_system/web/frontend/src/styles/index.css#L151) `grid-collapse-mobile` 的 `1fr !important` 强制折叠为单列 6 行——和 v1.2 行为一致

**真正的空间收益不在栅格列数，而在外层包裹**：v1.2 = 6 个 `<Stat>`(每个=Card 带 border+CardContent padding) → v1.3 = 1 个外 Card + 6 个无包裹 div，手机端从"6 张独立卡纵向堆叠"变成"1 张卡内 6 行 KPI"，省掉 5 圈 border + 5 份 Card padding。

#### 15.3.2 圆桌辩论 verdict 中文化 + 大师名单

verdict badge：
- `rt.split === true` → `不共识`（红 / sell variant）
- `rt.split === false` → `共识`（绿 / buy variant）

把现有"共识 N 人 · 异议 N 人"摘要保留，新增**两行明确的大师名单**：

```tsx
{consensusGurus.length > 0 && (
  <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
    <span className="text-emerald-400 shrink-0">共识方:</span>
    <span className="text-foreground/90">{consensusGurus.join("、")}</span>
  </div>
)}
{dissentGurus.length > 0 && (
  <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
    <span className="text-red-400 shrink-0">异议方:</span>
    <span className="text-foreground/90">{dissentGurus.join("、")}</span>
  </div>
)}
```

辩论 snippets（🟢/🔴/⚖️ 分色边框）**完全保留**——这部分本来就是中文的（来自 `GuruSignal.reasoning[:300]` + 中文裁判 prompt）。

#### 15.3.3 14 大师 signal 三档中文化

新增表示层 helper（**不动**底层枚举）：

```tsx
function signalLabelZh(signal: string | null | undefined): string {
  const s = (signal || "").toLowerCase()
  if (s.includes("bull") || s.includes("buy")) return "看多"
  if (s.includes("bear") || s.includes("sell")) return "看空"
  return "中性"  // 包含 hold / neutral / 空值
}
```

替换 3 处英文展示（全部 badge variant 仍走 `signalBadge()`，颜色不变）：
- 桌面表格"信号"列 `<Badge>{sig.toUpperCase()}</Badge>` → `<Badge>{signalLabelZh(sig)}</Badge>`
- 移动端候选卡片同上
- `CandidateExpanded` 每位大师 `<Badge>{(s.signal ?? "—").toUpperCase()}</Badge>` → `<Badge>{signalLabelZh(s.signal)}</Badge>`

**注意**：v1.0 GuruSignal 设计上有 buy/sell/hold 同义词（兼容某些大师 prompt 输出），helper 用 `includes("bull") || includes("buy")` 等保兼容性。

#### 15.3.4 股票中文名称暴露

新增 helper（防御性 fallback）：

```tsx
function stockName(f: Record<string, unknown> | null | undefined): string {
  if (!f) return ""
  const n = f["short_name"] ?? f["shortName"] ?? f["long_name"] ?? f["longName"] ?? f["name"]
  return typeof n === "string" ? n : ""
}
```

接入点（**全部复用 v1.2 已有的 `funds` state**，无新 fetch）：

| 位置 | 渲染 | 缺失时降级 |
|---|---|---|
| 圆桌辩论卡片标题 | `<span className="font-mono">{ticker}</span> · {name}` | 不显示 `·` 之后的部分 |
| 桌面候选表 ticker 列 | ticker 加粗 + 下一行小字显示 name（`max-w-[140px] truncate`） | 不显示第二行 |
| 移动端候选卡 ticker 行 | `{ticker} · {name}`（同一行 truncate） | 只显示 ticker |
| 候选展开卡标题 | `{ticker} · {name} — 大师评分详情` | 不显示 `·` |

**为什么不在 KPI 顶部显示主体公司名**：那是聚合结果，不绑某只 ticker。

### 15.4 实施清单

| 步 | 范围 | 工时 |
|---|---|---|
| 1 | 新 helper：`signalLabelZh()` + `stockName()` | 5min |
| 2 | 新 `SummaryKpi` 内联 KPI 组件（不嵌 Card） | 10min |
| 3 | `ResultsView` 顶部 7 卡 → 1 卡（替换 header + 6 `<Stat>`） | 15min |
| 4 | 圆桌辩论卡片：badge 中文化 + 共识/异议大师名单 + 标题加 name | 20min |
| 5 | 14 大师 signal 三处替换为 `signalLabelZh()` | 5min |
| 6 | 候选列表 4 处（桌面表 / 移动卡 / 展开标题 / 圆桌标题）加 name | 15min |
| 7 | 删未用 `Stat` import | 1min |
| 8 | tsc -b / vite build / vitest run + 提交 | 15min |
| **合计** | | **~1.5h** |

### 15.5 强约束

- **不动**后端 schema / DTO / `_aggregate` / `RoundtableResult` —— 全部仅前端 UI 层
- **不发明**新 API 端点；`stockName()` 100% 复用 `/api/fundamentals/<ticker>` 30s LocalCache
- **不删** v1.2 已有的 `signalBadge()` / `consensusBadge()` / `VotesBar` / `CandidateExpanded` 结构
- **不引入**新依赖（连 `lucide-react` icon 都没新增）
- `stockName()` / `signalLabelZh()` 必须对 null / undefined / 空字符串 / 未知 signal 全部安全降级（不能让一只缺基本面的 ticker 把整行渲染崩掉）
- 桌面表 ticker 列加 name 后**不许**让其它 8 列被挤出（`max-w-[140px] truncate` 钉死宽度）
- "共识"中文标签**只用** `rt.split` 字段，**不重新推**（避免与后端 `consensus_gurus` 计算逻辑不一致）

### 15.6 与 v1.2 spec 的显式覆盖

| v1.2 落点 | v1.2 写的是 | v1.3 改为 | 原因 |
|---|---|---|---|
| §14.4.1 KPI 6 列 | 6 个 `<Stat>` 独立卡 | 1 卡内 6 个 `SummaryKpi` | 视觉密度（用户 2026-05-17） |
| §14.4.3 圆桌 verdict badge | `CONSENSUS` / `CONTESTED`（英文） | `共识` / `不共识` | 全站中文一致性 |
| §14.4.4 大师 signal badge | `BULLISH` / `BEARISH` / `NEUTRAL`（英文） | `看多` / `看空` / `中性` | 同上 |
| 全局 | 仅 `ticker` 显示 | `ticker · short_name` 多处暴露 | 用户识别成本（A 股六位数字尤甚） |

## 13. 版本历史

| 版本 | 日期 | 变更 |
|---|---|---|
| v1.0 | 2026-04-19 | 初版：新建 `screener/v3/` + 14 大师 agent（12 清洁重写 + 2 自建）+ 并发缓存流式 + 预选面板 + 成本预估 + 圆桌辩论 + 经典模式兼容保留 |
| v1.1 | 2026-04-19 | 复用审计修订（依据 [engineering-principles.md](../engineering-principles.md) §5.1）：§4.1 改用 `ChatOpenAI.with_structured_output()`；§4.3 改用 `tenacity` 重试；§4.9 复用 TradingAgents 辩论图节点；新增 §12 复用清单（自写 LOC 减 ~31%）|
| v1.2 | 2026-05-01 | 选股结果决策透明化（用户 2026-05-01 提，~5h）：现状信号列 `-` / 看多看空 KPI 全 0 / 大师数都是 4 / 圆桌辩论看不到。后端 `_aggregate` 加 verdict 计算（bullish/bearish/neutral/split）+ votes 计数 + consensus chip + confidence_range + top_bull/bear_argument；payload 加 `run_metadata` (mode/llm_calls/cache_hit_pct/duration/gurus_used)。前端 4 块视觉：(1) KPI 扩 6 列（候选/均分/看多/看空/中性/共识率）；(2) 运行模式 banner（mode chip + LLM call + cache 命中 + 耗时 + 大师 Avatar）；(3) Top 5 圆桌独立 grid 按 ticker 卡片化（debate_snippets 按 🟢🔴⚖️ 分色边框）；(4) 候选表扩列（投票分布条 + 共识 Badge + 现价/PE 懒加载）+ 展开行 4 大师卡（完整 reasoning + tier + philosophy）+ KPI 底栏 + 跳 AI 分析 / 观察列表按钮。复用 `/api/fundamentals/<ticker>` 30s LocalCache（v1.6 R-perf）；不动 `RoundtableResult` dataclass / `_aggregate` 已有字段。|
| v1.3 | 2026-05-17 | 结果页头部紧凑化 + 圆桌/大师中文化 + 股票名称暴露（用户 2026-05-17 提，~1.5h）：**纯前端**，零后端契约改动。(1) 顶部"标题行 + 6 个 `<Stat>` 独立卡"合并为单 `<Card>`，新建 `SummaryKpi` 内联组件替代 `<Stat>`（`<Stat>` 内嵌 Card 是七卡视觉的根因）；移动端栅格 `grid-cols-3` 改两行 3 列。(2) 圆桌辩论 verdict badge `CONSENSUS`/`CONTESTED` → `共识`/`不共识`（仅本地化标签，`rt.split` 真值不动）；新增"共识方:"/"异议方:" 两行中文展示 `consensus[]` / `dissent[]` 大师名单（v1.0 已存的字段，v1.2 只显示了人数没列名字）。(3) 14 大师 signal `BULLISH`/`BEARISH`/`NEUTRAL`（`(s.signal).toUpperCase()`）→ `看多`/`看空`/`中性`，新加 `signalLabelZh()` helper（buy/bull→看多 / sell/bear→看空 / else→中性，对空值降级），替换桌面表 + 移动卡 + 展开卡 3 处。(4) 股票中文名 4 处暴露（圆桌标题 / 桌面表 ticker 下小字 / 移动卡 ticker 同行 / 展开卡标题），全部复用 v1.2 已有的 `funds` 缓存（`/api/fundamentals/<ticker>`），新加 `stockName()` 多 key fallback helper（`short_name`/`shortName`/`long_name`/`longName`/`name`）。显式覆盖 v1.2 §14.4.1（6 卡→1 卡）/§14.4.3（英文 verdict→中文）/§14.4.4（英文 signal→中文）。验证：`tsc -b` 0 err / `vite build` 成功（screener-v3 chunk 46.19KB）/ `vitest run` 37/37 pass。|
