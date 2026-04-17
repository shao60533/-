# 自我迭代 Agent 能力模块 — 技术方案

> **版本**: 3.0  
> **日期**: 2026-04-18  
> **状态**: 已确认  
> **定位**: 包裹 TradingAgents 7-Agent 管线的独立迭代能力，可开关  
> **原则**: 能复用就复用，能引用成熟代码就不从 0 开发  
> **参考**: atlas-elenchus（github.com/leonbreukelman/atlas-elenchus）+ 现有 paper trade 系统

---

## 一、核心思想

**prompt 是权重，Sharpe 是 loss，git 是优化器。**（ATLAS / Karpathy 哲学）

在现有 TradingAgents 管线**外围**叠加三层进化机制：

| 层 | 做什么 | 频率 | 新建 or 复用 |
|----|--------|------|-------------|
| **Agent Scorer** | 提取每个 agent 的方向信号，记录后续表现 | 每次分析后 | **新建**（唯一核心新模块） |
| **Darwinian 权重** | top 25% 升权 × 1.05 / bottom 25% 降权 × 0.95 | 每日盘后 | 采用 atlas-elenchus 常量 |
| **Meta Agent** | qwen3.6-plus 改写最差 agent 的 prompt | 每周日 | 采用 atlas-elenchus MUTATOR_SYSTEM_PROMPT |

A/B 验证 → **复用 paper trade sessions 对比**，不新建验证框架。

---

## 二、复用清单

### 2.1 直接复用（零新代码）

| 需求 | 已有组件 | 位置 |
|------|---------|------|
| 信号→交易→P&L 全链路 | `analysis_tracked` + `paper_trade_trades` | `session_store.py:147-197` |
| 每日权益快照 | `paper_trade_equity` | `session_store.py:169` |
| Sharpe / 最大回撤 / 胜率 | `compute_session_metrics()` | `metrics.py:11-112` |
| 每 ticker 命中率 | `ticker_summary()` | `tracking.py:81-107` |
| 分析后自动追踪钩子 | `auto_track_analysis()` | `tracking.py:17-56` |
| A/B 对比基础设施 | paper_trade_sessions 的 `config_json` + `metrics_json` | `session_store.py:29-49` |
| 价格获取 | `DataRouter.get_price()` | `data/data_manager.py` |

### 2.2 从 atlas-elenchus 直接采用

| 组件 | 参考文件 | 采用内容 |
|------|---------|---------|
| Darwinian 常量 | `src/agent.py` | `WEIGHT_MIN=0.3, MAX=2.5, BOOST=1.05, DECAY=0.95` |
| Prompt 改写 prompt | `src/autoresearch.py` | MUTATOR_SYSTEM_PROMPT 全文（适配中文） |
| mutate → evaluate → commit/revert 流程 | `src/autoresearch.py` | 流程逻辑，用 DB 版本管理替代 git branch |
| 信号加权公式 | `src/portfolio.py` | `score = conviction × darwinian_weight` |
| A/B 判定 | `src/autoresearch.py::evaluate()` | `sharpe_after > sharpe_before → activate, else retire` |

### 2.3 必须新建（无法复用）

| 模块 | 原因 |
|------|------|
| **agent_scorer.py** | 现有 paper trade 追踪**最终信号**，不追踪 7 个 agent 各自的方向判断 |
| **darwinian.py** | 权重管理逻辑（常量复用 atlas，但管理层需新写） |
| **prompt_store.py** | Prompt 版本管理（DB-backed） |
| **meta_agent.py** | Prompt 改写编排（prompt 复用 atlas，编排需新写） |

---

## 三、系统架构

