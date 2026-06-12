'use client'

import Link from 'next/link'
import { usePathname } from 'next/navigation'
import {
  LayoutDashboard,
  CandlestickChart,
  Bot,
  Swords,
  TrendingUp,
  Lightbulb,
  Settings2,
  Menu,
  Activity,
  Brain,
  Power,
} from 'lucide-react'
import { useEffect, useState } from 'react'
import { UI_COPY } from '@/constants/copy'
import { useDashboardStore } from '@/stores/useDashboardStore'
import { ThemeToggle } from '@/components/ThemeToggle'
import { Button } from '@/components/ui/button'
import { useGlobalWebSocket } from '@/hooks/useGlobalWebSocket'
import { api } from '@/lib/apiClient'
import { formatUSD } from '@/lib/formatters'
import { pnlColorClass } from '@/lib/dashboard-helpers'
import { TONE_DOT } from '@/lib/design/sentiment'
import { cn } from '@/lib/utils'
import { useTerminalAccount } from '@/components/dashboard/terminal'

const NAV = [
  { href: '/dashboard', label: UI_COPY.nav.overview, Icon: LayoutDashboard },
  { href: '/dashboard/trading', label: UI_COPY.nav.trading, Icon: CandlestickChart },
  { href: '/dashboard/agents', label: UI_COPY.nav.agents, Icon: Bot },
  { href: '/dashboard/challengers', label: UI_COPY.nav.challengers, Icon: Swords },
  { href: '/dashboard/learning', label: UI_COPY.nav.learning, Icon: TrendingUp },
  { href: '/dashboard/proposals', label: UI_COPY.nav.proposals, Icon: Lightbulb },
  { href: '/dashboard/cognitive', label: UI_COPY.nav.cognitive, Icon: Brain },
  { href: '/dashboard/system', label: UI_COPY.nav.system, Icon: Settings2 },
]

const LogoGlyph = () => (
  // Token-driven mark: chip + glyph derive from the success token so the
  // glyph flips with the theme and never renders dark-on-dark.
  <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-success/15 text-success">
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
      <path d="M3 17l5-5 4 3 6-7" />
      <path d="M3 21h18" />
    </svg>
  </div>
)

const Wordmark = () => (
  <span className="text-sm font-bold uppercase tracking-caps-wide text-foreground">
    Trading<span className="text-brand">Control</span>
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
  return (
    <span className="font-mono text-2xs tabular-nums text-muted-foreground">
      {`${now || UI_COPY.header.clockEmpty} ${UI_COPY.header.timezone}`}
    </span>
  )
}

function HeaderStat({ label, value, className }: { label: string; value: string; className?: string }) {
  return (
    <div className="flex items-center gap-1.5">
      <span className="text-3xs font-semibold uppercase tracking-caps text-muted-foreground">{label}</span>
      <span className={cn('font-mono text-xs font-bold tabular-nums text-foreground/80', className)}>{value}</span>
    </div>
  )
}

