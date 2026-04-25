# 测试用例：UI React Island

| 项 | 值 |
|---|---|
| Feature | `ui-react-island` |
| 版本 | v1.0 |
| 日期 | 2026-04-21 |
| 关联 PRD | [../prd/ui-react-island.md](../prd/ui-react-island.md) |
| 关联设计 | [../design/ui-react-island.md](../design/ui-react-island.md) |

## 汇总

| 分类 | 用例数 |
|---|---|
| 构建管道：Vite + Flask | 10 |
| 共享基础设施（lib/api, socket, auth） | 12 |
| UI 组件库单元测试 | 14 |
| Screener V3 island | 12 |
| Tasks island | 10 |
| Paper-trade detail island | 8 |
| Dashboard island | 7 |
| 跨岛屿集成 | 6 |
| 样式与视觉一致性 | 8 |
| 非迁移页回归 | 7 |
| 性能 | 5 |
| 安全（CSRF / session） | 5 |
| 真机 / 部署验证 | 4 |
| **总计** | **108** |

---

## 1. 构建管道：Vite + Flask（10）

### TC-UI-B1：Dev 模式 Flask 启动后，访问 `/screener-v3` → 返回的 HTML 包含 `http://localhost:5173/@vite/client`

### TC-UI-B2：Dev 模式 React 代码修改 → Vite HMR 推送 → 浏览器 < 500ms 更新

### TC-UI-B3：Prod 构建 `npm run build` 产出 `static/dist/.vite/manifest.json`

### TC-UI-B4：Prod 模式访问 `/screener-v3` → HTML 内 `<script>` src 是 `/static/dist/assets/screener-v3-[hash].js`

### TC-UI-B5：Prod 模式 `manifest.json` 中每个 entry 的 `imports` 字段被正确追加到 script 列表（chunk 预加载）

### TC-UI-B6：Prod 模式 `manifest.json` 中 CSS 文件被注入 `<link rel="stylesheet">`

### TC-UI-B7：`vite_helpers.vite_assets()` 幂等：多次调用返回相同结果

### TC-UI-B8：`FLASK_ENV=production` 时跳过 Vite dev URL

### TC-UI-B9：Railway Nixpacks 构建含 `nodejs-18_x`（验证 `.nixpacks/environment.toml`）

### TC-UI-B10：`railway.json` buildCommand 包含 `npm install && npm run build`

---

## 2. 共享基础设施（12）

### 2.1 `lib/api.ts`（5）

**TC-UI-U1**：`apiGet` 默认 credentials=same-origin

**TC-UI-U2**：非 GET 请求自动附加 `X-CSRFToken` header

**TC-UI-U3**：`apiPost` 自动 JSON.stringify body + `Content-Type: application/json`

**TC-UI-U4**：非 2xx 响应抛 `ApiError`，包含 status 和 body

**TC-UI-U5**：响应 401 时（session 过期）触发全局重定向 `/login?next=<current>`（v1.1 可选）

### 2.2 `lib/socket.ts`（4）

**TC-UI-U6**：`getSocket()` 返回单例（多次调用同一实例）

**TC-UI-U7**：`subscribeTaskStream` 订阅后，收到 seq > lastSeq 的事件才触发 onEvent

**TC-UI-U8**：`socket.connect` 事件触发 catch-up `/api/tasks/events?since=<lastSeq>`

**TC-UI-U9**：`destroy()` 清理 socket listener 不泄漏

### 2.3 `lib/auth.ts`（3）

**TC-UI-U10**：`getCurrentUser()` 从 `<meta name="user-id">` 读取

**TC-UI-U11**：未登录（meta 为空）返回 null

**TC-UI-U12**：display-name 含特殊字符时被 Jinja `|e` 转义（不 XSS）

---

## 3. UI 组件单元（14）

每个 shadcn 组件 1 条冒烟用例。

- **TC-UI-C1**：Button 6 变体渲染
- **TC-UI-C2**：Dialog open/close + Escape 关闭
- **TC-UI-C3**：Sheet 4 side 方向
- **TC-UI-C4**：DropdownMenu 键盘导航（↑↓ Enter）
- **TC-UI-C5**：Popover align 属性
- **TC-UI-C6**：Tooltip hover 延迟 150ms
- **TC-UI-C7**：Select 单选 + 键盘 open
- **TC-UI-C8**：Tabs value 受控 + URL sync
- **TC-UI-C9**：Accordion single + multiple
- **TC-UI-C10**：Command 搜索过滤
- **TC-UI-C11**：Alert 5 variant（default/info/success/warning/destructive）
- **TC-UI-C12**：Progress value 动画过渡
- **TC-UI-C13**：Skeleton 动画 CSS 类存在
- **TC-UI-C14**：Toaster sonner 4 级通知（default/success/warning/error）

