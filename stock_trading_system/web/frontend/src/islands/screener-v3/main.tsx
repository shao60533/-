import { StrictMode } from "react"
import { createRoot } from "react-dom/client"
import "@/styles/index.css"
import { ScreenerV3Page } from "./ScreenerV3Page"

document.documentElement.classList.add("dark")

createRoot(document.getElementById("react-root")!).render(
  <StrictMode>
    <ScreenerV3Page />
  </StrictMode>,
)
