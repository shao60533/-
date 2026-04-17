# 股票辅助决策系统 Web 端重构 — 技术方案设计文档

> **版本**: 1.0  
> **日期**: 2026-04-12  
> **状态**: 草稿  
> **输入**: [PRD V2.0](PRD_STOCK_TRADING_SYSTEM.md) + [UI/UX 重设计方案](UI_UX_REDESIGN_PROPOSAL.md)

---

## 一、概述

### 1.1 项目背景

系统后端已具备完整能力（7 Agent AI 分析、三层选股、持仓管理、预警监控、报告生成、通知推送），但 Web 前端几乎不可用：9 个页面中 8 个为空壳，`app.js` 90% 为占位函数。本技术方案旨在将 PRD 定义的功能需求和 UI/UX 设计方案落地为可执行的工程计划。

### 1.2 目标

| 目标 | 来源 | 技术映射 |
|------|------|----------|
| Web 端功能完整可用 | PRD G1 | 补全 8 个空页面 + 20+ 个 API 端点 |
| 手机端核心操作 ≤ 2 步 | PRD G2 | Mobile-first CSS + 底部 Tab Bar + 快捷入口 |
| 分析结果可追溯 | PRD G3 | `analysis_history` 表 + 历史查询 API |
| 实时感 | PRD G4 | WebSocket 事件推送 + 前端动画 |
| 零运维可部署 | PRD G5 | Railway 兼容（PORT 环境变量、health 端点） |

### 1.3 范围与非目标

**做**：PRD P0 + P1 全部需求，P2 部分需求（骨架屏、PWA）

**不做**：自动化交易、多用户权限、原生 App、实时 K 线（见 PRD NG1~NG5）

---

## 二、现有系统盘点

### 2.1 后端模块清单

| 模块 | 路径 | 核心类/函数 | 状态 |
|------|------|-------------|------|
| AI 分析 | `agents/analyzer.py` | `StockAnalyzer.analyze(ticker, date) → AnalysisResult` | ✅ 可用 |
| 三层选股 | `screener/screener.py` | `StockScreener.screen(market, strategy, criteria)` | ✅ 可用 |
| 持仓管理 | `portfolio/manager.py` | `PortfolioManager.add_position/sell_position/get_holdings/get_pnl/...` | ✅ 可用 |
| 预警监控 | `alerts/monitor.py` | `AlertMonitor` | ✅ 可用 |
| 报告生成 | `reports/report_generator.py` | `ReportGenerator` | ✅ 可用 |
| 策略引擎 | `strategy/strategy_engine.py` | `StrategyEngine.generate_advice()` | ✅ 可用 |
| 定时任务 | `scheduler/task_scheduler.py` | `TaskScheduler` | ✅ 可用 |
| 数据获取 | `data/data_manager.py` | `DataManager`（yfinance/Polygon/AkShare/IB） | ✅ 可用 |
| 配置管理 | `config/settings.py` | `load_config/get_config` | ✅ 可用 |
| 通知推送 | `alerts/telegram_bot.py`, `email_notifier.py` | Telegram/Email 通知 | ✅ 已修复 |

### 2.2 已有 Web 层

| 文件 | 行数 | 状态 |
|------|------|------|
| `web/app.py` | 610 行 | ✅ 已有大部分 API，部分需补全 |
| `web/templates/index.html` | 634 行 | ⚠️ 仅 Dashboard 有实际内容，其余页面为空壳 |
| `web/static/js/app.js` | 1091 行 | ⚠️ 已有框架代码，但部分功能为占位 |
| `web/static/css/style.css` | 614 行 | ✅ 暗色主题基础完整，需增量扩展 |