```
┌──────────────────────────────────────────────────────────────────┐
│  Meta Agent (qwen3.6-plus, 每周日)                                │
│  采用 atlas-elenchus MUTATOR_SYSTEM_PROMPT                       │
│  找最差 agent → 改写 prompt → 创建 paper trade A/B session        │
│  5 天后 compare_session_metrics() → activate or retire            │
└───────────────┬──────────────────────────────────────────────────┘
                │
┌───────────────▼──────────────────────────────────────────────────┐
│  TradingAgents 7-Agent 管线（不改动核心逻辑）                      │
│                                                                    │
│  Market → Sentiment → News → Fundamentals                         │
│      ↓                                                            │
│  Bull ↔ Bear → Research Manager → Trader                          │
│      ↓                                                            │
│  Aggressive ↔ Conservative ↔ Neutral → Portfolio Manager          │
│                                                                    │
│  ▲ 注入点 1：weight context → init_state messages                 │
│  ▲ 注入点 2：prompt overrides → create_*() 的 system_prompt 参数   │
└───────────────┬──────────────────────────────────────────────────┘
                │ final_state (含每个 agent 的独立输出)
                ▼
┌──────────────────────────────────────────────────────────────────┐
│  Agent Scorer（唯一核心新模块）                                    │
│  从 final_state 提取 7 个 agent 各自的方向信号                     │
│  记录到 agent_scorecards 表                                       │
│  每日盘后：回填 5d return → 算 per-agent Sharpe → 更新权重         │
└──────────────────────────────────────────────────────────────────┘
                │
                ▼
┌──────────────────────────────────────────────────────────────────┐
│  现有 Paper Trade 系统（复用）                                     │
│  analysis_tracked → paper_trade_trades → metrics.py               │
│  ├─ 最终信号 P&L 追踪（已有）                                      │
│  └─ A/B 测试：两个 session 对比 Sharpe（复用）                     │
└──────────────────────────────────────────────────────────────────┘
```

---

## 四、Agent Scorer 详细设计

### 4.1 Per-Agent 信号提取

TradingAgents final_state 中每个 agent 的输出和提取方式：

| Agent ID | State Key | 提取方式 | 说明 |
|----------|-----------|---------|------|
| `market_analyst` | `market_report` | LLM 提取 | qwen3.6-plus 从报告文本提取 BULLISH/BEARISH/NEUTRAL |
| `sentiment_analyst` | `sentiment_report` | LLM 提取 | 同上 |
| `news_analyst` | `news_report` | LLM 提取 | 同上 |
| `fundamentals_analyst` | `fundamentals_report` | LLM 提取 | 同上 |
| `bull_researcher` | `investment_debate_state["bull_history"]` | 固定 BULLISH | 角色决定方向 |
| `bear_researcher` | `investment_debate_state["bear_history"]` | 固定 BEARISH | 角色决定方向 |
| `trader` | `trader_investment_plan` | 正则提取 | 文本含 "FINAL TRANSACTION PROPOSAL: **BUY/HOLD/SELL**" |

**不记录 Portfolio Manager**：它是最终决策者，对自己打分没意义。
**不记录 3 个风险辩论者**：结构性角色（aggressive/conservative/neutral），不是独立方向判断。

LLM 信号提取 prompt（4 个 analyst 共用）：

```
Extract the directional signal from this analyst report.
Output exactly one JSON: {"signal": "BULLISH" | "BEARISH" | "NEUTRAL"}
Report: {report_text_truncated_to_2000_chars}
```

### 4.2 Scorecard 表

```sql
CREATE TABLE agent_scorecards (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    analysis_id INTEGER NOT NULL,    -- FK to analysis_history.id
    agent_id TEXT NOT NULL,          -- market_analyst / bull_researcher / ...
    ticker TEXT NOT NULL,
    date TEXT NOT NULL,
    signal TEXT NOT NULL,            -- BULLISH / BEARISH / NEUTRAL
    price_at_call REAL,
    return_5d REAL,                  -- 盘后回填
    hit_5d INTEGER,                  -- 方向正确 = 1
    return_20d REAL,                 -- 盘后回填
    hit_20d INTEGER,
    created_at TEXT NOT NULL
);

CREATE INDEX idx_sc_agent_date ON agent_scorecards(agent_id, date DESC);
CREATE INDEX idx_sc_backfill ON agent_scorecards(date) 
    WHERE return_5d IS NULL AND price_at_call IS NOT NULL;
```

### 4.3 回填与指标计算

每日盘后 worker 执行：

```python
def daily_score_update(scorer, data_router):
    """1. 回填价格  2. 算 per-agent Sharpe  3. 更新权重"""
    
    # Step 1: 回填 5d/20d return（复用 data_router.get_price）
    scorer.backfill_returns(data_router)
    
    # Step 2: 计算 per-agent 滚动 Sharpe
    # 复用 metrics.py 的 Sharpe 公式：mean/std * sqrt(252/period)
    for agent_id in AGENT_MAP:
        returns = scorer.get_returns(agent_id, window_days=30)
        if len(returns) >= 5:
            sharpe = compute_sharpe(returns, period=5)  # 5 日 return
            hit_rate = sum(1 for r in returns if r["hit_5d"]) / len(returns)
            scorer.save_metrics(agent_id, sharpe, hit_rate)
    
    # Step 3: 更新 Darwinian 权重
    update_darwinian_weights(scorer)
```

