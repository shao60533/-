# 测试用例：智能选股 V3

| 项 | 值 |
|---|---|
| Feature | `screener-v3` |
| 版本 | v1.0 |
| 日期 | 2026-04-19 |
| 关联 PRD | [../prd/screener-v3.md](../prd/screener-v3.md) |
| 关联设计 | [../design/screener-v3.md](../design/screener-v3.md) |

## 汇总

| 分类 | 用例数 |
|---|---|
| BaseGuruAgent / Pydantic 单元 | 8 |
| 14 大师 agent（每位 3-4 条） | 52 |
| Pipeline 编排 | 9 |
| 并发 & 重试 | 7 |
| 缓存 | 6 |
| 成本/时长预估 | 6 |
| 流式 WebSocket | 5 |
| Round-table 辩论 | 8 |
| API 端点 | 10 |
| 前端：预选面板 + 任务页 + 结果页 | 12 |
| 经典模式兼容 | 5 |
| 集成：model-switch / multi-tenant / self-iterating / paper | 8 |
| 性能 | 5 |
| 回归（v2 不受影响） | 4 |
| **总计** | **145** |

---

## 1. BaseGuruAgent & Pydantic 单元（8）

### TC-SV3-U1：GuruSignal schema 合法 payload 通过

```python
from stock_trading_system.screener.v3.gurus_agents.base import GuruSignal, SubAnalysis

def test_valid_signal():
    sig = GuruSignal(
        guru="buffett", ticker="AAPL",
        signal="bullish", confidence=0.85,
        reasoning="long text ...",
        sub_analyses=[SubAnalysis(name="moat", score=9.0, details="...")],
        key_metrics={"intrinsic_value": 220.0},
        total_score=88,
    )
    assert sig.signal == "bullish"
```

### TC-SV3-U2：confidence > 1 被 Pydantic 拒绝

### TC-SV3-U3：signal 非 literal 值被拒

### TC-SV3-U4：total_score 超 100 被拒（`le=100`）

### TC-SV3-U5：sub_analyses 空列表允许（数据缺失场景）

### TC-SV3-U6：`GuruSignal.model_dump_json()` → `model_validate_json()` 往返一致

### TC-SV3-U7：BaseGuruAgent 子类不实现 `evaluate_deep` 抛 NotImplementedError

### TC-SV3-U8：BaseGuruAgent `_llm_reason` 调用时传递正确 system_prompt 到 LLMTextClient

---

## 2. 14 大师 agent —— 每位 3-4 条（52）

对每位大师的共同断言（52 = 14 × 平均 3.7，各 mod 略）：

**共同断言模式**：
- T1: 输入完整数据 → 返回合法 GuruSignal
- T2: 数据缺失（某子分析输入为 None）→ 该子分析 score=0，整体降级
- T3: 代表性 positive 场景（代码假数据模拟该大师看好）→ signal="bullish", confidence > 0.6
- T4（仅部分大师）：代表性 negative 场景

下面列出前 3 位详细用例，其余 11 位按同模板。

### 2.1 Buffett（5 条）

**TC-SV3-B1**：完整数据 → returns GuruSignal with 8 sub_analyses

```python
def test_buffett_full_pipeline(mock_llm):
    bundle = _mock_bundle(ticker="AAPL", roe=0.35, fcf_margin=0.25, ...)
    sig = BuffettAgent().evaluate_deep("AAPL", bundle, {})
    assert sig.guru == "buffett"
    assert len(sig.sub_analyses) == 8
    assert "moat" in {s.name for s in sig.sub_analyses}
    assert "intrinsic_value" in sig.key_metrics
```

**TC-SV3-B2**：5 年财报序列缺失 → consistency sub_analysis score=0

**TC-SV3-B3**：高 ROE + 高 FCF → signal="bullish", confidence > 0.7

**TC-SV3-B4**：高负债（D/E > 2）+ 负 FCF → signal="bearish"

**TC-SV3-B5**：intrinsic_value 计算正确（owner earnings × DCF）

### 2.2 Graham（4 条）

**TC-SV3-G1**：完整数据返回合法 signal