### 2.3 已有 API 端点（app.py 已实现）

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/dashboard` | GET | 仪表盘汇总数据 |
| `/api/portfolio/holdings` | GET | 持仓列表 |
| `/api/portfolio/add` | POST | 买入 |
| `/api/portfolio/sell` | POST | 卖出 |
| `/api/portfolio/transactions` | GET | 交易记录 |
| `/api/portfolio/pnl` | GET | 盈亏汇总 |
| `/api/portfolio/allocation` | GET | 仓位分布 |
| `/api/portfolio/history` | GET | 历史快照 |
| `/api/portfolio/update_cost` | POST | 修改成本 |
| `/api/portfolio/snapshot` | POST | 记录快照 |
| `/api/analyze` | POST | 触发 AI 分析（已有 WebSocket 推送） |
| `/api/screen` | POST | 触发选股 |
| `/api/alerts` | GET | 预警列表 |
| `/api/alerts/add` | POST | 添加预警 |
| `/api/alerts/remove` | POST | 删除预警 |
| `/api/alerts/check` | POST | 手动检查预警 |
| `/api/history` | GET | 分析历史列表 |
| `/api/history/<id>` | GET | 分析详情 |
| `/api/report` | POST | 生成报告 |
| `/api/price/<ticker>` | GET | 实时价格 |
| `/api/quote/<ticker>` | GET | 详细行情 |
| `/api/chart/<ticker>` | GET | K 线数据 |
| `/api/fundamentals/<ticker>` | GET | 基本面数据 |
| `/api/news/<ticker>` | GET | 新闻 |
| `/api/scheduler/status` | GET | 定时任务状态 |
| `/api/scheduler/start` | POST | 启动定时任务 |
| `/api/scheduler/stop` | POST | 停止定时任务 |
| `/api/settings` | GET | 获取设置（脱敏） |
| `/api/seed` | POST | 填充演示数据 |
| `/api/health` | GET | 健康检查 |

### 2.4 待补全 API 端点

| 端点 | 方法 | PRD 需求 | 说明 |
|------|------|----------|------|
| `/api/settings` | PUT | R-1.5 | 更新设置（白名单 key） |
| `/api/alerts/history` | GET | US-6.5 | 预警触发历史 |
| `/api/search` | GET | US-10.1 | 全局搜索（跨持仓/分析/预警） |
| `/api/backtest/strategies` | GET | US-8.1 | 可用回测策略列表 |
| `/api/backtest/run` | POST | US-8.1 | 执行回测 |
| `/api/screener/strategies` | GET | US-4.1 | 可用选股策略列表 |
| `/api/report/send` | POST | US-7.3 | 发送报告到 Telegram |

### 2.5 待新建后端模块

| 模块 | 说明 | PRD 需求 |
|------|------|----------|
| 回测引擎 `strategy/backtester.py` | 策略回测（SMA 交叉/RSI 均值回归/买入持有） | R-1.3, US-8.1~8.4 |

> **注意**: 回测功能在 PRD 中为 P1 优先级，但后端尚无 `Backtester` 类。需新建。

---

## 三、技术架构

### 3.1 整体架构（不变）

```
┌─────────────────────────────────────────────────────────┐
│                    浏览器（手机/桌面）                      │
│  index.html (SPA) + app.js + style.css + ECharts        │
├──────────────────────┬──────────────────────────────────┤
│     HTTP REST API    │      WebSocket (Socket.IO)       │
├──────────────────────┴──────────────────────────────────┤
│                  Flask + Flask-SocketIO                  │
│                      web/app.py                         │
├─────────────────────────────────────────────────────────┤
│  agents/   │ screener/ │ portfolio/ │ alerts/ │ reports/ │
│  analyzer  │ screener  │ manager    │ monitor │ report   │
│            │           │ database   │ telegram│ generator│
├─────────────────────────────────────────────────────────┤
│  data/ (yfinance, Polygon, AkShare, IB TWS)             │
├─────────────────────────────────────────────────────────┤
│  SQLite (portfolio.db) + YAML (config.yaml)             │
└─────────────────────────────────────────────────────────┘
```

### 3.2 前端技术栈（保持不变，不引入新框架）

| 依赖 | 版本 | 用途 | 引入方式 |
|------|------|------|----------|
| Bootstrap 5.3 | CDN | 网格 + 基础组件 | 已有 |
| Font Awesome 6.5 | CDN | 图标系统 | 已有 |
| ECharts 5.x | CDN | 数据可视化 | 已有 |
| Socket.IO 4.7 | CDN Client | WebSocket 通信 | 已有 |
| **marked.js** | CDN | Markdown → HTML 渲染 | **新增** |

**不引入 React/Vue/Svelte** — 单页应用但页面间交互简单，原生 JS + DOM 操作足够。引入框架会增加构建步骤和部署复杂度，违反"零运维"原则。

### 3.3 后端技术栈（保持不变）

| 依赖 | 用途 |
|------|------|
| Flask 3.x | HTTP 路由 |
| Flask-SocketIO | WebSocket |
| SQLite | 持仓/分析历史持久化 |
| YAML | 配置文件 |

---

## 四、前端改造方案

### 4.1 文件改动范围

| 文件 | 改动性质 | 预估行数 |
|------|----------|----------|
| `templates/index.html` | **重写** — 补全 8 个空页面的完整 HTML 结构 | ~1500 行（现 634 行） |
| `static/js/app.js` | **重写** — 占位函数替换为真实 API 调用 + ECharts 渲染 + WebSocket 事件处理 | ~2000 行（现 1091 行） |
| `static/css/style.css` | **增量** — 新增组件样式（保留现有暗色主题基础） | +800 行（现 614 行） |

### 4.2 页面结构设计

所有页面为 SPA 内的 `<div id="page-xxx" class="page-content">` 容器，通过 `data-page` 属性切换显示。

#### 4.2.1 仪表盘（Dashboard）— 补全图表和数据

**来源**: PRD R-0.1, UI 设计 3.1

**HTML 结构**:
```
page-dashboard
├── 四大统计卡（总市值/总盈亏/收益率/活跃预警） ← 已有，需接API
├── 图表行
│   ├── 净值曲线（ECharts 折线图 + 7D/1M/3M/1Y 切换）
│   └── 仓位分布（ECharts 环形图 + 中心总市值）
├── 持仓表格（桌面）/ 持仓卡片列表（移动端）
└── 今日预警摘要 + 快捷操作入口（分析/选股/报告）
```

**数据流**: `GET /api/dashboard` → 统计卡 + 持仓; `GET /api/portfolio/history?days=N` → 净值曲线; `GET /api/portfolio/allocation` → 饼图

#### 4.2.2 AI 分析（Analysis）— 全新

**来源**: PRD R-0.2, US-2.1~2.6, UI 设计 3.2

**HTML 结构**:
```
page-analysis
├── 输入区（ticker + 日期 + 开始分析按钮）
├── 管线进度条（7 步节点：技术/基本面/情绪/新闻/辩论/风险/决策）
│   ├── 桌面：水平管线
│   └── 移动端：垂直时间线
├── 结论三卡片（信号 BUY/SELL/HOLD + 置信度 + 建议操作）
├── 详情 Tab（技术面/基本面/情绪/新闻）
│   └── 每个 Tab 内 Markdown 渲染（marked.js）
│   └── 移动端：手风琴折叠替代 Tab
└── 多空辩论区（双栏对比）
```

**数据流**:
1. `POST /api/analyze {ticker, date}` → 返回 `{task_id}`
2. WebSocket `analysis_step` 事件 → 逐步更新进度节点
3. WebSocket `analysis_complete` 事件 → 渲染结论 + 详情
4. 自动存入历史（后端完成）

**关键实现**:
- 进度条状态机：`pending → running → done`，每个节点独立状态
- Markdown 渲染：使用 `marked.parse()` 将 AI 报告转为 HTML
- 信号卡样式：BUY 绿色 / SELL 红色 / HOLD 黄色，大字 32px

#### 4.2.3 分析记录（History）— 全新

**来源**: PRD R-0.3, US-3.1~3.3, UI 设计 3.3

**HTML 结构**:
```
page-history
├── 搜索/筛选栏（ticker 搜索 + 信号筛选）
├── 桌面：左右 master-detail 布局
│   ├── 左栏：分析记录列表（按时间倒序）
│   └── 右栏：选中记录的完整详情
└── 移动端：列表页 → 点击进入详情全屏
```

**数据流**: `GET /api/history?ticker=&page=&limit=` → 列表; `GET /api/history/<id>` → 详情

#### 4.2.4 智能选股（Screener）— 全新

**来源**: PRD R-1.2, US-4.1~4.3, UI 设计 3.4

**HTML 结构**:
```
page-screener
├── 参数区（市场下拉 + 策略下拉 + 开始筛选按钮）
├── 漏斗进度可视化（三层：IB Scanner → finviz → AI 精选）
└── 结果表格（Rank/Ticker/名称/价格/信号/AI摘要）
    └── Ticker 可点击 → 跳转 AI 分析页