---

## 4. Screener V3 island（12）

### TC-UI-S1：访问 `/screener-v3` 后台要求已登录（未登录 302 /login）

### TC-UI-S2：已登录访问 → 页面加载 + React 挂载成功

### TC-UI-S3：GET `/api/screen/v3/gurus` 被调用 → 返回 14 位大师数据 → 列表渲染

### TC-UI-S4：点"推荐 4"按钮 → 选中 Buffett/Graham/Munger/Lynch

### TC-UI-S5：NL textarea 输入 → debounce 500ms → POST `/api/screen/v3/estimate`

### TC-UI-S6：estimate 返回后 cost/duration/calls 三栏更新

### TC-UI-S7：mode=classic → 预估区显示"免费 / 秒级 / —"

### TC-UI-S8：点"开始筛选" → POST `/api/screen/v3/trigger` → 跳转 `/tasks/<task_id>`

### TC-UI-S9：候选数量 chip 10/20/30/50 切换重新计算预估

### TC-UI-S10：大师勾选变化也触发重估

### TC-UI-S11：Provider（Qwen/Gemini）变化时预估 cost 更新（集成 model-switch）

### TC-UI-S12：移动端 375px → guru 列表 1 列、depth 3 radio 垂直叠

---

## 5. Tasks island（10）

### TC-UI-T1：访问 `/tasks` → 默认 tab="my"

### TC-UI-T2：切换到 tab="all" → GET `/api/tasks?scope=all`

### TC-UI-T3：`/tasks/<id>` → 渲染 TaskDetail

### TC-UI-T4：TaskDetail 订阅 SocketIO room `user:<id>`

### TC-UI-T5：收到 `task_progress` 事件 → 进度条更新

### TC-UI-T6：收到 `guru_unit_done`（screener-v3）→ 添加一行到流式列表

### TC-UI-T7：断线 → 显示"连接中断"banner

### TC-UI-T8：重连 → GET `/api/tasks/events?task_id=<id>&since=<seq>` 补齐

### TC-UI-T9：`task_completed` → Toast 提示 + 可跳到结果页

### TC-UI-T10：点"停止任务"→ POST `/api/tasks/<id>/cancel`

---

## 6. Paper-trade detail island（8）

### TC-UI-P1：访问 `/paper-trade/NVDA` → React 挂载

### TC-UI-P2：GET `/api/paper/tickers/NVDA` → 数据渲染

### TC-UI-P3：tier 卡片在 <768px 走移动布局（2 行 stack）

### TC-UI-P4：tier 卡片在 ≥768px 走 12 栏 grid

### TC-UI-P5：AI 最终决策区展示 `trade_decision` Markdown 全文

### TC-UI-P6：执行记录 tab 内 chip-row 切换 按 Plan / 按 Event 视图

### TC-UI-P7：日度数据 ECharts 图双 grid + drawdown markArea 渲染

### TC-UI-P8：移动端 日度图表隐藏 pnl 柱形（仅显示净值曲线）

---

## 7. Dashboard island（7）

### TC-UI-D1：访问 `/dashboard` → GET `/api/dashboard` 聚合接口被调用

### TC-UI-D2：4 stat 卡渲染（总值 / PnL / 胜率 / 活跃预警）

### TC-UI-D3：AI 洞察列表按 score 降序

### TC-UI-D4：运行中任务卡片挂 `ProgressStream(compact)`

### TC-UI-D5：持仓概览 top 3 显示

### TC-UI-D6：桌面 1440px 一屏可见全部信息区

### TC-UI-D7：移动端 stat 卡 2x2 栅格

---

## 8. 跨岛屿集成（6）

### TC-UI-I1：screener-v3 触发任务 → 跳 `/tasks/<id>` → Progress 实时更新（同一 user_id 穿透）

### TC-UI-I2：同一用户多标签页 → SocketIO room `user:<id>` 全部广播

