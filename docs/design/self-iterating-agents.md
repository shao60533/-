# 自我迭代美股分析 Agent 技术方案

> **版本**: 1.0  
> **日期**: 2026-04-18  
> **状态**: 草稿 — 待评审  
> **依据**: A 股自我迭代方案（ATLAS 哲学）→ 美股适配 + 现有 TradingAgents 架构整合

---

## 一、核心思想

**prompt 是权重，Sharpe 是 loss，git 是优化器。**

在现有 TradingAgents 7-Agent 分析管线之上，叠加三层进化机制：
1. **Scorecard** — 记录每个 agent 每次 call 的后续表现
2. **Darwinian 权重** — 每日根据 scorecard 动态调节 agent 话语权
3. **Meta Agent** — 每周自动改写表现最差 agent 的 prompt

---

## 二、与 A 股方案的关键差异

| 维度 | A 股方案 | 美股适配 |
|------|---------|---------|
| **数据源** | akshare（免费） | yfinance + Qwen web search（已有） |
| **L1 宏观因子** | 北向资金、产业政策、央行 | Fed 利率路径、VIX、DXY、机构持仓 13F |
| **L2 板块** | AI算力、白酒医药、券商 | Tech/AI、Healthcare、Financials、Energy、Consumer、Defense |
| **L3 风格** | 林园价值、冯柳成长 | Buffett 价值、Cathie Wood 成长、动量、均值回归 |
| **特殊因子** | 龙虎榜、涨跌停、T+1 | Options flow、Earnings surprise、After-hours |
| **交易限制** | T+1、10%涨跌停 | T+0、无涨跌停 |
| **现有基础** | 从零搭建 | **已有 TradingAgents 7-Agent 管线 + TaskManager + analysis_history** |
| **LLM 提供者** | 纯 Qwen | Qwen 主 + Gemini 兜底（已有多 provider 架构） |

**核心优势**：我们不用从零搭建，现有 TradingAgents 的 4-Stage 管线（分析→辩论→交易→风控）已经是一个成熟的 L3+L4 层。我们要做的是：
1. 加 L1（宏观）和 L2（板块）作为新的轻量 agent
2. 在现有管线外围包一层 scorecard + Darwinian + autoresearch

---

## 三、模型分工

复用项目已有的多 provider 架构（`llm_clients/factory.py`），按任务分三档：

| 角色 | 模型 | 单价参考 | 调用频率 |
|------|------|---------|---------|
| **日常 agent（L1/L2 数据分析）** | `qwen3.5-flash` | $0.065/$0.26 per 1M | 每天 12-18 次 |
| **辩论/决策 agent（L3/L4）** | 现有 TradingAgents 管线（Gemini/Qwen） | 已有成本 | 每次分析 1 次 |
| **Meta Agent（prompt 进化）** | `qwen3-max` | $0.78/$3.90 per 1M | 每周 3-5 次 |

**月成本估算**（覆盖 30 只标的）：

| 组件 | 日调用 | 月成本 |
|------|--------|--------|
| L1 宏观 agent × 5 | 5 次/天 | ~¥8 |
| L2 板块 agent × 6 | 6 次/天 | ~¥10 |
| L3+L4 个股分析（现有管线） | 按需 | 已有预算 |
| Meta Agent 周迭代 | 3-5 次/周 | ~¥4 |
| **合计新增** | | **~¥22/月** |

---

## 四、系统架构

