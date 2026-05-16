const CSRF = () =>
  document.querySelector<HTMLMetaElement>('meta[name="csrf-token"]')?.content ?? ""

type PerfFields = Record<string, string | number | boolean | null | undefined>

const DASHBOARD_BOOT_API =
  /^\/api\/(?:dashboard|tasks\b|portfolio\/(?:allocation|transactions|summary)\b)/

let flushTimer: number | null = null
const queue: { name: string; fields: PerfFields }[] = []

function canUseBrowserPerf() {
  return typeof window !== "undefined" && typeof performance !== "undefined"
}

export function perfNow(): number {
  return canUseBrowserPerf() ? performance.now() : Date.now()
}

function shouldReportApi(path: string, elapsedMs: number): boolean {
  return DASHBOARD_BOOT_API.test(path) || elapsedMs >= 800
}

function enqueue(name: string, fields: PerfFields = {}) {
  if (typeof window === "undefined") return
  queue.push({ name, fields })
  if (flushTimer != null) return
  flushTimer = window.setTimeout(flushPerfEvents, 250)
}

export function recordPerfEvent(name: string, fields: PerfFields = {}) {
  const cleanFields: PerfFields = {}
  for (const [key, value] of Object.entries(fields)) {
    if (
      value == null
      || typeof value === "string"
      || typeof value === "number"
      || typeof value === "boolean"
    ) {
      cleanFields[key] = value
    }
  }
  if (typeof console !== "undefined") {
    console.info("[perf]", name, cleanFields)
  }
  enqueue(name, cleanFields)
}

export function recordApiTiming(
  path: string,
  method: string,
  elapsedMs: number,
  status: number,
  ok: boolean,
) {
  if (!shouldReportApi(path, elapsedMs)) return
  recordPerfEvent("api.request", {
    path,
    method,
    elapsed_ms: Math.round(elapsedMs),
    status,
    ok,
  })
}

export function flushPerfEvents() {
  if (flushTimer != null) {
    window.clearTimeout(flushTimer)
    flushTimer = null
  }
  if (queue.length === 0) return
  const events = queue.splice(0, 20)
  const body = JSON.stringify({ events })
  fetch("/api/perf/client", {
    method: "POST",
    credentials: "same-origin",
    keepalive: body.length < 60_000,
    headers: {
      "Content-Type": "application/json",
      "X-CSRFToken": CSRF(),
    },
    body,
  }).catch(() => {
    // Performance telemetry must never affect the product flow.
  })
}
