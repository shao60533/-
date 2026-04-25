import { useEffect, useState } from "react"
import { Sparkles, Lock, ChevronDown } from "lucide-react"
import { Button } from "@/components/ui/button"
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuTrigger,
  DropdownMenuLabel, DropdownMenuSeparator,
  DropdownMenuRadioGroup, DropdownMenuRadioItem,
} from "@/components/ui/dropdown-menu"
import { toast } from "@/components/ui/toaster"
import { apiGet, apiPost } from "@/lib/api"

interface LLMState {
  active: string
  has_qwen_key: boolean
  has_gemini_key: boolean
  locked_by_env: boolean
}

const PROVIDERS: { value: string; label: string; keyField: "has_qwen_key" | "has_gemini_key" }[] = [
  { value: "qwen",  label: "Qwen (通义千问)", keyField: "has_qwen_key" },
  { value: "gemini", label: "Gemini",          keyField: "has_gemini_key" },
]

export function LLMSwitcher() {
  const [state, setState] = useState<LLMState | null>(null)
  const [switching, setSwitching] = useState(false)

  useEffect(() => {
    apiGet<LLMState>("/api/settings/llm-provider")
      .then(setState)
      .catch(() => {})
  }, [])

  if (!state) return null

  const displayName = state.active === "qwen" ? "Qwen" : state.active === "gemini" ? "Gemini" : state.active

  const onSwitch = async (target: string) => {
    if (target === state.active || switching) return
    const prev = state.active
    setSwitching(true)
    setState({ ...state, active: target }) // optimistic

    try {
      await apiPost("/api/settings/llm-provider", { provider: target })
      const label = target === "qwen" ? "Qwen" : "Gemini"
      toast.success(`已切换到 ${label}，下次分析生效`)
    } catch (e: any) {
      setState({ ...state, active: prev }) // rollback
      const status = e?.status ?? 0
      const reason = e?.body?.reason ?? ""
      if (status === 400 && reason === "missing_api_key") {
        toast.error(`${target} API key 未配置`, {
          action: { label: "去设置", onClick: () => { location.href = "/settings" } },
        })
      } else if (status === 409 && reason === "locked_by_env") {
        toast.error("已被环境变量锁定，无法切换")
      } else {
        toast.error("切换失败")
      }
    } finally {
      setSwitching(false)
    }
  }

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" size="sm" className="gap-1.5 w-full justify-start text-xs px-2 h-8">
          <Sparkles className="h-3.5 w-3.5 shrink-0" />
          <span className="truncate">模型: {displayName}</span>
          {state.locked_by_env && <Lock className="h-3 w-3 text-amber-500 shrink-0" />}
          <ChevronDown className="h-3 w-3 ml-auto shrink-0 opacity-50" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start" className="w-56">
        <DropdownMenuLabel>切换 AI 模型</DropdownMenuLabel>
        <DropdownMenuSeparator />
        <DropdownMenuRadioGroup value={state.active} onValueChange={onSwitch}>
          {PROVIDERS.map(p => {
            const hasKey = state[p.keyField]
            return (
              <DropdownMenuRadioItem
                key={p.value}
                value={p.value}
                disabled={!hasKey || state.locked_by_env || switching}
              >
                {p.label}
                {!hasKey && <span className="ml-auto text-xs text-muted-foreground">未配置</span>}
              </DropdownMenuRadioItem>
            )
          })}
        </DropdownMenuRadioGroup>
        {state.locked_by_env && (
          <>
            <DropdownMenuSeparator />
            <div className="px-2 py-1.5 text-xs text-muted-foreground flex items-center gap-1.5">
              <Lock className="h-3 w-3" /> 由环境变量锁定
            </div>
          </>
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