```
┌────────────────────────────────────────────────────────────┐
│  Meta Agent (qwen3-max)                                     │
│  每周日跑一次：                                              │
│  - 读 scorecard 找最差 agent                                │
│  - 生成 prompt diff                                         │
│  - 创建 feature branch                                     │
│  - 5 个交易日后 Sharpe 对比决定 merge 或丢弃                │
└───────────────┬────────────────────────────────────────────┘
                │
                ▼
┌────────────────────────────────────────────────────────────┐
│  四层 Agent Pipeline（每交易日盘后跑）                       │
│                                                              │
│  L1 宏观层 (5 agents, qwen3.5-flash)  ← 新增              │
│  ┌─────────────────────────────────────────────────────┐  │
│  │ Fed Watcher     — 联储利率路径、会议纪要、点阵图      │  │
│  │ Risk Gauge      — VIX、MOVE 指数、信用利差            │  │
│  │ Dollar/Rates    — DXY、10Y yield、yield curve        │  │
│  │ Flows Tracker   — 13F 机构持仓、ETF 资金流向          │  │
│  │ Commodities     — 原油、黄金、铜（与板块联动）         │  │
│  └─────────────────────────────────────────────────────┘  │
│                                                              │
│  L2 板块层 (6 agents, qwen3.5-flash)  ← 新增              │
│  ┌─────────────────────────────────────────────────────┐  │
│  │ Tech/AI         — 半导体、Cloud、AI 算力              │  │
│  │ Healthcare      — 生物科技、制药、医疗设备             │  │
│  │ Financials      — 银行、保险、券商                     │  │
│  │ Energy          — 石油、天然气、新能源                 │  │
│  │ Consumer        — 零售、食品、奢侈品                   │  │
│  │ Defense/Infra   — 军工、基建、工业                     │  │
│  └─────────────────────────────────────────────────────┘  │
│                                                              │
│  L3 风格层 + L4 决策层  ← 复用现有 TradingAgents 管线      │
│  ┌─────────────────────────────────────────────────────┐  │
│  │ Market Analyst → Sentiment → News → Fundamentals     │  │
│  │         ↓                                             │  │
│  │ Bull Researcher ↔ Bear Researcher → Research Manager  │  │
│  │         ↓                                             │  │
│  │ Trader → Aggressive ↔ Conservative ↔ Neutral          │  │
│  │         ↓                                             │  │
│  │ Portfolio Manager → final_trade_decision              │  │
│  └─────────────────────────────────────────────────────┘  │
│                                                              │
│  ▲ L1/L2 输出注入 L3 的 context                            │
│  ▲ Darwinian 权重影响 L4 CIO 的采信度                      │
└───────────────┬────────────────────────────────────────────┘
                │
                ▼
┌────────────────────────────────────────────────────────────┐
│  Scorecard DB (SQLite)                                      │
│  每个 agent 每只股票每次 call + 后续 5/20 日涨跌            │
│  → 滚动 Sharpe → Darwinian 权重                            │
└────────────────────────────────────────────────────────────┘
```

### 4.1 L1/L2 与 L3/L4 的衔接方式

L1/L2 是**独立运行的轻量 agent**，每个交易日盘后运行一次，产出写入 `macro_signals` 和 `sector_signals` 表。

当用户对某只股票触发 L3/L4 分析（即现有 TradingAgents 管线）时：
1. 从 `macro_signals` 取当日 L1 宏观综述
2. 从 `sector_signals` 取该股票所属板块的 L2 板块观点
3. 注入到 TradingAgents 的 `create_initial_state` 中，作为 analysts 的额外 context

```python
# 注入方式：扩展 initial state 的 messages
init_state = create_initial_state(ticker, date)
init_state["messages"].append(
    ("system", f"宏观环境摘要：\n{macro_summary}\n\n板块观点：\n{sector_view}")
)
```

这样 **不改动 TradingAgents 内部逻辑**，只是让它在分析时多了宏观和板块背景信息。

---

## 五、Scorecard 系统

### 5.1 表结构

```sql
-- Agent 的每次 call 记录 + 后续验证
CREATE TABLE agent_scorecards (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id TEXT NOT NULL,         -- 'L1_fed_watcher', 'L2_tech_ai', 'ta_market_analyst' 等
    agent_layer TEXT NOT NULL,      -- 'L1', 'L2', 'L3', 'L4'
    prompt_version TEXT,            -- git commit sha 或版本号
    date TEXT NOT NULL,             -- call 日期
    ticker TEXT,                    -- L1 宏观 agent 可能为 null（市场级信号）
    
    -- Agent 输出
    call_signal TEXT,               -- BUY/HOLD/SELL 或定性标签（bullish/bearish/neutral）
    call_score REAL,                -- 1-5 评分（如果 agent 输出了的话）
    call_rationale TEXT,            -- agent 给的理由摘要
    call_raw TEXT,                  -- 完整原始输出
    
    -- 后续真实表现（盘后批量更新）
    price_at_call REAL,
    price_5d REAL,
    price_20d REAL,
    return_5d REAL,
    return_20d REAL,
    
    -- 计算指标（滚动更新）
    sharpe_30d REAL,                -- 滚动 30 天 Sharpe
    hit_rate_30d REAL,              -- 滚动 30 天方向命中率
    
    -- 权重
    darwinian_weight REAL DEFAULT 1.0,
    
    -- 来源追溯
    analysis_id INTEGER,            -- 若关联到 analysis_history
    
    created_at TEXT NOT NULL
);

CREATE INDEX idx_sc_agent_date ON agent_scorecards(agent_id, date DESC);
CREATE INDEX idx_sc_ticker_date ON agent_scorecards(ticker, date DESC);
CREATE INDEX idx_sc_pending ON agent_scorecards(return_5d) WHERE return_5d IS NULL;
```