```

**数据流**:
1. `POST /api/screen {market, strategy}` → 返回 `{task_id}`
2. WebSocket `screener_progress` → 更新每层漏斗
3. WebSocket `screener_complete` → 渲染结果列表

#### 4.2.5 持仓管理（Portfolio）— 补全交互

**来源**: PRD R-0.4, US-5.1~5.5, UI 设计 3.5

**HTML 结构**:
```
page-portfolio
├── 操作按钮组（买入/卖出/快照）
├── 内容区
│   ├── 持仓表格/卡片
│   │   └── 每行有 [分析] [卖出] 快捷按钮
│   └── 盈亏概览 + 仓位分布饼图
├── 交易记录表格（支持按 ticker 筛选）
└── 买入/卖出模态框（桌面）/ 全屏抽屉（移动端）
```

**数据流**: `GET /api/portfolio/holdings` + `GET /api/portfolio/pnl` + `GET /api/portfolio/allocation`; `POST /api/portfolio/add` / `sell`

#### 4.2.6 预警中心（Alerts）— 全新

**来源**: PRD R-0.5, US-6.1~6.5, UI 设计 3.6

**HTML 结构**:
```
page-alerts
├── 操作栏（新建规则 + 启动/停止监控）
├── 桌面：左右分栏
│   ├── 左栏：活跃规则列表（状态标识：监控中🟢/已触发🔴）
│   └── 右栏：规则编辑器（ticker/条件类型/阈值 + 实时价格预览）
├── 移动端：列表 → 点击进编辑全屏
├── 预设模板（止损/止盈/突破/涨跌幅/放量）
└── 预警触发历史
```

**数据流**: `GET /api/alerts` → 列表; `POST /api/alerts/add` → 创建; `POST /api/alerts/remove` → 删除; WebSocket `alert_triggered` → Toast

#### 4.2.7 报告中心（Reports）— 全新

**来源**: PRD R-1.4, US-7.1~7.3, UI 设计 3.7

**HTML 结构**:
```
page-reports
├── 参数区（报告类型下拉 + ticker输入 + 生成按钮）
├── 报告渲染区（marked.js Markdown → HTML）
└── 操作栏（复制 + 发送 Telegram）
```

**数据流**: `POST /api/report {type, ticker?}` → 返回 Markdown; 前端 `marked.parse()` 渲染

#### 4.2.8 策略回测（Backtest）— 全新

**来源**: PRD R-1.3, US-8.1~8.4, UI 设计 3.8

**HTML 结构**:
```
page-backtest
├── 参数区（ticker/策略/日期范围/初始资金 + 开始回测）
├── 结果区
│   ├── 指标卡组（总收益/最大回撤/胜率/交易次数/年化收益）
│   ├── 净值曲线（ECharts 双线：策略 vs 基准）
│   └── 交易记录明细表
└── 移动端：参数面板默认收起
```

**数据流**: `POST /api/backtest/run {ticker, strategy_id, initial_capital, period, params}` → 返回 `{metrics, equity_curve, trades}`

#### 4.2.9 设置（Settings）— 补全写入

**来源**: PRD R-1.5, US-9.1~9.4, UI 设计 3.9

**HTML 结构**:
```
page-settings
├── API Keys 区（脱敏展示 + 修改按钮）
├── 通知渠道区（Telegram/Email 配置）
├── 定时任务区（启停开关 + 下次执行时间）
└── 系统信息区（数据目录/日志级别）
```

**数据流**: `GET /api/settings` → 脱敏展示; `PUT /api/settings {path: value}` → 更新; `GET /api/scheduler/status` + `POST /api/scheduler/start|stop`

### 4.3 状态管理

所有 9 个页面统一实现 4 种状态（PRD 8.2）:

```javascript
// app.js 中的通用状态管理
function setPageState(pageId, state, data = null) {
    // state: 'loading' | 'data' | 'empty' | 'error'
    const page = document.getElementById(`page-${pageId}`);
    page.querySelectorAll('.state-loading, .state-data, .state-empty, .state-error')
        .forEach(el => el.classList.add('d-none'));
    page.querySelector(`.state-${state}`).classList.remove('d-none');
    if (state === 'data' && data) renderPageData(pageId, data);
    if (state === 'error' && data) page.querySelector('.error-message').textContent = data;
}
```

| 状态 | UI 表现 |
|------|---------|
| loading | Spinner + "加载中…" 提示（P0）；后续升级骨架屏（P2） |
| data | 正常展示内容 |
| empty | 大图标（64px, opacity:0.2）+ 文字提示 + 引导操作按钮 |
| error | 红色警告图标 + 错误消息 + [重试] 按钮 |

### 4.4 WebSocket 事件处理

```javascript
// app.js WebSocket 事件注册
const socket = io();

