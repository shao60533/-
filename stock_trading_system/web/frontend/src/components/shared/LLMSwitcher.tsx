import { useEffect, useState } from "react"
import { Sparkles, Lock, ChevronDown, Settings } from "lucide-react"
import { Button } from "@/components/ui/button"
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuTrigger,
  DropdownMenuLabel, DropdownMenuSeparator,
  DropdownMenuRadioGroup, DropdownMenuRadioItem,
} from "@/components/ui/dropdown-menu"
import { toast } from "@/components/ui/toaster"
import { apiGet, apiPost } from "@/lib/api"
import { cn } from "@/lib/utils"

/**
 * LLM provider switch — three-state (qwen / gemini / openrouter) with
 * a second OR-only section that lets the user pick which deep / quick
 * preset is active. See docs/design/llm-openrouter.md v1.0 §9.
 *
 * Two-tier mental model:
 *   1. Top section = which LLM provider runs.
 *   2. (only when active=openrouter) bottom section = which OR preset
 *      maps to the deep / quick role. Switching deep preset resets the
 *      analyzer's TradingAgents graph (cache key includes the preset
 *      ids so the next analysis uses the new model).
 */

interface LLMState {
  active: string
  has_qwen_key: boolean
  has_gemini_key: boolean
  has_openrouter_key: boolean
  locked_by_env: boolean
}

interface OpenRouterPreset {
  id: string
  label: string
  model: string
  role: string
  provider_order?: string[]
  kwargs?: Record<string, unknown>
}

interface OpenRouterActive {
  deep: OpenRouterPreset
  quick: OpenRouterPreset
  presets: OpenRouterPreset[]
  active: { deep?: string; quick?: string }
  active_provider: string | null
}

type ApiError = {
  status?: number
  body?: { reason?: string; message?: string }
}

const PROVIDERS: {
  value: string
  label: string
  keyField: "has_qwen_key" | "has_gemini_key" | "has_openrouter_key"
}[] = [
  { value: "qwen",       label: "Qwen (通义千问)",   keyField: "has_qwen_key" },
  { value: "gemini",     label: "Gemini",            keyField: "has_gemini_key" },
  { value: "openrouter", label: "OpenRouter (聚合)", keyField: "has_openrouter_key" },
]

const PROVIDER_LABEL: Record<string, string> = {
  qwen:       "Qwen",
  gemini:     "Gemini",
  openrouter: "OpenRouter",
}

/**
 * Trigger style. ``full`` = legacy ghost button used in the desktop
 * sidebar + the More sheet (full-width text trigger). ``pill`` =
 * mobile-ui-v1.3.1 demo-style blue pill with a glowing dot, used in
 * the MobileTopbar where horizontal real estate is tight.
 */
export type LLMSwitcherVariant = "full" | "pill"

export interface LLMSwitcherProps {
  variant?: LLMSwitcherVariant
}