### 5.2 对现有分析的记分

TradingAgents 的 7 个 agent（4 analysts + Research Manager + Trader + Portfolio Manager）每次分析都有输出。我们在 analysis 完成后，从结果中提取每个 agent 的 call：

```python
def record_analysis_scorecards(analysis_result, analysis_id):
    """从一次完整分析中提取每个 agent 的 call 并记录 scorecard。"""
    
    # 1. Market Analyst → 从 market_report 提取 bullish/bearish 倾向
    record_agent_call(
        agent_id="ta_market_analyst",
        layer="L3",
        ticker=analysis_result.ticker,
        raw=analysis_result.market_report,
        signal=extract_direction(analysis_result.market_report),  # Qwen-flash 提取
        analysis_id=analysis_id,
    )
    
    # 2. 类似处理 sentiment, news, fundamentals
    # 3. Research Manager → 从 investment_debate.judge_decision 提取
    # 4. Trader → 从 trader_investment_plan 提取
    # 5. Portfolio Manager → final_trade_decision 已经是明确的 BUY/SELL/HOLD
    
    # Portfolio Manager 的 call 直接就是最终信号
    record_agent_call(
        agent_id="ta_portfolio_manager",
        layer="L4",
        ticker=analysis_result.ticker,
        raw=str(analysis_result.trade_decision),
        signal=analysis_result.signal,  # 已提取
        analysis_id=analysis_id,
    )
```

### 5.3 后续价格回填

每个交易日盘后运行一个定时任务：

```python
def backfill_returns():
    """补填 5 日/20 日后续涨跌。"""
    pending_5d = db.query("""
        SELECT id, ticker, date, price_at_call
        FROM agent_scorecards
        WHERE return_5d IS NULL
          AND date <= date('now', '-5 days')
          AND price_at_call IS NOT NULL
    """)
    
    for row in pending_5d:
        price_5d = get_close_price(row["ticker"], 
                                    trading_day_offset(row["date"], 5))
        if price_5d:
            return_5d = (price_5d - row["price_at_call"]) / row["price_at_call"]
            db.update(row["id"], price_5d=price_5d, return_5d=return_5d)
    
    # 同理处理 20d
```

### 5.4 Sharpe 和命中率计算

每日盘后，更新每个 agent 的滚动 30 天 Sharpe：

```python
def update_rolling_metrics():
    """更新所有 agent 的滚动 30 天指标。"""
    agents = db.query("SELECT DISTINCT agent_id FROM agent_scorecards")
    
    for agent in agents:
        returns = db.query("""
            SELECT return_5d FROM agent_scorecards
            WHERE agent_id = ? AND return_5d IS NOT NULL
              AND date >= date('now', '-30 days')
            ORDER BY date
        """, agent["agent_id"])
        
        if len(returns) < 5:
            continue
        
        arr = [r["return_5d"] for r in returns]
        sharpe = np.mean(arr) / (np.std(arr) + 1e-8) * np.sqrt(252/5)
        
        # 命中率：信号方向与实际方向一致的比例
        hits = db.query("""
            SELECT COUNT(*) as n FROM agent_scorecards
            WHERE agent_id = ? AND return_5d IS NOT NULL
              AND date >= date('now', '-30 days')
              AND ((call_signal IN ('BUY','bullish') AND return_5d > 0)
                OR (call_signal IN ('SELL','bearish') AND return_5d < 0)
                OR (call_signal IN ('HOLD','neutral') AND ABS(return_5d) < 0.03))
        """, agent["agent_id"])
        
        hit_rate = hits[0]["n"] / len(returns)
        
        # 更新最近一条记录
        db.execute("""
            UPDATE agent_scorecards
            SET sharpe_30d = ?, hit_rate_30d = ?
            WHERE agent_id = ? AND date = (
                SELECT MAX(date) FROM agent_scorecards WHERE agent_id = ?
            )
        """, sharpe, hit_rate, agent["agent_id"], agent["agent_id"])
```

---

## 六、Darwinian 权重系统

### 6.1 每日权重更新

