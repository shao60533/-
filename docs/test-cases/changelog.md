# 测试用例变更记录

| 日期 | 文档 | 版本 | 用例数 | 变更内容 | 关联设计 |
|------|------|------|--------|---------|---------|
| 2026-04-14 | [v2.0-manual-test-cases.md](v2.0-manual-test-cases.md) | v1.0 | 151 | 初版测试用例：后端 API(42) + 前端页面(47) + 移动端(12) + WebSocket(8) + 状态(10) + 图表(8) + Toast(4) + 跨页面(4) + 异常(9) + 性能(7) | PRD v2.0 + 技术方案 v1.0 |
| 2026-04-15 | [architecture-upgrade.md](architecture-upgrade.md) | v1.0 | 204 | 架构升级测试用例：TaskManager(51) + LocalCache(18) + DataRouter(17) + Qwen 扩展(16) + TV Widget(16) + 回测(16) + 任务中心 UI(19) + WebSocket(6) + 性能(12) + 幂等(5) + 异常(10) + 回归(8) | 架构升级方案 |
| 2026-04-15 | [screener-v2.md](screener-v2.md) | v1.0 | 110 | 选股 V2 测试用例：单元测试(56) + 集成(18) + 前端(20) + 回归(8) + 性能(8) | 选股 V2 技术方案 |
| 2026-04-18 | [model-switch.md](model-switch.md) | v1.0 | 66 | 模型切换测试用例：单元(22: resolver 12 + client 4 + config 6) + 集成(11: analyzer 6 + screener 5) + API(10) + 前端(7) + 异常(8) + 回归(5) + 性能(3) | 模型切换技术方案 |
| 2026-04-18 | [mobile-optimization.md](mobile-optimization.md) | v1.0 | 82 | 移动端优化测试用例：通用组件单元(12) + 断点矩阵 11 页×3 断点(33) + 可达性(8) + 表格卡片降级(5) + 横滑(4) + 折叠行(5) + 性能 Lighthouse(4) + 桌面回归(6) + 真机(5) | 移动端优化技术方案 |
| 2026-04-19 | [multi-tenant.md](multi-tenant.md) | v1.0 | 130 | 多租户测试用例：auth 单元(14) + 邀请码(8) + repository(10) + 迁移脚本(9) + 权限隔离(18) + 共享可见性(6) + 任务中心(7) + model-switch 用户级(6) + auth API(14) + admin API(6) + 前端 E2E(10) + 安全(10) + 回归(5) + 性能(4) + 真机(3) | 多租户技术方案 |
| 2026-04-19 | [screener-v3.md](screener-v3.md) | v1.0 | 145 | 选股 V3 测试用例：Pydantic 单元(8) + 14 大师(52) + Pipeline(9) + 并发重试(7) + 缓存(6) + 成本预估(6) + 流式 WS(5) + 圆桌辩论(8) + API(10) + 前端(12) + 经典兼容(5) + 跨模块集成(8) + 性能(5) + 回归(4) | 选股 V3 技术方案 |
| 2026-04-19 | [paper-trade.md](paper-trade.md) | v1.0 | 89 | 纸面交易测试用例（首版，补齐历史缺口）：基线 v1.0-v1.2(38) + v1.3 F1 dedup(10) + F2 AI 决策 surface(6) + F3 executive_summary(9) + F4 图表(7) + F5 tab 合并(8) + 集成(6) + 性能回归(5) | 纸面交易 v1.0-v1.3 |
| 2026-04-20 | [unified-progress.md](unified-progress.md) | v1.0 | 101 | 统一进度系统测试用例：emit_event 单元(8) + task_events 表(5) + ProgressStream 组件(12) + per-user room(7) + 断线续传(8) + 11 task 发射(12) + 5 页面集成(10) + 3 布局视觉(9) + 5 态动画(6) + 移动端(6) + 异常(8) + 性能(5) + 回归(5) | 统一进度系统技术方案 |
| 2026-04-21 | [ui-react-island.md](ui-react-island.md) | v1.0 | 108 | UI React Island 测试用例：构建管道 Vite+Flask(10) + lib api/socket/auth(12) + shadcn 组件(14) + Screener V3 island(12) + Tasks(10) + Paper-trade(8) + Dashboard(7) + 跨岛集成(6) + 视觉一致性(8) + 非迁移页回归(7) + 性能(5) + 安全 CSRF(5) + 真机部署(4) | UI React Island 技术方案 |
| 2026-04-21 | [ui-react-island.md](ui-react-island.md) | v2.0 | 74 | 剩余 11 页测试用例：共享组件 AppShell/DataTable/Form/EChartsPanel(12) + Portfolio/History/Alerts/Reports(20) + Backtest/Paper list/Analysis(18) + Settings(7) + Auth Login/Register/Reset(9) + Phase 18 废弃旧代码(5) + v2.0 性能(3) | UI React Island v2.0 技术方案 |
| 2026-04-24 | [ui-migration-validation.md](ui-migration-validation.md) | v1.0 | 164 | 架构级迁移完整验证测试用例：L0 冒烟 5 + L1 基础 E2E 33 + L2 功能回归矩阵 74 + L3 跨模块集成脚本 20 + L4 数据完整性（row count/抽样/invariant/FK）14 + L5 对抗性（越权 8 + CSRF 3 + session 4 + 并发 3）18 | 迁移验证技术方案 |
| 2026-04-25 | [ui-react-island-regression.md](ui-react-island-regression.md) | v1.0 | 90 | 迁移回归修复测试用例：P0 CRITICAL 9 + P1 HIGH 26 + P2 MEDIUM/LOW 24 + 共享组件（Stat/ChartPanel/form-row-mobile）8 + Playwright E2E 12 + 视觉回归 11；P0 闸门强约束 + 老 Jinja baseline 截图归档 | 迁移回归修复技术方案 |
| 2026-04-25 | [ui-react-island-regression.md](ui-react-island-regression.md) | v1.1 | 94 | 补充：P0 新增 paper-trade 列表页 1 条（TC-RG-P0-3b 默认 session 突出卡 + 工具栏 + 卡 grid）+ 菜单重组 3 条（TC-RG-P0-10~12 桌面 Sidebar 6 组 / active 高亮 / Mobile Tabbar 5+更多） | 迁移回归修复 v1.1 |

## 用例总数汇总

| 文档 | 用例数 |
|------|--------|
| V2.0 手动测试用例 | 151 |
| 架构升级测试用例 | 204 |
| 选股 V2 测试用例 | 110 |
| 模型切换测试用例 | 66 |
| 移动端优化测试用例 | 82 |
| 多租户测试用例 | 130 |
| 选股 V3 测试用例 | 145 |
| 纸面交易测试用例 | 89 |
| 统一进度系统测试用例 | 101 |
| UI React Island 测试用例（v1.0 + v2.0）| 182 |
| 迁移验证测试用例 | 164 |
| 迁移回归修复测试用例（v1.0 + v1.1）| 94 |
| **总计** | **1518** |

## 覆盖状态

- 自动化测试（Python + Node）：208 个已实现（170 Python + 38 Node）
- 手动测试用例：465 个已定义
- 缺口：纸面交易模块测试用例已补齐（v1.0 89 条，2026-04-19）