**TC-SV3-G2**：净净股（current_assets - total_liabilities > market_cap）→ signal="bullish", confidence > 0.85

**TC-SV3-G3**：安全边际 < 20% → signal="neutral"

**TC-SV3-G4**：PE < 15 + PB < 1.5 + 流动比率 > 2 → 所有子分析 met

### 2.3 Munger（4 条）

**TC-SV3-M1**：完整数据返回 GuruSignal

**TC-SV3-M2**：质量评分（ROIC trend stable upward）高 → bullish

**TC-SV3-M3**：Lollapalooza 效应识别（多重利好叠加）→ confidence > 0.8

**TC-SV3-M4**：估值过高（PE > 50 且未见增长）→ bearish

### 2.4 Lynch（4 条）、Fisher（3）、Burry（4）、Ackman（4）、Wood（4）、Druckenmiller（4）、Damodaran（4）、Pabrai（4）、Taleb（3）、Marks（3）、Dalio（3）

按同模板，各自加 1 条对**该大师独有能力**的用例：

- Lynch: "PEG < 1 且故事一致" → bullish
- Fisher: "ROE 高 + 定性竞争优势（由 mock LLM 返回）" → bullish
- Burry: "深度 NAV discount + 反共识" → bullish
- Ackman: "Catalyst 事件（earnings / spin-off）mock 新闻有" → bullish high confidence
- Wood: "颠覆性叙事（AI / 基因 / 清洁能源） ticker" → bullish
- Druckenmiller: "宏观信号（flight to quality） + 大盘蓝筹" → bullish
- Damodaran: "DCF intrinsic_value 计算结果出现在 key_metrics"
- Pabrai: "Kelly formula 计算仓位占比在 key_metrics"
- Taleb: "极端下行风险 > 20% → bearish"
- Marks: "贪婪市场 + 高估值 → bearish；恐惧市场 + 被打压价值股 → bullish"
- Dalio: "四象限判定（通胀 × 增长）→ 期望表现在 reasoning 中"

---

## 3. Pipeline 编排（9）

### TC-SV3-P1：Phase 1-3 复用 v2 模块，输入 NL → 得 20 候选

### TC-SV3-P2：Phase 4 对 20 候选 × 4 大师 → 80 GuruSignal

### TC-SV3-P3：Phase 5 `with_roundtable=True` 且 Top 5 存在牛熊分歧 → 产生 debate

### TC-SV3-P4：Phase 5 Top 5 完全一致看多 → 跳过 debate（results.roundtable = consensus only）

### TC-SV3-P5：Phase 6 aggregator 正确合并 GuruSignal → total_score

### TC-SV3-P6：Pipeline 收到 cancel 信号在 Phase 4 中途 → 返回部分结果

### TC-SV3-P7：Pipeline 某 agent 抛异常 → 该 unit 结果为 error signal，不中断其他

### TC-SV3-P8：`mode="classic"` → 跳过 Phase 4/5，走 v2 旧 guru 代码

### TC-SV3-P9：`mode="agent"` 不选任何大师 → 返回 400 `no_gurus_selected`

---

## 4. 并发 & 重试（7）

### TC-SV3-C1：Semaphore(10) 确实限制同时运行单元数 ≤ 10（mock stopwatch）

### TC-SV3-C2：rate-limit error → 退避 2/4/8s 重试 3 次

### TC-SV3-C3：3 次重试仍失败 → 返回 error signal（signal=neutral, confidence=0）

### TC-SV3-C4：并发 10 任务，8 成功 2 失败 → pipeline 完整返回

### TC-SV3-C5：CANCEL flag 在 unit 运行中不中断当前 unit，下一个 unit 开始前退出

### TC-SV3-C6：asyncio 任务内所有 LLM 调用都 await 正确（无 hanging）

### TC-SV3-C7：长时间运行（模拟 5 分钟）内存无持续增长（leak 检查）

---

## 5. 缓存（6）

### TC-SV3-K1：首次 (AAPL, buffett, 2026-04-19) → cache miss → LLM 调用 + 写入 cache

### TC-SV3-K2：同日第二次同 (ticker, guru) → cache hit，不调用 LLM

### TC-SV3-K3：次日（date 变）→ cache miss 重跑