```python
def update_darwinian_weights():
    """每日盘后更新 agent 权重。"""
    
    # 取所有 agent 最近 30 天 Sharpe
    rankings = db.query("""
        SELECT agent_id, sharpe_30d
        FROM agent_scorecards
        WHERE date = (SELECT MAX(date) FROM agent_scorecards)
          AND sharpe_30d IS NOT NULL
        ORDER BY sharpe_30d DESC
    """)
    
    n = len(rankings)
    if n < 4:
        return
    
    top_25 = set(r["agent_id"] for r in rankings[:n//4])
    bottom_25 = set(r["agent_id"] for r in rankings[-(n//4):])
    
    for r in rankings:
        agent_id = r["agent_id"]
        current_weight = get_current_weight(agent_id)
        
        if agent_id in top_25:
            new_weight = current_weight * 1.05
        elif agent_id in bottom_25:
            new_weight = current_weight * 0.95
        else:
            new_weight = current_weight
        
        # 硬边界
        new_weight = max(0.3, min(2.5, new_weight))
        save_weight(agent_id, new_weight)
```

### 6.2 权重在分析中的应用

权重影响 L4 Portfolio Manager 的决策。在注入 context 时加入：

```python
# 在 TradingAgents 管线开始前，注入权重信息
weight_summary = format_agent_weights()
# 例如："Agent 可信度权重 — Market Analyst: 1.35 (top), Sentiment: 0.72 (bottom), ..."

# 注入到 Portfolio Manager 的 system prompt 补充
portfolio_manager_context += f"\n\n各分析师可信度权重（基于近 30 天表现）：\n{weight_summary}"
```

这样 Portfolio Manager 在做最终决策时，会自然地更重视高权重 agent 的观点。

---

## 七、L1/L2 Agent 设计（新增）

### 7.1 L1 宏观 Agent

每个 agent 是一个轻量函数，每天盘后运行一次，产出一份结构化信号。

```python
class MacroAgent:
    """L1 宏观 agent 基类。"""
    
    def __init__(self, agent_id: str, system_prompt_path: str):
        self.agent_id = agent_id
        self.system_prompt = load_prompt(system_prompt_path)
        self.tier = "flash"  # 用最便宜的模型
    
    def run(self, date: str) -> dict:
        """产出当日宏观信号。"""
        context = self._gather_context(date)
        
        response = qwen.call(
            self.tier,
            self.system_prompt,
            f"日期: {date}\n数据:\n{context}\n\n"
            "输出 JSON: {signal, confidence, key_factors[], summary}"
        )
        
        result = parse_json(response)
        
        # 记录 scorecard（宏观 agent 的 ticker 用 SPY 代替）
        record_agent_call(
            agent_id=self.agent_id, layer="L1",
            ticker="SPY", signal=result["signal"],
            raw=response,
        )
        
        return result
```

**5 个 L1 Agent 的数据源和关注点**：

| Agent | ID | 数据源 | 关注指标 | 输出信号 |
|-------|----|----|---------|---------|
| Fed Watcher | `L1_fed` | Qwen web search（FOMC、Fed speeches） | 利率预期、缩表进度、前瞻指引 | hawkish/dovish/neutral |
| Risk Gauge | `L1_risk` | yfinance（`^VIX`, `^MOVE`）+ Qwen | VIX 水位、VIX term structure、信用利差 | risk_on/risk_off/neutral |
| Dollar/Rates | `L1_rates` | yfinance（`DX-Y.NYB`, `^TNX`） | DXY 趋势、10Y yield、2s10s curve | tightening/easing/flat |
| Flows | `L1_flows` | Qwen web search（13F、ETF flows） | 机构增减仓方向、热门 ETF 资金流 | inflow/outflow/mixed |
| Commodities | `L1_commodities` | yfinance（`CL=F`, `GC=F`, `HG=F`） | 原油/黄金/铜 趋势，通胀预期 | inflationary/deflationary/stable |

### 7.2 L2 板块 Agent

```python
class SectorAgent:
    """L2 板块 agent，评估板块内 top holdings 的综合态势。"""
    
    SECTOR_ETFS = {
        "tech_ai": ["XLK", "SMH", "ARKK"],
        "healthcare": ["XLV", "XBI", "IBB"],
        "financials": ["XLF", "KBE", "KRE"],
        "energy": ["XLE", "XOP", "ICLN"],
        "consumer": ["XLY", "XLP", "IBUY"],
        "defense_infra": ["ITA", "PAVE", "XLI"],
    }
    
    def run(self, date: str) -> dict:
        """评估板块当前态势。"""
        etfs = self.SECTOR_ETFS[self.sector_id]
        
        # 取板块 ETF 近期表现
        etf_data = [get_etf_performance(etf, days=30) for etf in etfs]
        
        # 取板块相关新闻
        news = qwen_web_search(f"{self.sector_name} sector outlook {date}")
        
        context = format_sector_context(etf_data, news)
        
        response = qwen.call(
            "flash", self.system_prompt,
            f"板块: {self.sector_name}\n日期: {date}\n数据:\n{context}\n\n"
            "输出 JSON: {signal, momentum, key_drivers[], risks[], top_picks[]}"
        )
        
        result = parse_json(response)
        
        # 记录 scorecard（板块 agent 的 ticker 用板块 ETF 代替）
        record_agent_call(
            agent_id=f"L2_{self.sector_id}", layer="L2",
            ticker=etfs[0], signal=result["signal"],
            raw=response,
        )
        
        return result
```

