# 实施指令 — 自我迭代美股分析 Agent

> 在新会话中说：
> "读 docs/design/self-iterating-agents.impl.md，按 Phase 1 实施，完成后跑 pytest tests/ -x"

---

## 上下文

技术方案：`docs/design/self-iterating-agents.md`（v2.0，完整方案，必读第五~九节）

**核心定位**：独立于现有 TradingAgents 管线的新模块，统一用 `qwen3.6-plus`，有自己的 Agent 体系、Scorecard、Darwinian 权重和 Meta Agent 自我进化。

## Phase 1 实施范围 — 骨架 + Scorecard + 3 个 Agent 闭环

### 新建目录和文件

```
stock_trading_system/agents/iterative/
├── __init__.py
├── qwen_client.py         ← 方案第五节，qwen3.6-plus 客户端封装
├── base.py                ← 方案第六节，IterativeAgent 基类
├── scorecard.py           ← 方案第八节，scorecard 记录 + 回填 + 指标计算
├── darwinian.py           ← 方案第九节，权重更新
├── pipeline.py            ← 简化版管线（Phase 1 只跑 3 个 agent）
│
├── L1_macro/
│   ├── __init__.py
│   └── fed_watcher.py     ← 第一个 L1 agent
│
├── L2_sector/
│   ├── __init__.py
│   └── tech_ai.py         ← 第一个 L2 agent
│
├── L4_decision/
│   ├── __init__.py
│   └── cio.py             ← CIO 综合决策
│
└── prompts/
    ├── L1_fed.md           ← Fed Watcher 的 system prompt
    ├── L2_tech_ai.md       ← Tech/AI 板块 agent 的 system prompt
    └── L4_cio.md           ← CIO 的 system prompt
```

### 修改文件

1. **`stock_trading_system/portfolio/database.py`**
   - 在 `_init_db()` 新增 3 张表的 CREATE TABLE：
     - `agent_scorecards`（方案第八节 SQL）
     - `darwinian_weights`（方案第十二节 SQL）
     - `macro_signals`（方案第十二节 SQL）

2. **`stock_trading_system/tasks/workers.py`**
   - 新增 `make_iterative_daily_worker(deps)` — 调用 pipeline.run_daily()
   - 新增 `make_scorecard_backfill_worker(deps)` — 调用 scorecard.daily_scorecard_update()
   - 在 `register_default_workers()` 中注册 `iterative_daily` 和 `scorecard_backfill`

3. **`stock_trading_system/web/app.py`**
   - 新增 `POST /api/iterative/run` — 手动触发管线（提交 iterative_daily 任务）
   - 新增 `GET /api/iterative/latest` — 返回最近一次运行结果
   - 新增 `GET /api/iterative/agents` — 返回所有 agent 的 Sharpe/权重/命中率

4. **`stock_trading_system/config/default_config.yaml`**
   - 新增 `iterative:` 配置节（方案第十四节，enabled 默认 false）

### 测试文件

5. **`tests/test_iterative_scorecard.py`**（新建）
   - 测试 SC-1 ~ SC-8（方案第十七节）
   - mock qwen_client.call_json 返回固定 JSON
   - mock yfinance 的 get_close_price

6. **`tests/test_iterative_darwinian.py`**（新建）
   - 测试 DW-1 ~ DW-5

7. **`tests/test_iterative_pipeline.py`**（新建）
   - 测试 PL-1（简化版：3 agent 闭环）+ PL-6 + PL-8
   - mock 全部 Qwen 调用

## 实施顺序

1. 读完方案第五~九节 + 第十二节（表结构）+ 第十四节（配置）
2. `database.py` → 建表
3. `qwen_client.py` → Qwen 封装
4. `base.py` → Agent 基类
5. 3 个 prompt 文件 → `prompts/L1_fed.md`, `L2_tech_ai.md`, `L4_cio.md`
6. 3 个 agent 实现 → `fed_watcher.py`, `tech_ai.py`, `cio.py`
7. `scorecard.py` → 记录 + 回填 + 指标
8. `darwinian.py` → 权重更新
9. `pipeline.py` → 简化版管线（只 3 个 agent）
10. `workers.py` → 注册任务
11. `app.py` → 3 个 API
12. `pytest tests/test_iterative_*.py` → 单元测试
13. `pytest tests/ -x` → 回归测试

## 完成标准

- [ ] `POST /api/iterative/run` 触发管线，返回 task_id
- [ ] 管线运行完成后，`agent_scorecards` 表新增 3 条记录（L1_fed + L2_tech_ai + L4_cio）
- [ ] `macro_signals` 表新增 1 条 Fed Watcher 信号
- [ ] `daily_scorecard_update()` 正确回填 5d 价格 + 计算 Sharpe
- [ ] `update_darwinian_weights()` 正确调节权重
- [ ] `GET /api/iterative/agents` 返回 3 个 agent 的状态
- [ ] `iterative.enabled: false` 时不运行任何逻辑
- [ ] `pytest tests/test_iterative_*.py` 全部通过
- [ ] `pytest tests/ -x` 无回归