### TC-SV3-K4：`prompt_version` 升级 → 旧 cache key 不命中（新 key）

### TC-SV3-K5：cache hit 也触发 on_unit_done（cached=True 标记）

### TC-SV3-K6：`LocalCache` 写入失败 → 不阻塞主流程（warn log + 继续）

---

## 6. 成本/时长预估（6）

### TC-SV3-E1：`estimate(20, 4, False, "qwen")` 返回 80 calls / 160s / ~¥1.5

### TC-SV3-E2：`with_roundtable=True` 加 15 calls + ~60s

### TC-SV3-E3：不同 provider（qwen vs gemini）价格差异正确

### TC-SV3-E4：concurrency 参数变化影响 duration（5 vs 10 vs 20）

### TC-SV3-E5：动态校准：首 5 unit 实际值更新常量 → 下次 estimate 更准

### TC-SV3-E6：预估与实际偏差 ≤ 20%（3 次真实跑的校准验证）

---

## 7. 流式 WebSocket（5）

### TC-SV3-W1：task 创建后 `WS /ws/tasks/<task_id>` 可连接

### TC-SV3-W2：每个 unit 完成推送 `guru_unit_done` 事件

### TC-SV3-W3：roundtable 开始/结束分别推 `roundtable_start` / `roundtable_done`

### TC-SV3-W4：task 完成推 `task_complete` + result_url

### TC-SV3-W5：WS 断线重连后 `/api/tasks/<id>/state` 拉快照补齐

---

## 8. Round-table 辩论（8）

### TC-SV3-R1：Top 5 全看多 → RoundtableResult.consensus=全部, no debate

### TC-SV3-R2：Top 5 全看空 → 同上（consensus=bearish）

### TC-SV3-R3：牛熊分歧 → bull_champion 和 bear_champion 正确挑出（最高 confidence）

### TC-SV3-R4：双大师辩论 2 轮 → debate_snippets 长度 4（2 轮 × 2 角色）

### TC-SV3-R5：辩论 LLM 失败 → roundtable skipped，task 不失败

### TC-SV3-R6：辩论 prompt 包含对方论点（让大师真 "反驳"）

### TC-SV3-R7：consensus 多数派正确（4 bullish + 2 bearish → consensus=bullish）

### TC-SV3-R8：split 情况（3 bullish + 3 bearish）→ split=True

---

## 9. API 端点（10）

### TC-SV3-A1：`POST /estimate` 正常参数返回预估

### TC-SV3-A2：`POST /estimate` 缺参数返回 400

### TC-SV3-A3：`POST /trigger` 创建 task 并返回 task_id

### TC-SV3-A4：`POST /trigger` mode=classic → 同步返回结果（无 task）

### TC-SV3-A5：`POST /trigger` 未登录 → 401（multi-tenant）

### TC-SV3-A6：`POST /trigger` params 入库时 user_id 正确（ref `tasks.created_by`）

### TC-SV3-A7：`GET /results/<id>` 返回完整 results_json

### TC-SV3-A8：`POST /tasks/<id>/cancel` 已完成 task 返回 409

### TC-SV3-A9：`POST /tasks/<id>/cancel` 运行中 task → 下个 unit 前停止

### TC-SV3-A10：`GET /results/<id>` 对非触发者也可读（共享，multi-tenant 约束）

---

## 10. 前端（12）

### TC-SV3-F1：预选面板打开，默认 4 大师选中

### TC-SV3-F2：点"全选"→ 14 大师全选

### TC-SV3-F3：修改选项 500ms debounce 调 `/estimate` 更新成本显示

### TC-SV3-F4：候选数量切 10/20/30/50 → 对应更新

### TC-SV3-F5：深度模式 = 经典阈值 → 候选数量/大师选项灰显

### TC-SV3-F6：开始筛选 → 跳转 `/page-tasks`，显示新建 task

### TC-SV3-F7：任务详情页订阅 WS 并渲染进度条

### TC-SV3-F8：unit 完成实时插入列表行

### TC-SV3-F9：按股票/按大师两视图切换

### TC-SV3-F10：结果页 Top 10 列表点击展开抽屉