### 7.3 Prompt 存储

所有 agent 的 system prompt 独立存文件，便于 Meta Agent 修改和 git 跟踪：

```
stock_trading_system/
└── agents/
    └── prompts/                    ← 新增目录
        ├── L1_fed.md
        ├── L1_risk.md
        ├── L1_rates.md
        ├── L1_flows.md
        ├── L1_commodities.md
        ├── L2_tech_ai.md
        ├── L2_healthcare.md
        ├── L2_financials.md
        ├── L2_energy.md
        ├── L2_consumer.md
        ├── L2_defense_infra.md
        └── meta_agent.md
```

TradingAgents 现有 7 个 agent 的 prompt 嵌在代码里（`agents/analysts/*.py`），暂不迁移。Meta Agent 改写时直接修改上面的 `.md` 文件。后续可考虑把 TradingAgents 的 prompt 也外置。

---

## 八、Meta Agent（Autoresearch Loop）

### 8.1 每周日执行流程

```python
class MetaAgent:
    """每周自动改写表现最差 agent 的 prompt。"""
    
    def run(self):
        # 第一步：挑目标
        worst = db.query("""
            SELECT agent_id, AVG(sharpe_30d) as avg_sharpe, AVG(hit_rate_30d) as avg_hit
            FROM agent_scorecards
            WHERE date >= date('now', '-30 days')
              AND sharpe_30d IS NOT NULL
            GROUP BY agent_id
            ORDER BY avg_sharpe ASC
            LIMIT 1
        """)[0]
        
        # 第二步：收集证据
        bad_calls = db.query("""
            SELECT date, ticker, call_signal, return_5d, return_20d, call_rationale
            FROM agent_scorecards
            WHERE agent_id = ? AND date >= date('now', '-30 days')
            ORDER BY return_5d ASC
            LIMIT 10
        """, worst["agent_id"])
        
        best_agent = db.query("""
            SELECT agent_id FROM agent_scorecards
            WHERE agent_layer = (SELECT agent_layer FROM agent_scorecards WHERE agent_id = ? LIMIT 1)
              AND date >= date('now', '-30 days')
              AND sharpe_30d IS NOT NULL
            GROUP BY agent_id
            ORDER BY AVG(sharpe_30d) DESC
            LIMIT 1
        """, worst["agent_id"])
        
        current_prompt = load_prompt(worst["agent_id"])
        best_prompt = load_prompt(best_agent["agent_id"]) if best_agent else ""
        
        # 第三步：让 qwen3-max 生成改进版 prompt
        new_prompt = qwen.call("max", META_SYSTEM_PROMPT, f"""
        ## 需要改进的 Agent
        - ID: {worst["agent_id"]}
        - 近 30 天 Sharpe: {worst["avg_sharpe"]:.2f}
        - 命中率: {worst["avg_hit"]:.1%}
        
        ## 当前 Prompt
        {current_prompt}
        
        ## 最差 10 次 Call（真实后续表现）
        {format_bad_calls(bad_calls)}
        
        ## 同层最佳 Agent 的 Prompt（参考）
        {best_prompt}
        
        ## 任务
        输出改进版 system prompt。说明修改理由。
        格式：
        ---PROMPT_START---
        (新 prompt 完整内容)
        ---PROMPT_END---
        ---REASONING---
        (修改理由)
        """)
        
        # 第四步：保存新 prompt + 记录
        new_prompt_text = extract_between(new_prompt, "PROMPT_START", "PROMPT_END")
        reasoning = extract_after(new_prompt, "REASONING")
        
        save_prompt_version(worst["agent_id"], new_prompt_text, reasoning)
        
        return {
            "target_agent": worst["agent_id"],
            "old_sharpe": worst["avg_sharpe"],
            "reasoning": reasoning,
        }
```

### 8.2 Prompt 版本管理

不引入 git branch 机制（过重），改用**数据库版本控制**：

