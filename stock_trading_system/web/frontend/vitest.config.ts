/// <reference types="vitest" />
import path from "node:path"
import { defineConfig } from "vitest/config"
import react from "@vitejs/plugin-react"

/**
 * Vitest config used only for runtime smoke tests of the structured
 * analysis cards (and friends). Kept separate from ``vite.config.ts``
 * so the production build does NOT pick up jsdom / testing-library —
 * those would balloon the bundle.
 */
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: { "@": path.resolve(__dirname, "./src") },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    include: ["src/**/*.test.ts", "src/**/*.test.tsx"],
    css: false,
  },
})
