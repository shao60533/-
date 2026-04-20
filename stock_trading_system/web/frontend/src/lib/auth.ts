/**
 * Current user from <meta> tags injected by layout.html.
 */

export interface CurrentUser {
  id: number
  displayName: string
  role: string
}

export function getCurrentUser(): CurrentUser | null {
  const id = document.querySelector<HTMLMetaElement>('meta[name="user-id"]')?.content
  const displayName = document.querySelector<HTMLMetaElement>('meta[name="user-display"]')?.content
  const role = document.querySelector<HTMLMetaElement>('meta[name="user-role"]')?.content
  if (!id || !displayName) return null
  return { id: parseInt(id, 10), displayName, role: role ?? "user" }
}