```sql
CREATE TABLE prompt_versions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id TEXT NOT NULL,
    version INTEGER NOT NULL,       -- 自增版本号
    prompt_text TEXT NOT NULL,
    reasoning TEXT,                  -- Meta Agent 的修改理由
    status TEXT DEFAULT 'testing',   -- testing | active | retired
    sharpe_before REAL,              -- 改前 30d Sharpe
    sharpe_after REAL,               -- 改后 5d Sharpe（验证期结束填）
    created_at TEXT NOT NULL,
    activated_at TEXT,               -- status → active 的时间
    UNIQUE(agent_id, version)
);

CREATE INDEX idx_pv_agent ON prompt_versions(agent_id, status);
```

**版本生命周期**：
1. Meta Agent 生成新版本 → `status = 'testing'`
2. 5 个交易日验证期 → 用新 prompt 跑，scorecard 记录用新 `prompt_version`
3. 验证结束 → 对比 testing 版本 vs 最后一个 active 版本的 Sharpe
4. 改善 → `status = 'active'`，旧版本 → `'retired'`
5. 没改善 → `status = 'retired'`，继续用旧版本

### 8.3 A/B 测试机制

验证期内，新旧 prompt 可以**并行运行**同一只 ticker，各自记录 scorecard：

```python
def run_agent_with_ab(agent_id, ticker, date, context):
    """如果有 testing 版本，同时跑 active 和 testing。"""
    active_prompt = get_active_prompt(agent_id)
    testing_prompt = get_testing_prompt(agent_id)
    
    # active 版本结果（用于实际决策）
    active_result = run_with_prompt(agent_id, active_prompt, ticker, context)
    record_scorecard(agent_id, active_prompt.version, ticker, active_result)
    
    # testing 版本结果（仅记录，不影响决策）
    if testing_prompt:
        test_result = run_with_prompt(agent_id, testing_prompt, ticker, context)
        record_scorecard(agent_id, testing_prompt.version, ticker, test_result)
    
    return active_result  # 决策只用 active 版本
```

---

## 九、数据层

### 9.1 数据源矩阵（美股）

| 数据类型 | 来源 | 用途 | 已有 |
|---------|------|------|------|
| 行情 K 线 | yfinance | L1/L2 ETF 表现 + 回填价格 | ✅ |
| 基本面 | yfinance + Qwen | Fundamentals Analyst | ✅ |
| 新闻 | Qwen web search | News Analyst + L1/L2 | ✅ |
| VIX/MOVE/DXY | yfinance（`^VIX`, `DX-Y.NYB`, `^TNX`） | L1 Risk/Rates | ✅（可取） |
| 商品期货 | yfinance（`CL=F`, `GC=F`, `HG=F`） | L1 Commodities | ✅（可取） |
| 板块 ETF | yfinance（XLK, XLV, XLF, XLE, XLY, ITA） | L2 板块 | ✅（可取） |
| 机构持仓 13F | Qwen web search | L1 Flows | 新增 |
| ETF 资金流 | Qwen web search | L1 Flows | 新增 |
| Options flow | Qwen web search | 可选增强 | 后续 |

**关键优势**：美股数据通过 yfinance 全部免费可得，不需要额外数据源。

### 9.2 新增表汇总

| 表名 | 用途 |
|------|------|
| `agent_scorecards` | Agent 每次 call 记录 + 后续表现 |
| `prompt_versions` | Prompt 版本管理 |
| `macro_signals` | L1 宏观 agent 每日产出 |
| `sector_signals` | L2 板块 agent 每日产出 |
| `darwinian_weights` | Agent 权重历史 |

```sql
-- L1 宏观信号
CREATE TABLE macro_signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id TEXT NOT NULL,
    date TEXT NOT NULL,
    signal TEXT,                     -- hawkish/dovish/risk_on/risk_off/...
    confidence REAL,
    key_factors TEXT,                -- JSON array
    summary TEXT,
    raw_output TEXT,
    created_at TEXT NOT NULL,
    UNIQUE(agent_id, date)
);

-- L2 板块信号
CREATE TABLE sector_signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id TEXT NOT NULL,
    sector TEXT NOT NULL,
    date TEXT NOT NULL,
    signal TEXT,                     -- bullish/bearish/neutral
    momentum TEXT,                   -- accelerating/decelerating/flat
    key_drivers TEXT,                -- JSON array
    risks TEXT,                      -- JSON array
    top_picks TEXT,                  -- JSON array of tickers
    raw_output TEXT,
    created_at TEXT NOT NULL,
    UNIQUE(agent_id, date)
);

-- Darwinian 权重历史
CREATE TABLE darwinian_weights (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id TEXT NOT NULL,
    date TEXT NOT NULL,
    weight REAL NOT NULL,
    sharpe_30d REAL,
    hit_rate_30d REAL,
    rank INTEGER,                    -- 当日排名
    UNIQUE(agent_id, date)
);
```

