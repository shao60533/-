import { StrictMode } from "react"
import { createRoot } from "react-dom/client"
import "@/styles/index.css"
import { AppShell } from "@/components/shared/AppShell"
import { PortfolioPage } from "./PortfolioPage"

document.documentElement.classList.add("dark")

const pageTitle =
  window.location.search.includes("tab=transactions") || window.location.hash === "#transactions"
    ? "持仓 · 交易记录"
    : "持仓 · 管理"

createRoot(document.getElementById("react-root")!).render(
  <StrictMode><AppShell pageTitle={pageTitle}><PortfolioPage /></AppShell></StrictMode>,
)
