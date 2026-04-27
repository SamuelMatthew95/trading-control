'use client'

import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { LayoutDashboard, CandlestickChart, Bot, TrendingUp, Settings2, BarChart3, Activity } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { useCodexStore } from '@/stores/useCodexStore'
import { useWebSocket } from '@/hooks/useWebSocket'
import { api } from '@/lib/apiClient'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from '@/components/ui/alert-dialog'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import { TopBar } from '@/components/dashboard/TopBar'
import type { SystemStatusState } from '@/components/dashboard/SystemStatus'

const NAV = [
  { href: '/dashboard', label: 'Overview', Icon: LayoutDashboard },
  { href: '/dashboard/trading', label: 'Trading', Icon: CandlestickChart },
  { href: '/dashboard/agents', label: 'Agents', Icon: Bot },
  { href: '/dashboard/learning', label: 'Learning', Icon: TrendingUp },
  { href: '/dashboard/system', label: 'System', Icon: Settings2 },
]

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  useWebSocket()

  const pathname = usePathname()
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const [killSwitchPending, setKillSwitchPending] = useState(false)
  const { killSwitchActive, orders, positions, wsConnected, setKillSwitch, marketTickCount, wsDiagnostics } = useCodexStore()

  const dailyPnl = useMemo(() => {
    const realized = orders.reduce((sum, order) => sum + (Number(order?.pnl) || 0), 0)
    const unrealized = positions.reduce((sum, position) => sum + (Number(position?.pnl) || 0), 0)
    return realized + unrealized
  }, [orders, positions])
  const systemStatus = useMemo<SystemStatusState>(() => {
    if (wsDiagnostics.lastError) return 'error'
    if (!wsConnected) return 'idle'
    if (orders.length > 0) return 'active'
    return 'idle'
  }, [orders.length, wsConnected, wsDiagnostics.lastError])

  // Hydrate the kill-switch state from the server so the UI starts in sync
  // with Redis even if no one has toggled it in this session yet.
  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        const response = await fetch(api('/dashboard/kill-switch'))
        if (!response.ok) return
        const data = (await response.json()) as { active?: boolean }
        if (!cancelled && typeof data.active === 'boolean') setKillSwitch(data.active)
      } catch {
        // Network issues are handled by the WebSocket reconnect loop; leave UI as-is.
      }
    })()
    return () => {
      cancelled = true
    }
  }, [setKillSwitch])

  const handleKillSwitch = async (activate: boolean) => {
    if (killSwitchPending) return
    setKillSwitchPending(true)
    try {
      const response = await fetch(api('/dashboard/kill-switch'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ active: activate }),
      })
      if (response.ok) setKillSwitch(activate)
    } finally {
      setKillSwitchPending(false)
    }
  }

  return (
    <div className="flex min-h-screen bg-slate-950 text-slate-100">
      <aside
        className={cn(
          'fixed inset-y-0 left-0 z-40 w-16 border-r border-slate-800 bg-slate-900 transition-transform md:static md:translate-x-0',
          sidebarOpen ? 'translate-x-0' : '-translate-x-full'
        )}
      >
        <div className="flex h-12 items-center justify-center border-b border-slate-800">
          <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-slate-800 text-slate-100">
            <BarChart3 className="h-4 w-4" />
          </div>
        </div>
        <nav className="space-y-1 p-2">
          {NAV.map(({ href, label, Icon }) => {
            const active = href === '/dashboard' ? pathname === '/dashboard' : pathname.startsWith(href)
            return (
              <Link
                key={href}
                href={href}
                title={label}
                onClick={() => setSidebarOpen(false)}
                className={cn(
                  'flex h-10 items-center justify-center rounded-lg border transition-colors',
                  active
                    ? 'border-slate-700 bg-slate-800 text-slate-100'
                    : 'border-transparent text-slate-400 hover:bg-slate-800 hover:text-slate-100'
                )}
              >
                <Icon className="h-4 w-4" />
                <span className="sr-only">{label}</span>
              </Link>
            )
          })}
        </nav>
        <div className="mt-auto border-t border-slate-800 p-3">
          <div className="flex items-center justify-center text-xs font-sans text-slate-400">
            <Activity className="h-4 w-4" />
          </div>
        </div>
      </aside>

      {sidebarOpen && <button className="fixed inset-0 z-30 bg-slate-950/50 md:hidden" onClick={() => setSidebarOpen(false)} aria-label="Close sidebar" />}

      <div className="flex min-w-0 flex-1 flex-col">
        <TopBar onOpenSidebar={() => setSidebarOpen(true)} pnl={dailyPnl} marketTickCount={marketTickCount} systemStatus={systemStatus} />
        <div className="border-b border-slate-800 bg-slate-950 px-4 py-2">
          <AlertDialog>
            <AlertDialogTrigger asChild>
              <Button variant={killSwitchActive ? 'destructive' : 'outline'} shortcut={killSwitchActive ? 'ESC' : '⏎'}>
                {killSwitchActive ? 'Kill Switch On' : 'Kill Switch Off'}
              </Button>
            </AlertDialogTrigger>
            <AlertDialogContent className="rounded-xl border border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900">
              <AlertDialogHeader>
                <AlertDialogTitle className="font-sans text-sm font-bold uppercase tracking-widest text-slate-900 dark:text-slate-100">
                  {killSwitchActive ? 'Deactivate Kill Switch' : 'Activate Kill Switch'}
                </AlertDialogTitle>
                <AlertDialogDescription className="text-sm font-sans text-slate-600 dark:text-slate-300">
                  {killSwitchActive ? 'This will resume signal processing and order placement.' : 'This will halt all signal processing and order placement.'}
                </AlertDialogDescription>
              </AlertDialogHeader>
              <AlertDialogFooter>
                <AlertDialogCancel className="font-mono text-[11px] uppercase tracking-[0.04em]">Cancel</AlertDialogCancel>
                <AlertDialogAction
                  className="h-7 rounded-[4px] border border-slate-200 bg-slate-100 px-3 font-mono text-[11px] uppercase tracking-[0.04em] text-slate-950 hover:bg-slate-200 disabled:opacity-50"
                  disabled={killSwitchPending}
                  onClick={() => handleKillSwitch(!killSwitchActive)}
                >
                  {killSwitchPending ? 'Working…' : killSwitchActive ? 'Deactivate ⏎' : 'Activate ⏎'}
                </AlertDialogAction>
              </AlertDialogFooter>
            </AlertDialogContent>
          </AlertDialog>
        </div>

        <main className="flex-1 overflow-y-auto">{children}</main>
      </div>
    </div>
  )
}
