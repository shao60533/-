import { MobileTabbar, Sidebar } from "./Sidebar"
import { MobileTopbar } from "./MobileTopbar"
import { OnboardingChecklist, TASKS } from "./onboarding/OnboardingChecklist"
import { useOnboardingState } from "./onboarding/useOnboardingState"
import { useOnboardingTour } from "./onboarding/useOnboardingTour"
import { WelcomeModal } from "./onboarding/WelcomeModal"

export function AppShell({
  children,
  pageTitle,
}: {
  children: React.ReactNode
  pageTitle?: string
}) {
  const { state, markWelcomed, dismissChecklist } = useOnboardingState()
  const { start: startTour } = useOnboardingTour()

  const showWelcome = !!(state && state.welcome_pending && !state.welcomed)
  const completedCount = state
    ? TASKS.filter((t) => state.steps_completed[t.id]).length
    : 0
  const showChecklist = !!(
    state &&
    state.welcomed &&
    !state.checklist_dismissed &&
    completedCount < TASKS.length
  )

  return (
    <div className="flex min-h-screen bg-background">
      <Sidebar />
      <div className="flex flex-1 min-w-0 flex-col">
        <MobileTopbar pageTitle={pageTitle} />
        <main className="flex-1 min-w-0 pb-16 md:pb-0">{children}</main>
      </div>
      <MobileTabbar />

      <WelcomeModal
        open={showWelcome}
        onSkip={() => markWelcomed(false)}
        onStartTour={() => {
          // Flip welcomed=1 BEFORE the tour starts so a hard reload mid-tour
          // doesn't re-trigger the modal. Tour completion (any termination)
          // then flips tour_completed=1 via the onDone callback.
          markWelcomed(false)
          startTour({ onDone: () => markWelcomed(true) })
        }}
      />
      {showChecklist && state && (
        <OnboardingChecklist
          stepsCompleted={state.steps_completed}
          onDismiss={dismissChecklist}
        />
      )}
    </div>
  )
}
