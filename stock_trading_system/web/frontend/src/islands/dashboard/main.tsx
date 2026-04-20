import { StrictMode } from "react"
import { createRoot } from "react-dom/client"

function DashboardPage() {
  return <div style={{padding: 40, color: '#e6edf3'}}>
    <h1>Dashboard Island</h1>
    <p>React island loaded successfully.</p>
  </div>
}

createRoot(document.getElementById("react-root")!).render(
  <StrictMode><DashboardPage /></StrictMode>
)
