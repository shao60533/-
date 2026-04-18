# 设计方案变更记录

| 日期 | 文档 | 版本 | 变更内容 | 关联 Commit |
|------|------|------|---------|-------------|
| 2026-04-18 | [model-switch.md](model-switch.md) | v1.0 | 全局模型切换：新建 `stock_trading_system/llm/` 模块（router + client + constants），analyzer graph 按 provider 缓存，screener V2 call site 改用 LLMTextClient 抽象，Nav 下拉 + `/api/settings/llm-provider` GET/POST | — |
| 2026-04-18 | [self-iterating-agents.md](self-iterating-agents.md) | v3.0 | 自我迭代能力模块（包裹 TradingAgents）：最大化复用版。Agent Scorer(唯一核心新模块) + Darwinian 权重(采用 atlas-elenchus 常量) + Meta Agent(采用 atlas MUTATOR_SYSTEM_PROMPT) + A/B 验证复用 paper trade sessions。仅 2 张新表 | — |
| 2026-04-18 | [batch-analyze-holdings.md](batch-analyze-holdings.md) | v1.0 | 一键持仓分析方案：batch_analysis worker + 逐只推送 + 跳过近期 + 进度面板 | — |
| 2026-04-12 | [ui-ux-redesign.md](ui-ux-redesign.md) | v1.0 | 初版 UI/UX 重设计方案：9 页面线框图、移动端适配、组件规范（8 大类） | — |
| 2026-04-12 | [technical-design.md](technical-design.md) | v1.0 | 初版技术方案：前端改造 + 后端 API 补全 + 回测引擎 + PRD 追踪矩阵 | — |
| 2026-04-15 | [architecture-upgrade.md](architecture-upgrade.md) | v1.0 | 架构升级方案：Qwen 主导数据层 + TradingView 图表 + 异步任务系统 | — |
| 2026-04-15 | [architecture-upgrade.md](architecture-upgrade.md) | v1.1 | 补充：三层数据策略、TaskManager 设计、缓存策略、配置扩展 | — |
| 2026-04-15 | [screener-v2.md](screener-v2.md) | v1.0 | 智能选股 V2：8 Agent 并行打分 + 8 Guru 哲学 + Regime 自适应权重 | — |
| 2026-04-16 | [screener-v2.md](screener-v2.md) | v1.1 | 修订：NL 驱动优先，strategy chip 退化为辅助提示 | — |
| 2026-04-16 | [paper-trade.md](paper-trade.md) | v1.0 | 纸面交易方案：AI 信号回放 + 前向追踪 + 权益曲线 | — |
| 2026-04-16 | [paper-trade.md](paper-trade.md) | v1.1 | 修订：独立菜单 + 可选留痕 + 个股绑定 analysis_tracked 表 | — |
| 2026-04-16 | [paper-trade.md](paper-trade.md) | v1.2 | 修订：全量自动追踪（所有非 ERROR 分析自动进入默认 session） | — |
| 2026-04-15 | — | — | Phase A-E 架构升级实施完成（commit `034efe0`） | `034efe0` |

## 决策摘要

| 决策 | 选择 | 原因 |
|------|------|------|
| K 线图方案 | TradingView Widget（展示）+ ECharts（净值/回测） | TV 零数据成本，专业体验 |
| 回测数据源 | yfinance + LocalCache，不走 Qwen | 精度 + 可复现性 |
| 异步任务 | ThreadPoolExecutor + SQLite，非 Celery | 单人项目，零运维 |
| 数据主源 | Qwen（语义/判断/单点查询），Local（精确结构化） | LLM 做语义，专业 API 做数据 |
| 选股 V2 NL 优先 | 自然语言输入为主，strategy 为辅 | 用户反馈 |
| 纸面交易追踪 | 全量自动，非 opt-in | 100% 覆盖率，AI 效果可量化 |