### TC-UI-I3：alice 打开 screener-v3 + bob 打开 dashboard → 事件不相互泄露

### TC-UI-I4：session 过期 → fetch 401 → 重定向 login（保留 next 参数）

### TC-UI-I5：model-switch 切 provider → 新建任务使用新 provider（与 multi-tenant user_settings 对齐）

### TC-UI-I6：从 paper-trade 页点"再次分析"→ POST /api/analyze → 跳 /tasks/<id>

---

## 9. 样式与视觉一致性（8）

### TC-UI-V1：React island 色值与 `style.css` 一致（Chrome DevTools 读取 `--color-accent-blue` 值）

### TC-UI-V2：Radius token 与 mobile-optimization.md §2.3 一致

### TC-UI-V3：字号 clamp() 响应式在 375/768/1440 三点 pixel-match

### TC-UI-V4：图标库（lucide-react）与 Bootstrap Icons 视觉接近（stroke-width 2）

### TC-UI-V5：Tab 组件 active 状态与 paper-trade 的现有 `.nav-link.active` 视觉接近

### TC-UI-V6：Button primary 颜色 = CSS `--color-accent-blue`

### TC-UI-V7：Toast 位置（top-right）+ 暗色主题

### TC-UI-V8：Scrollbar 宽度 10px + 暗色 thumb

---

## 10. 非迁移页回归（7）

### TC-UI-R1：`/login` Jinja 渲染正常，Playwright 截图 pixel-match baseline

### TC-UI-R2：`/register` 邀请码注册流程不受影响

### TC-UI-R3：`/settings` 旧页面完整工作

### TC-UI-R4：`/alerts` 旧页面完整工作

### TC-UI-R5：`/reports` 旧页面完整工作

### TC-UI-R6：旧 `static/js/app.js` 在非迁移页继续 bind event

### TC-UI-R7：旧 `static/css/style.css` 未被 Tailwind 覆盖（非迁移页的 CSS 不受影响）

---

## 11. 性能（5）

### TC-UI-PP1：每个 island entry 首屏 JS gzipped ≤ 180KB

### TC-UI-PP2：react-vendor + radix + ui 三个共享 chunk 存在

### TC-UI-PP3：Lighthouse Mobile Performance（任意 island）≥ 85

### TC-UI-PP4：LCP ≤ 2.5s（4G throttle）

### TC-UI-PP5：Vite build 总时长 ≤ 20s（Railway 环境）

---

## 12. 安全（5）

### TC-UI-SEC1：所有 POST/PUT/DELETE fetch 带 `X-CSRFToken` header

### TC-UI-SEC2：未带 CSRF token → Flask 返回 403

### TC-UI-SEC3：Session cookie 仍为 HttpOnly（JS 无法读取）

### TC-UI-SEC4：XSS：display_name 含 `<script>` → React 自动转义（不执行）

### TC-UI-SEC5：未登录访问受保护 island 路由 → 302 /login

---

## 13. 真机 / 部署验证（4）

### TC-UI-M1：Railway staging 部署成功 + 4 island 均可访问

### TC-UI-M2：iPhone Safari 15+ 访问 paper-trade 详情页（touch 交互正常）

### TC-UI-M3：Android Chrome 90+ 访问 screener-v3（输入法不遮挡 NL textarea）

### TC-UI-M4：隐私模式（无 cookie）→ 登录流程正常跳转

---

## 覆盖要求

| 模块 | 目标 |
|---|---|
| `frontend/src/lib/` | 行覆盖 ≥ 90% |
| `frontend/src/components/ui/` | ≥ 85% |
| `frontend/src/components/shared/` | ≥ 90% |
| `frontend/src/islands/*/` | ≥ 75% |
| `stock_trading_system/web/vite_helpers.py` | 100% |

### 运行命令

```bash
# 前端单元 + 组件
cd stock_trading_system/web/frontend
npm test

# 前端类型检查
npx tsc --noEmit

# 前端 lint
npm run lint

# 后端 + 集成
pytest tests/web/test_vite_helpers.py tests/integration/test_islands/

# E2E（跨 island）
npx playwright test tests/e2e/

# 生产构建冒烟
npm run build && python -c "from stock_trading_system.web.vite_helpers import vite_assets; print(vite_assets('src/islands/screener-v3/main.tsx'))"

# 视觉回归（非迁移页）
npx playwright test tests/visual/non-migrated.spec.ts --update-snapshots  # 首次
npx playwright test tests/visual/non-migrated.spec.ts                     # 回归
```

