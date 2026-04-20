# PRD: UI React Island —— Flask 外壳 + React 岛屿式前端升级

| 项 | 值 |
|---|---|
| Feature | `ui-react-island` |
| 版本 | v1.0 |
| 日期 | 2026-04-21 |
| 关联技术方案 | [../design/ui-react-island.md](../design/ui-react-island.md) |
| 关联测试用例 | [../test-cases/ui-react-island.md](../test-cases/ui-react-island.md) |
| POC 参考 | `/tmp/stock-ui-demo/`（Vite + React 19 + Tailwind v4 + shadcn/ui）|

## 1. 背景

### 1.1 现状

- [web/templates/index.html](../../stock_trading_system/web/templates/index.html) 单文件 1201 行，11 页全塞其中
- [static/css/style.css](../../stock_trading_system/web/static/css/style.css) 1818 行散乱样式，Bootstrap 5 + 大量 inline style 混用
- [static/js/app.js](../../stock_trading_system/web/static/js/app.js) 4000+ 行 vanilla JS，各页面 render 函数杂耦
- 无构建管道、无组件复用、无类型系统

### 1.2 累积痛点

| 痛点 | 根因 | 已产生的后果 |
|---|---|---|
| [screener-v3](./screener-v3.md) 后端全齐但 UI 完全未交付 | Phase 6 前端工作量巨大，vanilla JS + 14 大师面板 + 流式 WS 难实现 | v3 后端跑着但用户不可用 |
| [mobile-optimization](../design/mobile-optimization.md) 产出 7 组件 + 11 页清单仍要手写 CSS + HTML | Bootstrap 约束 + 无组件化 | 移动端改动跨多 `.page` DOM 修补 |
| [paper-trade v1.3](../design/paper-trade.md) 的 tier 卡片布局问题 | 写死 bootstrap row/col 栅格，不响应式 | 中屏挤压、文字竖排 |
| [unified-progress](../design/unified-progress.md) 需要统一 ProgressStream 组件 | vanilla JS 各页各自 SocketIO handler | 逻辑重复、UI 不一致 |
| 用户反馈"想要 shadcn/MUI/Ant Design 风格" | 所有现代组件库都是 React 生态 | 不升级前端架构就彻底无法采纳 |

### 1.3 技术选型（已定）