### 4.4 Per-Agent Sharpe 公式

```python
def compute_agent_sharpe(returns_5d: list[float], annualize_factor=252/5) -> float:
    """复用 metrics.py:71-87 的 Sharpe 公式，但输入是 5d returns 而非 daily equity。"""
    if len(returns_5d) < 5:
        return 0.0
    arr = np.array(returns_5d)
    std = arr.std()
    if std < 1e-8:
        return 0.0
    return float((arr.mean() / std) * np.sqrt(annualize_factor))
```

---

## 五、Darwinian 权重

### 5.1 常量（直接采用 atlas-elenchus）

```python
# 来自 atlas-elenchus/src/agent.py
WEIGHT_MIN = 0.3
WEIGHT_MAX = 2.5
WEIGHT_BOOST = 1.05   # top 25% 每日 +5%
WEIGHT_DECAY = 0.95   # bottom 25% 每日 -5%
```

ATLAS 实盘 378 天后的权重分布：最高 2.5（地缘政治、商品、波动率 agent），最低 0.3（CIO、央行、半导体 agent）。权重比最大 8.33x。

### 5.2 每日更新逻辑

```python
def update_darwinian_weights(scorer):
    """每日盘后：按 30 天 Sharpe 排名，top/bottom 25% 调权重。"""
    metrics = scorer.get_all_agent_metrics()  # {agent_id: {sharpe, hit_rate}}
    
    ranked = sorted(metrics.items(), key=lambda x: x[1]["sharpe"], reverse=True)
    n = len(ranked)
    if n < 4:
        return
    
    top_n = max(1, n // 4)
    bottom_n = max(1, n // 4)
    top_ids = {r[0] for r in ranked[:top_n]}
    bottom_ids = {r[0] for r in ranked[-bottom_n:]}
    
    for agent_id, m in ranked:
        old_w = scorer.get_weight(agent_id)
        if agent_id in top_ids:
            new_w = min(old_w * WEIGHT_BOOST, WEIGHT_MAX)
        elif agent_id in bottom_ids:
            new_w = max(old_w * WEIGHT_DECAY, WEIGHT_MIN)
        else:
            new_w = old_w
        scorer.save_weight(agent_id, new_w)
```

### 5.3 权重注入到 TradingAgents（零改动 TradingAgents 代码）

在 `analyzer.py` 中，绕过 `propagate()` 直接调用 `graph.invoke()`，在 init state 的 messages 中注入权重 context：

```python
# analyzer.py — analyze() 方法改动
def analyze(self, ticker, date, progress_callback=None):
    self._init_graph()
    
    # 构造 init state
    init_state = self._graph.propagator.create_initial_state(ticker, date)
    
    # 注入权重 context（如果迭代模块启用）
    if self._iteration_enabled:
        weight_text = self._format_weight_context()
        if weight_text:
            init_state["messages"].insert(0, ("system", weight_text))
    
    # 注入 prompt overrides（Phase 3 才需要改 TradingAgents）
    if self._iteration_enabled and self._prompt_overrides:
        self._apply_prompt_overrides()
    
    # 执行分析
    args = self._graph.propagator.get_graph_args()
    if self._graph.debug:
        # stream 模式（保留现有 debug 行为）
        trace = []
        for chunk in self._graph.graph.stream(init_state, **args):
            if chunk.get("messages"):
                chunk["messages"][-1].pretty_print()
            trace.append(chunk)
        final_state = trace[-1] if trace else {}
    else:
        final_state = self._graph.graph.invoke(init_state, **args)
    
    signal = self._graph.process_signal(final_state.get("final_trade_decision", ""))
    
    # 构造 AnalysisResult（现有逻辑不变）
    result = AnalysisResult(
        ticker=ticker, signal=str(signal),
        market_report=final_state.get("market_report", ""),
        sentiment_report=final_state.get("sentiment_report", ""),
        news_report=final_state.get("news_report", ""),
        fundamentals_report=final_state.get("fundamentals_report", ""),
        investment_debate=final_state.get("investment_debate_state", {}),
        risk_assessment=final_state.get("risk_debate_state", {}),
        trade_decision=final_state.get("final_trade_decision", {}),
    )
    
    return result, final_state  # 新增：返回 final_state 供 scorer 用
```