### TC-SV3-F11：抽屉内切换 tab：各大师 / 圆桌 / 原始数据

### TC-SV3-F12：移动端（375px）预选面板无横滑，控件 ≥ 44 高

---

## 11. 经典模式兼容（5）

### TC-SV3-CL1：v2 原 4 guru `BuffettGuru.evaluate()` 行为不变（diff 测试）

### TC-SV3-CL2：现有 `/api/screen/v2/trigger` 路径可用

### TC-SV3-CL3：v2 数据库记录不被 v3 改动（engine 字段兼容 NULL = "v2"）

### TC-SV3-CL4：前端"经典阈值"模式 → 不创建 async task，直接同步返回

### TC-SV3-CL5：现有 selector UI（4 个 guru toggle）在"经典模式"下继续工作

---

## 12. 集成（8）

### TC-SV3-I1：[model-switch](../design/model-switch.md)：alice 设 gemini，v3 worker 所有 LLM 调用用 Gemini

### TC-SV3-I2：bob 设 qwen，并发任务互不干扰

### TC-SV3-I3：[multi-tenant](../design/multi-tenant.md)：tasks.created_by = alice.id

### TC-SV3-I4：bob 登录看共享结果 Top 10 可读，audit 显示由 alice 触发

### TC-SV3-I5：[self-iterating-agents](../design/self-iterating-agents.md)：每个 GuruSignal 写入 `agent_scorecards`，cron 可计算 agent 表现

### TC-SV3-I6：prompt_version 升级触发 cache 失效

### TC-SV3-I7：[paper-trade](../design/paper-trade.md)：v3 Top 10 自动进 auto_track session

### TC-SV3-I8：任务取消后 paper-trade 仍能消费已产出的 Top 部分（部分完成容忍）

---

## 13. 性能（5）

### TC-SV3-PE1：20 股 × 4 大师实跑 ≤ 2.5 min

### TC-SV3-PE2：20 股 × 14 大师实跑 ≤ 5 min

### TC-SV3-PE3：20 股 × 14 大师 + roundtable 实跑 ≤ 6 min

### TC-SV3-PE4：缓存全命中（二次跑）耗时 ≤ 10s（仅 DB 读）

### TC-SV3-PE5：预估 vs 实际偏差 ≤ 20%（跑 3 次平均）

---

## 14. 回归（4）

### TC-SV3-RG1：v2 `/api/screen/v2/trigger` NL 筛选无变化

### TC-SV3-RG2：v2 4 guru 评估结果和上线前 baseline 一致

### TC-SV3-RG3：V2 历史 `screen_results_v2` 可在前端"记录"页正常查看

### TC-SV3-RG4：现有其他功能（分析 / 持仓 / 预警 / 回测）不受 v3 影响

---

## 覆盖要求

| 模块 | 目标 |
|---|---|
| `screener/v3/gurus_agents/*.py` | 行覆盖 ≥ 90%（每位大师） |
| `screener/v3/pipeline.py` | 行覆盖 ≥ 90% |
| `screener/v3/concurrency.py` | 行覆盖 ≥ 85%（含退避路径） |
| `screener/v3/cache.py` | 100% |
| `screener/v3/estimator.py` | 100% |
| `screener/v3/roundtable.py` | ≥ 85% |
| 前端 predict 面板 JS | ≥ 75% |

### 运行命令

```bash
# 单元 + 集成
pytest tests/screener/v3/ --cov=stock_trading_system/screener/v3 --cov-report=term-missing

# 真实 E2E（耗 LLM 额度，谨慎运行）
pytest tests/screener/v3/test_e2e_real_llm.py -m "slow"

# 前端
npx playwright test tests/frontend/test_screener_v3_*.spec.js
```

## 版本历史

| 版本 | 日期 | 用例数 | 变更 |
|---|---|---|---|
| v1.0 | 2026-04-19 | 145 | 初版：Pydantic 单元 8 + 14 大师 52 + Pipeline 9 + 并发 7 + 缓存 6 + 预估 6 + 流式 5 + 圆桌 8 + API 10 + 前端 12 + 经典兼容 5 + 集成 8 + 性能 5 + 回归 4 |
