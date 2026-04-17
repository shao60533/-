# 股票辅助决策系统 — 文档中心

> 本目录统一管理所有产品需求、设计方案、测试用例和部署文档。
> 每次功能变更需在对应 `changelog.md` 中留痕。

---

## 目录结构

```
docs/
├── README.md                            # 本文件 — 文档索引
├── prd/                                 # 产品需求文档
│   ├── v2.0-stock-trading-system.md     # PRD V2.0（2026-04-12）
│   └── changelog.md                     # PRD 变更记录
├── design/                              # 设计方案（UI + 架构 + 技术详设）
│   ├── ui-ux-redesign.md                # UI/UX 重设计方案
│   ├── architecture-upgrade.md          # 架构升级方案（Qwen + TV + 异步任务）
│   ├── technical-design.md              # Web 端重构技术方案
│   ├── screener-v2.md                   # 智能选股 V2（8 Agent + 8 Guru）
│   ├── paper-trade.md                   # 纸面交易（AI 效果追踪）
│   └── changelog.md                     # 设计方案变更记录
├── test-cases/                          # 测试用例
│   ├── v2.0-manual-test-cases.md        # V2.0 手动测试（151 例）
│   ├── architecture-upgrade.md          # 架构升级测试（204 例）
│   ├── screener-v2.md                   # 选股 V2 测试（110 例）
│   └── changelog.md                     # 测试用例变更记录
└── deploy/                              # 部署文档
    ├── railway.md                       # Railway PaaS 部署指南
    └── changelog.md                     # 部署文档变更记录
```

---

## 功能演进时间线

| 日期 | 里程碑 | 关键文档 | Commit |
|------|--------|---------|--------|
| 2026-03-xx | 初始系统：CLI + 7 Agent AI 分析 + 三层选股 | — | `0cb4040` |
| 2026-04-xx | Web 仪表盘 + Telegram 机器人 | — | `78980f9` |
| 2026-04-xx | H5 移动端适配 + 设置页 + K 线/基本面/新闻 | — | `3a00968` |
| 2026-04-xx | Qwen (DashScope) 数据源接入 | — | `90afe73` |
| 2026-04-12 | PRD V2.0 + UI/UX 方案 + 技术方案 | [PRD](prd/v2.0-stock-trading-system.md) / [UI](design/ui-ux-redesign.md) / [Tech](design/technical-design.md) | — |
| 2026-04-14 | V2.0 手动测试用例（151 例） | [Test Cases](test-cases/v2.0-manual-test-cases.md) | — |
| 2026-04-15 | 架构升级方案 + 测试用例（204 例） | [Arch](design/architecture-upgrade.md) / [Tests](test-cases/architecture-upgrade.md) | — |
| 2026-04-15 | 选股 V2 方案 + 测试用例（110 例） | [Design](design/screener-v2.md) / [Tests](test-cases/screener-v2.md) | — |
| 2026-04-15 | Phase A-E 架构升级实施完成 | — | `034efe0` |
| 2026-04-15 | Railway 部署指南 | [Deploy](deploy/railway.md) | `fa3c653` |
| 2026-04-16 | 纸面交易方案（v1.0 ~ v1.2） | [Paper Trade](design/paper-trade.md) | — |
| 2026-04-16 | 选股 V2 修订：NL 驱动优先 | [Screener V2 v1.1](design/screener-v2.md) | — |
| 2026-04-18 | 一键持仓分析方案 | [Batch Analyze](design/batch-analyze-holdings.md) | — |

---

## 文档数量统计

| 分类 | 文档数 | 总行数 |
|------|--------|--------|
| PRD | 1 | ~440 |
| 设计方案 | 5 | ~4,880 |
| 测试用例 | 3（465 例） | ~1,090 |
| 部署文档 | 1 | ~224 |
| **合计** | **10** | **~6,634** |

---

## 如何使用

### 新功能开发流程

1. **写 PRD** → 放入 `prd/`，在 `prd/changelog.md` 记录
2. **写设计方案** → 放入 `design/`，在 `design/changelog.md` 记录
3. **写测试用例** → 放入 `test-cases/`，在 `test-cases/changelog.md` 记录
4. **实施完成** → 更新本文件的"功能演进时间线"，关联 commit hash
5. **部署变更** → 更新 `deploy/`，在 `deploy/changelog.md` 记录

### 命名规范

- PRD：`v{版本号}-{功能名}.md`（如 `v2.0-stock-trading-system.md`）
- 设计方案：`{功能名}.md`（如 `screener-v2.md`）
- 测试用例：与设计方案同名或加 `v{版本}` 前缀
- 部署文档：`{平台名}.md`（如 `railway.md`）

### 变更留痕规则

每次修改文档时，必须同步更新对应 `changelog.md`：

```markdown
| 2026-04-18 | [文件名](文件名.md) | v1.1 | 变更说明 | `commit-hash` |
```
