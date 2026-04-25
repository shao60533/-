/**
 * API fetch wrapper — all requests go through here.
 * Enforces CSRF token + credentials (same-origin cookies).
 */

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
      Accept: "application/json",
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
    throw new ApiError(res.status, body, (body as any).message ?? res.statusText)
  }
  return res.json()
}

export const apiGet = <T>(path: string, opts?: ApiOptions) =>
  api<T>(path, { ...opts, method: "GET" })

export const apiPost = <T>(path: string, json?: unknown, opts?: ApiOptions) =>
  api<T>(path, { ...opts, method: "POST", json })

export const apiDel = <T>(path: string, opts?: ApiOptions) =>
  api<T>(path, { ...opts, method: "DELETE" })
