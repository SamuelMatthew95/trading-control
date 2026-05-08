'use client'

import Link from 'next/link'
import { usePathname } from 'next/navigation'
import {
  LayoutDashboard,
  CandlestickChart,
  Bot,
  TrendingUp,
  Settings2,
  Menu,
  BarChart3,
  Activity,
} from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { useCodexStore } from '@/stores/useCodexStore'
import { ThemeToggle } from '@/components/ThemeToggle'
import { useWebSocket } from '@/hooks/useWebSocket'
import { useSystemStatus } from '@/hooks/useSystemStatus'
import { getKillSwitch, setKillSwitch as apiSetKillSwitch } from '@/lib/api'
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
import { TONE_CLASSES, getNumberTone, toneForSystemStatus } from '@/lib/state'
import { formatSignedCurrency } from '@/lib/format'
import { RECONNECT_BANNER } from '@/lib/styles'

const NAV = [
  { href: '/dashboard', label: 'Overview', Icon: LayoutDashboard },
  { href: '/dashboard/trading', label: 'Trading', Icon: CandlestickChart },
  { href: '/dashboard/agents', label: 'Agents', Icon: Bot },
  { href: '/dashboard/learning', label: 'Learning', Icon: TrendingUp },
  { href: '/dashboard/system', label: 'System', Icon: Settings2 },
]

const RECONNECT_DOT = 'inline-block h-2 w-2 animate-pulse rounded-full align-middle'