---

## 十、调度与任务集成

### 10.1 定时任务

| 任务 | 频率 | 时间 | TaskManager 类型 |
|------|------|------|-----------------|
| L1 宏观 agent 运行 | 每交易日 | 美东 17:00（盘后） | `macro_scan` |
| L2 板块 agent 运行 | 每交易日 | 美东 17:05 | `sector_scan` |
| Scorecard 价格回填 | 每交易日 | 美东 17:30 | `scorecard_backfill` |
| Darwinian 权重更新 | 每交易日 | 美东 17:35 | `darwinian_update` |
| Meta Agent 迭代 | 每周日 | 20:00 | `meta_autoresearch` |
| Prompt A/B 验证结算 | 每周五 | 18:00 | `prompt_ab_settle` |

### 10.2 与现有系统的集成点

| 集成点 | 方式 |
|--------|------|
| 个股分析触发时 | `analyzer.py` 在 `create_initial_state` 后注入当日 L1/L2 context |
| 分析完成后 | `workers.py` 的 analysis_worker 末尾调用 `record_analysis_scorecards()` |
| 仪表盘 | 新增"Agent 健康度"卡片，展示 top/bottom agent 和权重分布 |
| 任务中心 | 所有定时任务通过 TaskManager 执行，可在任务中心查看 |
| 设置页 | 新增"自我迭代"开关（enable_self_iteration），可关闭整个机制 |

---

## 十一、美股特有注意事项

| # | 坑 | 应对 |
|---|----|----|
| 1 | **盘后/盘前交易** | Scorecard 只用收盘价，忽略盘后波动。Agent 分析应明确说"基于收盘数据" |
| 2 | **Earnings season** | 每季度 1 月/4 月/7 月/10 月中下旬集中财报。L2 agent prompt 需感知"当前是否财报季" |
| 3 | **FOMC 日历** | Fed Watcher 的 prompt 需包含下次 FOMC 会议日期，距离越近权重应越高 |
| 4 | **股票拆分/分红** | yfinance 默认返回调整后价格（`Adj Close`），scorecard 回填要用 adj close |
| 5 | **ETF 的 NAV vs 市价** | 板块 agent 用 ETF 收盘价即可，NAV 偏差对信号级分析无影响 |
| 6 | **小盘股流动性** | Scorecard 回填时若成交量 < 10 万股/天，标记 `low_liquidity=True`，不计入 Sharpe |
| 7 | **美股休市日** | 定时任务需检查是否交易日（Martin Luther King、Presidents Day、Memorial Day 等） |

---

## 十二、分阶段实施

### Phase 1 — Scorecard 基础（1 周）

| 步骤 | 内容 | 验证 |
|------|------|------|
| 1.1 | 新建 `agent_scorecards` 表 | 表创建成功 |
| 1.2 | 在现有 analysis_worker 末尾加 `record_analysis_scorecards()` | 每次分析后 7 条 scorecard 记录生成 |
| 1.3 | 实现 `backfill_returns` 定时任务 | 5 天后 return_5d 自动回填 |
| 1.4 | 实现 `update_rolling_metrics` | Sharpe / hit_rate 计算正确 |
| 1.5 | 前端"Agent 健康度"展示（仪表盘新卡片） | 可看到每个 agent 的 Sharpe 排名 |

**Phase 1 结束时你能看到**：每次分析后，7 个 agent 各自"被打分"，5/20 天后能看到谁说对了谁说错了。

### Phase 2 — Darwinian 权重（0.5 周）

| 步骤 | 内容 | 验证 |
|------|------|------|
| 2.1 | 新建 `darwinian_weights` 表 | 表创建成功 |
| 2.2 | 实现每日权重更新逻辑 | top 25% 权重上调、bottom 25% 下调 |
| 2.3 | 在分析管线中注入权重 context | Portfolio Manager 的输入包含权重信息 |

**Phase 2 结束时你能看到**：差 agent 的话语权在自动降低，好 agent 的权重在上升。

### Phase 3 — L1/L2 Agent（1 周）

