import { StrictMode } from "react"
import { createRoot } from "react-dom/client"

import "@/styles/index.css"
import { AppShell } from "@/components/shared/AppShell"

import { AccountPage } from "./AccountPage"

document.documentElement.classList.add("dark")

createRoot(document.getElementById("react-root")!).render(
  <StrictMode>
    <AppShell pageTitle="账号">
      <AccountPage />
    </AppShell>
  </StrictMode>,
)