const HeaderDivider = () => <div className="h-4 w-px bg-border" />

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  useGlobalWebSocket()

  const pathname = usePathname()
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const [killSwitchPending, setKillSwitchPending] = useState(false)
  const [killConfirm, setKillConfirm] = useState(false)
  const [mounted, setMounted] = useState(false)
  const { killSwitchActive, wsConnected, setKillSwitch, hydrateFromLocalStorage } = useDashboardStore()

  // Real account stats — broker-truth cash with live-marked positions on top
  // (see useTerminalAccount). P&L is lifetime paper P&L vs starting capital.
  const { equity, pnl, buyingPower } = useTerminalAccount()

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
    <div className="flex min-h-screen bg-background text-foreground">
      <aside
        className={cn(
          'fixed inset-y-0 left-0 z-sidebar flex w-64 flex-col border-r bg-card transition-transform md:static md:translate-x-0',
          sidebarOpen ? 'translate-x-0' : '-translate-x-full',
        )}
      >
        <div className="flex h-12 items-center gap-2.5 border-b px-4">
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
                aria-current={active ? 'page' : undefined}
                className={cn(
                  'flex min-h-10 items-center gap-2 rounded-lg px-3 text-sm font-sans font-semibold transition-colors',
                  active
                    ? 'bg-brand/10 text-brand'
                    : 'text-muted-foreground hover:bg-muted hover:text-foreground',
                )}
              >
                <Icon className="h-4 w-4" aria-hidden />
                {label}
              </Link>
            )
          })}
        </nav>
        <div className="mt-auto border-t p-3">
          <div className="flex items-center gap-2 text-xs font-sans text-muted-foreground">
            <Activity className="h-4 w-4" aria-hidden />
            {UI_COPY.header.sidebarFooter}
          </div>
        </div>
      </aside>

      {sidebarOpen && (
        <button
          type="button"
          className="fixed inset-0 z-overlay bg-black/50 md:hidden"
          onClick={() => setSidebarOpen(false)}
          aria-label={UI_COPY.aria.closeSidebar}
        />
      )}

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-header h-12 border-b bg-card/95 backdrop-blur">
          <div className="flex h-full items-center gap-4 px-3 sm:px-4">
            <Button
              variant="ghost"
              size="icon"
              onClick={() => setSidebarOpen(true)}
              className="md:hidden"
              aria-label={UI_COPY.aria.openSidebar}
            >
              <Menu className="h-4 w-4" />
            </Button>

            {/* Account stats — hidden on small screens like the terminal design */}
            <div className="hidden items-center gap-2 lg:flex">
              <HeaderStat label={UI_COPY.header.equity} value={formatUSD(equity)} className="text-foreground" />
              <HeaderDivider />
              <HeaderStat
                label={UI_COPY.header.pnl}
                value={`${pnl >= 0 ? '+' : '-'}${formatUSD(pnl)}`}
                className={pnlColorClass(pnl)}
              />
              <HeaderDivider />
              <HeaderStat label={UI_COPY.header.buyingPower} value={formatUSD(buyingPower)} />
            </div>

            <div className="ml-auto flex items-center gap-3">
              <div className="flex items-center gap-1.5">
                <span className={cn('h-1.5 w-1.5 rounded-full', live ? `animate-pulse ${TONE_DOT.success}` : TONE_DOT.neutral)} />
                <span className="font-mono text-3xs uppercase tracking-caps text-muted-foreground">
                  {live ? UI_COPY.header.live : UI_COPY.header.halted}
                </span>
              </div>
              {mounted && <Clock />}
              <ThemeToggle />
              <HeaderDivider />

              {!killConfirm ? (
                <Button
                  variant={killSwitchActive ? 'solid' : 'outline'}
                  tone="danger"
                  onClick={() => setKillConfirm(true)}
                  className={cn(
                    'px-3 font-mono text-2xs font-bold uppercase tracking-caps',
                    !killSwitchActive && 'hover:border-danger hover:text-danger',
                  )}
                >
                  <Power className="h-3 w-3" aria-hidden />
                  {killSwitchActive ? UI_COPY.killSwitch.halted : UI_COPY.killSwitch.label}
                </Button>
              ) : (
                <div className="flex items-center gap-1">
                  <span className="font-mono text-3xs uppercase tracking-caps text-muted-foreground">
                    {killSwitchActive ? UI_COPY.killSwitch.confirmResume : UI_COPY.killSwitch.confirmHalt}
                  </span>
                  <Button
                    variant="solid"
                    tone="danger"
                    onClick={() => handleKillSwitch(!killSwitchActive)}
                    disabled={killSwitchPending}
                    className="font-mono text-2xs font-bold uppercase tracking-caps"
                  >
                    {killSwitchPending ? '…' : UI_COPY.killSwitch.confirm}
                  </Button>
                  <Button
                    onClick={() => setKillConfirm(false)}
                    className="font-mono text-2xs uppercase tracking-caps"
                  >
                    {UI_COPY.killSwitch.cancel}
                  </Button>
                </div>
              )}
            </div>
          </div>
        </header>

        {showReconnectBanner && (
          <div className="border-b border-warning/30 bg-warning/10 px-4 py-2 text-xs font-sans font-semibold text-warning">
            <span className="inline-block h-2 w-2 animate-pulse rounded-full bg-warning align-middle" />
            <span className="ml-2">{UI_COPY.banners.reconnecting}</span>
          </div>
        )}

        <main className="flex-1 overflow-y-auto">{children}</main>
      </div>
    </div>
  )
}