**注意**：`analyze()` 新增返回 `final_state`。调用方（`workers.py` 的 analysis_worker）在拿到 final_state 后调用 scorer。

权重 context 格式：

```
[Agent Reliability Weights — based on 30-day rolling Sharpe]
  Market Analyst:       1.85 ★ (top performer)
  Fundamentals Analyst: 1.42
  News Analyst:         1.15
  Bull Researcher:      0.88
  Sentiment Analyst:    0.72
  Bear Researcher:      0.45 ⚠ (underperforming)
  Trader:               0.60

When synthesizing agent reports, give proportionally more weight to higher-scored agents.
```

Portfolio Manager 自然会在最终决策时更多采信高权重 agent 的观点。

---

## 六、Meta Agent 改写

### 6.1 Prompt（采用 atlas-elenchus 模式）

```python
# 来自 atlas-elenchus/src/autoresearch.py，适配中文
MUTATOR_SYSTEM_PROMPT = """You are a prompt engineer specializing in financial analysis agent prompts.

You will receive:
1. An agent's current system prompt
2. Its role and recent performance (rolling Sharpe, hit rate, Darwinian weight)
3. Its worst recent calls with actual market outcomes
4. The best-performing agent's prompt for reference

Your job: produce a TARGETED modification to the prompt.

Rules:
- Make ONE focused change, not a complete rewrite
- Preserve the agent's core role and analytical framework
- Add specificity where the prompt is vague
- Add decision criteria where the prompt lacks them
- If the agent has a pattern of false positives, add confirmation requirements
- If the agent misses obvious signals, add detection criteria

Output format:
---NEW_PROMPT---
(complete modified prompt)
---END_PROMPT---
---REASONING---
(explanation of what you changed and why, referencing specific bad calls)
"""
```

### 6.2 每周流程

```python
class MetaAgent:
    def run_weekly(self):
        # Step 1: 找最差 agent（采用 atlas 模式）
        worst = self.scorer.get_worst_agent_by_sharpe(window_days=30)
        best = self.scorer.get_best_agent_by_sharpe(window_days=30)
        
        # Step 2: 收集证据
        bad_calls = self.scorer.get_worst_calls(worst.agent_id, n=5)
        
        # Step 3: qwen3.6-plus 生成改进 prompt
        new_prompt = self.qwen.call(
            MUTATOR_SYSTEM_PROMPT,
            self._build_mutation_context(worst, best, bad_calls)
        )
        
        # Step 4: 存入 prompt_versions（status=testing）
        version_id = self.prompt_store.save_version(
            agent_id=worst.agent_id,
            prompt_text=extract_prompt(new_prompt),
            reasoning=extract_reasoning(new_prompt),
            source="meta_agent",
        )
        
        # Step 5: 创建 A/B paper trade sessions（复用！）
        baseline_session = self._get_or_create_baseline_session()
        test_session = self.paper_store.create_session(
            name=f"A/B: {worst.agent_id} prompt v{version_id}",
            mode="live",
            auto_track=True,
            config_json={**DEFAULT_AB_CONFIG, "prompt_version_id": version_id},
        )
        self.prompt_store.update_version(version_id,
            ab_session_id=test_session["id"],
            baseline_session_id=baseline_session["id"],
        )
```

### 6.3 A/B 验证结算（复用 paper trade metrics）

