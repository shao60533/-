# 技术方案：移动端信息架构与 UI 实装 v1.3

| 项 | 值 |
|---|---|
| Feature | `mobile-ui-v1.3` |
| 版本 | v1.3 |
| 日期 | 2026-05-09 |
| 关联 PRD | [../prd/mobile-ui-v1.3.md](../prd/mobile-ui-v1.3.md) |
| 关联测试用例 | [../test-cases/mobile-ui-v1.3.md](../test-cases/mobile-ui-v1.3.md) |
| Demo 契约 | [../../demo_mobile_full_v1.html](../../demo_mobile_full_v1.html) |

## 1. 设计原则

本方案只做移动端信息架构和 UI 层重组，不改变产品功能、后端 API、任务系统、数据库、LLM provider、分析/选股/纸面交易业务逻辑。

实装时以 demo 为准，优先级如下：

1. Demo 当前状态优先于早期移动端方案。
2. 已实装功能不得遗漏。
3. Demo 中被删掉的冗余块不得重新加入。
4. Demo 中标注为产品缺口的能力不得伪装为已实装。
5. 生产兼容路由/API 可以保留，但移动端主入口必须按 demo 收口。

## 2. 影响范围

### 2.1 前端文件

| 区域 | 目标文件 | 操作 |
|---|---|---|
| App shell / mobile nav | `stock_trading_system/web/frontend/src/components/shared/AppShell.tsx` | 底部 tab、More 入口、标题/active 状态 |
| 首页 | `stock_trading_system/web/frontend/src/islands/dashboard/DashboardPage.tsx` | 合并持仓明细、5/9 切换、持仓看分析 |
| 分析 | `stock_trading_system/web/frontend/src/islands/analysis/AnalysisPage.tsx` | 详情结构、8 tabs、删除 Quick Info/Inbox 工具 |
| 分析结构化卡 | `stock_trading_system/web/frontend/src/components/analysis/*` | 复用现有 8 Card，不新增第 9 个原文卡 |
| 发现/选股 | `stock_trading_system/web/frontend/src/islands/screener-v3/ScreenerV3Page.tsx` | 删除取消按钮、透明度块；大师详情折叠 |
| 纸面列表 | `stock_trading_system/web/frontend/src/islands/paper-trade-list/PaperTradeListPage.tsx` | 一级 tab 页面，删除返回更多 |
| 纸面详情 | `stock_trading_system/web/frontend/src/islands/paper-trade/PaperTradePage.tsx` | 删除策略/日度 tabs、按钮去重、结构化决策 |
| 样式 | `stock_trading_system/web/frontend/src/styles/index.css` | 必要的移动端布局/折叠/按钮细节 |

### 2.2 不应修改

| 不动 | 原因 |
|---|---|
| Flask route / API endpoint | 本期不改后端 |
| SQLite schema / migrations | 本期无数据模型变更 |
| workers / TaskManager / task_events | 本期不改任务系统 |
| LLM provider / LLMSwitcher 业务逻辑 | 只保持 demo 中两段式展示 |
| Analysis rendering schema | 继续使用 8 Card |
| Screener V3 后端 pipeline | 只改结果展示密度 |
| Paper trade order engine | 只改详情页表达 |

## 3. 共享组件建议

允许新增轻量前端展示组件，但必须保持现有 React island 架构。

| 组件 | 建议位置 | 用途 |
|---|---|---|
| `MobileHoldingCard` | `islands/dashboard/` 或共享局部组件 | 首页持仓卡 |
| `HoldingVisibilityToggle` | `islands/dashboard/` | 显示 5 / 全部 9 |
| `StructuredDecisionPanel` | `components/shared/` 或 `components/analysis/` | 纸面详情复用分析核心风格 |
| `GuruScoreDetails` | `islands/screener-v3/` | 14 大师折叠详情 |
| `MobileMoreGrid` | `components/shared/AppShell.tsx` 内部或拆组件 | More 低频入口 |