| 步骤 | 内容 | 验证 |
|------|------|------|
| 3.1 | 新建 `agents/prompts/` 目录 + 11 个 prompt 文件 | 文件存在 |
| 3.2 | 实现 MacroAgent 基类 + 5 个 L1 agent | 每个能独立运行并产出信号 |
| 3.3 | 实现 SectorAgent 基类 + 6 个 L2 agent | 每个能独立运行并产出信号 |
| 3.4 | 新建 `macro_signals` / `sector_signals` 表 | 每日信号持久化 |
| 3.5 | 注入到 TradingAgents 管线 | 分析 AAPL 时，context 中包含 L1 宏观 + L2 Tech 板块观点 |
| 3.6 | L1/L2 的 scorecard 记录 | macro/sector agent 也被打分 |
| 3.7 | 定时调度（盘后自动运行） | APScheduler 触发 |

### Phase 4 — Meta Agent 自我迭代（1 周）

| 步骤 | 内容 | 验证 |
|------|------|------|
| 4.1 | 新建 `prompt_versions` 表 | 表创建成功 |
| 4.2 | 实现 MetaAgent.run() | 能找到最差 agent 并生成新 prompt |
| 4.3 | 实现 A/B 测试机制 | testing 版本并行运行，scorecard 分别记录 |
| 4.4 | 实现验证期结算 | 5 天后自动对比 Sharpe，决定 activate 或 retire |
| 4.5 | 每周日定时调度 | APScheduler 触发 |

**Phase 4 结束时**：系统已经在自我进化——差 agent 被自动识别、prompt 被自动改写、改写效果被自动验证。

### Phase 5 — 可选增强

- Options flow agent（需要数据源）
- Earnings calendar 感知（自动标注财报日）
- Agent 之间的交叉验证（L1 宏观信号影响 L2 板块权重）
- 前端 Agent 进化历史可视化（prompt 版本时间线 + Sharpe 曲线）

---

## 十三、测试用例

### 13.1 Scorecard

| ID | 用例 | 预期 |
|----|------|------|
| SC-1 | 分析 AAPL 后记录 scorecard | 7 条记录（4 analyst + Research Mgr + Trader + Portfolio Mgr） |
| SC-2 | 5 天后回填 return_5d | price_5d 和 return_5d 正确填充 |
| SC-3 | 30 天滚动 Sharpe | 计算值与手动验算一致 |
| SC-4 | 命中率计算 | BUY+上涨 / SELL+下跌 / HOLD+横盘 |
| SC-5 | 空数据容错 | < 5 条记录时不计算 Sharpe |

### 13.2 Darwinian 权重

| ID | 用例 | 预期 |
|----|------|------|
| DW-1 | Top 25% agent 权重上调 | 新权重 = old × 1.05 |
| DW-2 | Bottom 25% agent 权重下调 | 新权重 = old × 0.95 |
| DW-3 | 权重硬边界 | 不超过 2.5，不低于 0.3 |
| DW-4 | 权重注入到分析 context | Portfolio Manager 输入含权重信息 |

### 13.3 L1/L2 Agent

| ID | 用例 | 预期 |
|----|------|------|
| L1-1 | Fed Watcher 产出信号 | JSON 含 signal/confidence/key_factors/summary |
| L1-2 | Risk Gauge 读取 VIX | 从 yfinance 取 ^VIX 数据 |
| L2-1 | Tech/AI agent 产出 | JSON 含 signal/momentum/top_picks |
| L2-2 | 信号注入到个股分析 | 分析 NVDA 时 context 含 L2 Tech 观点 |

### 13.4 Meta Agent

| ID | 用例 | 预期 |
|----|------|------|
| MA-1 | 找到最差 agent | 返回 Sharpe 最低的 agent_id |
| MA-2 | 生成新 prompt | 输出含 PROMPT_START/END 标记 |
| MA-3 | A/B 测试并行 | active 和 testing 版本各自有 scorecard |
| MA-4 | 验证期结算 | Sharpe 改善 → activate；没改善 → retire |
| MA-5 | 无 testing 版本时跳过 | 不报错 |

---

## 十四、与现有系统的兼容性

| 现有功能 | 影响 | 说明 |
|---------|------|------|
| 单票 AI 分析 | 增强 | 分析时自动获得 L1/L2 context + agent 权重信息 |
| 批量持仓分析 | 增强 | 每只分析都自动记录 scorecard |
| 选股 V2 | 不影响 | 独立系统 |
| Paper Trade | 增强 | Scorecard 本质是更细粒度的 paper trade |
| 任务中心 | 增强 | 新增 macro_scan / sector_scan / meta_autoresearch 任务类型 |
| 设置页 | 增强 | 新增 self_iteration.enabled 开关 |

**关键设计原则**：`self_iteration.enabled = false` 时，系统行为与现在完全一致，没有任何 L1/L2/scorecard/Darwinian 机制运行。开关打开后才激活。

---

*方案 v1.0 结束。请审阅后确认优先级和实施节奏。*