## v2.0 用例补充（剩余 11 页）

### 14. 共享组件（12）

- **TC-UI-V2-1**：`<AppShell>` 渲染 Nav + Sidebar + MobileTabbar
- **TC-UI-V2-2**：Sidebar active 态基于 `window.location.pathname`
- **TC-UI-V2-3**：`<DataTable>` 排序点击切换 asc/desc
- **TC-UI-V2-4**：`<DataTable>` 搜索过滤实时生效
- **TC-UI-V2-5**：`<DataTable>` 分页按钮工作
- **TC-UI-V2-6**：`<DataTable>` 移动端 ≤768px 切卡片视图
- **TC-UI-V2-7**：`<Form>` zod 校验失败显示字段错误
- **TC-UI-V2-8**：`<Form>` 提交态 loading + 禁用按钮
- **TC-UI-V2-9**：`<EChartsPanel>` ResizeObserver 正确 resize
- **TC-UI-V2-10**：`<EChartsPanel>` loading 状态显示 spinner
- **TC-UI-V2-11**：`<AuthCard>` 居中布局 + 响应式
- **TC-UI-V2-12**：`<FilterBar>` chip 与 search 组合状态

### 15. Portfolio island（6）

- **TC-UI-V2-13**：`/portfolio` 加载显示 4 stat 卡
- **TC-UI-V2-14**：[+ 买入] Dialog 提交走 `/api/portfolio` POST
- **TC-UI-V2-15**：持仓表排序按盈亏
- **TC-UI-V2-16**：行末菜单「分析」跳 `/analysis?ticker=<x>`
- **TC-UI-V2-17**：移动端 ≤768px 持仓表切 m-card 卡片
- **TC-UI-V2-18**：净值曲线 ECharts 渲染 + 响应式

### 16. History island（5）

- **TC-UI-V2-19**：`/history` 渲染分析记录卡片列表
- **TC-UI-V2-20**：FilterBar "我的 / 全部" tab 切换
- **TC-UI-V2-21**：★ 书签切换 → `/api/analysis/bookmarks` POST/DELETE
- **TC-UI-V2-22**：无限滚动加载（data > 30 行后触发）
- **TC-UI-V2-23**：搜索框在 ticker/关键词中都能匹配

### 17. Alerts island（5）

- **TC-UI-V2-24**：Tabs 规则 / 历史切换
- **TC-UI-V2-25**：[+ 新增规则] Dialog 字段（ticker / 条件 / 阈值 / 通知）
- **TC-UI-V2-26**：启用 Switch 切换走 `/api/alerts/<id>` PUT
- **TC-UI-V2-27**：历史 tab 按时间倒序
- **TC-UI-V2-28**：删除规则 Dialog 二次确认

### 18. Reports island（4）

- **TC-UI-V2-29**：生成表单 → POST `/api/reports` → 跳 `/tasks/<id>`
- **TC-UI-V2-30**：已生成列表渲染
- **TC-UI-V2-31**：下载按钮（PDF / MD / HTML）触发正确 API
- **TC-UI-V2-32**：过期（> 30 天）报告灰显标记

### 19. Backtest island（7）

- **TC-UI-V2-33**：新建 tab 左右两栏布局
- **TC-UI-V2-34**：参数变化触发 `/api/backtest/estimate` 更新预览
- **TC-UI-V2-35**：[+参数组合] 动态加字段（多策略对比）
- **TC-UI-V2-36**：开始回测 → 跳 `/tasks/<id>` → 完成后 `/backtest/<id>`
- **TC-UI-V2-37**：结果详情页 ECharts 净值曲线 + 指标卡
- **TC-UI-V2-38**：交易明细 DataTable 分页
- **TC-UI-V2-39**：参数 JSON Accordion 可展开

### 20. Paper list island（3）

- **TC-UI-V2-40**：默认 session 置顶 ★ 标记
- **TC-UI-V2-41**：grid 响应式（桌面 3 列 / 平板 2 列 / 移动 1 列）
- **TC-UI-V2-42**：点卡片跳 `/paper-trade/<session_id>`

### 21. Analysis island（8）