不需要为了本期引入新的状态管理库。局部 `useState` 足够。

## 4. 页面施工图

### 4.1 AppShell / Mobile Nav

目标：底部主入口固定为 5 个。

```text
首页 | 分析 | 发现 | 纸面 | 更多
```

实现要点：

- `首页` 指向 Dashboard。
- `发现` 指向 Screener V3。
- `纸面` 指向 PaperTradeList。
- `更多` 打开 More 页面/Sheet。
- 移动端不再出现一级 `持仓` tab。
- More 不再重复展示 `纸面交易`，保留 `交易记录`。
- More 删除：
  - 复盘与运营状态卡。
  - 调度器快捷入口。
  - 系统设置副标题里的“调度器”。

验收：

- 375px 下底部 tab 文案不换行。
- 点击 `纸面` 后进入纸面列表，不显示 `返回更多`。
- 点击 `更多` 后只看到低频入口。

### 4.2 Dashboard 首页

目标：Dashboard 成为移动端“资产 + 持仓”首页。

结构：

```text
账户总览
持仓明细
  搜索 + 买入
  显示 5 / 全部 9 / 交易记录 / 纸面计划
  产品缺口：批量分析持仓
  持仓卡 x 5 默认
  持仓卡 x 4 折叠
净值与仓位
快捷操作
```

持仓卡字段：

| 字段 | 必须展示 |
|---|---|
| ticker | 是 |
| shares / market / 标签 | 是 |
| PnL 百分比 | 是 |
| 成本 | 是 |
| 现价 | 是 |
| 盈亏 | 是 |
| 市值 | 是 |
| 仓位 / 状态 / 风险 / 来源 | 是 |

持仓卡动作：

- `看分析`：跳转到既有 Analysis 入口/详情，不新增 ticker 聚合页。
- `卖出`、`修正成本`、`移除`：复用现有 Portfolio 操作能力。

折叠规则：

- 默认显示：NVDA、TSLA、AAPL、MSFT、AVGO。
- `全部 9` 显示：LLY、META、AMD、TSM。
- `显示 5` 恢复默认。

不展示：

- 跨页面待办聚合。
- 今日决策队列。
- 独立 Portfolio 页面入口。

### 4.3 Analysis

#### 分析首页

保留：

- 发起分析表单。
- 标准 / 深度。
- 分析记录 Inbox。

删除：

- `Inbox 工具` 区块。
- `刷新 / 筛选 / 看任务` 三按钮。

#### 分析详情

结构：

```text
返回分析
结构化分析核心
  8 tabs: 概览/市场/情绪/新闻/基本面/辩论/风险/决策
  score ring + 综合结论 + evidence
  导出/分享/收藏/删除
K 线走势
记录与操作
原始报告 fallback/debug
```

必须删除/避免：

- 结构化 tabs 中的 `原文`。
- Quick Info。
- 顶部重复结论大卡。

兼容：

- 如果 rendering 缺失，原始报告 fallback 仍能展示 markdown/raw 内容。

### 4.4 Screener V3 / 发现

#### 表单

保留：

- 自然语言描述。
- 美股/A股/港股。
- 高级配置 details。
- 14 大师列表。
- 全选/推荐/全不选。
- 经典阈值 / Agent 深度 / 圆桌辩论。
- LLM 调用、时长、成本。
- `开始筛选`。

删除：

- 表单底部 `取消`。

#### 最近选股

保留：

- success-only 历史卡。
- running 行产品缺口提示。

不扩展：

- 不实装 `include_running=true`。

#### 结果页

保留：

- 候选数、平均分、看多、共识率。
- 候选排名。
- 投票条。
- 14 大师评分详情。
- 圆桌辩论摘要。
- 发起分析 / 加入观察。

删除：

- 透明度链路 / 审计信息。
- dynamic_llm / off-theme / cache hit 等审计展示。

14 大师：

- 默认 `<details>` 关闭。
- summary 必须展示：`查看 14 位大师评分（共识 64% / 看多 9 / 看空 2 / 中性 3）`。

