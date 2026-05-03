/** Task result → landing page URL mapping (9 types + fallback). */

interface TaskLike {
  id: string
  type?: string
  status?: string
  result_ref?: string
  params_json?: string
}

export function getTaskResultUrl(task: TaskLike): string {
  if (!task) return "/tasks"

  const t = (task.type ?? "").toLowerCase()
  const ref = task.result_ref ?? ""
  let params: Record<string, string> = {}
  try {
    params = task.params_json ? JSON.parse(task.params_json) : {}
  } catch { /* ignore */ }

  // Running/pending tasks → task detail page
  if (task.status === "running" || task.status === "pending") {
    return `/tasks/${task.id}`
  }

  switch (t) {
    case "analysis":
      return ref ? `/analysis/${ref}` : `/tasks/${task.id}`

    case "batch_analysis":
      return `/history?batch_id=${task.id}`

    case "screen":
    case "screen_v2":
    case "screen_v3":
      return `/screener-v3?result=${task.id}`

    case "backtest":
      return ref ? `/backtest-v2/${ref}` : `/tasks/${task.id}`

    case "report":
      // Report detail loads through /api/tasks/<task_id>/result so the
      // owner/admin privacy check can run before exposing holdings/PnL.
      // Never use result_ref here: task_results_generic:N is not a task id
      // and will strand users on the loading skeleton.
      return task.id ? `/reports?id=${task.id}` : "/reports"

    case "paper_trade":
      return params.ticker ? `/paper-trade/${params.ticker}` : "/paper-trade"

    case "paper_backfill":
      return "/paper-trade"

    case "qwen_fundamentals":
    case "qwen_news":
      return params.ticker ? `/analysis?ticker=${params.ticker}` : `/tasks/${task.id}`

    default:
      return `/tasks/${task.id}`
  }
}
