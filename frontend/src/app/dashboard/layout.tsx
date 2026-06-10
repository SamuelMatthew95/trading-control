'use client'

import Link from 'next/link'
import { usePathname } from 'next/navigation'
import {
  LayoutDashboard,
  CandlestickChart,
  Bot,
  TrendingUp,
  Lightbulb,
  Settings2,
  Menu,
  Activity,
  Brain,
  Power,
} from 'lucide-react'
import { useEffect, useState } from 'react'
import { useCodexStore } from '@/stores/useCodexStore'
import { ThemeToggle } from '@/components/ThemeToggle'
import { useWebSocket } from '@/hooks/useWebSocket'
import { api } from '@/lib/apiClient'
import { formatUSD } from '@/lib/formatters'
import { cn } from '@/lib/utils'
import { useTerminalAccount } from '@/components/dashboard/terminal'

const NAV = [
  { href: '/dashboard', label: 'Overview', Icon: LayoutDashboard },
  { href: '/dashboard/trading', label: 'Trading', Icon: CandlestickChart },
  { href: '/dashboard/agents', label: 'Agents', Icon: Bot },
  { href: '/dashboard/learning', label: 'Learning', Icon: TrendingUp },
  { href: '/dashboard/proposals', label: 'Proposals', Icon: Lightbulb },
  { href: '/dashboard/cognitive', label: 'Cognitive', Icon: Brain },
  { href: '/dashboard/system', label: 'System', Icon: Settings2 },
]

const LogoGlyph = () => (
  <div className="flex h-7 w-7 items-center justify-center rounded-lg" style={{ background: 'var(--accent)' }}>
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="#04141a" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
      <path d="M3 17l5-5 4 3 6-7" />
      <path d="M3 21h18" />
    </svg>
  </div>
)

const Wordmark = () => (
  <span className="text-[13px] font-bold uppercase tracking-[0.2em] text-slate-900 dark:text-slate-100">
    Trading<span style={{ color: 'var(--accent)' }}>Control</span>
  </span>
)

function Clock() {
  const [now, setNow] = useState<string>('')
  useEffect(() => {
    const update = () => setNow(new Date().toLocaleTimeString('en', { hour12: false }))
    update()
    const id = setInterval(update, 1000)
    return () => clearInterval(id)
  }, [])
  return <span className="font-mono text-[11px] tabular-nums text-slate-500">{now ? `${now} ET` : '--:--:-- ET'}</span>
}

function HeaderStat({ label, value, className }: { label: string; value: string; className?: string }) {
  return (
    <div className="flex items-center gap-1.5">
      <span className="text-[10px] font-semibold uppercase tracking-wider text-slate-500">{label}</span>
      <span className={cn('font-mono text-xs font-bold tabular-nums text-slate-700 dark:text-slate-200', className)}>{value}</span>
    </div>
  )
}

