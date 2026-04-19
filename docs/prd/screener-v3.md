# PRD: 智能选股 V3 —— 大师 Agent 深度评估

| 项 | 值 |
|---|---|
| Feature | `screener-v3` |
| 版本 | v1.0（产品版本 v3） |
| 日期 | 2026-04-19 |
| 关联技术方案 | [../design/screener-v3.md](../design/screener-v3.md) |
| 关联测试用例 | [../test-cases/screener-v3.md](../test-cases/screener-v3.md) |
| 替代 | [../design/screener-v2.md](../design/screener-v2.md) v1.1（guru 层）|

## 1. 背景

### 1.1 现状（V2）

[screener-v2.md](../design/screener-v2.md) 的 4 位大师实现（[buffett.py](../../stock_trading_system/screener/v2/gurus/buffett.py) 等）是**硬阈值脚本**：

```python
# 现状：单次评估 = 4 条 if 判断 + 一句 motto
if roe > 0.15: met.append("ROE > 15%")
if d2e < 0.5: met.append("低负债")
...
return make_match(met, unmet, reason="符合 3/4 条")
```

- 没有任何 LLM 推理
- 没有定性分析（护城河、管理质量、故事叙事）
- 没有内在价值/DCF/NCAV 等估值计算
- 大师之间互相独立，无辩论/共识
- 只有 4 位（Buffett / Graham / Lynch / O'Neil），缺 Munger / Fisher / Burry / Ackman / Wood / Marks / Dalio 等

### 1.2 用户反馈

> "选股逻辑比较简单，最好有现成的 agent 项目。"
> "NL 筛选后再跑 agent；成本/时间范围要让用户选前决定。"

### 1.3 调研结论（复用优先）