export function LLMSwitcher({ variant = "full" }: LLMSwitcherProps = {}) {
  const [state, setState] = useState<LLMState | null>(null)
  const [or, setOr] = useState<OpenRouterActive | null>(null)
  const [switching, setSwitching] = useState(false)

  useEffect(() => {
    apiGet<LLMState>("/api/settings/llm-provider")
      .then(setState)
      .catch(() => {})
  }, [])

  // Lazy-load OR preset state when the active provider becomes
  // openrouter. Done in a second effect (rather than always) so users
  // on qwen/gemini don't pay the round-trip on every page load.
  useEffect(() => {
    if (state?.active === "openrouter") {
      apiGet<OpenRouterActive>("/api/settings/openrouter/active")
        .then(setOr)
        .catch(() => { /* preset section silently hidden on failure */ })
    } else {
      setOr(null)
    }
  }, [state?.active])

  if (!state) return null

  const displayName = PROVIDER_LABEL[state.active] ?? state.active

  const onSwitchProvider = async (target: string) => {
    if (target === state.active || switching) return
    const prev = state.active
    setSwitching(true)
    setState({ ...state, active: target })  // optimistic

    try {
      await apiPost("/api/settings/llm-provider", { provider: target })
      toast.success(`已切换到 ${PROVIDER_LABEL[target] ?? target}，下次分析生效`)
    } catch (caught) {
      const e = caught as ApiError
      setState({ ...state, active: prev })  // rollback
      const status = e?.status ?? 0
      const reason = e?.body?.reason ?? ""
      const label = PROVIDER_LABEL[target] ?? target
      if (status === 400 && reason === "missing_api_key") {
        toast.error(`${label} API key 未配置`, {
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

  const onSwitchPreset = async (role: "deep" | "quick", preset_id: string) => {
    if (!or) return
    const cur = role === "deep" ? or.deep.id : or.quick.id
    if (preset_id === cur) return

    try {
      await apiPost("/api/settings/openrouter/active", { role, preset_id })
      // Re-fetch so deep/quick resolved-preset blocks reflect server truth.
      const fresh = await apiGet<OpenRouterActive>(
        "/api/settings/openrouter/active",
      )
      setOr(fresh)
      const label = (fresh.presets.find(p => p.id === preset_id) || {}).label ?? preset_id
      toast.success(`${role === "deep" ? "深度" : "快速"} 模型切换为 ${label}`)
    } catch (caught) {
      const e = caught as ApiError
      const reason = e?.body?.reason ?? ""
      if (reason === "locked_by_env") {
        toast.error("已被环境变量锁定，无法切换")
      } else if (reason === "unknown_preset") {
        toast.error(`preset 不存在：${preset_id}`)
      } else {
        toast.error("preset 切换失败")
      }
    }
  }

  // OR sub-sections — filter the pool by role. Presets declared with
  // role="both" appear in both sections (used for testing / single-
  // model setups).
  const deepPresets  = or?.presets.filter(p => p.role === "deep"  || p.role === "both") ?? []
  const quickPresets = or?.presets.filter(p => p.role === "quick" || p.role === "both") ?? []

  // mobile-ui-v1.3.1 fixup #2: pill variant matches demo `.provider`
  // — rounded-full button, blue dot with soft halo, blue text on a
  // 8% blue tint background. Single trigger element so the dropdown
  // contents stay identical in both variants.
  const trigger = variant === "pill" ? (
    <button
      type="button"
      data-llm-pill=""
      className={cn(
        "inline-flex items-center gap-1.5 h-8 px-2.5 rounded-full",
        "border border-[color-mix(in_srgb,var(--color-accent-blue)_30%,transparent)]",
        "bg-[color-mix(in_srgb,var(--color-accent-blue)_10%,transparent)]",
        "text-[var(--color-accent-blue)] text-xs font-semibold whitespace-nowrap",
        "hover:bg-[color-mix(in_srgb,var(--color-accent-blue)_18%,transparent)]",
        "transition-colors disabled:opacity-50",
      )}
      disabled={switching}
    >
      <span
        aria-hidden="true"
        className="w-1.5 h-1.5 rounded-full bg-[var(--color-accent-blue)] shadow-[0_0_0_4px_color-mix(in_srgb,var(--color-accent-blue)_18%,transparent)]"
      />
      <span className="truncate max-w-[90px]">{displayName}</span>
      {state.locked_by_env && <Lock className="h-3 w-3 text-amber-500 shrink-0" />}
      <ChevronDown className="h-3 w-3 shrink-0 opacity-70" />
    </button>
  ) : (
    <Button variant="ghost" size="sm" className="gap-1.5 w-full justify-start text-xs px-2 h-8">
      <Sparkles className="h-3.5 w-3.5 shrink-0" />
      <span className="truncate">模型: {displayName}</span>
      {state.locked_by_env && <Lock className="h-3 w-3 text-amber-500 shrink-0" />}
      <ChevronDown className="h-3 w-3 ml-auto shrink-0 opacity-50" />
    </Button>
  )

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>{trigger}</DropdownMenuTrigger>
      <DropdownMenuContent align="start" className="w-72">
        <DropdownMenuLabel>切换 AI 模型</DropdownMenuLabel>
        <DropdownMenuSeparator />
        <DropdownMenuRadioGroup value={state.active} onValueChange={onSwitchProvider}>
          {PROVIDERS.map(p => {
            const hasKey = state[p.keyField] as boolean
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

        {/* OR preset section — only renders when OR is the active
            provider AND the API returned preset data. Two radio
            groups, one per role; switching deep cascades to a fresh
            graph cache key in the analyzer (see §6 cache_key spec). */}
        {state.active === "openrouter" && or && (
          <>
            <DropdownMenuSeparator />
            <DropdownMenuLabel className="text-xs text-muted-foreground">
              深度推理（14 大师 / TradingAgents）
            </DropdownMenuLabel>
            <DropdownMenuRadioGroup
              value={or.deep.id}
              onValueChange={pid => onSwitchPreset("deep", pid)}
            >
              {deepPresets.map(p => (
                <DropdownMenuRadioItem key={p.id} value={p.id}
                  disabled={state.locked_by_env}>
                  {p.label}
                </DropdownMenuRadioItem>
              ))}
            </DropdownMenuRadioGroup>

            <DropdownMenuSeparator />
            <DropdownMenuLabel className="text-xs text-muted-foreground">
              快速思考（NL 解析 / RenderingExtractor）
            </DropdownMenuLabel>
            <DropdownMenuRadioGroup
              value={or.quick.id}
              onValueChange={pid => onSwitchPreset("quick", pid)}
            >
              {quickPresets.map(p => (
                <DropdownMenuRadioItem key={p.id} value={p.id}
                  disabled={state.locked_by_env}>
                  {p.label}
                </DropdownMenuRadioItem>
              ))}
            </DropdownMenuRadioGroup>

            <DropdownMenuSeparator />
            <a
              href="/settings#openrouter"
              className="flex items-center gap-1.5 px-2 py-1.5 text-xs text-muted-foreground hover:text-foreground"
            >
              <Settings className="h-3 w-3" /> 管理预设
            </a>
          </>
        )}

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
