/**
 * Onboarding state hook — talks to /api/onboarding/* + caches state in
 * React state. Single source of truth for the welcome modal, checklist,
 * and tour completion flags.
 *
 * Spec: docs/design/onboarding.md §4.2.
 */
import { useCallback, useEffect, useState } from "react"

import { apiGet, apiPost } from "@/lib/api"

export interface OnboardingState {
  welcome_pending: boolean
  welcomed: boolean
  tour_completed: boolean
  checklist_dismissed: boolean
  steps_completed: Record<string, boolean>
}

export interface UseOnboardingState {
  state: OnboardingState | null
  loading: boolean
  refresh: () => Promise<void>
  markWelcomed: (tourCompleted?: boolean) => Promise<void>
  dismissChecklist: () => Promise<void>
  reset: () => Promise<void>
}

export function useOnboardingState(): UseOnboardingState {
  const [state, setState] = useState<OnboardingState | null>(null)
  const [loading, setLoading] = useState<boolean>(true)

  const refresh = useCallback(async () => {
    try {
      const data = await apiGet<OnboardingState>("/api/onboarding/state")
      setState(data)
    } catch {
      // Silent: API failures (401 on logged-out pages, transient network)
      // must NEVER block render. The consumer reads state===null and
      // simply renders no onboarding UI.
      setState(null)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    refresh()
  }, [refresh])

  const markWelcomed = useCallback(
    async (tourCompleted = false) => {
      try {
        await apiPost("/api/onboarding/mark-welcomed", {
          tour_completed: tourCompleted,
        })
      } catch {
        // fail-soft — fall through to refresh which will re-fetch the
        // ground-truth state from the server.
      }
      await refresh()
    },
    [refresh],
  )

  const dismissChecklist = useCallback(async () => {
    try {
      await apiPost("/api/onboarding/dismiss-checklist", {})
    } catch {
      // fail-soft
    }
    await refresh()
  }, [refresh])

  const reset = useCallback(async () => {
    try {
      await apiPost("/api/onboarding/reset", {})
    } catch {
      // fail-soft
    }
    await refresh()
  }, [refresh])

  return { state, loading, refresh, markWelcomed, dismissChecklist, reset }
}
