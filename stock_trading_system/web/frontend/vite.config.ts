/// <reference types="vitest" />
import path from "node:path"
import { defineConfig } from "vite"
import react from "@vitejs/plugin-react"
import tailwindcss from "@tailwindcss/vite"

const DIST = path.resolve(__dirname, "../static/dist")

export default defineConfig({
  // analysis-rendering v1.5 (2026-05-03, restored on main 2026-05-07):
  // Flask serves built assets from /static/dist/, but Vite's runtime
  // ``__vitePreload`` helper bakes ``base`` into ``return base + i`` so
  // it can resolve dynamic CSS/JS chunk URLs at lazy-import time.
  // Without ``base``, the helper hardcodes ``/`` and lazy-loaded
  // ``AnalysisCards`` chunks request ``/assets/card-*.css`` which 404s
  // → ErrorBoundary fallback → "结构化摘要暂不可用". Setting it to
  // ``/static/dist/`` makes the helper emit ``/static/dist/assets/...``
  // matching the Flask static mount. The regression is locked by
  // ``tests/web/test_vite_asset_base.py``.
  base: "/static/dist/",
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: { "@": path.resolve(__dirname, "./src") },
  },
  server: {
    port: 5173,
    strictPort: true,
    cors: true,
    origin: "http://localhost:5173",
  },
  test: {
    globals: true,
    environment: "jsdom",
    setupFiles: ["./test/setup.ts"],
    css: true,
    include: ["src/**/*.{test,spec}.{ts,tsx}"],
    exclude: ["e2e/**", "node_modules/**", "../static/dist/**"],
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
          "react-vendor": ["react", "react-dom"],
          "icons-vendor": ["lucide-react"],
          "echarts-vendor": ["echarts/core", "echarts/charts", "echarts/components", "echarts/renderers"],
        },
      },
    },
  },
})
