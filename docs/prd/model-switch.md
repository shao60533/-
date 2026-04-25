# PRD: 全局模型切换（Qwen ↔ Gemini）

| 项 | 值 |
|---|---|
| Feature | `model-switch` |
| 版本 | v1.0 |
| 日期 | 2026-04-18 |
| 关联技术方案 | [../design/model-switch.md](../design/model-switch.md) |
| 关联测试用例 | [../test-cases/model-switch.md](../test-cases/model-switch.md) |

## 1. 背景

### 1.1 现状

系统同时接入了 Qwen（通义千问）与 Google Gemini 两家 LLM，但**选择逻辑是硬编码**：

> [analyzer.py:97-145](../../stock_trading_system/agents/analyzer.py) —— 有 Qwen key 就 Qwen，否则 Gemini。

这意味着：

- 要从 Qwen 切到 Gemini，必须**删除环境变量 + 重启进程**；
- Nav 栏、设置页、API 都**没有暴露切换入口**；
- 没有"试一下另一家"的轻量路径，对比两家效果需要改配置重跑。

### 1.2 问题

用户（单人使用）在以下场景频繁需要切换：

1. **效果对比**：同一只股票分别用 Qwen / Gemini 各跑一轮，比较 signal / 报告风格。
2. **成本/配额控制**：Qwen 有 DashScope 配额，Gemini 有 Google 配额，单家触顶时要切另一家。
3. **地域/网络问题**：部分网络环境 Gemini 抖动，Qwen 稳定；反之亦然。
4. **模型能力差异**：Qwen3 thinking 强在中文/A 股，Gemini 强在英文新闻与跨域。

当前切换要改环境变量 + 重启，门槛太高，实际使用中**几乎没人切**。

## 2. 目标

让用户在 **Web UI 一键切换**系统的主推理 LLM，切换后**立刻对后续所有分析生效**，不需要重启进程。

### 2.1 成功指标

| 指标 | 目标 |
|---|---|
| 切换操作步骤 | ≤ 2 次点击（Nav 打开下拉 + 选中） |
| 切换生效延迟 | ≤ 3 秒（持久化到 yaml + 下一次分析采用新 provider） |
| 切换成功率 | ≥ 99%（失败仅限目标 provider 缺 key） |
| 冷启动兼容 | 未改动的老配置继续按原行为运行（零迁移） |

## 3. 范围

### 3.1 In Scope（v1.0）

**推理层 LLM 调用全部受开关控制**：

| 调用点 | 文件 | 说明 |
|---|---|---|
| StockAnalyzer / TradingAgents 7-agent pipeline | [analyzer.py:77-157](../../stock_trading_system/agents/analyzer.py) | 占 ~80% token 成本的主推理链路 |
| 选股 V2 —— NL → FilterSpec 解析 | [screener/v2/nl_parser.py:114](../../stock_trading_system/screener/v2/nl_parser.py) | 自然语言解析 |
| 选股 V2 —— Universe 筛选（Layer A） | [screener/v2/universe.py:41](../../stock_trading_system/screener/v2/universe.py) | 股池初筛 |
| 旧选股器 AI 评分 | [screener/screener.py:90-91](../../stock_trading_system/screener/screener.py) | Tier-3 AI eval |

**配置/持久化**：
- 新增顶层配置项 `llm_provider: "qwen" | "gemini"`（默认回退到现有自动探测逻辑）。
- 持久化到 `~/.stock_trading/config.yaml`（复用现有 [save_config()](../../stock_trading_system/config/settings.py) 原子写入）。
- 支持环境变量 `LLM_PROVIDER` 覆盖（部署/CI 用）。

**UI**：
- 顶部 Nav 栏右侧新增模型切换下拉：`模型: [Qwen ▼]` / `[Gemini ▼]`。
- 切换成功 → Toast：`已切换到 Gemini，下次分析生效`。
- 切换失败（目标 provider 缺 key） → Toast + 引导到设置页/README。

**API**：
- `GET /api/settings/llm-provider` —— 查询当前 provider + 两家可用状态。
- `POST /api/settings/llm-provider` —— `{"provider": "qwen" | "gemini"}`。

### 3.2 Out of Scope（不做）

