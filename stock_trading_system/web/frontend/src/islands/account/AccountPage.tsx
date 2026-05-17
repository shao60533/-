/**
 * AccountPage — standalone /account page for non-admin users.
 *
 * mobile-ui-v1.3.1 addendum #3 §3. Replaces the prior shared
 * SettingsPage account section so non-admin users have a dedicated,
 * minimal surface for "who am I + log out" without seeing admin-only
 * config panels.
 */
import { useState } from "react"
import { Hash, LogOut, Shield, UserCircle } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { toast } from "@/components/ui/toaster"
import { apiPost } from "@/lib/api"
import { getCurrentUser } from "@/lib/auth"

export function AccountPage() {
  const user = getCurrentUser()
  const [busy, setBusy] = useState(false)

  async function onLogout() {
    if (!window.confirm("确认退出登录？")) return
    setBusy(true)
    try {
      await apiPost("/api/auth/logout", {})
      window.location.href = "/login"
    } catch {
      toast.error("退出失败，请重试")
      setBusy(false)
    }
  }

  if (!user) {
    return (
      <div className="p-4 md:p-6 max-w-md mx-auto">
        <p className="text-center text-muted-foreground py-8">未登录</p>
      </div>
    )
  }

  const isAdmin = user.role === "admin"

  return (
    <div className="p-4 md:p-6 max-w-md mx-auto space-y-4">
      <Card>
        <CardContent className="pt-5 space-y-3">
          <div className="flex items-center gap-3 pb-3 border-b border-border">
            <div className="w-12 h-12 rounded-full bg-primary/10 grid place-items-center shrink-0">
              <UserCircle className="w-7 h-7 text-primary" />
            </div>
            <div className="min-w-0">
              <div className="font-semibold truncate">{user.displayName}</div>
              <Badge
                variant={isAdmin ? "blue" : "muted"}
                className="mt-0.5 text-[10px]"
              >
                {isAdmin ? "管理员" : "用户"}
              </Badge>
            </div>
          </div>

          <InfoRow icon={<Hash className="w-4 h-4" />} label="账号 ID" value={`#${user.id}`} />
          <InfoRow icon={<Shield className="w-4 h-4" />} label="角色" value={user.role} />
          <InfoRow icon={<UserCircle className="w-4 h-4" />} label="显示名" value={user.displayName} />
        </CardContent>
      </Card>

      <Button
        variant="destructive"
        className="w-full"
        onClick={onLogout}
        disabled={busy}
        data-account-logout
      >
        <LogOut className="w-4 h-4 mr-2" />
        {busy ? "退出中..." : "退出登录"}
      </Button>
    </div>
  )
}

interface InfoRowProps {
  icon: React.ReactNode
  label: string
  value: string
}

function InfoRow({ icon, label, value }: InfoRowProps) {
  return (
    <div className="flex items-center gap-2 text-sm">
      <span className="text-muted-foreground">{icon}</span>
      <span className="text-muted-foreground">{label}</span>
      <span className="ml-auto font-mono text-xs truncate">{value}</span>
    </div>
  )
}
