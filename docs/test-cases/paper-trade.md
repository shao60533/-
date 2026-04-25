# 测试用例：纸面交易（Paper Trade）

| 项 | 值 |
|---|---|
| Feature | `paper-trade` |
| 版本 | v1.0（首版；覆盖设计 v1.0-v1.3） |
| 日期 | 2026-04-19 |
| 关联设计 | [../design/paper-trade.md](../design/paper-trade.md) v1.3 |
| 前置说明 | 本文件补齐 [test-cases/changelog.md](./changelog.md) 标注的"纸面交易测试用例待补充" |

## 汇总

| 分类 | 用例数 |
|---|---|
| 设计 v1.0-v1.2 基线（现有功能）| 38 |
| v1.3 F1 · Plan dedup | 10 |
| v1.3 F2 · AI 最终决策 surface | 6 |
| v1.3 F3 · executive_summary 抽取 | 9 |
| v1.3 F4 · 日度图表重配 | 7 |
| v1.3 F5 · 执行记录 tab 合并 | 8 |
| 集成：multi-tenant / model-switch | 6 |
| 性能 & 回归 | 5 |
| **总计** | **89** |

---

## 1. 基线功能 v1.0-v1.2（38）

### 1.1 Session 管理（8）

- **TC-PT-B1**：创建 replay session（指定 ticker + 日期区间）→ session 记录入库
- **TC-PT-B2**：创建 live session（auto_track=True）→ 标记为系统默认 session
- **TC-PT-B3**：session 删除 → 其 trades / equity / events 子表级联
- **TC-PT-B4**：session 列表按 user_id 过滤（集成 multi-tenant）
- **TC-PT-B5**：session 列表分页
- **TC-PT-B6**：系统默认 session 不可被手动删除
- **TC-PT-B7**：同一用户可创建多个非默认 session
- **TC-PT-B8**：session `metrics_json` 汇总字段正确（num_trades, win_rate, total_return_pct）

### 1.2 自动追踪（10）

- **TC-PT-B9**：一条新 analysis（signal=BUY，非 ERROR）→ 自动创建 `analysis_tracked` 记录，状态 pending
- **TC-PT-B10**：analysis_tracked 关联到用户默认 live session
- **TC-PT-B11**：信号过期前 strategy_engine 执行 → 状态 → executed
- **TC-PT-B12**：信号未命中触发条件 → 状态 → skipped 含 skip_reason
- **TC-PT-B13**：ERROR 分析不触发 tracked 记录
- **TC-PT-B14**：同一 ticker 连续两次分析 → 两条 tracked 记录（供 plan 层做 dedup，见 F1）
- **TC-PT-B15**：分析页徽章显示"已追踪"
- **TC-PT-B16**：历史记录页 analysis 行展示追踪状态列
- **TC-PT-B17**：session 详情页按时间顺序列出该 session 所有 tracked
- **TC-PT-B18**：tracked 记录删除不影响 analysis_history

### 1.3 交易与权益（10）

- **TC-PT-B19**：BUY 信号 + entry 条件满足 → trade 写入 + position_shares 增
- **TC-PT-B20**：SELL 信号 + exit 条件满足 → trade 写入 + position_shares 减
- **TC-PT-B21**：HOLD 信号 → 不产生 trade
- **TC-PT-B22**：止损触发 → trade 标记 reason=stop_loss
- **TC-PT-B23**：止盈触发 → trade 标记 reason=take_profit
- **TC-PT-B24**：时间止损触发 → trade 标记 reason=time_limit
- **TC-PT-B25**：每日 snapshot 写入 `paper_trade_equity`
- **TC-PT-B26**：equity total_value = cash + position_shares × price
- **TC-PT-B27**：daily_pnl = 今日 total_value - 昨日 total_value
- **TC-PT-B28**：cum_pnl_pct 基于初始本金计算

### 1.4 前端展示（10）

- **TC-PT-B29**：`/page-paper` 展示 session 卡片列表
- **TC-PT-B30**：点击 session 卡 → session 详情页
- **TC-PT-B31**：session 详情的 4 个 tab 可切换（v1.3 后变 3 tab，见 F5）
- **TC-PT-B32**：当前策略 tab 显示最新 active plan
- **TC-PT-B33**：持仓状态卡显示股数 / 成本 / 现价 / 浮盈 / 市值 / 现金 / 总值
- **TC-PT-B34**：投资周期显示 holding_months_min-max
- **TC-PT-B35**：档位列表按 sequence 排序
- **TC-PT-B36**：已执行档位显示执行日期 + 价格
- **TC-PT-B37**：待触发档位显示触发条件文本
- **TC-PT-B38**：空 session（无分析）显示合理占位