// AI 分析进度
socket.on('analysis_step', (data) => {
    // data: {task_id, step, status, data?}
    updatePipelineNode(data.step, data.status);
});

socket.on('analysis_complete', (data) => {
    // data: {task_id, result}
    renderAnalysisResult(data.result);
    showToast('success', '分析完成', `${data.result.ticker} 分析结果已保存`);
});

// 选股进度
socket.on('screener_progress', (data) => {
    updateFunnelLayer(data.layer, data.count, data.status);
});

socket.on('screener_complete', (data) => {
    renderScreenerResults(data.results);
});

// 预警触发
socket.on('alert_triggered', (data) => {
    showToast('alert', '预警触发', `${data.ticker} ${data.condition} ${data.threshold}`);
    updateAlertBadge();
});

// 价格更新
socket.on('price_update', (data) => {
    updatePriceCell(data.ticker, data.price, data.change);
});
```

### 4.5 数据可视化

#### 4.5.1 图表技术选型

系统涉及两类图表场景，采用不同方案：

| 场景 | 方案 | 理由 |
|------|------|------|
| 通用图表（净值曲线/饼图/回测权益） | **ECharts 5.x**（已引入） | 通用性强，已有依赖 |
| K 线图（分析页价格走势） | **ECharts candlestick**（已实现），增强 dataZoom + 均线 | 避免引入新依赖 |

**K 线图组件评估**:

| 组件 | 体积 | 移动端 | 技术指标 | 结论 |
|------|------|--------|----------|------|
| ECharts candlestick（当前） | 0（已引入） | 一般 | 需手动计算叠加 | **当前采用** — 不额外增加依赖 |
| Lightweight Charts（TradingView 开源） | ~40KB | 优秀 | 需手动叠加 | **未来升级首选** — 体积小、专业、移动端触摸体验好 |
| KLineChart（国产开源） | ~150KB | 优秀 | 内置 30+ 指标 | 备选 — 开箱即用但社区较小 |
| Highcharts Stock | ~300KB | 优秀 | 丰富 | 排除 — 商业授权 |

**决策**: PRD 明确"不做实时 K 线图/盘中 tick 级行情"（NG4），K 线仅作为分析辅助展示。当前 ECharts candlestick 已满足需求（[app.js:340-387](stock-trading-system/stock_trading_system/web/static/js/app.js#L340-L387)），在此基础上增强即可。如未来需要更专业的移动端金融图表体验，可单独替换为 Lightweight Charts（Apache 2.0 开源，CDN: `https://unpkg.com/lightweight-charts/dist/lightweight-charts.standalone.production.js`）。

**现有 K 线图增强点**（Phase 2）:

1. **dataZoom 缩放拖拽** — 添加底部滑动条 + 触摸捏合缩放
2. **MA 均线叠加** — 在 K 线图上叠加 MA5/MA20/MA60 线
3. **移动端优化** — tooltip 改为点击触发（`trigger: 'click'`），避免手指遮挡

```javascript
// K 线增强配置（增加 dataZoom + MA 均线）
{
    dataZoom: [
        { type: 'inside', xAxisIndex: [0, 1], start: 60, end: 100 },  // 触摸缩放
        { type: 'slider', xAxisIndex: [0, 1], start: 60, end: 100,    // 底部滑块
          height: 20, bottom: 5,
          borderColor: '#30363d', fillerColor: 'rgba(88,166,255,0.15)',
          handleStyle: { color: '#58a6ff' } }
    ],
    series: [
        { name: 'K线', type: 'candlestick', data: kdata, ... },
        { name: 'MA5', type: 'line', data: calcMA(5, closes), smooth: true,
          lineStyle: { width: 1 }, symbol: 'none' },
        { name: 'MA20', type: 'line', data: calcMA(20, closes), smooth: true,
          lineStyle: { width: 1 }, symbol: 'none' },
        { name: '成交量', type: 'bar', xAxisIndex: 1, yAxisIndex: 1, data: volumes }
    ]
}
```

#### 4.5.2 图表清单

| 图表 | 页面 | ECharts 类型 | 数据源 |
|------|------|-------------|--------|
| 净值曲线 | 仪表盘 | line + areaStyle | `/api/portfolio/history?days=N` |
| 仓位饼图 | 仪表盘/持仓 | pie (ring) | `/api/portfolio/allocation` |
| K 线 + 成交量 + 均线 | 分析 | candlestick + bar + line | `/api/chart/<ticker>` |
| 回测权益曲线 | 回测 | line (双线) | `/api/backtest/run` 返回的 equity_curve |
| 选股漏斗 | 选股 | CSS 实现（非 ECharts） | WebSocket 推送 |

#### 4.5.3 ECharts 暗色主题注册

```javascript
echarts.registerTheme('dark-trading', {
    backgroundColor: 'transparent',
    textStyle: { color: '#8b949e' },
    categoryAxis: {
        axisLine: { lineStyle: { color: '#30363d' } },
        splitLine: { lineStyle: { color: 'rgba(48,54,61,0.5)', type: 'dashed' } }
    },
    color: ['#58a6ff', '#3fb950', '#f85149', '#d29922', '#bc8cff', '#f0883e'],
    tooltip: {
        backgroundColor: '#1c2128',
        borderColor: '#30363d',
        textStyle: { color: '#e6edf3' }
    }
});
```

