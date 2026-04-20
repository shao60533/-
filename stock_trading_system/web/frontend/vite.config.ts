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
        "dashboard":   "src/islands/dashboard/main.tsx",
        "tasks":       "src/islands/tasks/main.tsx",
      },
      output: {
        manualChunks: {
          "react-vendor": ["react", "react-dom"],
        },
      },
    },
  },
})
