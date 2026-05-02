import path from "node:path"
import { defineConfig } from "vite"
import react from "@vitejs/plugin-react"
import tailwindcss from "@tailwindcss/vite"

const DIST = path.resolve(__dirname, "../static/dist")

export default defineConfig({
  plugins: [react(), tailwindcss()],
  // Production assets are served by Flask under ``/static/dist/`` (see
  // ``stock_trading_system/web/vite_helpers.py`` which prepends that
  // prefix to every manifest entry). Vite's runtime ``__vitePreload``
  // helper, however, only knows about ``base`` — without this setting
  // it builds dynamic-chunk URLs as ``/assets/foo.js`` (defaulting to
  // ``/``), which 404s in production and surfaces as
  // ``Unable to preload CSS for /assets/card-*.css``. The browser
  // throws inside the dynamic import, the per-tab ErrorBoundary catches
  // it and shows the "结构化摘要暂不可用" fallback — even though the
  // structured data itself is fine.
  //
  // Aligning ``base`` with Flask's mount makes the static (HTML <link>)
  // and dynamic (JS preload helper) paths agree. ``vite_helpers.py``
  // still works because Vite's manifest emits paths relative to
  // ``outDir`` (``"assets/foo.js"``) regardless of ``base`` — only the
  // bundled runtime helper is affected.
  base: "/static/dist/",
  resolve: {
    alias: { "@": path.resolve(__dirname, "./src") },
  },
  server: {
    port: 5173,
    strictPort: true,
    cors: true,
    origin: "http://localhost:5173",
  },
  build: {
    outDir: DIST,
    emptyOutDir: true,
    manifest: true,
    rollupOptions: {
      input: {
        "screener-v3": "src/islands/screener-v3/main.tsx",
        "paper-trade": "src/islands/paper-trade/main.tsx",
        "paper-trade-list": "src/islands/paper-trade-list/main.tsx",
        "dashboard":   "src/islands/dashboard/main.tsx",
        "tasks":       "src/islands/tasks/main.tsx",
        "portfolio":   "src/islands/portfolio/main.tsx",
        "history":     "src/islands/history/main.tsx",
        "alerts":      "src/islands/alerts/main.tsx",
        "analysis":    "src/islands/analysis/main.tsx",
        "backtest":    "src/islands/backtest/main.tsx",
        "reports":     "src/islands/reports/main.tsx",
        "settings":    "src/islands/settings/main.tsx",
      },
      output: {
        manualChunks: {
          "react-vendor": [
            "react",
            "react/jsx-runtime",
            "react-dom",
            "react-dom/client",
            "scheduler",
          ],
          "icons-vendor": ["lucide-react"],
          "echarts-vendor": ["echarts/core", "echarts/charts", "echarts/components", "echarts/renderers"],
        },
      },
    },
  },
})
