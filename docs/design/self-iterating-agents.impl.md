# 实施指令 — 自我迭代 Agent 能力模块

> 在新会话中说：
> "读 docs/design/self-iterating-agents.impl.md，按 Phase 1 实施，完成后跑 pytest tests/ -x"

---

## 上下文

技术方案：`docs/design/self-iterating-agents.md`（v3.0，必读第四~五节）

**核心定位**：包裹 TradingAgents 7-Agent 管线的独立迭代能力模块。分析仍走 TradingAgents，迭代模块观察每个 agent 表现、调权重、改 prompt。

**复用原则**：
- Sharpe/胜率计算 → 复用 `strategy/paper_trader/metrics.py`
- A/B 验证 → 复用 paper_trade_sessions
- Darwinian 常量 → 采用 atlas-elenchus（0.3/2.5/1.05/0.95）
- Meta Agent prompt → 采用 atlas-elenchus MUTATOR_SYSTEM_PROMPT

## Phase 1 实施范围 — Agent Scorer + Darwinian 权重

### 新建文件

```
stock_trading_system/agents/iterative/
├── __init__.py
├── config.py              # IterationConfig dataclass，从 config.yaml 的 iteration: 节加载
├── agent_scorer.py        # 核心模块，方案第四节
│   - AGENT_MAP: 7 个 agent 的 state_key + 提取方式
│   - record_analysis(analysis_id, ticker, date, final_state, price): 提取 7 个信号并写入
│   - backfill_returns(data_router): 回填 5d/20d return
│   - compute_agent_sharpe(returns): 复用 metrics.py 的 Sharpe 公式
│   - get_all_agent_metrics(): 返回每个 agent 的 {sharpe, hit_rate, weight}
├── darwinian.py           # 方案第五节
│   - update_darwinian_weights(scorer): top/bottom 25% 调权
│   - format_weight_context(): 生成注入到 init_state 的权重文本
│   - 常量: WEIGHT_MIN=0.3, MAX=2.5, BOOST=1.05, DECAY=0.95 (atlas-elenchus)
└── signal_extractor.py    # 工具函数
    - extract_signal_llm(report_text, qwen_client): 从报告文本提取 BULLISH/BEARISH/NEUTRAL
    - extract_signal_regex(trader_plan): 从 trader 输出正则提取 BUY/SELL/HOLD → BULLISH/BEARISH/NEUTRAL
    - bull/bear 固定返回，不调 LLM
```

### 修改文件

1. **`stock_trading_system/agents/analyzer.py`**（关键改动，方案第五节第三小节）
   - `analyze()` 方法改造：
     - 绕过 `self._graph.propagate()`，改为直接调 `self._graph.graph.invoke(init_state, **args)`
     - 如果 `iteration.enabled`，在 init_state["messages"] 前插入 weight context
     - 返回值从 `AnalysisResult` 改为 `(AnalysisResult, final_state)` 二元组
   - 新增 `_format_weight_context()` 方法
   - 新增 `_iteration_enabled` 属性（读 config）
   - **注意**：用 `self._graph.propagator.create_initial_state()` 和 `self._graph.propagator.get_graph_args()` 构造参数，保留 debug 的 stream 模式

2. **`stock_trading_system/portfolio/database.py`**
   - 在 `_init_db()` 新增 `agent_scorecards` 表（方案第八节 SQL）

3. **`stock_trading_system/tasks/workers.py`**
   - `make_analysis_worker` 末尾：分析成功后调用 `scorer.record_analysis()`
     - 需要处理 `analyze()` 返回二元组的变化
     - 需要获取 price_at_call（复用 data_router.get_price）
   - 新增 `make_score_update_worker(deps)` — 调用 `scorer.backfill_returns()` + `update_darwinian_weights()`
   - 在 `register_default_workers()` 中注册 `agent_score_update`

4. **`stock_trading_system/web/app.py`**
   - 新增 `GET /api/iteration/agents` — 返回 7 个 agent 的 sharpe/hit_rate/weight

5. **`stock_trading_system/config/default_config.yaml`**
   - 新增 `iteration:` 配置节（方案第九节），enabled 默认 false

### 测试文件

6. **`tests/test_iterative.py`**（新建）
   - 测试 IS-1 ~ IS-8 + DW-1 ~ DW-5 + REG-1 ~ REG-3（方案第十二节）
   - mock 要点：
     - mock `signal_extractor.extract_signal_llm` 返回固定信号
     - mock `data_router.get_price` 返回固定价格
     - mock `analyzer.analyze` 返回带 final_state 的二元组
   - 重点验证 REG-1：`iteration.enabled=false` 时 analyze() 行为完全不变

## 实施顺序

1. 读完方案第四~五节 + 第八节（SQL）+ 第九节（config）
2. `config/default_config.yaml` → 新增 iteration 配置
3. `agents/iterative/__init__.py` + `config.py` + `signal_extractor.py`
4. `portfolio/database.py` → 建表
5. `agents/iterative/agent_scorer.py` → 核心实现
6. `agents/iterative/darwinian.py` → 权重管理··
7. `agents/analyzer.py` → 改造 analyze() 方法（**最关键改动，仔细对照方案第五节第三小节**）
8. `tasks/workers.py` → 集成 scorer + 注册 worker
9. `web/app.py` → 新增 API
10. `tests/test_iterative.py` → 写测试
11. `pytest tests/test_iterative.py -x` → 单元测试
12. `pytest tests/ -x` → 回归测试

## 完成标准

- [ ] `iteration.enabled: false` 时，analyze() 行为与改前完全一致（REG-1）
- [ ] `iteration.enabled: true` 时，分析 AAPL 后 agent_scorecards 新增 7 条记录
- [ ] signal_extractor 正确处理 4 种提取方式（LLM/fixed/regex）
- [ ] backfill_returns 正确回填 5d return 和 hit
- [ ] compute_agent_sharpe 计算正确
- [ ] update_darwinian_weights 正确调节（top ×1.05 / bottom ×0.95 / 边界 0.3~2.5）
- [ ] format_weight_context 生成格式化权重文本
- [ ] GET /api/iteration/agents 返回 7 个 agent 状态
- [ ] `pytest tests/test_iterative.py` 全部通过
- [ ] `pytest tests/ -x` 无回归

## 关键注意事项

- `analyzer.py` 改动最大：从调 `self._graph.propagate()` 改为直接调 `self._graph.graph.invoke()`。必须保留 debug stream 模式的行为。仔细对照方案中的代码。
- `analyze()` 返回二元组 `(AnalysisResult, final_state)` 会影响所有调用方（workers.py 的 analysis_worker）。确保所有调用点都更新。
- `agent_scorer.record_analysis` 中的 LLM 调用（提取 4 个 analyst 的信号）是额外的 API 调用。如果分析本身失败了·（signal=ERROR），不要调 scorer。