- **TC-UI-V2-43**：`/analysis` 触发表单校验（ticker 必填 + 合法）
- **TC-UI-V2-44**：深度模式 radio 切换影响预估
- **TC-UI-V2-45**：`/analysis/<id>` 8 tab 全部可切
- **TC-UI-V2-46**：Executive Summary 高亮展示
- **TC-UI-V2-47**：Markdown 渲染（react-markdown）+ 代码块语法高亮
- **TC-UI-V2-48**：移动端 tab 横滑（tabs-scrollable）
- **TC-UI-V2-49**：[再次分析] 走 `/api/analyze` + 跳 tasks
- **TC-UI-V2-50**：[加入持仓追踪] 写入 paper_trade_sessions

### 22. Settings island（7）

- **TC-UI-V2-51**：SettingsTabs 左侧导航 + 右侧内容
- **TC-UI-V2-52**：账号/修改密码 表单走 `/api/auth/change-password`
- **TC-UI-V2-53**：集成/LLM provider 切换（集成 model-switch）
- **TC-UI-V2-54**：系统/邀请码 admin 专属（非 admin 不可见）
- **TC-UI-V2-55**：系统/邀请码 [生成新码] 走 `/api/admin/invites` POST
- **TC-UI-V2-56**：高级/诊断 显示系统状态
- **TC-UI-V2-57**：移动端 SettingsTabs 折叠为下拉

### 23. Auth 三页（9）

#### Login（3）
- **TC-UI-V2-58**：居中 AuthCard 布局
- **TC-UI-V2-59**：回车提交
- **TC-UI-V2-60**：失败 shake 动画 + 错误 inline 提示

#### Register（4）
- **TC-UI-V2-61**：邀请码 debounce 校验（`/api/invite/validate`）
- **TC-UI-V2-62**：邮箱格式 zod 校验
- **TC-UI-V2-63**：密码强度校验（≥ 8 字符，非纯数字）
- **TC-UI-V2-64**：两次密码一致校验

#### Reset（2）
- **TC-UI-V2-65**：无效 token → 显示错误 card + 返回登录链接
- **TC-UI-V2-66**：新密码 + 确认一致后提交

### 24. Phase 18 废弃旧代码（5）

- **TC-UI-V2-67**：旧 `index.html` 各 `<div class="page">` 全部不渲染（404 或重定向）
- **TC-UI-V2-68**：`app.js` 删除后 console 无错误
- **TC-UI-V2-69**：`style.css` 仅保留 CSS vars，Bootstrap 选择器全删
- **TC-UI-V2-70**：bootstrap.min.css / bootstrap.bundle.min.js `<script>` 标签已移除
- **TC-UI-V2-71**：bootstrap-icons 引用已移除，全 lucide-react

### 25. v2.0 性能（3）

- **TC-UI-V2-72**：Analysis 详情 8 tab 首屏 JS ≤ 200KB gzipped
- **TC-UI-V2-73**：全部 11 页 Lighthouse Mobile ≥ 85
- **TC-UI-V2-74**：废弃 app.js 后总 JS 体积比 v1.0 之前小 40%+

---

## v2.0 汇总

| 分类 | 用例数（v2.0 新增）|
|---|---|
| 共享组件（AppShell / DataTable / Form / EChartsPanel）| 12 |
| Portfolio / History / Alerts / Reports | 20 |
| Backtest / Paper list / Analysis | 18 |
| Settings | 7 |
| Auth（Login/Register/Reset）| 9 |
| 废弃旧代码 | 5 |
| 性能 | 3 |
| **v2.0 小计** | **74** |

**总计（v1.0 + v2.0）= 108 + 74 = 182 条**

---

## 版本历史

| 版本 | 日期 | 用例数 | 变更 |
|---|---|---|---|
| v1.0 | 2026-04-21 | 108 | 初版：构建管道 10 + lib 12 + UI 组件 14 + 4 岛屿（Screener V3 12 / Tasks 10 / Paper-trade 8 / Dashboard 7）+ 跨岛集成 6 + 视觉一致 8 + 非迁移回归 7 + 性能 5 + 安全 5 + 真机 4 |
| v2.0 | 2026-04-21 | 74（+182 累计）| 覆盖剩余 11 页：共享组件 12 + Portfolio/History/Alerts/Reports 20 + Backtest/Paper list/Analysis 18 + Settings 7 + Auth 三页 9 + Phase 18 废弃旧代码 5 + v2.0 性能 3 |
