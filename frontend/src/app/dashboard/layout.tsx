'use client'

import Link from 'next/link'
import { usePathname } from 'next/navigation'
import {
  LayoutDashboard,
  CandlestickChart,
  Bot,
  TrendingUp,
  Settings2,
  AlertTriangle,
} from 'lucide-react'
import { useCodexStore } from '@/stores/useCodexStore'
import { ThemeToggle } from '@/components/ThemeToggle'
import { useWebSocket } from '@/hooks/useWebSocket'
import { useMemo, useState } from 'react'
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

const NAV = [
  { href: '/dashboard',          label: 'Overview',  Icon: LayoutDashboard },
  { href: '/dashboard/trading',  label: 'Trading',   Icon: CandlestickChart },
  { href: '/dashboard/agents',   label: 'Agents',    Icon: Bot },
  { href: '/dashboard/learning', label: 'Learning',  Icon: TrendingUp },
  { href: '/dashboard/system',   label: 'System',    Icon: Settings2 },
]

function cn(...classes: (string | boolean | undefined | null)[]) {
  return classes.filter(Boolean).join(' ')
}

export default function DashboardLayout({
  children,
}: {
  children: React.ReactNode
}) {
  useWebSocket()

  const pathname = usePathname()
  const { orders, regime, wsConnected, killSwitchActive, setKillSwitch } =
    useCodexStore()

  const dailyPnl = useMemo(
    () => orders.reduce((sum, o) => sum + Number(o.pnl || 0), 0),
    [orders]
  )

  const regimeColor =
    regime === 'RISK ON'
      ? 'bg-green-500/10 text-green-600 dark:text-green-400 ring-green-500/30'
      : regime === 'RISK OFF'
      ? 'bg-red-500/10 text-red-600 dark:text-red-400 ring-red-500/30'
      : 'bg-amber-500/10 text-amber-600 dark:text-amber-400 ring-amber-500/30'

  const handleKillSwitch = async (activate: boolean) => {
    try {
      const apiBase = (
        process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000/api'
      ).replace(/\/$/, '')
      const res = await fetch(`${apiBase}/v1/dashboard/kill_switch`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ active: activate }),
      })
      if (res.ok) setKillSwitch(activate)
    } catch {}
  }

  return (
    <div className="flex h-screen overflow-hidden bg-background text-foreground">

      {/* ── SIDEBAR ── */}
      <aside className="hidden md:flex w-56 flex-shrink-0 flex-col border-r border-border bg-surface">
        {/* Logo */}
        <div className="flex h-14 items-center gap-2.5 border-b border-border px-4">
          <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-accent text-accent-foreground text-xs font-bold select-none">
            TB
          </div>
          <span className="font-semibold text-sm tracking-tight">
            Trading Bot
          </span>
        </div>

        {/* Nav */}
        <nav className="flex-1 overflow-y-auto p-2 space-y-0.5">
          {NAV.map(({ href, label, Icon }) => {
            const active =
              href === '/dashboard'
                ? pathname === '/dashboard'
                : pathname.startsWith(href)
            return (
              <Link key={href} href={href}>
                <div
                  className={cn(
                    'flex items-center gap-3 rounded-md px-3 py-2 text-sm transition-colors cursor-pointer',
                    active
                      ? 'bg-accent/10 text-accent font-medium'
                      : 'text-muted-foreground hover:bg-muted hover:text-foreground'
                  )}
                >
                  <Icon className="h-4 w-4 flex-shrink-0" />
                  {label}
                </div>
              </Link>
            )
          })}
        </nav>

        {/* Sidebar footer */}
        <div className="border-t border-border p-3">
          <p className="text-xs text-muted-foreground">Phase 2 · Paper Mode</p>
        </div>
      </aside>

      {/* ── MAIN COLUMN ── */}
      <div className="flex flex-1 flex-col overflow-hidden min-w-0">

        {/* ── HEADER ── */}
        <header className="flex h-14 flex-shrink-0 items-center justify-between border-b border-border bg-surface px-4 md:px-6 gap-4">

          {/* Regime badge */}
          <span
            className={cn(
              'inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium ring-1',
              regimeColor
            )}
          >
            <span className="h-1.5 w-1.5 rounded-full bg-current" />
            {regime?.toUpperCase() || 'NEUTRAL'}
          </span>

          {/* Right controls */}
          <div className="flex items-center gap-3 ml-auto">

            {/* WS status */}
            <div className="flex items-center gap-1.5">
              <span
                className={cn(
                  'h-2 w-2 rounded-full',
                  wsConnected
                    ? 'bg-green-500 animate-pulse'
                    : 'bg-red-500'
                )}
              />
              <span className="text-xs text-muted-foreground hidden sm:inline">
                {wsConnected ? 'Live' : 'Offline'}
              </span>
            </div>

            {/* P&L */}
            <span
              className={cn(
                'text-sm font-mono font-semibold tabular-nums hidden sm:inline',
                dailyPnl >= 0 ? 'text-green-600 dark:text-green-400' : 'text-red-600 dark:text-red-400'
              )}
            >
              {dailyPnl >= 0 ? '+' : ''}${Math.abs(dailyPnl).toFixed(2)}
            </span>

            {/* Theme toggle */}
            <ThemeToggle />

            {/* Kill switch */}
            <AlertDialog>
              <AlertDialogTrigger asChild>
                <button
                  className={cn(
                    'rounded-md px-3 py-1.5 text-xs font-semibold transition-all border',
                    killSwitchActive
                      ? 'bg-red-600 border-red-600 text-white shadow-lg shadow-red-500/20 animate-pulse'
                      : 'border-red-500/50 text-red-500 hover:bg-red-500/10'
                  )}
                >
                  {killSwitchActive ? '⬛ ACTIVE' : 'Kill Switch'}
                </button>
              </AlertDialogTrigger>
              <AlertDialogContent>
                <AlertDialogHeader>
                  <AlertDialogTitle>
                    {killSwitchActive ? 'Deactivate Kill Switch?' : 'Activate Kill Switch?'}
                  </AlertDialogTitle>
                  <AlertDialogDescription>
                    {killSwitchActive
                      ? 'This will resume signal processing and order placement.'
                      : 'This will immediately halt all signal processing and order placement.'}
                  </AlertDialogDescription>
                </AlertDialogHeader>
                <AlertDialogFooter>
                  <AlertDialogCancel>Cancel</AlertDialogCancel>
                  <AlertDialogAction
                    onClick={() => handleKillSwitch(!killSwitchActive)}
                    className={killSwitchActive ? '' : 'bg-red-600 hover:bg-red-700'}
                  >
                    Confirm
                  </AlertDialogAction>
                </AlertDialogFooter>
              </AlertDialogContent>
            </AlertDialog>
          </div>
        </header>

        {/* ── PAGE CONTENT ── */}
        <main className="flex-1 overflow-y-auto p-4 md:p-6">
          {children}
        </main>

        {/* ── FOOTER ── */}
        <footer className="flex h-9 flex-shrink-0 items-center justify-between border-t border-border px-4 md:px-6">
          <span className="text-xs text-muted-foreground">
            AI Trading Bot · Phase 2 · Paper Mode
          </span>
          <span className="text-xs text-muted-foreground">© 2026</span>
        </footer>
      </div>
    </div>
  )
}