### 4.6 移动端适配策略

**来源**: UI 设计第六节

#### 断点

| 断点 | 范围 | 布局 |
|------|------|------|
| sm | < 768px | 单列，底部 Tab Bar |
| md | 768px ~ 1199px | 双列混合 |
| lg | ≥ 1200px | 侧边栏 + 多列 |

#### 关键适配

| 组件 | 桌面 | 移动端 |
|------|------|--------|
| 导航 | 侧边栏（已有） | 底部 Tab Bar（已有） |
| 数据表格 | `<table>` | 堆叠卡片列表（`d-none d-md-block` / `d-md-none`）|
| 统计卡 | 4 列 | 2×2 网格 |
| 模态框 | 居中弹窗 | 底部全屏抽屉（`100dvh`） |
| 图表 | 280px 高 | 200px 高，tooltip 点击触发 |
| 管线进度 | 水平 | 垂直时间线 |
| Tab 详情 | Tab 切换 | 手风琴折叠 |
| master-detail | 左右分栏 | 列表 → 全屏详情 |

#### 触摸规范

- 最小触摸目标 44px × 44px
- 输入框字号 ≥ 16px（阻止 iOS 自动缩放）
- 按钮间距 ≥ 8px

---

## 五、后端改造方案

### 5.1 已有 API 调整

现有 `app.py` 已实现大部分 PRD 要求的 API 端点。以下为需要调整的部分：

| API | 调整内容 |
|-----|----------|
| `POST /api/analyze` | 确认 WebSocket 事件名与前端一致（`analysis_step` / `analysis_complete`） |
| `GET /api/settings` | 已有脱敏逻辑，需确认覆盖所有 key |
| `POST /api/screen` | 确认 WebSocket 推送漏斗进度 |

### 5.2 待补全 API 端点

#### 5.2.1 `PUT /api/settings` — 更新设置

```python
@app.route("/api/settings", methods=["PUT"])
def api_settings_update():
    """更新设置项（白名单控制）"""
    WRITABLE_KEYS = [
        "api.gemini_key", "api.polygon_key", "api.qwen_key",
        "notifications.telegram.bot_token", "notifications.telegram.chat_id",
        "notifications.email.smtp_server", "notifications.email.username",
        "notifications.email.password",
    ]
    data = request.json  # {path: value}
    for path, value in data.items():
        if path not in WRITABLE_KEYS:
            return jsonify({"error": f"Key '{path}' is not writable"}), 403
    # 写入 config.yaml
    ...
    return jsonify({"updated": list(data.keys())})
```

#### 5.2.2 `GET /api/alerts/history` — 预警触发历史

```python
@app.route("/api/alerts/history")
def api_alert_history():
    """返回预警触发历史记录"""
    monitor = _get_alert_monitor()
    history = monitor.get_trigger_history()  # 需确认 AlertMonitor 是否有此方法
    return jsonify(history)
```

#### 5.2.3 `GET /api/search` — 全局搜索

```python
@app.route("/api/search")
def api_search():
    """跨持仓/分析/预警搜索"""
    q = request.args.get("q", "").upper()
    results = {
        "holdings": [h for h in _get_portfolio_mgr().get_holdings() if q in h.get("ticker", "")],
        "analyses": [...],  # 查询 analysis_history 表
        "alerts": [a for a in _get_alert_monitor().get_alerts() if q in a.get("ticker", "")]
    }
    return jsonify(results)
```

#### 5.2.4 `GET /api/screener/strategies` — 选股策略列表

```python
@app.route("/api/screener/strategies")
def api_screener_strategies():
    return jsonify([
        {"id": "growth", "label": "成长型", "description": "高收入增长 + 高利润率"},
        {"id": "value", "label": "价值型", "description": "低 PE/PB + 高股息"},
        {"id": "momentum", "label": "动量型", "description": "强劲价格趋势 + 放量"},
        {"id": "low_vol", "label": "低波动", "description": "低 beta + 稳定收益"}
    ])
```

#### 5.2.5 `POST /api/report/send` — 发送报告

```python
@app.route("/api/report/send", methods=["POST"])
def api_report_send():
    """发送报告到 Telegram"""
    data = request.json  # {content, channel: "telegram"|"email"}
    if data["channel"] == "telegram":
        from stock_trading_system.alerts.telegram_notifier import TelegramNotifier
        notifier = TelegramNotifier(get_config())
        notifier.send(data["content"])
    return jsonify({"sent": True})
```

### 5.3 回测引擎（新建）

**文件**: `strategy/backtester.py`

```python
@dataclass
class BacktestResult:
    ticker: str
    strategy: str
    period: str
    initial_capital: float
    final_value: float
    total_return: float          # 百分比
    annualized_return: float     # 百分比
    max_drawdown: float          # 百分比
    win_rate: float              # 百分比
    total_trades: int
    equity_curve: list[dict]     # [{date, value, benchmark}]
    trades: list[dict]           # [{date, action, price, shares, pnl, holding_days}]

class Backtester:
    STRATEGIES = {
        "sma_crossover": {"label": "SMA 交叉", "params": {"short_period": 20, "long_period": 50}},
        "rsi_mean_reversion": {"label": "RSI 均值回归", "params": {"period": 14, "oversold": 30, "overbought": 70}},
        "buy_and_hold": {"label": "买入持有", "params": {}}
    }

    def __init__(self, config: dict):
        self.config = config

    def run(self, ticker, strategy_id, initial_capital=100000, period="1y", params=None) -> BacktestResult:
        """执行回测"""
        # 1. 获取历史数据（yfinance）
        # 2. 按策略生成买卖信号
        # 3. 模拟交易计算权益曲线
        # 4. 计算绩效指标
        ...

    def get_strategies(self) -> list[dict]:
        return [{"id": k, **v} for k, v in self.STRATEGIES.items()]
```