const HeaderDivider = () => <div className="h-4 w-px bg-slate-300 dark:bg-slate-800" />

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  useWebSocket()

  const pathname = usePathname()
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const [killSwitchPending, setKillSwitchPending] = useState(false)
  const [killConfirm, setKillConfirm] = useState(false)
  const [mounted, setMounted] = useState(false)
  const { killSwitchActive, wsConnected, setKillSwitch, hydrateFromLocalStorage } = useCodexStore()

  // Real account stats — broker-truth cash with live-marked positions on top
  // (see useTerminalAccount). P&L is lifetime paper P&L vs starting capital.
  const { equity, pnl, buyingPower } = useTerminalAccount()
  const pnlUp = pnl >= 0

  const live = !killSwitchActive

  useEffect(() => {
    hydrateFromLocalStorage()
    setMounted(true)
  }, [hydrateFromLocalStorage])

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

  const showReconnectBanner = mounted && !wsConnected

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
      setKillConfirm(false)
    }
  }

  return (
    <div className="flex min-h-screen bg-slate-100 text-slate-900 dark:bg-slate-950 dark:text-slate-100">
      <aside
        className={cn(
          'fixed inset-y-0 left-0 z-40 flex w-64 flex-col border-r border-slate-200 bg-white transition-transform dark:border-slate-800 dark:bg-slate-950 md:static md:translate-x-0',
          sidebarOpen ? 'translate-x-0' : '-translate-x-full',
        )}
      >
        <div className="flex h-12 items-center gap-2.5 border-b border-slate-200 px-4 dark:border-slate-800">
          <LogoGlyph />
          <Wordmark />
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
                  'flex min-h-10 items-center gap-2 rounded-lg border px-3 text-sm font-sans font-semibold transition-colors',
                  active
                    ? 'border-transparent text-[var(--accent)]'
                    : 'border-transparent text-slate-600 hover:bg-slate-100 hover:text-slate-900 dark:text-slate-400 dark:hover:bg-slate-900 dark:hover:text-slate-200',
                )}
                style={active ? { background: 'var(--accent-soft)' } : undefined}
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
        <header className="sticky top-0 z-50 h-12 border-b border-slate-200 bg-white/95 backdrop-blur dark:border-slate-800 dark:bg-slate-950/95">
          <div className="flex h-full items-center gap-4 px-3 sm:px-4">
            <button
              onClick={() => setSidebarOpen(true)}
              className="flex h-9 w-9 items-center justify-center rounded-lg text-slate-500 transition-colors hover:bg-slate-100 hover:text-slate-900 dark:text-slate-400 dark:hover:bg-slate-900 dark:hover:text-slate-100 md:hidden"
              aria-label="Open sidebar"
            >
              <Menu className="h-4 w-4" />
            </button>

            {/* Account stats — hidden on small screens like the terminal design */}
            <div className="hidden items-center gap-2 lg:flex">
              <HeaderStat label="Equity" value={formatUSD(equity)} className="text-slate-900 dark:text-slate-100" />
              <HeaderDivider />
              <HeaderStat
                label="P&L"
                value={`${pnlUp ? '+' : '-'}${formatUSD(pnl)}`}
                className={pnlUp ? 'txt-up' : 'txt-down'}
              />
              <HeaderDivider />
              <HeaderStat label="Buying Power" value={formatUSD(buyingPower)} />
            </div>

            <div className="ml-auto flex items-center gap-3">
              <div className="flex items-center gap-1.5">
                <span className={cn('h-1.5 w-1.5 rounded-full', live ? 'animate-pulse bg-[var(--up)]' : 'bg-slate-500')} />
                <span className="font-mono text-[10px] uppercase tracking-wider text-slate-500">{live ? 'Live · Paper' : 'Halted'}</span>
              </div>
              {mounted && <Clock />}
              <ThemeToggle />
              <HeaderDivider />

              {!killConfirm ? (
                <button
                  onClick={() => setKillConfirm(true)}
                  className={cn(
                    'flex h-7 items-center gap-1.5 whitespace-nowrap rounded-md border px-3 font-mono text-[11px] font-bold uppercase tracking-wider transition-colors',
                    killSwitchActive
                      ? 'border-[var(--down)] bg-[var(--down)] text-slate-950'
                      : 'border-slate-300 text-slate-600 hover:border-[var(--down)] hover:text-[var(--down)] dark:border-slate-700 dark:text-slate-300',
                  )}
                >
                  <Power className="h-[11px] w-[11px]" />
                  {killSwitchActive ? 'Halted' : 'Kill Switch'}
                </button>
              ) : (
                <div className="flex items-center gap-1">
                  <span className="font-mono text-[10px] uppercase tracking-wide text-slate-500 dark:text-slate-400">
                    {killSwitchActive ? 'Resume?' : 'Halt all?'}
                  </span>
                  <button
                    onClick={() => handleKillSwitch(!killSwitchActive)}
                    disabled={killSwitchPending}
                    className="h-7 rounded-md bg-[var(--down)] px-2.5 font-mono text-[11px] font-bold uppercase tracking-wider text-slate-950 disabled:opacity-50"
                  >
                    {killSwitchPending ? '…' : 'Confirm'}
                  </button>
                  <button
                    onClick={() => setKillConfirm(false)}
                    className="h-7 rounded-md border border-slate-300 px-2.5 font-mono text-[11px] uppercase tracking-wider text-slate-500 hover:text-slate-800 dark:border-slate-700 dark:text-slate-400 dark:hover:text-slate-200"
                  >
                    Esc
                  </button>
                </div>
              )}
            </div>
          </div>
        </header>

        {showReconnectBanner && (
          <div className="border-b border-warning/30 bg-warning/10 px-4 py-2 text-xs font-sans font-semibold text-warning">
            <span className="inline-block h-2 w-2 animate-pulse rounded-full bg-warning align-middle" />
            <span className="ml-2">Reconnecting to live feed…</span>
          </div>
        )}

        <main className="flex-1 overflow-y-auto">{children}</main>
      </div>
    </div>
  )
}