```python
def settle_ab_tests(self):
    """每周五盘后：检查进行中的 A/B 测试是否该结算。"""
    active_tests = self.prompt_store.get_testing_versions()
    
    for version in active_tests:
        days_elapsed = (today() - version["created_at"]).days
        if days_elapsed < 5:
            continue  # 还没到验证期
        
        # 复用 metrics.py 算两个 session 的 Sharpe
        baseline_metrics = compute_session_metrics(
            trades=self.paper_store.get_trades(version["baseline_session_id"]),
            equity=self.paper_store.get_equity(version["baseline_session_id"]),
            start_capital=100000,
        )
        test_metrics = compute_session_metrics(
            trades=self.paper_store.get_trades(version["ab_session_id"]),
            equity=self.paper_store.get_equity(version["ab_session_id"]),
            start_capital=100000,
        )
        
        sharpe_before = baseline_metrics.get("sharpe_ratio", 0)
        sharpe_after = test_metrics.get("sharpe_ratio", 0)
        
        # 采用 atlas-elenchus 判定逻辑
        if sharpe_after > sharpe_before:
            self.prompt_store.activate_version(version["id"])
            logger.info("Prompt v%d activated: Sharpe %.2f → %.2f",
                        version["id"], sharpe_before, sharpe_after)
        else:
            self.prompt_store.retire_version(version["id"])
            logger.info("Prompt v%d retired: no improvement", version["id"])
```

ATLAS 实盘数据：54 次改写中 17 次保留（~30% 保留率）。

---

## 七、TradingAgents 最小改动（Phase 2）

### 7.1 改动模式

**4 个 Analyst**（ChatPromptTemplate 模式）— 加 `system_prompt=None` 参数：

```python
# 改前 (market_analyst.py:12)
def create_market_analyst(llm):
    def market_analyst_node(state):
        system_message = """You are a trading assistant..."""

# 改后
def create_market_analyst(llm, system_prompt=None):
    def market_analyst_node(state):
        system_message = system_prompt or """You are a trading assistant..."""
```

**6 个非 Analyst**（f-string 模式）— 加 `prompt_prefix=None` 参数：

```python
# 改前 (bull_researcher.py:14)
def create_bull_researcher(llm, memory):
    def bull_researcher_node(state):
        prompt = f"""You are a Bull Analyst..."""

# 改后
def create_bull_researcher(llm, memory, prompt_prefix=None):
    def bull_researcher_node(state):
        base_prompt = f"""You are a Bull Analyst..."""
        prompt = f"{prompt_prefix}\n\n{base_prompt}" if prompt_prefix else base_prompt
```

**为什么非 Analyst 用 prefix 而不是全文替换**：f-string prompt 中包含运行时变量（`{market_research_report}`, `{history}` 等），全文替换会破坏这些引用。前缀追加是安全的。

### 7.2 setup.py 传递

```python
# graph/setup.py — setup_graph() 改动
def setup_graph(self, selected_analysts=None):
    prompts = self.agent_prompts or {}
    
    if "market" in selected_analysts:
        analyst_nodes["market"] = create_market_analyst(
            self.quick_thinking_llm,
            system_prompt=prompts.get("market_analyst", {}).get("system_prompt"),
        )
    # ... 其他 analyst 同理
    
    bull_researcher_node = create_bull_researcher(
        self.quick_thinking_llm, self.bull_memory,
        prompt_prefix=prompts.get("bull_researcher", {}).get("prompt_prefix"),
    )
    # ... 其他非 analyst 同理
```

### 7.3 改动文件清单

| 文件 | 改动行数 |
|------|---------|
| `agents/analysts/market_analyst.py` | +3 行 |
| `agents/analysts/social_media_analyst.py` | +3 行 |
| `agents/analysts/news_analyst.py` | +3 行 |
| `agents/analysts/fundamentals_analyst.py` | +3 行 |
| `agents/researchers/bull_researcher.py` | +3 行 |
| `agents/researchers/bear_researcher.py` | +3 行 |
| `agents/managers/research_manager.py` | +3 行 |
| `agents/managers/portfolio_manager.py` | +3 行 |
| `agents/trader/trader.py` | +3 行 |
| `graph/setup.py` | +20 行 |
| `graph/trading_graph.py` | +5 行 |
| **合计** | **~50 行** |

---

## 八、DB 表（仅 2 张新表）