基线：**fork [virattt/ai-hedge-fund](https://github.com/virattt/ai-hedge-fund)**（56.3K ⭐、同栈 LangChain 0.3 + LangGraph + Pydantic 2、14 大师 × 每位 6-10 子分析）。

嫁接三处：
- [hengruiyun/AI-Investment-Master](https://github.com/hengruiyun/AI-Investment-Master)：AKShare 数据适配思路 + 中文 prompt（**借鉴重写**，避开 AGPL-3.0 传染）
- [KRSHH/ritadel](https://github.com/KRSHH/ritadel)：`round_table.py` 辩论层（MIT 可直接用）
- [GuruAgents arXiv 2510.01664](https://arxiv.org/html/2510.01664v1)：自建 Howard Marks / Ray Dalio prompt 模板

## 2. 目标

让选股从"静态阈值过滤"升级为"多位大师 agent 深度评估 + 圆桌辩论"，同时**预算可预估、范围可选择、过程可回看**。

### 2.1 成功指标

| 指标 | 目标 |
|---|---|
| 每位大师评估深度 | 6-10 个子分析维度 + 1 次 LLM 结构化推理 |
| 大师覆盖数 | 14 位（原 4 位 + 新 10 位） |
| 单次选股总时长（典型 20 候选 × 全 14 大师并发 10） | 3-5 分钟 |
| 单次成本可预估（跑前告知） | ± 20% 准确度 |
| 流式回显 | 每完成 1 大师/1 股 WebSocket 推送 1 条 |
| 中断可恢复 | 任务完成后可回看任何已完成部分 |
| 回归：原 4 位大师行为 | 保留"兼容模式"，UI 可选"经典阈值模式 / Agent 深度模式" |

## 3. 范围

### 3.1 In Scope（v3.0）

**流水线**（6 步）：

```
用户 NL → NL Parser → Universe Filter → Threshold Prefilter
                                             │
                                             ▼ Top 20 候选
                            ┌──── Guru Agents Pool ────┐
                            │   14 位并发 10            │
                            │   每位：6-10 子分析 + LLM │
                            │   输出：Pydantic 信号     │
                            └──────────┬───────────────┘
                                       │ Top 5
                                       ▼
                              Round-table 辩论
                                       │
                                       ▼
                           Regime 权重 + 最终排序
                                       │
                                       ▼
                                 Top 10-20 输出
```

**14 位大师**（分三批）：

| 批次 | 大师 | 来源 |
|---|---|---|
| 核心 8 位（virattt 移植）| Warren Buffett, Benjamin Graham, Charlie Munger, Peter Lynch, Philip Fisher, Michael Burry, Bill Ackman, Cathie Wood | virattt 代码借鉴 + 我们 clean-room 重写 |
| 进阶 4 位（virattt 移植）| Stanley Druckenmiller, Aswath Damodaran, Mohnish Pabrai, Nassim Taleb | 同上 |
| 独家 2 位（自建）| Howard Marks（周期/记忆/贪婪恐惧）, Ray Dalio（全天候/桥水原则）| arXiv 2510.01664 模板 + 自建 prompt |

**每位大师的内部结构**（以 Buffett 为例）：

```
WarrenBuffettAgent(BaseGuruAgent)
├── analyze_fundamentals()       # ROE/ROIC/利润率趋势
├── analyze_consistency()        # 过去 5 年盈利稳定性
├── analyze_moat()               # 毛利率稳定性 + 无形资产
├── analyze_pricing_power()      # 价格提升对销量的影响
├── analyze_book_value_growth()  # 账面价值复合增长率
├── analyze_management_quality() # 分红/回购/债务决策
├── calculate_intrinsic_value()  # DCF + owner earnings
├── calculate_margin_of_safety() # price vs 内在价值
└── llm_reason()                 # LLM 输出 Pydantic WarrenBuffettSignal
                                 #   { signal, confidence, reasoning, key_metrics }
```

**Round-table 辩论层**（Top 5）：
- 轮次 1：每位大师陈述对 5 只股票的意见（batch 召唤 5 大师 × 5 股 = 25 次 LLM，或聚合成 5 次"多股意见表"）
- 轮次 2：挑出分歧最大的 2-3 只股票，让持相反意见的大师互相反驳（~2-3 次 LLM）
- 聚合：Consensus / Dissent / Split —— 展示在结果页

**预选配置面板**（用户点"AI 筛选"前出现）：

```
┌─ 大师选择 ────────────────────────────────────────┐
│ [全选] [全不选]              估算：20 股 × N 大师 │
│  ☑ Warren Buffett            ☑ Benjamin Graham    │
│  ☑ Charlie Munger            ☑ Peter Lynch        │
│  ☐ Philip Fisher             ☐ Michael Burry      │
│  ☐ Bill Ackman               ☐ Cathie Wood        │
│  ☐ Stanley Druckenmiller     ☐ Aswath Damodaran   │
│  ☐ Mohnish Pabrai            ☐ Nassim Taleb       │
│  ☐ Howard Marks              ☐ Ray Dalio          │
├─ 深度模式 ────────────────────────────────────────┤
│  ○ 经典阈值（秒级完成，v2 行为）                  │
│  ● Agent 深度（LLM 推理，约 3-5 分钟）            │
│  ○ Agent + 圆桌辩论（多 30-60 秒，质量最高）      │
├─ 候选数量 ────────────────────────────────────────┤
│  NL 筛选后取 [ 20 ▼] 只候选股进入 Agent 评估       │
│  可选：10 / 20 / 30 / 50                          │
├─ 预计成本（跑前估算）───────────────────────────── │
│  20 股 × 4 大师 = ~80 次 LLM 调用                  │
│  预计时长：2-3 分钟                                │
│  预计 token：~160K 输入 / 40K 输出                 │
│  预计花费：¥1.5（Qwen）/ ~$0.15（Gemini）          │
├───────────────────────────────────────────────────┤
│              [取消]      [开始筛选 ►]              │
└───────────────────────────────────────────────────┘
```

**异步任务集成**：
- 走 [existing task_manager](../../stock_trading_system/tasks/task_store.py)
- `task.type = "screen_v3"`
- 结果写入 [screen_results_v2](../../stock_trading_system/tasks/task_store.py#L385)（schema 扩展）
- `tasks.created_by = g.user.id`（[multi-tenant](./multi-tenant.md) 约束）

**流式回显 & 中断恢复**：
- 每完成 1 (guru, ticker) WebSocket 推 `{ guru, ticker, signal, confidence, reasoning_preview }`
- 任务中途 UI 按 "停止" → worker 收到 cancel 标志 → 当前轮跑完后退出
- 任何时间重进任务详情页 → 渲染已完成部分 + 剩余占位

**缓存**：
- Key: `(ticker, guru, date_yyyy-mm-dd)` → value: full Pydantic signal JSON
- 写入 `kv_cache` category = `guru_signal`
- TTL：当日结束（新交易日失效）
- 命中率预期 ~60%（用户常重跑同一候选集）

### 3.2 Out of Scope（v3.0）

| 项 | 原因 | 未来 |
|---|---|---|
| 大师自定义 prompt（用户自己写 Buffett 怎么思考）| 风险大、收益低 | 不计划 |
| 实时监听（大师观点因新新闻自动更新）| 成本爆炸 | 不计划 |
| 大师之间跨股比较的"组合优化"（portfolio-level） | 进入组合配置领域，超出选股范围 | v3.1 或独立 feature |
| 非美股 A 股特殊规则（科创板、ST、限售股） | 借鉴 AI-Investment-Master 思路但需独立 PRD | v3.1 |
| 把大师 agent 嵌入持仓页（"Buffett 会怎么看我现在的仓位"） | 场景清晰但引入复杂度 | 未来 feature |
| 完全抛弃原 v2 硬阈值代码 | 保留"经典阈值模式"供省钱/快速使用 | 不做（长期保留） |

### 3.3 与 V2 的关系

- V2 的 **NL parser / Universe filter / Threshold prefilter / Aggregator / Regime detector** 全保留，无任何改动
- V2 的 **gurus/ 目录下 4 个文件**作为"经典阈值模式"保留不动
- V3 新增 `gurus_agents/` 目录（14 位 agent），在 UI 层由用户选择走哪条路径
- `BaseGuru` 接口升级兼容：`evaluate()` 同签名，返回同类型 `GuruMatch`，内部可能是旧逻辑或新 agent

## 4. 用户故事

### US-SV3-1（核心）：一次标准 Agent 筛选

> **作为**用户，输入"AI 方向，PE<30，负债低"，
> **希望**系统先 NL 筛选出 20 只候选股，然后用我选的 4 位大师深度评估，
> **3-5 分钟内**看到最终排序的 Top 10。

**验收**：
- 点"AI 筛选"→ 弹预选面板 → 选 4 大师 → 预估 ¥1.5 / 2-3 min
- 点"开始筛选"→ 异步任务创建 → 跳任务详情页
- 任务详情页实时显示：`Buffett × AAPL: ✓ 已完成`, `Graham × NVDA: 正在分析...`
- 3 分钟后任务完成 → 自动跳结果页显示 Top 10
- 每只股票下可展开看 4 位大师的信号 + 理由

### US-SV3-2：成本意识选择

> **作为**用户，不想每次都跑 14 位大师（成本/时间），
> **希望**根据当前需求选 2-14 位。

**验收**：
- 预选面板显示"已选 N 位"→ 下面预估 N × 候选 × ¥/call
- 只选 2 位时显示"快速模式：约 1 分钟"
- 选 14 位 + 圆桌时显示"全景模式：约 6 分钟"

### US-SV3-3：经典模式省钱

> **作为**用户，有时我只想秒级筛完拿个大概结果，
> **希望**能切回原来 V2 的硬阈值模式。

**验收**：
- 预选面板"深度模式"默认 Agent，但有"经典阈值（秒级）"选项
- 选经典 → 即时返回（无异步任务）→ 不花 token

### US-SV3-4：退出后能回看

> **作为**用户，5 分钟的任务跑着我关了浏览器，
> **希望**一小时后登录回来还能看到完整结果和每位大师的意见。

**验收**：
- 任务中心 "我的任务" tab 里看到该任务 status = success
- 点开任务详情 → 完整结果 + 每大师 per-ticker 意见 + 圆桌辩论记录
- 每大师的 reasoning 完整文本持久化（不只是 signal/confidence）

### US-SV3-5：中断可取消

> **作为**用户，跑到一半我觉得结果已经够用，
> **希望**能点"停止"退出，剩余 token 不花。

**验收**：
- 任务详情页有"停止"按钮
- 点后 worker 在当前 (guru, ticker) 跑完后退出
- 任务 status = cancelled，已完成部分可查看
- 剩余未跑的 (guru, ticker) 不消耗 token

### US-SV3-6：圆桌辩论增值

> **作为**进阶用户，**选"Agent + 圆桌辩论"**，
> **希望**对 Top 5 看到大师之间的不同观点碰撞。

**验收**：
- 结果页 Top 5 每只股票下有"大师圆桌"板块
- 显示：Consensus（一致看多/看空的大师） / Dissent（反对者） / Split
- 可点开看大师的反驳对话（prompt → response）

### US-SV3-7：缓存节省成本

> **作为**用户，对同样 20 候选重新点一次筛选（换了大师组合）
> **希望**已评估过的 (ticker, guru) 对不重跑。

**验收**：
- 第二次跑时 UI 显示 `缓存命中 48/80，新增 32 次调用`
- 预估成本相应下调
- 结果包含缓存结果与新结果混合

### US-SV3-8：Per-user model 生效

> **作为**选了 Gemini 的用户（[multi-tenant](./multi-tenant.md) 用户级设置），
> **希望**大师 agent 用 Gemini 跑，不是 Qwen。

**验收**：
- alice 设 llm_provider=gemini
- alice 触发 v3 筛选 → worker 日志显示 `Using Gemini for guru agents`
- 同时 bob 设 qwen → bob 的任务用 Qwen

## 5. 需求矩阵

### 5.1 P0 —— 必须上线

| ID | 描述 |
|---|---|
| R-SV3-1 | 14 位大师 agent 全部实现（每位 6-10 子分析 + LLM 推理） |
| R-SV3-2 | 预选配置面板 UI |
| R-SV3-3 | 成本/时长预估（± 20% 准确） |
| R-SV3-4 | 异步任务 + 流式 WebSocket 回显 |
| R-SV3-5 | 任务取消（剩余 call 不消费） |
| R-SV3-6 | 结果持久化（每大师 reasoning 全文存 DB） |
| R-SV3-7 | 缓存 (ticker, guru, date) |
| R-SV3-8 | 经典阈值模式（v2 行为）作为可选分支保留 |
| R-SV3-9 | 集成 [model-switch](../design/model-switch.md) 用户级 provider |
| R-SV3-10 | 集成 [multi-tenant](../design/multi-tenant.md) tasks.created_by |
| R-SV3-11 | 圆桌辩论层（Top 5，可选开启） |
| R-SV3-12 | BaseGuru 接口兼容：aggregator/regime 层零改动 |

### 5.2 P1 —— 可选

| ID | 描述 |
|---|---|
| R-SV3-13 | 大师模板"描述"页（每位点开看其原则、motto、代表持仓） |
| R-SV3-14 | 大师信号历史追溯（过去 30 天同大师对同股票的信号变化曲线） |
| R-SV3-15 | 结果导出（CSV / PDF） |
| R-SV3-16 | 大师之间的"相似度热图"（哪两位总是看法一致） |

### 5.3 P2 —— 未来

| ID | 描述 |
|---|---|
| R-SV3-17 | A 股特殊规则适配（参考 AI-Investment-Master）独立 PRD |
| R-SV3-18 | Portfolio-level 组合优化（基于大师意见） |
| R-SV3-19 | 大师自我迭代：把大师 prompt 纳入 [self-iterating-agents](../design/self-iterating-agents.md) 演化 |

## 6. 非功能需求

### 6.1 性能

| 场景 | 目标 |
|---|---|
| 20 候选 × 4 大师（经典量） | 1-2 分钟 |
| 20 候选 × 14 大师（全家桶） | 3-5 分钟 |
| 20 候选 × 14 大师 + 圆桌 | 4-6 分钟 |
| 预估 API 响应 | ≤ 200ms |
| WebSocket 推送延迟 | ≤ 500ms from guru-completes-ticker |

### 6.2 成本可预估性

- 预估值与实际成本偏差 ≤ 20%
- 缓存命中率达标（同候选集 24h 内复跑 ≥ 50%）

### 6.3 可观测性

- 每个 (guru, ticker) 调用记录 duration / tokens / cost
- 任务结束打印汇总：总时长 / 总 LLM 调用 / 缓存命中率 / 成本
- Prometheus/日志指标化（为 [self-iterating](./self-iterating-agents.md) 模块提供 agent_scorecards 数据源）

### 6.4 兼容性

- 不改 V2 现有数据库表 schema（仅 `screen_results_v2.results_json` 内容结构扩展）
- 不改 aggregator / regime 接口
- 经典模式走原代码路径，行为 100% 不变

## 7. 风险与假设

| 风险 | 缓解 |
|---|---|
| virattt 代码非明确 license，直接拉风险 | clean-room 重写：读其 agent 源码作为 spec，自写实现（独立模块 `gurus_agents/`） |
| 14 位大师 × 20 候选并发 10 触 LLM rate limit | Semaphore(10) + 指数退避；失败单元重试 ≤ 3 次 |
| 成本预估偏差大 | 校准：首批 5 (guru, ticker) 实际耗时/token 后动态修正剩余预估 |
| 流式回显丢消息 | 最终结果全量入库，前端打开任务详情重新拉取完整状态 |
| 同候选不同大师组合的缓存失效（新增大师） | 按 (ticker, guru, date) 细粒度缓存，与大师组合无关 |
| 圆桌辩论 LLM 跑偏（大师"出戏"） | 严格 system prompt 锚定身份；失败时降级为"无辩论"并标 "round-table skipped" |
| worker 崩溃丢中间结果 | 每单元完成后立即入库，重启任务从"未完成单元"继续（幂等） |

## 8. 与其他模块关系

| 模块 | 关系 |
|---|---|
| [screener-v2](../design/screener-v2.md) | v2 的 NL / Universe / Threshold / Aggregator 保留；gurus 层升级 |
| [model-switch](../design/model-switch.md) | router 接收 user_id → 14 大师用该用户的 provider |
| [multi-tenant](../design/multi-tenant.md) | tasks.created_by = user.id；user_settings.llm_provider 覆盖 |
| [mobile-optimization](../design/mobile-optimization.md) | 预选面板和任务详情复用 `form-row-mobile` / `chip-row` / `collapse-row` |
| [self-iterating-agents](../design/self-iterating-agents.md) | 每次 (guru, ticker) 调用写入 `agent_scorecards` —— 14 大师自动获得演化数据源 |
| [paper-trade](../design/paper-trade.md) | v3 产出的 Top 10 自动进入 auto_track 机制，纸面交易跟踪真实表现 |

## 9. 迁移策略

- V2 老数据（`screen_results_v2` 表里 v2 时代的结果）**保留**；status 字段新增 `engine: "v2" | "v3"` 区分
- 前端"筛选记录"页同时展示 v2 和 v3 结果，v3 行带"深度"标签
- V2 的 4 个 guru 页面卡片（UI 上的 Buffett / Graham / Lynch / O'Neil 开关）改造为"经典模式"的一组开关

## 10. 版本历史

| 版本 | 日期 | 变更 |
|---|---|---|
| v1.0 | 2026-04-19 | 初版：14 位大师 agent（virattt clean-room 借鉴）+ 圆桌辩论 + 预选配置面板 + 成本预估 + 缓存 + 经典模式兼容保留 |
