/**
 * useOnboardingTour — thin wrapper around Driver.js bound to TOUR_STEPS.
 *
 * Spec: docs/design/onboarding.md §4.5.
 *
 * The Driver.js CSS is imported globally from styles/index.css so we
 * don't have to import it here (avoids duplicate stylesheet inclusion).
 * The onDestroyed callback fires whether the user clicked × / pressed
 * Escape / finished the tour — that's the universal "tour is done" hook
 * we need to write `tour_completed=1` from AppShell.
 */
import { driver } from "driver.js"
import { useCallback } from "react"

import { TOUR_STEPS } from "./tour-steps"

export interface TourStartOptions {
  onDone: () => void
}

export interface UseOnboardingTour {
  start: (opts: TourStartOptions) => void
}

export function useOnboardingTour(): UseOnboardingTour {
  const start = useCallback(({ onDone }: TourStartOptions) => {
    const instance = driver({
      showProgress: true,
      progressText: "{{current}} / {{total}}",
      nextBtnText: "下一步 →",
      prevBtnText: "← 上一步",
      doneBtnText: "完成 ✓",
      allowClose: true,
      smoothScroll: true,
      stagePadding: 6,
      stageRadius: 10,
      steps: [...TOUR_STEPS],
      onDestroyed: () => onDone(),
    })
    instance.drive()
  }, [])

  return { start }
}