见 [../design/ui-react-island.md §2](../design/ui-react-island.md#2-选型) 的 POC 验证结果：

- **Vite 8 + React 19 + TypeScript**：主流组合，Vite 构建 200ms 级别
- **Tailwind CSS v4**：原生 CSS 变量 + `@theme` 指令，可直接对齐 [mobile-optimization tokens](../design/mobile-optimization.md)
- **shadcn/ui 风格**：组件源代码进仓库，可随意改样式（非运行时依赖），a11y 由底层 Radix 保证
- **Radix UI 原语**：Dialog/Dropdown/Popover/Select/... headless 组件
- **sonner + cmdk**：Toast 通知 + ⌘K 命令面板（shadcn 官方标配）
- **lucide-react**：图标系统，视觉与现有 bootstrap-icons 一致

POC 已在 `/tmp/stock-ui-demo/` 验证通过：4 页面 demo + 14 交互组件 Gallery，生产 bundle 151KB gzipped。

## 2. 目标

**以渐进 island 策略**把高价值页面升级为 React，同时保留 Flask 外壳和简单页面不动，实现"**零重写风险 + 高价值先享受**"。

### 2.1 成功指标

| 指标 | 目标 |
|---|---|
| 高复杂度页面用 React 实现 | 3-4 页（screener-v3 / paper-trade detail / dashboard / tasks 任务中心）|
| 简单页面保留 Jinja | 5+ 页（login / register / reset / settings / alerts / reports / history）|
| 首屏 LCP（任意岛屿页面，桌面 3G throttling） | ≤ 2.5s |
| React island 首屏 JS（gzipped） | ≤ 180KB per island |
| 桌面视觉 baseline pixel-match 回归为 0 | 100%（非迁移页不影响）|
| Dev hot-reload 延迟（React 岛屿修改） | ≤ 500ms HMR |
| 构建管道 CI 集成 | Railway 部署流程保持 1 命令 |
| 前端类型覆盖 | 100%（所有迁移的页面有 TS 类型） |

## 3. 范围

### 3.1 In Scope（v1.0）

**构建管道**
- Vite 构建输出到 `stock_trading_system/web/static/dist/`
- Flask 通过 Jinja 模板读取 Vite manifest.json，注入 hashed filename 的 `<script>` 和 `<link>`
- 开发模式：Vite dev server on :5173，Flask proxy 到 Vite（或 Vite proxy 到 Flask，择一）
- 生产模式：一个 `npm run build` → 产出 assets → `flask run`

**多岛屿组织**
- 每个 React "island" 是一个独立 entry point（如 `src/islands/screener/main.tsx`）
- 每个 island 挂到专门的 Flask 路由（`/screener-v3`, `/paper-trade/:ticker`）
- 共享 `src/components/ui/*`（shadcn 组件）+ `src/lib/*` + `src/data/*`

**首批迁移（v1.0）4 页**
- `/screener-v3` —— 全新实现（screener-v3 设计的 UI 层）
- `/paper-trade/:ticker` —— 详情页（含 tier 卡片 + AI 决策）
- `/dashboard` —— 仪表盘（多指标卡 + AI 洞察 + 实时进度流）
- `/tasks` —— 任务中心（集成 [unified-progress](./unified-progress.md) 的 ProgressStream）

**共享基础设施**
- `src/lib/api.ts` —— fetch 封装（自动带 CSRF token + cookie credentials）
- `src/lib/socket.ts` —— SocketIO client 封装（复用 [unified-progress](./unified-progress.md) 的 envelope schema）
- `src/lib/auth.ts` —— 读当前用户 session（通过 `<meta>` 注入或 `/api/auth/me` 拉取）
- `src/components/ui/*` —— 从 POC 迁过来 + 扩展

**保留 Jinja 不动**
- `/login` / `/register` / `/reset` —— 短期内无需复杂交互
- `/settings` —— 表单为主，先不动
- `/alerts` / `/reports` / `/history` / `/backtest` / `/analysis` —— 待 v1.1 评估

**样式对齐**
- Tailwind v4 `@theme` tokens 与 [mobile-optimization](./mobile-optimization.md) 的 CSS vars 完全一致（oklch 色彩空间）
- 旧 `style.css` 保持不动（对非迁移页面生效）
- 新 React 页面**不引入** Bootstrap，完全走 Tailwind + shadcn

### 3.2 Out of Scope（v1.0 不做）

| 项 | 原因 | 未来 |
|---|---|---|
| 迁移全部 11 页到 React | 工期爆炸，简单页收益低 | v1.1+ 按需扩展 |
| 改用 Next.js / Remix | 需 Node 服务端，和 Flask 架构冲突 | 极远未来，Path D |
| 换 MUI / Ant Design | 与 POC 验证的 shadcn 风格不符，视觉截然不同 | 不计划 |
| 服务端渲染（SSR） | 单用户量小，CSR 足够；SSR 引入 Node | 不计划 |
| 前端路由库（react-router） | 岛屿间切换走 Flask 路由，不做 SPA | 未来若全迁 React 再考虑 |
| 状态管理库（Redux / Zustand / Jotai） | 各 island 独立，local state + useContext 够 | 按需 v1.1 |
| i18n | 当前只支持中文 | 未来 |
| 主题切换（亮/暗） | 项目暗色定位清晰 | 不计划 |

### 3.3 范围决策原则

> 某页面**该不该**迁到 React？

迁到 React 的硬标准（任一满足）：
1. 页面有 **复杂交互**（多 tab + 嵌套折叠 + 流式订阅 + 高频状态切换）
2. 页面 **展示密度高**（大量数据 + 多卡片响应式栅格 + 信息分层）
3. 页面 **已在新设计中有明确 React 方案**（如 screener-v3 / paper-trade v1.3）

保留 Jinja 的硬标准：
1. 纯表单（login / register / password reset）
2. 纯列表 + 筛选（alerts / reports）
3. 少交互的配置页（settings）

## 4. 用户故事

### US-UI-1（核心）：Screener V3 UI 可用

> **作为**用户，过去 screener-v3 后端跑着但没前端，我只能通过 API 调用。
> **现在希望**打开 `/screener-v3` 看到完整的 14 大师选择 + 深度模式 + 成本预估面板。

**验收**：
- 访问 `/screener-v3`  → 看到 POC 中的 ScreenerV3Demo 效果（14 大师勾选 / 3 模式 radio / 候选数 chip / 成本实时预估）
- 点"开始筛选" → 调 `/api/screen/v3/trigger` → 任务 id 返回
- 跳 `/tasks/<id>` 看流式进度

### US-UI-2：Paper-trade 移动端可用

> **作为**移动端用户，paper-trade 详情页的 tier 卡片在手机上不挤压。

**验收**：
- `/paper-trade/NVDA` 在 375/414/768px 视口显示合理
- tier 卡片 ≤768px 走移动布局（两行：seq+label+target+status / trigger+detail+date）
- 桌面 ≥768px 走 12 栏网格不变

### US-UI-3：Dashboard 高密度信息

> **作为**每天要看多项指标的用户，希望 dashboard 一屏呈现：账户总值 / 今日 PnL / 胜率 / 活跃预警 / AI 洞察 / 运行中任务 / 持仓概览。

**验收**：
- 1440px 视口一屏可见全部 7 块信息区
- 375px 移动端 stat 卡 2x2，信息区竖排
- AI 洞察每行可点击跳到分析详情

### US-UI-4：任务中心统一进度流

> **作为**用户，希望任务中心展示所有运行中任务的流式进度，和 Dashboard 上的小卡片保持一致。

**验收**：
- `/tasks` 使用 [unified-progress](./unified-progress.md) 的 `ProgressStream` 组件
- 断线自动重连 + catch-up
- 复用 Dashboard 上的进度行视觉

### US-UI-5：开发者体验

> **作为**开发者，修改 React 代码 hot-reload 500ms 内刷新；CI 构建不超过现在流水线 2 倍时间。

**验收**：
- `npm run dev` 启动 + Flask 启动后，修改 `.tsx` 文件 HMR 生效
- `npm run build` + `flask run` 生产模式完整可用
- Railway 部署集成 `npm install && npm run build` 步骤

### US-UI-6：非迁移页面零影响

> **作为**用户，访问 `/settings` / `/alerts` 等未迁移页，视觉和交互与升级前**完全一致**。

**验收**：
- 非迁移页面视觉 pixel-match baseline（Playwright 截图）
- 非迁移页面功能不受影响
- 旧 `style.css` / `app.js` 继续工作

## 5. 需求矩阵

### 5.1 P0 —— 必须上线

| ID | 描述 |
|---|---|
| R-UI-1 | Vite 构建产物输出到 `static/dist/`，Jinja 通过 manifest 注入 |
| R-UI-2 | Dev 模式：Vite + Flask 并行（Flask :5000，Vite :5173，前端 fetch 经 Vite proxy）|
| R-UI-3 | Prod 模式：`npm run build` → `flask run` 单命令可用 |
| R-UI-4 | 4 个 island entry（screener-v3 / paper-trade / dashboard / tasks）独立打包 |
| R-UI-5 | 共享 `src/components/ui/` shadcn 组件库（从 POC 迁入）|
| R-UI-6 | `src/lib/api.ts` 自动携带 CSRF token + session cookie |
| R-UI-7 | `src/lib/socket.ts` 封装 SocketIO 且实现 [unified-progress](./unified-progress.md) catch-up |
| R-UI-8 | 4 个迁移页面功能与 POC demo 对齐 + 接通真实 API |
| R-UI-9 | Tailwind v4 tokens 与 `style.css` CSS vars 一致，不产生视觉冲突 |
| R-UI-10 | Railway 部署流程兼容（`npm install && npm run build` 加入 Procfile） |
| R-UI-11 | 非迁移页面视觉零回归（桌面 + 移动 pixel-match）|
| R-UI-12 | 4 个迁移页面类型覆盖率 100%（TS strict mode）|

### 5.2 P1 —— 可选

| ID | 描述 |
|---|---|
| R-UI-13 | 全局 `⌘K` 命令面板（shadcn Command）替换现有顶栏搜索 |
| R-UI-14 | 全局 Toast（sonner）替换散落的 alert() 和 Bootstrap toast |
| R-UI-15 | Analysis 详情页迁到 React（多 tab 报告）|
| R-UI-16 | History 页迁到 React（DataTable + 筛选）|
| R-UI-17 | Code splitting 按路由做 dynamic import |

### 5.3 P2 —— 未来

| ID | 描述 |
|---|---|
| R-UI-18 | 其余简单页（login/register/reset）也迁到 React（视觉一致性）|
| R-UI-19 | 引入状态管理库（Zustand / Jotai） |
| R-UI-20 | 国际化（i18n） |
| R-UI-21 | SSR / Next.js 全迁移 |

## 6. 非功能需求

### 6.1 性能

- **React island 首屏 JS**：≤ 180KB gzipped per entry（通过手动 chunk split 共享 ui/lib）
- **Dev HMR**：≤ 500ms
- **生产构建**：完整 4 岛屿 + 组件库 ≤ 20s（在 Railway 构建环境）
- **首屏 LCP**：≤ 2.5s（4G throttle）

### 6.2 兼容性

- 浏览器支持：Chrome / Safari / Firefox / Edge 近 2 个大版本
- iOS Safari 15+ / Android Chrome 90+
- 零新增后端依赖（Flask + Python 不变）
- 新增前端依赖：`npm` + Node ≥ 18 LTS

### 6.3 可观测性

- 每个 React island 的 crash 上报到 console（无需第三方工具 v1.0）
- Vite build manifest 归档在 deploy 产物中
- 前端错误 boundary 显示友好降级 UI

### 6.4 安全

- 所有 `/api/*` fetch 带 CSRF token（从 `<meta name="csrf-token">` 读取）
- Session cookie 仍由 Flask 管理（HttpOnly + SameSite=Lax）
- React island 不存储敏感信息到 localStorage
- CSP 策略：`script-src 'self'`；Vite 生产构建的 hash 化 filename 与 CSP 兼容

### 6.5 回滚

- 任一岛屿出问题：Flask 路由切回原 Jinja 模板即可（保留 dead-code 待删）
- 整体回滚：删除 `static/dist/` 并恢复 `<script>` tag 引用 `/static/js/app.js`
- 备份：迁移前的 `index.html` 保存为 `index.html.pre-react.bak`

## 7. 风险与假设

| 风险 | 概率 | 影响 | 缓解 |
|---|---|---|---|
| Vite + Flask 协作管道在生产/Railway 有坑 | 中 | 高 | POC 阶段先在 Railway 跑一次 minimal build；失败时降级方案见 §8 |
| React island 首屏 JS 超 180KB | 中 | 中 | manual chunks 共享 Radix + shadcn，每 island 只打自己的业务代码 |
| 桌面非迁移页面被新 CSS 污染 | 低 | 中 | Tailwind 新 CSS 加 `.ri-*` 前缀或限定在 `[data-ri-root]` 容器 |
| SocketIO 在 React 里重连错乱 | 低 | 中 | `src/lib/socket.ts` 做单例 + [unified-progress](./unified-progress.md) catch-up |
| CSRF token 在 fetch 时遗漏 | 中 | 高 | `src/lib/api.ts` 统一封装，项目内禁用裸 fetch（lint rule）|
| Tailwind v4 Alpha 版本变更 | 低 | 低 | 锁版本；若阻塞则降回 v3 |
| Vite 6 + React 19 配合有警告 | 低 | 低 | POC 已验证配合 OK（无警告）|
| 团队上手 React 成本 | 中（对单人项目较低）| 低 | 组件库 shadcn 代码本身即文档，AI 工具协助生成 |
| 迁移期间旧页 bug 堆积无人修 | 中 | 低 | 每迁移一页同时验证相邻页，`.pre-react.bak` 保留可回查 |

## 8. 回滚方案（详细）

### 8.1 单页回滚

任一岛屿失败：
1. Flask 路由改回 `render_template("index.html")`（简单注释切换）
2. `static/dist/` 里对应 entry 的 JS/CSS 保留（静态资源），下次构建覆盖
3. 用户刷新即回到 Jinja 页

### 8.2 整体回滚

1. 停 Flask
2. `git revert` 本 feature 相关 commits
3. 恢复 Procfile、Railway 构建命令
4. 重启 Flask

### 8.3 数据层兼容

- React island 调用的都是 **既有 API**（或本方案新增的）
- 旧 Jinja 页也调同一组 API
- 不存在数据模型变更 → 回滚零数据风险

## 9. 与其他模块的关系

| 模块 | 关系 |
|---|---|
| [screener-v3](./screener-v3.md) | 本 feature 的 **首要交付价值**：补齐 Phase 6 未完成的前端 |
| [paper-trade v1.3](./paper-trade.md) | 5 处 UX 修正在 React 里可以干净实现（tier 卡片响应式、AI 决策渲染、tab 合并）|
| [unified-progress](./unified-progress.md) | `ProgressStream` 组件在 Dashboard / Tasks 页用；React 版 ProgressStream 是唯一实现，废弃 vanilla JS 版 |
| [mobile-optimization](./mobile-optimization.md) | Tailwind v4 tokens 与本 feature 共用一套；`form-row-mobile` / `chip-row` / `collapse-row` 等组件在 React 里更易实现 |
| [multi-tenant](./multi-tenant.md) | React fetch 复用 Flask session cookie + CSRF，`g.user` 注入通过 `<meta>` 或 `/api/auth/me` |
| [model-switch](./model-switch.md) | 顶栏 provider 切换 dropdown 可迁到 React，或先保留 Jinja（simple）|
| [engineering-principles](../engineering-principles.md) | 严格遵守 L0→L4 阶梯；本 feature 代码多来自 shadcn copy（L2/L3）+ Radix primitives（L1）|

## 10. 迁移顺序（与技术方案 Phase 对齐）

1. **Phase 1** —— 构建管道：Vite + Flask 协作（~4h）
2. **Phase 2** —— 共享基础设施：UI 组件 + lib（~3h，大部分 POC 已做）
3. **Phase 3** —— Screener V3 island（~6h，收益最大）
4. **Phase 4** —— Tasks island（~4h，集成 unified-progress）
5. **Phase 5** —— Paper-trade detail island（~5h）
6. **Phase 6** —— Dashboard island（~4h）
7. **Phase 7** —— 收尾 + 回归测试（~2h）

**总计 ~28h**。详见 [技术方案 §10](../design/ui-react-island.md#10-实施计划)。

## 11. 版本历史

| 版本 | 日期 | 变更 |
|---|---|---|
| v1.0 | 2026-04-21 | 初版：4 岛屿首批迁移（screener-v3 / paper-trade / dashboard / tasks）+ Vite + Flask 协作管道 + 保留 7 页 Jinja 不动 + Tailwind v4 + shadcn/ui + POC 已验证 |