function ReconnectBanner() {
  return (
    <div className={cn(RECONNECT_BANNER, TONE_CLASSES.warn.card, TONE_CLASSES.warn.text)}>
      <span className={cn(RECONNECT_DOT, TONE_CLASSES.warn.bg)} />
      <span className="ml-2">Reconnecting to live feed…</span>
    </div>
  )
}

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  useWebSocket()

  const pathname = usePathname()
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const [killSwitchPending, setKillSwitchPending] = useState(false)
  const [mounted, setMounted] = useState(false)
  const {
    killSwitchActive,
    orders,
    positions,
    wsConnected,
    setKillSwitch,
    hydrateFromLocalStorage,
  } = useCodexStore()

  const dailyPnl = useMemo(() => {
    const realized = orders.reduce((sum, order) => sum + (Number(order?.pnl) || 0), 0)
    const unrealized = positions.reduce((sum, position) => sum + (Number(position?.pnl) || 0), 0)
    return realized + unrealized
  }, [orders, positions])
  const systemStatus = useSystemStatus()
  const systemTone = toneForSystemStatus(systemStatus)
  const pnlTone = getNumberTone(dailyPnl)

  // Hydrate persisted store data from localStorage AFTER the first client
  // render so the initial SSR'd HTML matches. Without this gate the first
  // render uses persisted data on the client but empty state on the server,
  // triggering React hydration errors #418/#423/#425.
  useEffect(() => {
    hydrateFromLocalStorage()
    setMounted(true)
  }, [hydrateFromLocalStorage])

  // Hydrate the kill-switch state from the server so the UI starts in sync
  // with Redis even if no one has toggled it in this session yet.
  useEffect(() => {
    let cancelled = false
    void (async () => {
      try {
        const data = await getKillSwitch()
        if (!cancelled && typeof data.active === 'boolean') setKillSwitch(data.active)
      } catch {
        // Network issues are handled by the WebSocket reconnect loop; leave UI as-is.
      }
    })()
    return () => {
      cancelled = true
    }
  }, [setKillSwitch])

  const showReconnectBanner = mounted && !wsConnected

  const handleKillSwitch = async (activate: boolean) => {
    if (killSwitchPending) return
    setKillSwitchPending(true)
    try {
      await apiSetKillSwitch(activate)
      setKillSwitch(activate)
    } catch {
      // Leave state unchanged on failure; user can retry.
    } finally {
      setKillSwitchPending(false)
    }
  }

  return (
    <div className="flex min-h-screen bg-slate-50 text-slate-900 dark:bg-slate-950 dark:text-slate-100">
      <aside
        className={cn(
          'fixed inset-y-0 left-0 z-40 w-64 border-r border-slate-200 bg-white transition-transform dark:border-slate-800 dark:bg-slate-900 md:static md:translate-x-0',
          sidebarOpen ? 'translate-x-0' : '-translate-x-full',
        )}
      >
        <div className="flex h-12 items-center gap-2 border-b border-slate-200 px-4 dark:border-slate-800">
          <div className="flex h-7 w-7 items-center justify-center rounded-[6px] bg-slate-200 text-slate-900">
            <BarChart3 className="h-4 w-4" />
          </div>
          <p className="text-sm font-bold uppercase tracking-widest text-slate-900 dark:text-slate-100">
            Trading Console
          </p>
        </div>
        <nav className="space-y-1 p-2">
          {NAV.map(({ href, label, Icon }) => {
            const active =
              href === '/dashboard' ? pathname === '/dashboard' : pathname.startsWith(href)
            return (
              <Link
                key={href}
                href={href}
                onClick={() => setSidebarOpen(false)}
                className={cn(
                  'flex min-h-11 items-center gap-2 rounded-[6px] border px-3 text-sm font-semibold transition-colors',
                  active
                    ? 'border-slate-300 bg-slate-100 text-slate-900 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100'
                    : 'border-transparent text-slate-600 hover:bg-slate-100 hover:text-slate-900 dark:text-slate-400 dark:hover:bg-slate-800 dark:hover:text-slate-100',
                )}
              >
                <Icon className="h-4 w-4" />
                {label}
              </Link>
            )
          })}
        </nav>
        <div className="mt-auto border-t border-slate-200 p-3 dark:border-slate-800">
          <div className="flex items-center gap-2 text-xs text-slate-500 dark:text-slate-400">
            <Activity className="h-4 w-4" />
            Phase 2 · Paper Mode
          </div>
        </div>
      </aside>

      {sidebarOpen ? (
        <button
          className="fixed inset-0 z-30 bg-slate-950/50 md:hidden"
          onClick={() => setSidebarOpen(false)}
          aria-label="Close sidebar"
        />
      ) : null}

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-50 h-12 border-b border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-950">
          <div className="flex h-full items-center px-4">
            <div className="flex flex-1 items-center gap-2">
              <button
                onClick={() => setSidebarOpen(true)}
                className="flex h-9 w-9 items-center justify-center rounded-[6px] text-slate-500 transition-colors hover:bg-slate-100 hover:text-slate-900 dark:text-slate-400 dark:hover:bg-slate-800 dark:hover:text-slate-100 md:hidden"
              >
                <Menu className="h-4 w-4" />
              </button>
              <span className="text-sm font-bold uppercase tracking-widest text-slate-900 dark:text-white">
                Trading Console
              </span>
            </div>

            <div className="flex flex-1 justify-end">
              <div className="flex items-center gap-3">
                <div className="hidden items-center gap-2 rounded-[6px] border border-slate-200 bg-slate-100 px-2.5 py-1 dark:border-slate-800 dark:bg-slate-900 sm:flex">
                  <span className="text-[10px] font-semibold uppercase tracking-[0.08em] text-slate-500 dark:text-slate-400">
                    Total P&L
                  </span>
                  <span
                    className={cn(
                      'text-xs font-mono font-bold tabular-nums',
                      pnlTone === 'muted'
                        ? 'text-slate-500 dark:text-slate-400'
                        : TONE_CLASSES[pnlTone].text,
                    )}
                  >
                    {formatSignedCurrency(dailyPnl)}
                  </span>
                </div>
                <ThemeToggle />
                <span
                  className={cn(
                    'text-[11px] font-mono uppercase tracking-[0.04em]',
                    TONE_CLASSES[systemTone].text,
                  )}
                >
                  {systemStatus}
                </span>
                <div className="h-5 w-px bg-slate-300 dark:bg-slate-700" aria-hidden="true" />

                <AlertDialog>
                  <AlertDialogTrigger asChild>
                    <Button
                      variant={killSwitchActive ? 'destructive' : 'outline'}
                      shortcut={killSwitchActive ? 'ESC' : '⏎'}
                    >
                      {killSwitchActive ? 'Kill Switch On' : 'Kill Switch Off'}
                    </Button>
                  </AlertDialogTrigger>
                  <AlertDialogContent className="rounded-[8px] border border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900">
                    <AlertDialogHeader>
                      <AlertDialogTitle className="text-sm font-bold uppercase tracking-widest text-slate-900 dark:text-slate-100">
                        {killSwitchActive ? 'Deactivate Kill Switch' : 'Activate Kill Switch'}
                      </AlertDialogTitle>
                      <AlertDialogDescription className="text-sm text-slate-600 dark:text-slate-300">
                        {killSwitchActive
                          ? 'This will resume signal processing and order placement.'
                          : 'This will halt all signal processing and order placement.'}
                      </AlertDialogDescription>
                    </AlertDialogHeader>
                    <AlertDialogFooter>
                      <AlertDialogCancel className="font-mono text-[11px] uppercase tracking-[0.04em]">
                        Cancel
                      </AlertDialogCancel>
                      <AlertDialogAction
                        className="h-7 rounded-[4px] border border-slate-200 bg-slate-100 px-3 font-mono text-[11px] uppercase tracking-[0.04em] text-slate-950 hover:bg-slate-200 disabled:opacity-50"
                        disabled={killSwitchPending}
                        onClick={() => void handleKillSwitch(!killSwitchActive)}
                      >
                        {killSwitchPending
                          ? 'Working…'
                          : killSwitchActive
                            ? 'Deactivate ⏎'
                            : 'Activate ⏎'}
                      </AlertDialogAction>
                    </AlertDialogFooter>
                  </AlertDialogContent>
                </AlertDialog>
              </div>
            </div>
          </div>
        </header>

        {showReconnectBanner ? <ReconnectBanner /> : null}

        <main className="flex-1 overflow-y-auto">{children}</main>
      </div>
    </div>
  )
}
