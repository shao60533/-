import { Sidebar, MobileTabbar } from "./Sidebar"

export function AppShell({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex min-h-screen bg-background">
      <Sidebar />
      <main
        className="flex-1 min-w-0"
        style={{ paddingBottom: "var(--mobile-tabbar-height)" }}
      >
        {children}
      </main>
      <MobileTabbar />
    </div>
  )
}
