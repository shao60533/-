import { Sidebar, MobileTabbar } from "./Sidebar"
import { MobileTopbar } from "./MobileTopbar"

export function AppShell({
  children,
  pageTitle,
}: {
  children: React.ReactNode
  pageTitle?: string
}) {
  return (
    <div className="flex min-h-screen bg-background">
      <Sidebar />
      <div className="flex flex-1 min-w-0 flex-col">
        <MobileTopbar pageTitle={pageTitle} />
        <main className="flex-1 min-w-0 pb-16 md:pb-0">
          {children}
        </main>
      </div>
      <MobileTabbar />
    </div>
  )
}