---

## 2. v1.3 F1 · Plan dedup（10）

### TC-PT-F1-1：首次插入 plan → fingerprint 计算正确

```python
@pytest.mark.unit
def test_fingerprint_stable():
    plan = Plan(entry_low=200, entry_high=210, stop_loss=180, take_profit=250,
                orders=[Order(seq=1, trigger="immediate", target_pct=12.5),
                        Order(seq=2, trigger="breakout_retrace", target_pct=70)])
    fp1 = _plan_fingerprint(plan)
    fp2 = _plan_fingerprint(plan)
    assert fp1 == fp2  # 稳定
```

### TC-PT-F1-2：orders 乱序后 fingerprint 相同（内部稳定排序）

### TC-PT-F1-3：entry_low 变化 → fingerprint 不同

### TC-PT-F1-4：完全一致的 plan 第二次 save → 不插新行，现有行 `reconfirmed_count` 从 1→2，`analysis_ids` 追加新 id

```python
@pytest.mark.integration
def test_dedup_on_identical_plan(db, session_id):
    p = _make_plan()
    id1 = save_plan(session_id, p, analysis_id=1)
    id2 = save_plan(session_id, p, analysis_id=2)
    assert id1 == id2
    row = db.fetchone("SELECT reconfirmed_count, analysis_ids FROM paper_trade_plans WHERE id=?", (id1,))
    assert row["reconfirmed_count"] == 2
    assert json.loads(row["analysis_ids"]) == [1, 2]
```

### TC-PT-F1-5：不同 plan（entry 变） → supersede 旧 + insert 新 + analysis_ids 独立

### TC-PT-F1-6：supersede 时 `superseded_by_plan_id` 指向新 plan

### TC-PT-F1-7：UI 当 `reconfirmed_count > 1` 时卡右上角显示"重复确认 × N · 最新 YYYY-MM-DD"

### TC-PT-F1-8：`reconfirmed_count == 1` 时不显示该标签（最常见情况不加噪声）

### TC-PT-F1-9：迁移脚本为存量数据回填 fingerprint（幂等）

### TC-PT-F1-10：并发 2 请求对同一 plan dedup（事务保护）→ 仅 1 条插入 + counter=2

---

## 3. v1.3 F2 · AI 最终决策 surface（6）

### TC-PT-F2-1：page-paper 底部板块名为 "AI 最终决策"（非 "AI 原文"）

### TC-PT-F2-2：内容为 `analysis_history.trade_decision` 的 Markdown 全文渲染

### TC-PT-F2-3：头部显示 `关联分析 #<id> · <created_at>`

### TC-PT-F2-4：点击头部跳转 `/page-analysis?id=<id>`

### TC-PT-F2-5：strategy_engine.py 的 signal→文案映射在**任务通知场景**继续有效（回归）

### TC-PT-F2-6：分析 trade_decision 为空 → 显示"（该分析暂无最终决策文本）"占位

---

## 4. v1.3 F3 · executive_summary 抽取（9）

### TC-PT-F3-1：analyzer 生成分析后 `result.executive_summary` 非空（2-3 句）

### TC-PT-F3-2：ExecutiveSummary Pydantic schema 合法（`thesis: str`）

### TC-PT-F3-3：`with_structured_output` 被调用（不走自写 JSON 解析）

### TC-PT-F3-4：LLM 返回异常 → executive_summary = None（不 raise）

### TC-PT-F3-5：`analysis_history.executive_summary` 列存在（迁移后）

### TC-PT-F3-6：plan_parser 读 executive_summary，不再写字面量 "regex 解析"

### TC-PT-F3-7：**代码库全局 grep 不出现 `"regex 解析"` 字符串**（硬断言）

### TC-PT-F3-8：thesis = None 时 UI 显示占位"（执行总结生成失败，查看完整分析 ›）"

### TC-PT-F3-9：迁移脚本为存量 analysis_history 回填 executive_summary（批次运行，成本约 ¥5）

---

## 5. v1.3 F4 · 日度图表重配（7）