```sql
-- Per-agent 方向信号记录
CREATE TABLE agent_scorecards (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    analysis_id INTEGER NOT NULL,
    agent_id TEXT NOT NULL,
    ticker TEXT NOT NULL,
    date TEXT NOT NULL,
    signal TEXT NOT NULL,         -- BULLISH / BEARISH / NEUTRAL
    price_at_call REAL,
    return_5d REAL,
    hit_5d INTEGER,
    return_20d REAL,
    hit_20d INTEGER,
    created_at TEXT NOT NULL
);
CREATE INDEX idx_sc_agent_date ON agent_scorecards(agent_id, date DESC);
CREATE INDEX idx_sc_backfill ON agent_scorecards(date) 
    WHERE return_5d IS NULL AND price_at_call IS NOT NULL;

-- Prompt 版本管理
CREATE TABLE prompt_versions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id TEXT NOT NULL,
    prompt_text TEXT NOT NULL,
    prompt_type TEXT NOT NULL,     -- system_prompt | prompt_prefix
    source TEXT NOT NULL,          -- default | meta_agent | manual
    reasoning TEXT,                -- Meta Agent 的改写理由
    status TEXT DEFAULT 'candidate',  -- active | testing | retired
    ab_session_id INTEGER,         -- FK to paper_trade_sessions（复用！）
    baseline_session_id INTEGER,
    sharpe_before REAL,
    sharpe_after REAL,
    created_at TEXT NOT NULL
);
CREATE INDEX idx_pv_agent_status ON prompt_versions(agent_id, status);
```

Darwinian 权重**不需要单独表**——从 `agent_scorecards` 实时计算即可（7 个 agent × 30 天 = 最多 210 行查询，毫秒级）。

---

## 九、配置

```yaml
# config.yaml 新增
iteration:
  enabled: false                  # 总开关，默认关闭
  model: "qwen3.6-plus"          # Meta Agent + 信号提取用
  fallback_model: "qwen-plus"
  
  scorer:
    extract_signals: true         # 是否提取 per-agent 信号
    backfill_5d: true
    backfill_20d: true
    rolling_window_days: 30
    min_samples: 5                # 少于 5 条不计算 Sharpe
  
  darwinian:
    enabled: true
    boost: 1.05                   # atlas-elenchus default
    decay: 0.95
    floor: 0.3
    ceiling: 2.5
  
  meta:
    enabled: false                # 默认关闭，Phase 3 开启
    ab_test_days: 5
    max_rewrites_per_week: 1
```

---

## 十、文件清单

### 新建（stock-trading-system）

```
stock_trading_system/agents/iterative/
├── __init__.py
├── config.py              # IterationConfig dataclass + 加载逻辑
├── agent_scorer.py        # 核心：信号提取 + scorecard 记录 + 回填 + Sharpe
├── darwinian.py           # 权重更新 + format_weight_context()
├── prompt_store.py        # prompt_versions 表 CRUD
├── meta_agent.py          # Meta Agent 改写 + A/B 结算（Phase 3）
└── signal_extractor.py    # LLM/regex 信号提取工具函数

tests/test_iterative.py    # 测试
```

### 修改（stock-trading-system）

| 文件 | 改动 |
|------|------|
| `agents/analyzer.py` | analyze() 绕过 propagate() + 注入 weight + 返回 final_state |
| `portfolio/database.py` | _init_db() 新增 2 张表 |
| `tasks/workers.py` | 注册 agent_score_update + meta_evolution worker |
| `web/app.py` | 新增 GET /api/iteration/agents + POST /api/iteration/meta/run |
| `config/default_config.yaml` | 新增 iteration: 节 |

### 修改（TradingAgents — Phase 2）

10 个 agent 文件 + setup.py + trading_graph.py（共 ~50 行改动）

---

## 十一、分阶段实施

### Phase 1 — Agent Scorer + Darwinian 权重（1 周）

| 步骤 | 内容 | 验证 |
|------|------|------|
| 1.1 | 新建 `agents/iterative/` 目录 + config.py + signal_extractor.py | 目录存在 |
| 1.2 | 实现 agent_scorer.py（record + backfill + sharpe） | 单元测试通过 |
| 1.3 | 实现 darwinian.py（权重更新 + format_weight_context） | 单元测试通过 |
| 1.4 | database.py 建表 agent_scorecards | 表创建成功 |
| 1.5 | analyzer.py 改造：绕过 propagate + 注入 weight + 返回 final_state | 分析结果不变 |
| 1.6 | workers.py：analysis_worker 末尾加 scorer 钩子 | 分析后 agent_scorecards 新增 7 条 |
| 1.7 | workers.py：注册 agent_score_update worker | 每日回填 + Sharpe 计算正确 |
| 1.8 | app.py：GET /api/iteration/agents | 返回 7 个 agent 的 Sharpe/权重 |

