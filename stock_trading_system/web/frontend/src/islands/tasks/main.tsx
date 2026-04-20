import { StrictMode } from "react"
import { createRoot } from "react-dom/client"

function TasksPage() {
  return <div style={{padding: 40, color: '#e6edf3'}}>
    <h1>Tasks Island</h1>
    <p>React island loaded successfully.</p>
  </div>
}

createRoot(document.getElementById("react-root")!).render(
  <StrictMode><TasksPage /></StrictMode>
)
