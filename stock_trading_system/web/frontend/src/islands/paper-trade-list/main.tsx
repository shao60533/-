import { StrictMode } from "react"
import { createRoot } from "react-dom/client"
import "@/styles/index.css"
import { AppShell } from "@/components/shared/AppShell"
import { PaperTradeListPage } from "./PaperTradeListPage"

document.documentElement.classList.add("dark")
createRoot(document.getElementById("react-root")!).render(
  <StrictMode><AppShell pageTitle="纸面交易"><PaperTradeListPage /></AppShell></StrictMode>,
)