| 项 | 原因 | 后续版本 |
|---|---|---|
| 数据层（[qwen_provider.py](../../stock_trading_system/data/qwen_provider.py) 的 get_price / get_news / get_fundamentals）切换 | 有 yfinance/AkShare 非 LLM 兜底；Gemini 无等价数据能力 | v2.0 可选 |
| 按分析任务临时覆盖（不改全局，只改这一次） | 单人使用，全局开关已够；临时需求可以改完再改回 | v1.1 |
| 多账号 / 多用户级 provider 配置 | 项目是单人部署，没有 users 表 | 无计划 |
| 新增第三家 provider（Claude / GPT / 豆包 / DeepSeek） | v1.0 聚焦现有两家；抽象层为后续扩展留口子 | v1.1+ |
| 回退/自动 failover（A 失败自动切 B） | 会掩盖问题，定位困难 | 不做 |
| 分 agent / 分阶段用不同 provider（如 judge 用 Gemini，fundamentals 用 Qwen） | 复杂度大幅上升，单人场景收益低 | 不做 |

## 4. 用户故事

### US-MS-1（核心）：一键切换主模型

> **作为**系统用户，
> **我希望**在 Web UI 顶部有一个下拉选项，
> **点击就能**把后续所有 AI 分析切换到 Qwen 或 Gemini，
> **这样**我不用重启服务，也不用改环境变量。

**验收标准**：
- 打开任意页面，Nav 栏右侧有 `模型` 下拉；
- 下拉打开显示两个选项，当前激活项有勾选标记；
- 选中另一项后，Toast 提示"已切换"；
- 新触发一次分析 → 后端日志显示新 provider（关键词 `Using Qwen LLM provider` 或 `Using Gemini LLM provider`）；
- 刷新页面，下拉依然是新选中的那一家（已持久化）。

### US-MS-2：切到缺 key 的家时有清晰拒绝

> **作为**用户，如果我尝试切到没有配置 API key 的那一家（比如 `GEMINI_API_KEY` 为空），
> **希望**系统拒绝切换并提示我去哪里配置，
> **而不是**默默切换然后下次分析报一个"401 Unauthorized"。

**验收标准**：
- 切换请求返回 `400 Bad Request`，body 带 `reason: "missing_api_key"`；
- UI Toast：`Gemini 未配置 API key，请先在 ~/.stock_trading/config.yaml 或环境变量 GEMINI_API_KEY 中设置`；
- 当前 provider 不变（回滚到切换前状态，无副作用）。

### US-MS-3：切换后立即生效，不需要重启

> **作为**用户，切换后下一次点"分析"就应该用新 provider，
> **不应该**看到"需要重启服务"之类的提示。

**验收标准**：
- 切换完成 ≤ 3 秒内，下一个 `POST /api/analyze` 请求使用新 provider；
- 正在跑的旧分析任务继续用旧 provider 跑完（不强制中断）；
- 无需重启 Flask / Python 进程。

### US-MS-4：env 变量优先级最高

> **作为**运维者，在 Railway 等云部署场景，
> **希望**通过设置环境变量 `LLM_PROVIDER=qwen` 强制固定 provider，
> **UI 上的切换不应该覆盖 env 设置**。

**验收标准**：
- 启动时若存在 env `LLM_PROVIDER`，以其为准；
- UI 下拉显示当前 provider 但切换按钮**禁用**，hover tooltip：`由环境变量 LLM_PROVIDER 锁定`；
- API `POST /api/settings/llm-provider` 返回 `409 Conflict`，`reason: "locked_by_env"`。

## 5. 需求矩阵

### 5.1 P0 —— 必须上线

| 需求 ID | 描述 | 验收方式 |
|---|---|---|
| R-MS-1 | 顶层配置 `llm_provider` + env `LLM_PROVIDER` 覆盖链 | 单测 + 集成 |
| R-MS-2 | `get_active_provider(config)` 单一真源函数 | 单测 |
| R-MS-3 | analyzer 按 active provider 分支 | 集成（两 provider 都跑通） |
| R-MS-4 | NL parser / universe / 旧 screener 按 active provider 分支 | 集成 |
| R-MS-5 | `POST /api/settings/llm-provider` 含 key 校验 | API 测试 |
| R-MS-6 | `GET /api/settings/llm-provider` 返回 provider + 两家 key 存在性 | API 测试 |
| R-MS-7 | Nav 栏模型下拉 UI + 持久化 | 前端 E2E |
| R-MS-8 | 切换成功/失败 Toast | 前端 E2E |
| R-MS-9 | Analyzer graph 缓存 key by provider（切换后下次分析用新 graph） | 集成 |
| R-MS-10 | env 锁定态：UI 禁用 + API 409 | API + UI 测试 |

