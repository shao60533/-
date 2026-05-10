import { StrictMode } from "react"
import { createRoot } from "react-dom/client"
import "@/styles/index.css"
import { AppShell } from "@/components/shared/AppShell"
import { ScreenerV3Page } from "./ScreenerV3Page"

document.documentElement.classList.add("dark")

createRoot(document.getElementById("react-root")!).render(
  <StrictMode><AppShell pageTitle="发现 · 智能选股 V3"><ScreenerV3Page /></AppShell></StrictMode>,
)