### 4.5 Paper Trade

#### PaperTradeList

结构：

```text
纸面交易
  搜索代码 + 刷新
  前向追踪 / 历史回放
  ticker 聚合卡
```

删除：

- `返回更多`。

#### PaperTradeDetail

结构：

```text
返回纸面交易
NVDA 纸面交易 · 详情
当前策略
日度数据
  刷新日度数据
  图表
  AI 决策核心 / 执行记录
    结构化决策卡
    按 Plan / 按 Event
```

删除：

- 顶部 `策略 / 日度数据` 页内 tab。
- 日度数据区重复的 `日度数据` 按钮。
- 英文 raw 决策原文。

保留：

- `刷新日度数据`。
- Plan/Event 双视图。
- 执行记录。

## 5. 样式与移动端规则

### 5.1 触控

- 主按钮和 tab 点击区域 >= 44px。
- chips 可横滑，但不能造成 body 横向滚动。
- 底部 tab 不遮挡页面最后内容。

### 5.2 信息密度

- 卡片内标题用紧凑字号，不使用 hero 级标题。
- 重复说明文案删除。
- 折叠内容必须在 summary 里暴露关键摘要。

### 5.3 颜色

沿用现有暗色终端风格：

- Buy / 盈利：绿色。
- Sell / 亏损：红色。
- Watch / gap：黄色。
- 当前导航 / 主按钮：蓝色。

不新增大面积渐变、装饰背景或营销式 hero。

## 6. 状态与数据

### 6.1 状态来源

所有数据继续来自现有页面/接口：

- Dashboard 数据：现有 dashboard/portfolio API。
- 持仓操作：现有 portfolio buy/sell/cost/remove 能力。
- Analysis 数据：现有 history + tasks + rendering。
- Screener 数据：现有 screen v3 task/results。
- Paper 数据：现有 paper trade list/detail/eod。

### 6.2 新增前端局部状态

| 状态 | 所属页面 | 类型 |
|---|---|---|
| `showAllHoldings` | Dashboard | boolean |
| `guruDetailsOpen` | Screener result | details 原生状态即可 |

不需要服务端持久化。

## 7. 回归策略

### 7.1 自动化

推荐新增 Playwright 用例覆盖：

- mobile nav 5 tab。
- dashboard 持仓 5/9 切换。
- analysis 8 tabs 无原文。
- screener guru details 默认收起。
- paper list 无返回更多。
- paper detail 无策略/日度 tabs。
- 375/390/430/768 无横向溢出。

### 7.2 手工 QA

按 demo 对照 5 个主入口：

1. 首页。
2. 分析。
3. 发现。
4. 纸面。
5. 更多。

逐页确认“删掉的东西没有回来”。

## 8. 实施顺序

1. AppShell nav + More。
2. Dashboard 合并持仓。
3. Analysis 详情收敛。
4. Screener V3 结果减重。
5. Paper list/detail。
6. Coverage/文案同步。
7. Playwright + build。

原因：导航和首页决定一级信息架构；分析/发现/纸面是核心路径；最后做回归，避免页面间入口反复改。

## 9. 执行禁令

- 不创建 `/ticker/<symbol>`。
- 不实装 Reports / Backtest 历史列表。
- 不实装 Settings Diagnostics / Schwab OAuth。
- 不实装 Analysis Inbox scope 三态。
- 不实装 Alerts -> Analysis 反向跳转。
- 不把 batch_analysis 标成已实装入口。
- 不恢复 Quick Info。
- 不恢复选股透明度审计块。
- 不恢复 More 运营状态卡。
- 不恢复纸面详情策略/日度 tabs。

## 10. 版本历史

| 版本 | 日期 | 变更 |
|---|---|---|
| v1.3 | 2026-05-09 | 基于高保真 demo 的移动端 IA/UI 施工图：导航、首页持仓合并、Analysis/Screener/Paper 减噪、More 收口、回归策略 |
