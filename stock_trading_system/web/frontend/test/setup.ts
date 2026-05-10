import "@testing-library/jest-dom/vitest"
import { afterEach } from "vitest"
import { cleanup } from "@testing-library/react"

// Reset jsdom between tests so leaked DOM state from a prior render
// can't bleed into a fresh component mount. Without this, queries like
// screen.getByText would match stale nodes from the previous test.
afterEach(() => {
  cleanup()
})

// Polyfills for components that touch APIs jsdom doesn't ship.
if (typeof globalThis.matchMedia === "undefined") {
  globalThis.matchMedia = ((query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addEventListener: () => undefined,
    removeEventListener: () => undefined,
    addListener: () => undefined,
    removeListener: () => undefined,
    dispatchEvent: () => false,
  })) as unknown as typeof window.matchMedia
}

// jsdom does not implement ResizeObserver — many radix-ui primitives
// instantiate it on mount. A no-op stub keeps the render tree alive.
if (typeof globalThis.ResizeObserver === "undefined") {
  globalThis.ResizeObserver = class {
    observe() { /* noop */ }
    unobserve() { /* noop */ }
    disconnect() { /* noop */ }
  } as unknown as typeof ResizeObserver
}
