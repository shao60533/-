/**
 * Vitest setup — registers ``@testing-library/jest-dom`` matchers
 * (``toHaveTextContent``, ``toBeInTheDocument`` etc.) globally and
 * tears down the JSDOM document between tests.
 */
import "@testing-library/jest-dom/vitest"
import { afterEach } from "vitest"
import { cleanup } from "@testing-library/react"

afterEach(() => {
  cleanup()
})
