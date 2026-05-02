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
          "react-vendor": ["react", "react-dom"],
          "icons-vendor": ["lucide-react"],
          "echarts-vendor": ["echarts/core", "echarts/charts", "echarts/components", "echarts/renderers"],
        },
      },
    },
  },
})
