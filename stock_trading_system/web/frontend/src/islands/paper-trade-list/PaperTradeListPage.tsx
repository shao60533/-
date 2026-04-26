import { useEffect, useState } from "react"
import {
  TestTube, Search, RefreshCw, Star, MoreHorizontal,
  Trash2, Pencil, Download,
} from "lucide-react"
import { Card, CardContent } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Input } from "@/components/ui/input"
import { Chip, ChipRow } from "@/components/ui/chip"
import { Skeleton } from "@/components/ui/skeleton"
import { Stat } from "@/components/ui/stat"
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { apiGet, apiDel } from "@/lib/api"

interface Session {
  id: number
  name: string
  mode: string
  status: string
  ticker: string | null
  start_capital: number
  auto_track: number
  is_system: number
  metrics_json: string | null
  created_at: string
}

function fmt(n: number) {
  return n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

export function PaperTradeListPage() {
  const [sessions, setSessions] = useState<Session[]>([])
  const [loading, setLoading] = useState(true)
  const [search, setSearch] = useState("")
  const [scope, setScope] = useState<"my" | "all">("my")

  const load = async () => {
    setLoading(true)
    try {
      const data = await apiGet<Session[]>("/api/paper/sessions")
      setSessions(Array.isArray(data) ? data : [])
    } catch {
      setSessions([])
    }
    setLoading(false)
  }

  useEffect(() => { load() }, [])

  const defaultSession = sessions.find(s => s.is_system === 1)
  const filtered = sessions.filter(s => {
    if (search && !(s.name?.toLowerCase().includes(search.toLowerCase()) || s.ticker?.toLowerCase().includes(search.toLowerCase()))) return false
    return true
  })

  const handleDelete = async (id: number) => {
    if (!confirm("确定删除该会话？")) return
    await apiDel(`/api/paper/sessions/${id}`)
    load()
  }

  if (loading) return (
    <div className="p-4 md:p-6 max-w-6xl mx-auto space-y-4">
      <Skeleton className="h-8 w-48" />
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {[1,2,3].map(i => <Skeleton key={i} className="h-40" />)}
      </div>
    </div>
  )

  return (
    <div className="p-4 md:p-6 max-w-6xl mx-auto space-y-6">
      <div className="flex items-center gap-3">
        <TestTube className="w-5 h-5 text-[var(--color-accent-blue)]" />
        <h1 className="text-xl font-bold">纸面交易</h1>
      </div>

      {/* Toolbar */}
      <div className="flex flex-wrap items-center gap-3">
        <div className="relative flex-1 min-w-[200px] max-w-xs">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
          <Input placeholder="搜索会话..." value={search} onChange={e => setSearch(e.target.value)} className="pl-9" />
        </div>
        <ChipRow>
          <Chip active={scope === "my"} onClick={() => setScope("my")}>我的</Chip>
          <Chip active={scope === "all"} onClick={() => setScope("all")}>全部</Chip>
        </ChipRow>
        <Button variant="outline" size="sm" onClick={load}>
          <RefreshCw className="w-4 h-4 mr-1" /> 刷新
        </Button>
      </div>

      {/* Default session highlight */}
      {defaultSession && (
        <Card className="border-[var(--color-accent-blue)]/30 bg-[var(--color-accent-blue)]/5">
          <CardContent className="pt-5">
            <a href={defaultSession.ticker ? `/paper-trade/${defaultSession.ticker}` : "#"} className="block">
              <div className="flex items-center gap-2 mb-3">
                <Star className="w-4 h-4 text-[var(--color-accent-yellow)] fill-[var(--color-accent-yellow)]" />
                <span className="font-semibold">{defaultSession.name}</span>
                <Badge variant="default">{defaultSession.status}</Badge>
                {defaultSession.ticker && <Badge variant="outline" className="font-mono">{defaultSession.ticker}</Badge>}
              </div>
              <div className="grid grid-cols-3 gap-4 grid-collapse-mobile">
                <Stat label="初始资金" value={`$${fmt(defaultSession.start_capital)}`} />
                <Stat label="模式" value={defaultSession.mode} />
                <Stat label="自动追踪" value={defaultSession.auto_track ? "开启" : "关闭"} />
              </div>
            </a>
          </CardContent>
        </Card>
      )}

      {/* Session grid */}
      {filtered.length === 0 ? (
        <div className="text-center py-16 text-muted-foreground">
          暂无会话
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {filtered.filter(s => s.id !== defaultSession?.id).map(s => (
            <SessionCard key={s.id} session={s} onDelete={handleDelete} />
          ))}
        </div>
      )}
    </div>
  )
}

function SessionCard({ session, onDelete }: { session: Session; onDelete: (id: number) => void }) {
  const metrics = session.metrics_json ? (() => {
    try { return JSON.parse(session.metrics_json) } catch { return null }
  })() : null

  return (
    <Card className="hover:border-[var(--color-border-bright)] transition-colors">
      <CardContent className="pt-5 relative">
        <a href={session.ticker ? `/paper-trade/${session.ticker}` : "#"} className="block">
          <div className="flex items-center gap-2 mb-2">
            <span className="font-semibold text-sm truncate flex-1">{session.name}</span>
            <Badge variant={session.status === "running" ? "default" : "muted"} className="text-[10px]">
              {session.status}
            </Badge>
          </div>
          {session.ticker && <span className="text-xs font-mono text-muted-foreground">{session.ticker}</span>}
          <div className="mt-2 text-xs text-muted-foreground">
            资金 ${fmt(session.start_capital)}
            {metrics?.sharpe_ratio != null && <span className="ml-2">Sharpe {Number(metrics.sharpe_ratio).toFixed(2)}</span>}
          </div>
        </a>
        {/* Menu */}
        <div className="absolute top-4 right-4">
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="ghost" size="sm" className="h-7 w-7 p-0">
                <MoreHorizontal className="w-4 h-4" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuItem><Pencil className="w-3.5 h-3.5 mr-2" />重命名</DropdownMenuItem>
              <DropdownMenuItem><Download className="w-3.5 h-3.5 mr-2" />导出</DropdownMenuItem>
              <DropdownMenuItem className="text-[var(--color-accent-red)]" onClick={() => onDelete(session.id)}>
                <Trash2 className="w-3.5 h-3.5 mr-2" />删除
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </CardContent>
    </Card>
  )
}
