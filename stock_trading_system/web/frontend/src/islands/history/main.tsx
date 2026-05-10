import { StrictMode } from "react"
import { createRoot } from "react-dom/client"
import "@/styles/index.css"
import { AppShell } from "@/components/shared/AppShell"
import { HistoryPage } from "./HistoryPage"

document.documentElement.classList.add("dark")

createRoot(document.getElementById("react-root")!).render(
  <StrictMode><AppShell pageTitle="分析 · 历史记录"><HistoryPage /></AppShell></StrictMode>,
)