**对应 API 端点**:

```python
@app.route("/api/backtest/strategies")
def api_backtest_strategies():
    return jsonify(_get_backtester().get_strategies())

@app.route("/api/backtest/run", methods=["POST"])
def api_backtest_run():
    data = request.json
    result = _get_backtester().run(
        ticker=data["ticker"],
        strategy_id=data["strategy_id"],
        initial_capital=data.get("initial_capital", 100000),
        period=data.get("period", "1y"),
        params=data.get("params")
    )
    return jsonify(asdict(result))
```

### 5.4 数据库 Schema 确认

需确认 `analysis_history` 表是否支持存储 7 个 Agent 的完整报告：

```sql
-- 预期 schema（需核实 portfolio/database.py）
CREATE TABLE IF NOT EXISTS analysis_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    date TEXT NOT NULL,
    signal TEXT,           -- BUY/SELL/HOLD
    confidence REAL,       -- 0~100
    summary TEXT,          -- 简要结论
    full_result TEXT,      -- JSON：包含各 Agent 报告、多空辩论、建议
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

如果 `full_result` 字段不存在或 schema 不完整，需要在 Phase 1 中扩展。

---

## 六、CSS 新增组件样式

### 6.1 新增样式清单

基于 UI 设计第八节"组件设计规范"，需在 `style.css` 中新增：

| 组件 | 预估行数 | 设计来源 |
|------|----------|----------|
| 管线进度条（`.pipeline-*`） | ~60 行 | 设计 8.11 |
| 信号徽章（`.badge-signal-*`） | ~40 行 | 设计 8.5 |
| 状态点（`.status-dot-*`） | ~30 行 | 设计 8.5 |
| 数据表格增强（`.data-table`） | ~50 行 | 设计 8.2 |
| 价格闪烁动画（`.cell-up/down`） | ~20 行 | 设计 8.2 |
| Toast 通知（`.toast-*`） | ~50 行 | 设计 8.9 |
| 空状态（`.empty-state`） | ~20 行 | 设计 8.8 |
| 骨架屏（`.skeleton`） | ~30 行 | 设计 8.8 |
| 移动端卡片（`.mobile-card`） | ~60 行 | 设计 6.3 |
| 移动端全屏抽屉（`.drawer-*`） | ~40 行 | 设计 6.3 |
| 多空辩论双栏（`.debate-*`） | ~30 行 | 设计 3.2 |
| 漏斗可视化（`.funnel-*`） | ~40 行 | 设计 3.4 |
| 手风琴折叠（`.accordion-*`） | ~30 行 | 设计 6.6 |
| 间距/圆角 CSS 变量 | ~30 行 | 设计 8.13 |
| 阴影/发光效果 | ~20 行 | 设计 8.14 |
| **合计** | **~550 行** | |

### 6.2 配色变量扩展

在现有 CSS 变量基础上新增：

```css
:root {
    /* 新增 */
    --gradient-profit: linear-gradient(135deg, #3fb950, #2ea043);
    --gradient-loss: linear-gradient(135deg, #f85149, #da3633);
    --bg-input: #161b22;

    /* 间距系统 */
    --space-xs: 4px;
    --space-sm: 8px;
    --space-md: 16px;
    --space-lg: 24px;
    --space-xl: 32px;

    /* 圆角系统 */
    --radius-sm: 4px;
    --radius-md: 6px;
    --radius-lg: 8px;
    --radius-xl: 12px;
    --radius-full: 9999px;
}
```

---

## 七、实施分阶段计划

### Phase 1 — 基础可用（对应 PRD P0）

**目标**: Web 端可替代 CLI 完成核心操作

| 步骤 | 内容 | 涉及文件 | 依赖 | PRD 需求 |
|------|------|----------|------|----------|
| 1.1 | 确认 app.py 所有 API 正常工作，补全 `PUT /api/settings` | `web/app.py` | 无 | R-0.7 |
| 1.2 | 重写 `index.html` — 补全 8 个页面完整 HTML | `templates/index.html` | 无 | R-0.6 |
| 1.3 | 重写 `app.js` — 接入所有 API + 基础页面逻辑 | `static/js/app.js` | 1.1 + 1.2 | R-0.1~R-0.5 |
| 1.4 | `style.css` 增量 — 新组件样式 + 4 种状态 | `static/css/style.css` | 1.2 | R-0.6, R-0.8 |
| 1.5 | 移动端适配（卡片列表/全屏抽屉/触摸规范） | `style.css` + `index.html` | 1.2~1.4 | R-0.8 |

**验收标准**:
- 9 个页面全部可交互
- 可通过 Web 完成：分析/买入/卖出/创建预警/查看历史
- 手机浏览器可正常使用

### Phase 2 — 体验提升（对应 PRD P1）

| 步骤 | 内容 | 涉及文件 | PRD 需求 |
|------|------|----------|----------|
| 2.1 | ECharts 图表渲染（净值曲线/仓位饼图） | `app.js` | R-1.1 |
| 2.2 | 分析管线实时进度（WebSocket + 动画） | `app.js` + `style.css` | R-1.6 |
| 2.3 | 预警实时 Toast + 铃铛角标 | `app.js` + `style.css` | R-1.7 |
| 2.4 | 引入 marked.js，渲染报告 Markdown | `index.html` + `app.js` | R-1.4 |
| 2.5 | 选股漏斗可视化 + WebSocket 进度 | `app.js` + `style.css` | R-1.2 |
| 2.6 | 新建回测引擎 + API + 前端 | `backtester.py` + `app.py` + `app.js` | R-1.3 |
| 2.7 | 设置页完整交互（写入设置 + 任务启停） | `app.js` + `app.py` | R-1.5 |

### Phase 3 — 打磨（对应 PRD P2）

| 步骤 | 内容 | PRD 需求 |
|------|------|----------|
| 3.1 | 骨架屏加载态替代 spinner | R-2.3 |
| 3.2 | 全局搜索面板 + 键盘导航 | R-2.2 |
| 3.3 | PWA 支持（manifest + Service Worker） | R-2.4 |
| 3.4 | 信号时间线 + 双条对比 | R-2.1 |
| 3.5 | 预警预设模板 | R-2.5 |
| 3.6 | 手势交互（左滑/下拉刷新） | R-2.6 |

---

## 八、关键技术决策

### 8.1 SPA 路由方案

**决策**: 保持现有 `data-page` 属性切换 `display:none/block` 的方式，不引入 hash router。

**理由**:
- 页面数固定（9 个），不需要动态路由
- 无 SEO 需求（单人工具）
- 简单直接，无额外依赖

### 8.2 Markdown 渲染

**决策**: 引入 `marked.js`（CDN）

**理由**:
- AI 分析报告和报告中心需要 Markdown → HTML 渲染
- marked.js 是最轻量的 Markdown 库（~30KB），CDN 引入零构建成本
- 替代方案 showdown.js 更大且更新不活跃

### 8.3 回测引擎位置

**决策**: 放在 `strategy/backtester.py`，与现有 `strategy_engine.py` 平级

**理由**:
- 回测与策略强相关，共享策略定义
- 可复用 `data_manager` 获取历史数据
- 不引入新的 package 目录

### 8.4 状态持久化

**决策**: 分析历史存 SQLite（`analysis_history` 表），预警配置存 SQLite（`alerts` 表），其余配置存 YAML

**理由**: 与现有架构一致，不引入新存储组件

### 8.5 移动端表格替代

**决策**: 桌面表格 + 移动端卡片列表并存于 HTML，通过 Bootstrap 响应式 class 切换

```html
<!-- 桌面表格 -->
<div class="d-none d-md-block">
    <table class="data-table">...</table>
</div>
<!-- 移动端卡片 -->
<div class="d-md-none">
    <div class="mobile-card">...</div>
</div>
```

**理由**: 纯 CSS 控制，无 JS 开销；两种视图共享同一数据源

### 8.6 K 线图组件选型

**决策**: 继续使用 ECharts candlestick（已实现），在 Phase 2 增强 dataZoom 缩放 + MA 均线叠加。不引入新的图表库。

**理由**:
- ECharts 已是项目依赖（净值曲线、饼图、回测曲线都用它），K 线只是多一个 series type
- PRD NG4 明确"不做实时 K 线图/盘中 tick 级行情"，K 线仅作分析辅助展示，ECharts 已满足
- 引入 Lightweight Charts 或 KLineChart 会增加一个 CDN 依赖，收益不大
- 如未来需升级移动端金融图表体验，Lightweight Charts（TradingView 开源，40KB）是最佳替换方案

---

## 九、风险与缓解

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|----------|
| AI 分析耗时 2~5 分钟，用户等待体验差 | 高 | 中 | WebSocket 实时进度 + 每步完成即展示部分结果 |
| ECharts CDN 在国内/海外访问不稳定 | 低 | 中 | 使用 jsdelivr CDN（全球 CDN）；备选本地打包 |
| `app.js` 2000+ 行在单文件中维护困难 | 中 | 低 | 按功能模块注释分块；不值得引入模块打包 |
| AkShare 在 Railway 海外节点不可用 | 中 | 高 | A 股功能降级提示，UI 标注"A 股数据暂不可用" |
| 回测引擎历史数据量大导致接口慢 | 低 | 低 | 限制回测最长时间范围（如 5 年） |
| 移动端 Safari WebSocket 断连 | 中 | 中 | 心跳机制 + 自动重连逻辑 |

---

## 十、开放问题

| # | 问题 | 当前假设 | 需确认 |
|---|------|----------|--------|
| Q1 | `analysis_history` 表 schema 是否支持存储完整 7 Agent 报告？ | 假设有 `full_result TEXT` 字段存 JSON | 查看 `portfolio/database.py` |
| Q2 | `AlertMonitor` 是否有 `get_trigger_history()` 方法？ | 假设没有，需新增 | 查看 `alerts/monitor.py` |
| Q3 | `ReportGenerator` 的 `generate()` 方法返回格式？ | 假设返回 Markdown 字符串 | 查看 `reports/report_generator.py` |
| Q4 | 选股 `StockScreener.screen()` 是否已支持 WebSocket 进度推送？ | 从 `app.py` 看已有基础实现 | 确认事件名和数据格式 |
| Q5 | Railway WebSocket 长连接是否有超时限制？ | 假设无，但需心跳机制兜底 | 部署后实测 |

---

## 十一、PRD 到技术方案的需求追踪矩阵

### P0 需求

| PRD ID | 需求 | 技术方案对应 |
|--------|------|-------------|
| R-0.1 | 仪表盘数据展示 | Phase 1.2~1.3: Dashboard HTML + API 调用 |
| R-0.2 | AI 分析触发与结果展示 | Phase 1.3: Analysis 页 + `POST /api/analyze` |
| R-0.3 | 分析结果持久化与历史查看 | Phase 1.3: History 页 + `GET /api/history` |
| R-0.4 | 持仓买入/卖出 | Phase 1.3: Portfolio 页 + `POST /api/portfolio/add|sell` |
| R-0.5 | 预警 CRUD | Phase 1.3: Alerts 页 + `GET|POST /api/alerts` |
| R-0.6 | 8 个空页面全部可交互 | Phase 1.2: 重写 index.html |
| R-0.7 | 后端 API 补全 | Phase 1.1: 确认已有 API + 补全缺失 |
| R-0.8 | 移动端基础可用 | Phase 1.5: 响应式适配 |

### P1 需求

| PRD ID | 需求 | 技术方案对应 |
|--------|------|-------------|
| R-1.1 | ECharts 图表渲染 | Phase 2.1 |
| R-1.2 | 智能选股完整流程 | Phase 2.5 |
| R-1.3 | 策略回测完整流程 | Phase 2.6: 新建 backtester.py |
| R-1.4 | 报告生成与展示 | Phase 2.4: marked.js |
| R-1.5 | 设置页完整 | Phase 2.7: `PUT /api/settings` |
| R-1.6 | 分析管线实时进度 | Phase 2.2: WebSocket |
| R-1.7 | 预警实时推送 | Phase 2.3: Toast + 铃铛 |

---

## 十二、UI/UX 设计方案摘要（完整设计见 [UI_UX_REDESIGN_PROPOSAL.md](UI_UX_REDESIGN_PROPOSAL.md)）

### 设计原则

1. **信息密度优先** — 一屏内尽可能多的关键数据
2. **操作路径最短** — 从信号到动作 ≤ 2 次点击
3. **实时感** — 脉冲动画、渐变色变
4. **渐进披露** — 概览层展示结论，详情层展示推理
5. **移动端不是缩小版** — 重新编排信息层级

### 视觉规范要点

| 维度 | 规范 |
|------|------|
| 配色 | 暗色交易主题，保留现有 CSS 变量，新增渐变强调和脉冲动画 |
| 字体 | 数据大字 32px → 统计值 24px → 表头 11px 大写 → 正文 13px |
| 动效 | 页面切换 fade 200ms；价格闪烁 600ms；卡片悬停 150ms |
| 图标 | Font Awesome 6.5 实心风格，统一语义映射（见设计稿 8.1） |
| 表格 | `tabular-nums` 数字等宽；右对齐金额；实时闪烁动画 |
| 按钮 | 三级：Primary（实心蓝）/ Secondary（描边）/ Ghost（幽灵） |
| 输入框 | `#161b22` 背景，聚焦蓝色发光边框 |
| 徽章 | BUY 绿/SELL 红/HOLD 黄，圆角 12px |
| Toast | 右下角滑入，左侧语义色条，3 秒自动消失 |
| 模态框 | 遮罩 `blur(4px)`，圆角 12px，移动端变全屏抽屉 |

### 页面布局线框图

所有 9 个页面的线框图详见 [UI_UX_REDESIGN_PROPOSAL.md 第三节](UI_UX_REDESIGN_PROPOSAL.md)，包括：

- 3.1 仪表盘：四大指标卡 + 图表行 + 持仓表 + 预警摘要
- 3.2 AI 分析：输入区 + 管线进度 + 结论三卡片 + Tab 详情 + 多空辩论
- 3.3 分析记录：master-detail + 信号变化时间线
- 3.4 智能选股：参数区 + 漏斗可视化 + 结果列表
- 3.5 持仓管理：操作按钮 + 持仓表 + 盈亏概览 + 交易记录
- 3.6 预警中心：规则列表 + 编辑器 + 预设模板 + 触发历史
- 3.7 报告中心：类型选择 + Markdown 渲染 + 发送操作
- 3.8 策略回测：参数区 + 指标卡 + 净值曲线 + 交易明细
- 3.9 设置：API Keys + 通知 + 定时任务 + 系统

### 移动端适配方案

完整的移动端设计见 [UI_UX_REDESIGN_PROPOSAL.md 第六节](UI_UX_REDESIGN_PROPOSAL.md)，包括：

- 6.1 断点与布局策略（xs/sm/md/lg 四级）
- 6.2 底部 Tab Bar 导航（5 个主入口 + "更多" sheet）
- 6.3 组件移动端变体（表格→卡片/模态→抽屉/统计卡 2×2）
- 6.4 触摸交互规范（最小目标 44px/防误触间距/下拉刷新）
- 6.5 各页面适配方案对照表
- 6.6 AI 分析页移动端特殊处理（垂直时间线/手风琴折叠）
- 6.7 PWA 增强
- 6.8 性能优化

### 组件设计规范

完整的组件规范见 [UI_UX_REDESIGN_PROPOSAL.md 第八节](UI_UX_REDESIGN_PROPOSAL.md)，包括：

- 8.1 图标系统（语义映射表 + 科技感装饰效果）
- 8.2 数据表格（表头/行/单元格样式 + 实时价格动画）
- 8.3 按钮系统（三级层次 + 四种尺寸 + 语义按钮）
- 8.4 表单输入（暗色输入框 + 下拉 + 日期 + 开关）
- 8.5 徽章与标签（信号/状态/市场）
- 8.6 卡片组件（统计卡/内容卡/持仓卡）
- 8.7 图表容器（ECharts 暗色主题配置）
- 8.8 加载与空状态（骨架屏/空状态/错误状态）
- 8.9 Toast 通知（成功/错误/警告/信息/预警触发）
- 8.10 模态框
- 8.11 进度指示器（管线进度/漏斗/通用进度条）
- 8.12 全局搜索面板
- 8.13 间距与圆角系统
- 8.14 阴影与光效

---

*文档结束。请审阅后确认是否可以进入实施阶段。*
