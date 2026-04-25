import { StrictMode } from "react"
import { createRoot } from "react-dom/client"
import "@/styles/index.css"
import { AppShell } from "@/components/shared/AppShell"
import { AlertsPage } from "./AlertsPage"

document.documentElement.classList.add("dark")

createRoot(document.getElementById("react-root")!).render(
  <StrictMode><AppShell><AlertsPage /></AppShell></StrictMode>,
)