### Phase 2 — Prompt 注入基础设施（3 天）

| 步骤 | 内容 | 验证 |
|------|------|------|
| 2.1 | TradingAgents 10 个 agent 文件加 optional prompt 参数 | 不传参数时行为不变 |
| 2.2 | setup.py + trading_graph.py 传递 agent_prompts | config 中有 agent_prompts 时正确分发 |
| 2.3 | prompt_store.py + 建表 prompt_versions | CRUD 正常 |
| 2.4 | analyzer.py 从 prompt_store 读 active prompt → 注入 ta_config | 手动写入 prompt_version 后验证生效 |

### Phase 3 — Meta Agent 自我进化（3 天）

| 步骤 | 内容 | 验证 |
|------|------|------|
| 3.1 | meta_agent.py（采用 MUTATOR_SYSTEM_PROMPT） | 能找到最差 agent 并生成新 prompt |
| 3.2 | A/B 验证复用 paper_trade_sessions | 创建对比 session 成功 |
| 3.3 | settle_ab_tests() 复用 compute_session_metrics | Sharpe 对比正确，activate/retire 生效 |
| 3.4 | workers.py 注册 meta_evolution worker | 手动触发一轮完整流程 |

### Phase 4 — 前端展示（可选）

| 步骤 | 内容 |
|------|------|
| 4.1 | 仪表盘 Agent 健康度卡片（Sharpe/权重/命中率） |
| 4.2 | Prompt 版本历史时间线 |
| 4.3 | A/B 测试结果对比面板 |

---

## 十二、测试用例

### Agent Scorer（8 例）

| ID | 用例 | 预期 |
|----|------|------|
| IS-1 | 分析 AAPL 后记录 scorecard | 7 条记录（4 analyst + bull + bear + trader） |
| IS-2 | 信号提取 — bullish 报告 | LLM 返回 BULLISH |
| IS-3 | 信号提取 — bull_researcher | 固定返回 BULLISH（不调 LLM） |
| IS-4 | 信号提取 — trader | 正则提取 BUY/SELL/HOLD |
| IS-5 | 5 天后回填 return_5d | 正确计算 return + hit |
| IS-6 | Sharpe 计算 | 与手动计算一致 |
| IS-7 | < 5 条时不算 Sharpe | 返回 0.0 |
| IS-8 | iteration.enabled=false 时不触发 | scorecard 表无记录 |

### Darwinian 权重（5 例）

| ID | 用例 | 预期 |
|----|------|------|
| DW-1 | Top 25% 升权 | new = old × 1.05 |
| DW-2 | Bottom 25% 降权 | new = old × 0.95 |
| DW-3 | 边界限制 | ≤ 2.5 且 ≥ 0.3 |
| DW-4 | 中间 50% 不变 | 权重保持 |
| DW-5 | Weight context 格式 | 含所有 agent + 权重值 + 排序 |

### Meta Agent（5 例，Phase 3）

| ID | 用例 | 预期 |
|----|------|------|
| MA-1 | 找最差 agent | 返回 Sharpe 最低者 |
| MA-2 | 生成改进 prompt | 输出含 NEW_PROMPT + REASONING |
| MA-3 | 创建 A/B paper trade sessions | 两个 session 创建成功 |
| MA-4 | settle: Sharpe 改善 → activate | prompt_versions status=active |
| MA-5 | settle: 没改善 → retire | prompt_versions status=retired |

### 回归（3 例）

| ID | 用例 | 预期 |
|----|------|------|
| REG-1 | iteration.enabled=false 时分析正常 | AnalysisResult 与改前完全一致 |
| REG-2 | 现有 paper trade 不受影响 | 自动追踪 + metrics 计算正常 |
| REG-3 | TradingAgents 不传 prompt 参数时行为不变 | 所有 agent 使用默认 prompt |

---

## 十三、成本

| 组件 | 调用频次 | 月成本 |
|------|---------|--------|
| 信号提取（4 analyst × 每次分析） | ~4 次/分析 × ~5 分析/天 | ~¥3 |
| Meta Agent 改写 | ~1 次/周 | ~¥1 |
| **合计新增** | | **~¥4/月** |

Darwinian 权重更新和回填是纯本地计算，零 API 成本。

---

*方案 v3.0 结束。*
