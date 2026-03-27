'use client'

import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { LayoutDashboard, CandlestickChart, Bot, TrendingUp, Settings2, Menu, Power, BarChart3, Activity } from 'lucide-react'
import { useMemo, useState } from 'react'
import { useCodexStore } from '@/stores/useCodexStore'
import { ThemeToggle } from '@/components/ThemeToggle'
import { useWebSocket } from '@/hooks/useWebSocket'
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
import { cn } from '@/lib/utils'

const NAV = [
  { href: '/dashboard', label: 'Overview', Icon: LayoutDashboard },
  { href: '/dashboard/trading', label: 'Trading', Icon: CandlestickChart },
  { href: '/dashboard/agents', label: 'Agents', Icon: Bot },
  { href: '/dashboard/learning', label: 'Learning', Icon: TrendingUp },
  { href: '/dashboard/system', label: 'System', Icon: Settings2 },
]

const formatUSD = (value?: number | null): string => {
  if (value == null || isNaN(value) || !isFinite(value)) return '$0.00'
  return `$${Math.abs(value).toFixed(2)}`
}

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  useWebSocket()

  const pathname = usePathname()
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const { killSwitchActive, orders, positions, wsConnected, setKillSwitch } = useCodexStore()

  const dailyPnl = useMemo(() => {
    const realized = orders.reduce((sum, order) => sum + (Number(order?.pnl) || 0), 0)
    const unrealized = positions.reduce((sum, position) => sum + (Number(position?.pnl) || 0), 0)
    return realized + unrealized
  }, [orders, positions])

  const handleKillSwitch = async (activate: boolean) => {
    const apiBase = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000/api'
    try {
      const response = await fetch(`${apiBase}/v1/dashboard/kill_switch`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ active: activate }),
      })
      if (response.ok) setKillSwitch(activate)
    } catch {
      setKillSwitch(activate)
    }
  }

  return (
    <div className="flex min-h-screen bg-slate-50 text-slate-900 dark:bg-slate-950 dark:text-slate-100">
      <aside
        className={cn(
          'fixed inset-y-0 left-0 z-40 w-64 border-r border-slate-200 bg-white transition-transform dark:border-slate-800 dark:bg-slate-900 md:static md:translate-x-0',
          sidebarOpen ? 'translate-x-0' : '-translate-x-full'
        )}
      >
        <div className="flex h-12 items-center gap-2 border-b border-slate-200 px-4 dark:border-slate-800">
          <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-indigo-600 text-slate-100">
            <BarChart3 className="h-4 w-4" />
          </div>
          <p className="text-sm font-bold uppercase tracking-widest font-sans text-slate-900 dark:text-slate-100">Trading Console</p>
        </div>
        <nav className="space-y-1 p-2">
          {NAV.map(({ href, label, Icon }) => {
            const active = href === '/dashboard' ? pathname === '/dashboard' : pathname.startsWith(href)
            return (
              <Link
                key={href}
                href={href}
                onClick={() => setSidebarOpen(false)}
                className={cn(
                  'flex min-h-11 items-center gap-2 rounded-lg border px-3 text-sm font-sans font-semibold transition-colors',
                  active
                    ? 'border-indigo-500 bg-indigo-500/15 text-indigo-600 dark:text-indigo-400'
                    : 'border-transparent text-slate-600 hover:bg-slate-100 hover:text-slate-900 dark:text-slate-400 dark:hover:bg-slate-800 dark:hover:text-slate-100'
                )}
              >
                <Icon className="h-4 w-4" />
                {label}
              </Link>
            )
          })}
        </nav>
        <div className="mt-auto border-t border-slate-200 p-3 dark:border-slate-800">
          <div className="flex items-center gap-2 text-xs font-sans text-slate-500 dark:text-slate-400">
            <Activity className="h-4 w-4" />
            Phase 2 · Paper Mode
          </div>
        </div>
      </aside>

      {sidebarOpen && <button className="fixed inset-0 z-30 bg-slate-950/50 md:hidden" onClick={() => setSidebarOpen(false)} aria-label="Close sidebar" />}

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-20 flex h-12 items-center gap-2 border-b border-slate-200 bg-slate-50/95 px-4 backdrop-blur dark:border-slate-800 dark:bg-slate-950/95">
          <button
            onClick={() => setSidebarOpen(true)}
            className="flex h-11 w-11 items-center justify-center rounded-lg text-slate-500 transition-colors hover:bg-slate-100 hover:text-slate-900 dark:text-slate-400 dark:hover:bg-slate-800 dark:hover:text-slate-100 md:hidden"
          >
            <Menu className="h-4 w-4" />
          </button>

          <div className="flex items-center gap-2">
            <span className={cn('h-2 w-2 rounded-full', wsConnected ? 'animate-pulse bg-emerald-500' : 'bg-slate-400')} />
            <span className="text-xs font-sans text-slate-500 dark:text-slate-400">{wsConnected ? 'LIVE' : 'OFFLINE'}</span>
          </div>

          <div className="ml-auto text-sm font-mono tabular-nums font-black text-slate-900 dark:text-slate-100">
            {`${dailyPnl >= 0 ? '+' : '-'}${formatUSD(dailyPnl)}`}
          </div>

          <ThemeToggle />

          <AlertDialog>
            <AlertDialogTrigger asChild>
              <button
                className={cn(
                  'flex min-h-11 min-w-11 items-center justify-center rounded-lg border px-3 text-xs font-sans font-semibold transition-transform active:scale-95',
                  killSwitchActive
                    ? 'border-rose-500 bg-rose-500 text-slate-100'
                    : 'border-slate-300 bg-slate-100 text-slate-700 hover:bg-slate-200 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-300 dark:hover:bg-slate-700'
                )}
              >
                <Power className="mr-1 h-3 w-3" />
                {killSwitchActive ? 'HALT' : 'ACTIVE'}
              </button>
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
                <AlertDialogCancel>Cancel</AlertDialogCancel>
                <AlertDialogAction className="bg-rose-600 text-slate-100 hover:bg-rose-700" onClick={() => handleKillSwitch(!killSwitchActive)}>
                  Confirm
                </AlertDialogAction>
              </AlertDialogFooter>
            </AlertDialogContent>
          </AlertDialog>
        </header>

        <main className="flex-1 overflow-y-auto">{children}</main>
      </div>
    </div>
  )
}