### 5.2 P1 —— 可选优化

| 需求 ID | 描述 |
|---|---|
| R-MS-11 | 设置页面（完整的 `/settings` 页，不只是 Nav 下拉） |
| R-MS-12 | 在分析结果页显示"本次使用：Qwen-plus"标签（provenance） |
| R-MS-13 | 切换历史日志（何时从 X 切到 Y） |

### 5.3 P2 —— 未来

| 需求 ID | 描述 |
|---|---|
| R-MS-14 | 临时覆盖：单次分析指定 provider（不改全局） |
| R-MS-15 | 数据层也支持切换（需开发 GeminiDataProvider） |
| R-MS-16 | 新增第三家 provider（抽象层需要足够通用） |

## 6. 非功能需求

### 6.1 性能

- 切换操作延迟（UI 点击 → yaml 持久化完成）≤ 500ms。
- 下次分析采用新 provider 的延迟 ≤ 3s（含 graph 重新初始化时间）。
- Graph 缓存命中情况下，第二次切到相同 provider 时 < 100ms。

### 6.2 兼容性

- **零迁移**：现有 `~/.stock_trading/config.yaml` 未手动添加 `llm_provider` 字段时，沿用"有 Qwen key 就 Qwen，否则 Gemini"的老逻辑。
- 现有环境变量 `DASHSCOPE_API_KEY` / `GEMINI_API_KEY` 行为不变。
- `default_config.yaml` 默认不设置 `llm_provider`（即 `null`），触发 legacy 自动探测。

### 6.3 可观测性

- 每次切换打 INFO 日志：`LLM provider switched: qwen -> gemini (source: ui)`。
- 每次 analyzer `_init_graph()` 打 INFO 日志包含 provider（现有行为，不改）。

### 6.4 安全

- API key 不会出现在任何前端 payload 中（GET 接口只返回布尔 `has_qwen_key` / `has_gemini_key`）。
- 切换接口不接受客户端传 API key（只接受 provider 名字）。
- 配置文件权限沿用现有策略（`~/.stock_trading/` 用户私有目录）。

## 7. 风险与假设

| 风险 | 影响 | 缓解 |
|---|---|---|
| 切换瞬间正在跑分析，graph 被重建 | 旧分析中断 | 正在跑的分析用旧 graph 引用跑完；只有**下一次** `_init_graph()` 读新 provider |
| 用户切到 Gemini 后遇到 HK 出口 IP 封禁 | 分析失败 | 错误 Toast 提示"Gemini 在当前网络环境不可达，请切回 Qwen 或检查代理"（沿用现有错误捕获） |
| NL parser / universe 的 Gemini 实现质量不如 Qwen | 选股 V2 效果下降 | v1.0 用相同 prompt + JSON mode；必要时为 Gemini 单独调 prompt（v1.1 议题） |
| 用户把 `llm_provider` 改成 `"claude"` 这种未支持值 | 启动崩溃 | 配置加载时 validate，未知值回退到 legacy 自动探测 + 打 warning 日志 |
| env 锁定但用户困惑为什么切不动 | 支持成本 | UI 明确 tooltip + API 返回 `locked_by_env` 原因码 |

## 8. 与其他模块的关系

| 模块 | 关系 | 影响 |
|---|---|---|
| 自我迭代 agents（v3.0） | 迭代模块读 `config["iteration"]`，独立于 provider | 无耦合。provider 切换后，迭代模块的 prompt_overrides 继续注入，相当于"在新 provider 上跑旧 prompt"——这正好也是一个对比实验 |
| 纸面交易 | 只消费 analyzer 产出的 signal | 无影响 |
| 数据层（DataRouter） | 内部仍用 Qwen 提取数据 | v1.0 不切换数据层（见 §3.2） |
| 任务系统（TaskManager） | 透明，只调 analyzer | 无影响 |

## 9. 版本历史

| 版本 | 日期 | 变更 |
|---|---|---|
| v1.0 | 2026-04-18 | 初版：推理层全局切换 + Nav 下拉 UI + env 锁定态 |