### TC-PT-F4-1：双 grid 布局：grid[0] 占高 60% 为净值，grid[1] 占高 18% 为 pnl 柱

### TC-PT-F4-2：净值曲线 `markPoint` 自动标注最高/最低点

### TC-PT-F4-3：drawdown_pct < 0 区段有红色半透明 `markArea` 阴影

### TC-PT-F4-4：pnl 柱形 `visualMap` 正值绿色、负值红色（与 CSS token 对齐）

### TC-PT-F4-5：tooltip 一行格式 `日期 · 价格 · 累计% · DD%`

### TC-PT-F4-6：移动端（≤575.98px）只显示净值 grid，pnl 柱隐藏

### TC-PT-F4-7：桌面端（≥768px）与 baseline 截图无 pixel 回归（不破坏原视觉外 F4 预期）

---

## 6. v1.3 F5 · 执行记录 tab 合并（8）

### TC-PT-F5-1：`#ptv-tabs` tab 数量 = 3（当前策略 / 执行记录 / 日度数据）

### TC-PT-F5-2：旧 DOM id `ptv-tab-timeline` / `ptv-tab-history` 已移除

### TC-PT-F5-3：新 tab `#ptv-tab-records` 默认 `按 Plan` 视图

### TC-PT-F5-4：chip-row 切换到 `按 Event` → 渲染原 timeline 数据

### TC-PT-F5-5：`按 Plan` 视图每卡片可展开显示该 plan 的关联 events（按 analysis_ids 过滤）

### TC-PT-F5-6：展开收起状态本地存储（刷新保持）

### TC-PT-F5-7：移动端（≤575.98px）tab 可横滑（复用 `.tabs-scrollable`）

### TC-PT-F5-8：后端 API `/api/paper/tickers/<ticker>` 零改动（只读现有字段）

---

## 7. 集成：multi-tenant & model-switch（6）

### TC-PT-I1：alice 的 sessions bob 不可见（[multi-tenant](../design/multi-tenant.md)）

### TC-PT-I2：alice 触发的 analysis → executive_summary 使用 alice 的 llm_provider（[model-switch](../design/model-switch.md)）

### TC-PT-I3：tasks.created_by = alice.id（若 F3 走异步 worker）

### TC-PT-I4：alice 和 bob 各自看自己 paper sessions，共享 analysis_history

### TC-PT-I5：session / plans / trades 子表 JOIN 始终走 `user_id` 过滤

### TC-PT-I6：admin 可只读查询其他用户 sessions（审计）

---

## 8. 性能 & 回归（5）

### TC-PT-P1：F1 dedup 查询走 `ix_plans_session_ticker_fp` 索引（EXPLAIN 无 full scan）

### TC-PT-P2：F3 executive_summary 抽取延迟 ≤ 3s（单次 LLM 调用）

### TC-PT-P3：F4 图表渲染 200 日数据 ≤ 300ms

### TC-PT-P4：v1.3 迁移脚本对 1000 行 plans 回填完成 ≤ 10s

### TC-PT-P5：回滚脚本（恢复 .pre-v1_3.bak）完整还原

---

## 覆盖要求

| 模块 | 目标 |
|---|---|
| `strategy/paper_trader/session_store.py` 改动行 | ≥ 90% |
| `strategy/paper_trader/plan_parser.py` 改动行 | ≥ 90% |
| `agents/analyzer.py` ExecutiveSummary 抽取分支 | ≥ 90% |
| `migrations/paper_trade_v1_3.py` | 100% |
| `app.js` 新增 view-switcher + ECharts 重配 | ≥ 75% |

### 运行命令

```bash
# 单元 + 集成
pytest tests/paper_trader/ tests/agents/test_executive_summary.py \
       --cov=stock_trading_system/strategy/paper_trader \
       --cov=stock_trading_system/agents/analyzer \
       --cov-report=term-missing

# 前端
npx playwright test tests/frontend/test_paper_trade_*.spec.js

# 字面量禁令
grep -rn '"regex 解析"' stock_trading_system/ && exit 1 || echo OK
```

## 版本历史

| 版本 | 日期 | 用例数 | 变更 |
|---|---|---|---|
| v1.0 | 2026-04-19 | 89 | 首版：基线 38 + v1.3 五项修订 40 + 集成 6 + 性能回归 5 |
