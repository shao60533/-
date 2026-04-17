# 实施指令 — 自我迭代美股分析 Agent

> 在新会话中说：
> "读 docs/design/self-iterating-agents.impl.md，按 Phase 1 实施，完成后跑 pytest tests/ -x"

---

## 上下文

技术方案：`docs/design/self-iterating-agents.md`（完整方案，必读第五~六节）

## Phase 1 实施范围 — Scorecard 基础

### 新建文件

1. **`stock_trading_system/agents/scorecard.py`**（新建）
   - `record_analysis_scorecards(analysis_result, analysis_id)` — 从一次分析中提取 7 个 agent 的 call 并写入 scorecard
   - `extract_direction(report_text)` — 用 Qwen-flash 从报告文本中提取 bullish/bearish/neutral
   - `backfill_returns()` — 回填 5d/20d 后续价格
   - `update_rolling_metrics()` — 更新滚动 30 天 Sharpe + 命中率
   - 参考方案第五节完整设计

2. **`stock_trading_system/agents/darwinian.py`**（新建）
   - `update_darwinian_weights()` — 每日权重更新（top 25% × 1.05, bottom 25% × 0.95, 边界 [0.3, 2.5]）
   - `get_current_weight(agent_id)` / `format_agent_weights()` — 读取和格式化权重
   - 参考方案第六节

3. **`tests/test_scorecard.py`**（新建）
   - 测试用例 SC-1 ~ SC-5 + DW-1 ~ DW-4（方案第十三节）
   - mock analysis_result 和 get_close_price

### 修改文件

4. **`stock_trading_system/tasks/workers.py`**
   - 在 `make_analysis_worker` 返回的 worker 函数末尾（分析成功后）：
     ```python
     from stock_trading_system.agents.scorecard import record_analysis_scorecards
     record_analysis_scorecards(result, analysis_id)
     ```
   - 注册新任务类型 `scorecard_backfill` 和 `darwinian_update`

5. **`stock_trading_system/portfolio/database.py`**
   - 在 `_init_db()` 中新增 `agent_scorecards` 表和 `darwinian_weights` 表的 CREATE TABLE
   - 参考方案第五节和第九节的 SQL

6. **`stock_trading_system/web/templates/index.html`**
   - 仪表盘新增"Agent 健康度"卡片：显示 top 3 / bottom 3 agent 的 Sharpe + 权重

7. **`stock_trading_system/web/static/js/app.js`**
   - 新增 `loadAgentHealth()` — 调 `/api/agents/health` 渲染健康度卡片

8. **`stock_trading_system/web/app.py`**
   - 新增 `GET /api/agents/health` — 返回每个 agent 的 Sharpe/命中率/权重

### 不改动

- TradingAgents 框架代码（`/Users/zhixingshao/TradingAgents/`）不动
- 现有分析流程不动（只在末尾追加 scorecard 记录）

## 实施顺序

1. 读完方案第五~六节
2. database.py → 建表
3. scorecard.py → 核心逻辑
4. darwinian.py → 权重逻辑
5. workers.py → 集成到分析流程
6. 跑 `pytest tests/test_scorecard.py`
7. app.py + index.html + app.js → 前端展示
8. `pytest tests/ -x` 确认无回归

## 完成标准

- [ ] 分析 AAPL 后 `agent_scorecards` 表新增 7 条记录
- [ ] 5 天后 `backfill_returns` 能回填 price_5d / return_5d
- [ ] `update_rolling_metrics` 计算 Sharpe 正确
- [ ] `update_darwinian_weights` 正确调节权重
- [ ] 仪表盘可看到 Agent 健康度卡片
- [ ] `pytest tests/test_scorecard.py` 全部通过
- [ ] `pytest tests/ -x` 无回归
