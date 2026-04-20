# 技术方案：UI React Island —— Flask + React 岛屿协作

| 项 | 值 |
|---|---|
| Feature | `ui-react-island` |
| 版本 | v1.0 |
| 日期 | 2026-04-21 |
| 关联 PRD | [../prd/ui-react-island.md](../prd/ui-react-island.md) |
| 关联测试用例 | [../test-cases/ui-react-island.md](../test-cases/ui-react-island.md) |
| POC | `/tmp/stock-ui-demo/`（已验证，4 页 + 14 组件 Gallery）|

## 1. 目标

见 [PRD §2](../prd/ui-react-island.md#2-目标)。一句话：**Flask 不改、SocketIO 不改、数据库不改，只把 4 个高价值页面的前端替换为 React + shadcn，简单页保留 Jinja**。

## 2. 选型

### 2.1 选型决策

已在 POC 中验证：

| 技术 | 版本 | 决策 |
|---|---|---|
| **React** | 19.2 | 最新稳定；服务端由 Flask 代劳，只需 CSR |
| **Vite** | 8.0 | 200ms 级构建，HMR < 500ms；原生 React 支持 |
| **TypeScript** | 6.x（现 Vite 默认）| strict mode；类型覆盖所有迁移代码 |
| **Tailwind CSS** | v4（`@tailwindcss/vite` 插件）| 原生 CSS vars + `@theme`；零配置文件 |
| **shadcn/ui 风格** | — | 组件源码进仓库，非运行时依赖 |
| **Radix UI** | 最新 | 底层 headless primitives；a11y 开箱 |
| **cmdk** | 最新 | ⌘K 命令面板 |
| **sonner** | 最新 | Toast 系统 |
| **lucide-react** | 最新 | 图标 |
| **class-variance-authority + tailwind-merge + clsx** | 最新 | 变体系统 |

### 2.2 不选的理由

- ~~Next.js / Remix~~：SSR 需 Node 服务端，和 Flask 架构冲突
- ~~MUI / Ant Design~~：运行时 CSS-in-JS，bundle 大且难深度改样式
- ~~Bulma / DaisyUI（纯 CSS）~~：无 JS 组件能力，复杂交互仍需手写
- ~~Web Components（Shoelace）~~：生态不如 React 丰富，未来扩展有限

## 3. 架构概览

```
┌─────────────── 浏览器 ───────────────┐
│                                        │
│  /login            /screener-v3        │
│  (Jinja HTML)      (Jinja + React)     │
│  简单表单            React root div     │
│  旧 style.css       + island JS bundle │
│                                        │
└─────────────────┬──────────────────────┘
                  │
                  ▼
┌─────────────── Flask :5000 ──────────────────┐
│                                              │
│  @app.route("/screener-v3")                  │
│  def screener_v3():                          │
│      return render_template(                 │
│        "islands/screener_v3.html",           │
│        manifest=load_vite_manifest(),        │
│      )                                       │
│                                              │
│  @app.route("/api/*") ...                    │
│  @socketio.on(...) ...                       │
│                                              │
└──────────────────────────────────────────────┘
                  │
                  ▼
┌─────────── Vite Build Output ──────────────┐
│                                            │
│  stock_trading_system/web/static/dist/     │
│    .vite/manifest.json  ← 入口清单          │
│    assets/screener-v3-[hash].js            │
│    assets/paper-trade-[hash].js            │
│    assets/dashboard-[hash].js              │
│    assets/tasks-[hash].js                  │
│    assets/vendor-[hash].js     ← 共享 chunk │
│    assets/ui-[hash].js         ← shadcn    │
│    assets/index-[hash].css                 │
│                                            │
└────────────────────────────────────────────┘
```

**关键设计**：
- **Flask 仍是路由总线**，每个 island 有独立 Flask 路由 + Jinja 模板壳
- Jinja 模板只负责 **注入正确的 hashed JS/CSS + meta 信息**（CSRF、user、provider）
- React 不做路由，岛屿间导航走 Flask `<a href>` 或 `window.location`
- 数据获取走 既有 `/api/*` REST + SocketIO（复用 [unified-progress](./unified-progress.md) 约束）

## 4. 目录结构

```
stock_trading_system/web/
├── templates/
│   ├── index.html                     # 旧 SPA 模板（保留，不动）
│   ├── layout.html (NEW)              # 共享 layout（nav + meta）
│   └── islands/                       # 新：每 island 的 Jinja 壳
│       ├── screener_v3.html
│       ├── paper_trade_detail.html
│       ├── dashboard.html
│       └── tasks.html
├── static/
│   ├── css/style.css                  # 保留，旧页面继续用
│   ├── js/app.js                      # 保留，旧页面继续用
│   └── dist/                          # Vite 产出（gitignored，CI 构建）
│       ├── .vite/manifest.json
│       └── assets/
└── frontend/                          # NEW：React 源码根目录
    ├── package.json
    ├── vite.config.ts
    ├── tsconfig.json
    ├── index.html                     # Vite dev 入口（仅 dev 用）
    └── src/
        ├── islands/                   # 每个 island 一个 entry
        │   ├── screener-v3/
        │   │   ├── main.tsx
        │   │   └── ScreenerV3Page.tsx
        │   ├── paper-trade/
        │   │   ├── main.tsx
        │   │   └── PaperTradePage.tsx
        │   ├── dashboard/
        │   │   ├── main.tsx
        │   │   └── DashboardPage.tsx
        │   └── tasks/
        │       ├── main.tsx
        │       └── TasksPage.tsx
        ├── components/
        │   ├── ui/                    # shadcn 原子组件（从 POC 迁入）
        │   │   ├── button.tsx
        │   │   ├── card.tsx
        │   │   ├── dialog.tsx
        │   │   ├── dropdown-menu.tsx
        │   │   ├── command.tsx
        │   │   ├── ...14 个
        │   └── shared/                # 业务组件
        │       ├── ProgressStream.tsx
        │       ├── GuruSelector.tsx
        │       ├── TierList.tsx
        │       └── ...
        ├── lib/
        │   ├── api.ts                 # fetch 封装 + CSRF + 错误处理
        │   ├── socket.ts              # SocketIO 封装 + catch-up
        │   ├── auth.ts                # current_user 读取
        │   ├── utils.ts               # cn() + formatters
        │   └── types.ts               # 共享 API 类型
        ├── data/
        │   └── gurus.ts               # 14 大师静态数据
        └── styles/
            └── index.css              # Tailwind v4 + design tokens
```

**保留不动**：`templates/index.html` / `static/css/style.css` / `static/js/app.js` —— 旧页面继续工作。

**新增**：`web/frontend/` 目录完全独立。

## 5. Vite ↔ Flask 协作管道

### 5.1 Dev 模式（开发时两个进程并行）

```
Terminal 1: cd stock_trading_system/web/frontend && npm run dev
            → Vite dev server on :5173

Terminal 2: flask --app stock_trading_system run
            → Flask on :5000
```

**Flask 端如何引用 Vite dev 资源**：

```python
# stock_trading_system/web/vite_helpers.py (NEW)
import os
import json
from pathlib import Path

VITE_DEV = os.environ.get("FLASK_ENV") == "development"
VITE_DEV_URL = "http://localhost:5173"
DIST_DIR = Path(__file__).parent / "static" / "dist"
MANIFEST_PATH = DIST_DIR / ".vite" / "manifest.json"


def vite_assets(entry: str) -> dict:
    """Return {'js': [...], 'css': [...]} URLs for a given entry.

    entry examples: 'src/islands/screener-v3/main.tsx'
    """
    if VITE_DEV:
        return {
            "js": [
                f"{VITE_DEV_URL}/@vite/client",
                f"{VITE_DEV_URL}/{entry}",
            ],
            "css": [],
            "dev": True,
        }

    # Prod: read manifest
    manifest = json.loads(MANIFEST_PATH.read_text())
    item = manifest[entry]
    result = {"js": [f"/static/dist/{item['file']}"], "css": [], "dev": False}
    for css in item.get("css", []):
        result["css"].append(f"/static/dist/{css}")
    # Imports (chunk split)
    for imp in item.get("imports", []):
        if imp in manifest:
            result["js"].insert(0, f"/static/dist/{manifest[imp]['file']}")
    return result
```

**Jinja 模板壳**（共用 `layout.html`）：

```jinja
{# stock_trading_system/web/templates/layout.html #}
<!doctype html>
<html lang="zh-CN" class="dark">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="csrf-token" content="{{ csrf_token() }}">
  <meta name="user-id" content="{{ g.user.id if g.user else '' }}">
  <meta name="user-display" content="{{ g.user.display_name if g.user else '' }}">
  <title>{% block title %}StockAI Terminal{% endblock %}</title>

  {# Vite dev client or prod CSS #}
  {% set assets = vite_assets(entry) %}
  {% for css in assets.css %}
    <link rel="stylesheet" href="{{ css }}">
  {% endfor %}
</head>
<body>
  <div id="react-root"></div>

  {% for js in assets.js %}
    <script type="module" src="{{ js }}"></script>
  {% endfor %}
</body>
</html>
```

**每 island 的模板**：

```jinja
{# stock_trading_system/web/templates/islands/screener_v3.html #}
{% extends "layout.html" %}
{% set entry = "src/islands/screener-v3/main.tsx" %}
{% block title %}智能选股 V3 · StockAI Terminal{% endblock %}
```

**React entry**：

```tsx
// stock_trading_system/web/frontend/src/islands/screener-v3/main.tsx
import { StrictMode } from "react"
import { createRoot } from "react-dom/client"
import "@/styles/index.css"
import { ScreenerV3Page } from "./ScreenerV3Page"

document.documentElement.classList.add("dark")

createRoot(document.getElementById("react-root")!).render(
  <StrictMode>
    <ScreenerV3Page />
  </StrictMode>,
)
```

### 5.2 Vite 配置（支持多 island）

```ts
// stock_trading_system/web/frontend/vite.config.ts
import path from "node:path"
import { defineConfig } from "vite"
import react from "@vitejs/plugin-react"
import tailwindcss from "@tailwindcss/vite"

const DIST = path.resolve(__dirname, "../static/dist")

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: { "@": path.resolve(__dirname, "./src") },
  },
  server: {
    port: 5173,
    strictPort: true,
    cors: true,
    origin: "http://localhost:5173",  // 让资源用绝对 URL
  },
  build: {
    outDir: DIST,
    emptyOutDir: true,
    manifest: true,                    // 产出 .vite/manifest.json
    rollupOptions: {
      input: {
        "screener-v3":  "src/islands/screener-v3/main.tsx",
        "paper-trade":  "src/islands/paper-trade/main.tsx",
        "dashboard":    "src/islands/dashboard/main.tsx",
        "tasks":        "src/islands/tasks/main.tsx",
      },
      output: {
        manualChunks: {
          "react-vendor": ["react", "react-dom"],
          "radix": [
            "@radix-ui/react-dialog",
            "@radix-ui/react-dropdown-menu",
            "@radix-ui/react-popover",
            "@radix-ui/react-select",
            "@radix-ui/react-tabs",
            "@radix-ui/react-tooltip",
            // ... 其他
          ],
          "ui": [/src\/components\/ui/],
        },
      },
    },
  },
})
```

**manual chunks 策略**：
- `react-vendor`（~40KB gzipped）—— react + react-dom，几乎不变
- `radix`（~30KB）—— 所有用到的 Radix primitives
- `ui`（~15KB）—— shadcn 组件层
- 每 island（~20-50KB）—— 自己的业务代码

4 岛同时加载的极端场景也 ≤ 160KB gzipped，单页 ≤ 130KB。符合 [PRD §6.1](../prd/ui-react-island.md#61-性能) 的 180KB 预算。

### 5.3 Prod 部署（Railway）

改 `Procfile`：

```
web: bash -lc "cd stock_trading_system/web/frontend && npm install && npm run build && cd /app && gunicorn ..."
```

或用 `railway.json`（推荐，已有）增加 build command：

```json
{
  "build": {
    "builder": "nixpacks",
    "buildCommand": "cd stock_trading_system/web/frontend && npm install && npm run build"
  },
  "deploy": {
    "startCommand": "gunicorn -k gevent -w 1 --timeout 120 stock_trading_system.web.app:create_app()"
  }
}
```

**Node 层加入 Nixpacks**：
- Railway nixpacks 默认检测 python。需要在 repo 根加 `.nixpacks/environment.toml`：

```toml
[phases.setup]
nixPkgs = ["python311", "nodejs-18_x", "npm"]
```

### 5.4 部署体积

| 产物 | 预估 |
|---|---|
| `static/dist/` 总体积 | ~600KB 未压缩（~180KB gzipped） |
| 4 个 manifest entry | 每 entry ~50-150KB |
| Railway build 新增时间 | +30-60s（npm install 缓存后） |

## 6. 共享基础设施

### 6.1 `lib/api.ts` —— fetch 封装

```ts
// frontend/src/lib/api.ts

const CSRF = () =>
  document.querySelector<HTMLMetaElement>('meta[name="csrf-token"]')?.content ?? ""

export interface ApiOptions extends RequestInit {
  json?: unknown
}

export class ApiError extends Error {
  constructor(public status: number, public body: unknown, message: string) {
    super(message)
  }
}

export async function api<T>(path: string, opts: ApiOptions = {}): Promise<T> {
  const { json, headers, ...rest } = opts
  const init: RequestInit = {
    credentials: "same-origin",
    headers: {
      "Accept": "application/json",
      ...(json !== undefined ? { "Content-Type": "application/json" } : {}),
      ...(rest.method && rest.method !== "GET" ? { "X-CSRFToken": CSRF() } : {}),
      ...(headers as Record<string, string>),
    },
    ...(json !== undefined ? { body: JSON.stringify(json) } : {}),
    ...rest,
  }
  const res = await fetch(path, init)
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new ApiError(res.status, body, body.message ?? res.statusText)
  }
  return res.json()
}

// 语法糖
export const apiGet  = <T>(path: string, opts?: ApiOptions) => api<T>(path, { ...opts, method: "GET" })
export const apiPost = <T>(path: string, json?: unknown, opts?: ApiOptions) => api<T>(path, { ...opts, method: "POST", json })
export const apiDel  = <T>(path: string, opts?: ApiOptions) => api<T>(path, { ...opts, method: "DELETE" })
```

### 6.2 `lib/socket.ts` —— SocketIO 封装

遵循 [unified-progress §4](./unified-progress.md#4-后端改造5-步) 的 envelope schema：

```ts
// frontend/src/lib/socket.ts
import { io, Socket } from "socket.io-client"

let socketInstance: Socket | null = null

export interface TaskEventEnvelope<P = unknown> {
  task_id: string
  user_id: number
  seq: number
  event: string
  payload: P
  emitted_at: string
}

export function getSocket(): Socket {
  if (!socketInstance) {
    socketInstance = io({ transports: ["websocket", "polling"] })
  }
  return socketInstance
}

export interface StreamOptions {
  taskIds: string[]
  onEvent: (env: TaskEventEnvelope) => void
  onStatusChange?: (s: "connecting" | "streaming" | "disconnected") => void
}

export function subscribeTaskStream(opts: StreamOptions) {
  const s = getSocket()
  const taskIds = new Set(opts.taskIds)
  const lastSeq = new Map<string, number>()

  const applyEnvelope = (env: TaskEventEnvelope) => {
    if (!taskIds.has(env.task_id)) return
    const last = lastSeq.get(env.task_id) ?? 0
    if (env.seq <= last) return
    lastSeq.set(env.task_id, env.seq)
    opts.onEvent(env)
  }

  const onConnect = async () => {
    opts.onStatusChange?.("streaming")
    // Catch-up per task (unified-progress §4.4)
    for (const tid of taskIds) {
      const since = lastSeq.get(tid) ?? 0
      const events = await fetch(`/api/tasks/events?task_id=${tid}&since=${since}`)
        .then(r => r.json()) as TaskEventEnvelope[]
      events.forEach(applyEnvelope)
    }
  }

  s.on("connect", onConnect)
  s.on("disconnect", () => opts.onStatusChange?.("disconnected"))
  s.onAny((event, env) => applyEnvelope({ ...env, event }))

  if (s.connected) onConnect()
  else opts.onStatusChange?.("connecting")

  return {
    subscribe:   (id: string) => { taskIds.add(id); onConnect() },
    unsubscribe: (id: string) => { taskIds.delete(id); lastSeq.delete(id) },
    destroy:     () => { s.off("connect", onConnect) },
  }
}
```

### 6.3 `lib/auth.ts` —— 当前用户

```ts
// frontend/src/lib/auth.ts
export interface CurrentUser {
  id: number
  displayName: string
}

export function getCurrentUser(): CurrentUser | null {
  const id = document.querySelector<HTMLMetaElement>('meta[name="user-id"]')?.content
  const displayName = document.querySelector<HTMLMetaElement>('meta[name="user-display"]')?.content
  if (!id || !displayName) return null
  return { id: parseInt(id, 10), displayName }
}
```

### 6.4 ProgressStream 组件（承接 [unified-progress](./unified-progress.md)）

```tsx
// frontend/src/components/shared/ProgressStream.tsx
import { useEffect, useState } from "react"
import { subscribeTaskStream, TaskEventEnvelope } from "@/lib/socket"
// ...

interface Props {
  taskIds: string[]
  layout: "compact" | "detail" | "inline-badge"
  onComplete?: (taskId: string) => void
}

export function ProgressStream({ taskIds, layout, onComplete }: Props) {
  const [events, setEvents] = useState<TaskEventEnvelope[]>([])
  const [status, setStatus] = useState<"connecting"|"streaming"|"disconnected">("connecting")

  useEffect(() => {
    const sub = subscribeTaskStream({
      taskIds,
      onEvent: (env) => {
        setEvents(prev => [...prev, env])
        if (env.event === "task_completed") onComplete?.(env.task_id)
      },
      onStatusChange: setStatus,
    })
    return () => sub.destroy()
  }, [taskIds.join(",")])

  // 三种布局渲染：compact | detail | inline-badge
  return <ProgressStreamView layout={layout} events={events} status={status} />
}
```

**对齐** [unified-progress §5](./unified-progress.md#5-前端改造) 的 React 实现。

## 7. 4 岛屿实施细节

### 7.1 `/screener-v3` Island

**Flask 路由**：

```python
# stock_trading_system/web/app.py
@app.route("/screener-v3")
@login_required
def screener_v3_page():
    return render_template("islands/screener_v3.html")
```

**React 组件**（移植 POC `ScreenerV3Demo.tsx`）：

```tsx
// islands/screener-v3/ScreenerV3Page.tsx
import { useEffect, useState } from "react"
import { apiGet, apiPost } from "@/lib/api"
import { GuruSelector } from "@/components/shared/GuruSelector"
// ...

export function ScreenerV3Page() {
  const [gurus, setGurus] = useState<Guru[]>([])
  const [selected, setSelected] = useState<Set<string>>(new Set(["buffett","graham","munger","lynch"]))
  const [mode, setMode] = useState<Mode>("agent")
  const [candidateN, setCandidateN] = useState(20)
  const [nl, setNl] = useState("")
  const [estimate, setEstimate] = useState<Estimate | null>(null)

  // 拉大师列表（来自 /api/screen/v3/gurus）
  useEffect(() => {
    apiGet<Guru[]>("/api/screen/v3/gurus").then(setGurus)
  }, [])

  // debounce 预估
  useEffect(() => {
    const t = setTimeout(async () => {
      if (mode === "classic") { setEstimate(null); return }
      const est = await apiPost<Estimate>("/api/screen/v3/estimate", {
        nl_query: nl, market: "US", candidate_n: candidateN,
        gurus: [...selected], mode, with_roundtable: mode === "agent_rt",
      })
      setEstimate(est)
    }, 500)
    return () => clearTimeout(t)
  }, [nl, candidateN, selected.size, mode])

  const onStart = async () => {
    const { task_id } = await apiPost<{ task_id: string }>("/api/screen/v3/trigger", {
      nl_query: nl, market: "US", candidate_n: candidateN,
      gurus: [...selected], mode, with_roundtable: mode === "agent_rt",
    })
    window.location.href = `/tasks/${task_id}`
  }

  return (
    <AppShell>
      {/* 完整 UI 照搬 POC ScreenerV3Demo 结构 */}
    </AppShell>
  )
}
```

**工作量**：复用 POC 90% 代码 + 接 API = ~6h

### 7.2 `/tasks` Island（集成 unified-progress）

**Flask 路由**：

```python
@app.route("/tasks")
@login_required
def tasks_page():
    return render_template("islands/tasks.html")

@app.route("/tasks/<task_id>")
@login_required
def task_detail_page(task_id):
    return render_template("islands/tasks.html")  # 同一 entry，内部根据 URL 判断
```

**React 组件**：

```tsx
// islands/tasks/TasksPage.tsx
import { useEffect, useState } from "react"
import { apiGet } from "@/lib/api"
import { ProgressStream } from "@/components/shared/ProgressStream"
// ...

export function TasksPage() {
  const taskId = window.location.pathname.split("/")[2] // /tasks/<id>
  const [tasks, setTasks] = useState<Task[]>([])
  const [scope, setScope] = useState<"my"|"all">("my")

  useEffect(() => {
    apiGet<Task[]>(`/api/tasks?scope=${scope}`).then(setTasks)
  }, [scope])

  if (taskId) {
    return <TaskDetail taskId={taskId} />
  }

  return (
    <AppShell>
      <Tabs value={scope} onValueChange={v => setScope(v as any)}>
        <TabsList>
          <TabsTrigger value="my">我的任务</TabsTrigger>
          <TabsTrigger value="all">全部任务</TabsTrigger>
        </TabsList>
        <TabsContent value={scope}>
          <TaskList tasks={tasks} />
        </TabsContent>
      </Tabs>
    </AppShell>
  )
}

function TaskDetail({ taskId }: { taskId: string }) {
  return (
    <AppShell>
      <ProgressStream
        taskIds={[taskId]}
        layout="detail"
        onComplete={() => { /* navigate to result */ }}
      />
    </AppShell>
  )
}
```

### 7.3 `/paper-trade/<ticker>` Island

复用 POC `PaperTradeDemo.tsx` + 接入真实 API（`GET /api/paper/tickers/<ticker>`）。移动端响应式已在 POC 修复。

### 7.4 `/dashboard` Island

复用 POC `DashboardDemo.tsx` + 接入 `/api/dashboard` 聚合接口（新增）。

## 8. 样式对齐

### 8.1 Tailwind v4 tokens

`frontend/src/styles/index.css` 已在 POC 完成（见 POC README）。

**关键一致性**：所有 `@theme` 里定义的 CSS vars 名称与 [mobile-optimization.md](./mobile-optimization.md) §2 完全一致：
- `--color-bg-primary` / `--color-bg-card`
- `--color-accent-blue` / `--color-accent-green` / `--color-accent-red`
- `--text-xs` → `--text-2xl`（clamp 响应式）
- `--radius-sm` → `--radius-xl`

旧 `style.css` 的 `:root { --color-*: ... }` 保持不变。新 Tailwind token 覆盖同名 CSS var。

### 8.2 作用域隔离

- React island 的 root 元素加 `data-ri-root` 属性（可选）
- 旧 `style.css` 的全局 reset 影响 island 内的元素 → Tailwind 的 `@tailwind base` 处理
- 测试：非迁移页视觉 pixel-match baseline（TC-UI-R1~R4）

### 8.3 Bootstrap 5 隔离

- React island **不引用** `bootstrap.min.css` / `bootstrap.bundle.min.js`
- 旧页面保留 Bootstrap（通过 index.html 的 `<link>`）
- layout.html 按需引入（islands 不 extends old index.html）

## 9. 开发工作流

```
# 一次性 setup
cd stock_trading_system/web/frontend
npm install

# 日常开发（两个 terminal）
# T1: Vite dev
cd stock_trading_system/web/frontend && npm run dev

# T2: Flask
export FLASK_ENV=development
flask --app stock_trading_system run --reload

# 访问 http://localhost:5000/screener-v3
# React 代码改动 → Vite HMR 推送 → 浏览器自动刷新
# Flask 代码改动 → Flask reloader → 浏览器手动刷新
```

## 10. 实施计划

### Phase 1 —— 构建管道（~4h）
- 建 `web/frontend/` 目录，`npm init` + Vite + React + Tailwind v4
- 配 `vite.config.ts`（多 entry + manualChunks）
- 写 `vite_helpers.py` + `layout.html` + 第一个空 island 模板
- 验证 Dev / Prod 双模式都能加载一个 Hello World island
- 更新 Procfile + nixpacks 配置

### Phase 2 —— 共享基础设施（~3h）
- 从 POC copy `src/components/ui/` 全部 14 组件
- 新建 `lib/api.ts` / `lib/socket.ts` / `lib/auth.ts` / `lib/utils.ts`
- 新建 `components/shared/ProgressStream.tsx`
- 从 POC copy `data/gurus.ts`
- 单测覆盖 `lib/*`

### Phase 3 —— Screener V3 island（~6h）
- 建 `islands/screener-v3/main.tsx` + `ScreenerV3Page.tsx`
- 复用 POC `ScreenerV3Demo` 结构
- 接 `/api/screen/v3/{gurus,estimate,trigger}` 三个现有 API
- Flask 路由 + 模板
- E2E：输入 NL → 选大师 → 预估 → 触发 → 跳 tasks
- **交付给用户：screener-v3 UI 可用（PRD §US-UI-1）**

### Phase 4 —— Tasks island（~4h）
- 建 `islands/tasks/main.tsx`
- `ProgressStream` 集成
- 列表页 + 详情页（同一 entry，路由内判）
- 与 Phase 3 联动：screener-v3 触发后跳进来

### Phase 5 —— Paper-trade detail island（~5h）
- 移植 POC `PaperTradeDemo`
- 接 `/api/paper/tickers/<ticker>`
- 解决 [paper-trade v1.3 F4 图表 + F5 tabs 合并](./paper-trade.md#二十七v13-修订2026-04-19)（React 版）
- Flask 路由 + 模板

### Phase 6 —— Dashboard island（~4h）
- 移植 POC `DashboardDemo`
- 新增 `/api/dashboard` 聚合端点（返回 stats + insights + running tasks + holdings overview）
- 旧 `/dashboard` Jinja 视图替换

### Phase 7 —— 收尾 + 验收（~2h）
- Playwright E2E 跑 PRD 6 个 US
- 桌面视觉回归（非迁移页 pixel-match）
- Lighthouse 移动端性能
- Railway 部署验证
- 更新 3 个 changelog + 主文档

**总计 ~28h**。

## 11. 复用 / Reuse

遵循 [engineering-principles.md](../engineering-principles.md) L0→L4：

### L0 项目内复用

- **全部既有 API**（`/api/screen/v3/*`, `/api/tasks/*`, `/api/paper/tickers/*`）—— 0 改动
- **Flask 外壳 + 路由系统** —— 保留，只加 4 个新路由
- **SocketIO 服务器** —— 复用（[unified-progress](./unified-progress.md) 约束）
- **CSRF token + session cookie** —— React fetch 继承
- **`style.css` CSS vars** —— Tailwind v4 `@theme` 复用同名变量
- **POC `/tmp/stock-ui-demo/` 的所有代码** —— 大部分可直接迁到 `web/frontend/`

### L1 依赖库

| 库 | 替代 |
|---|---|
| React 19 | 自写 vanilla render |
| Vite 8 | webpack / rollup 手搓 |
| Tailwind CSS v4 | 自写 CSS 工具类 |
| shadcn/ui 风格 | 自写组件（非运行时依赖，**代码进仓库**）|
| Radix UI 原语 | 自写 Dialog / Dropdown / Popover（a11y 复杂）|
| cmdk | 自写命令面板 |
| sonner | 自写 Toast 队列 |
| lucide-react | 自找图标 |
| class-variance-authority + tailwind-merge | 自写变体系统 |
| socket.io-client | 裸 WebSocket 自己管重连 |

### L2 思路参考

- [shadcn/ui 官方组件源码](https://ui.shadcn.com/docs/components)：**直接 copy** 样式（MIT license 允许）
- [Vite + Flask 社区方案](https://nickjanetakis.com/blog/using-vite-with-flask)：manifest.json 读取模式
- POC `/tmp/stock-ui-demo/` 自己做的 4 个 demo 页：迁移时 copy 90% 代码

### L3 Clean-room

无。

### L4 自写（业务特定）

| 模块 | 预估 LOC |
|---|---|
| Flask `vite_helpers.py` | ~40 |
| 4 个 island entry（main.tsx 各一）| ~80 |
| 4 个 island 页面组件（接 API + 状态管理）| ~800 |
| `lib/api.ts` / `lib/socket.ts` / `lib/auth.ts` | ~150 |
| 业务组件（GuruSelector 等）| ~300 |
| **总计新写** | **~1400 LOC** |
| **shadcn copy** | **~1200 LOC** |
| **POC 迁入** | **~1000 LOC** |

复用比例：**~60%**（shadcn copy + POC 迁入）。

## 12. 兼容性 & 回滚

### 12.1 向后兼容

- 任一 island 失败 → Flask 路由注释切回 `render_template("index.html")`
- 旧页面功能 100% 保留
- API 契约不变，旧 JS 和新 React 可并存访问

### 12.2 数据库 / 后端
- 0 改动

### 12.3 回滚步骤

1. 停服
2. `git revert` feature commits
3. 删除 `static/dist/`
4. 恢复 Procfile / railway.json
5. 重启

## 13. 风险缓解

| 风险 | 缓解 |
|---|---|
| Railway Nixpacks 不装 node | `.nixpacks/environment.toml` 显式加 nodejs-18_x |
| Vite prod build 生成的 hash 文件名与 Flask static 不配合 | `vite_helpers.py` 读 manifest 自动处理 |
| SocketIO 在 React StrictMode 下双连接 | `getSocket()` 单例 + effect cleanup |
| Tailwind v4 与 `style.css` CSS vars 冲突 | v4 `@theme` 覆盖同名，测试保证非迁移页 pixel-match |
| CSRF token 在 fetch 中遗漏 | `src/lib/api.ts` 强制注入，禁用裸 fetch |
| React island 间共享状态（如登录态）不一致 | 每 island 从 meta 读，不共享运行时状态 |
| 移动端 iOS Safari bundle loading 慢 | manualChunks + 首屏 ≤ 180KB gzipped |
| HMR 在 Flask template 里 `{{ csrf_token() }}` 刷新后失效 | HMR 只影响 JS，session 刷新走 Flask 正常路径 |

## 14. 与其他模块的集成

| 模块 | 集成点 |
|---|---|
| [screener-v3](./screener-v3.md) | 本方案 Phase 3 完成 PRD 未完成的 Phase 6 UI 部分 |
| [paper-trade v1.3](./paper-trade.md) | 本方案 Phase 5 完成 F4 图表 + F5 tab 合并的 React 实现 |
| [unified-progress](./unified-progress.md) | `ProgressStream` 统一 React 组件 |
| [mobile-optimization](./mobile-optimization.md) | Tailwind v4 tokens 对齐；移动端 375 / 768 断点复用 |
| [multi-tenant](./multi-tenant.md) | `g.user` 通过 `<meta>` 注入 + CSRF 无缝复用 |
| [model-switch](./model-switch.md) | 顶栏 provider dropdown **v1.1 可迁** 到 React，v1.0 保留 Jinja |

## 15. 版本历史

| 版本 | 日期 | 变更 |
|---|---|---|
| v1.0 | 2026-04-21 | 初版：Vite + Flask 协作管道 + manifest.json 驱动 + 4 岛屿首批迁移（screener-v3 / tasks / paper-trade / dashboard）+ 7 Phase 实施计划 + shadcn 组件库从 POC 迁入 + `lib/api.ts` / `lib/socket.ts` / `ProgressStream` 共享基础设施 + Railway 部署适配 |
