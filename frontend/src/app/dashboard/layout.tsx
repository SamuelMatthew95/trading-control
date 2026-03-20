'use client'

import { useState } from 'react'
import { usePathname } from 'next/navigation'
import { useCodexStore } from '@/stores/useCodexStore'
import {
  LayoutDashboard,
  CandlestickChart,
  Bot,
  TrendingUp,
  Settings2,
  Wifi,
  WifiOff,
  AlertTriangle,
  CheckCircle2,
  Power
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
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
import { ThemeToggle } from '@/components/ThemeToggle'
import { cn } from '@/lib/utils'
import { useWebSocket } from '@/hooks/useWebSocket'

const navigation = [
  { name: 'Overview', href: '/dashboard', icon: LayoutDashboard },
  { name: 'Trading', href: '/dashboard/trading', icon: CandlestickChart },
  { name: 'Agents', href: '/dashboard/agents', icon: Bot },
  { name: 'Learning', href: '/dashboard/learning', icon: TrendingUp },
  { name: 'System', href: '/dashboard/system', icon: Settings2 },
]

export default function DashboardLayout({
  children,
}: {
  children: React.ReactNode
}) {
  const pathname = usePathname()
  const [killSwitchDialogOpen, setKillSwitchDialogOpen] = useState(false)
  
  const {
    wsConnected,
    killSwitchActive,
    prices,
    orders,
    riskAlerts,
    regime,
    setKillSwitch
  } = useCodexStore()

  const dailyPnl = orders.reduce((sum, o) => sum + Number(o.pnl || 0), 0)

  const toggleKillSwitch = () => {
    setKillSwitch(!killSwitchActive)
    setKillSwitchDialogOpen(false)
  }

  // Initialize WebSocket
  useWebSocket()

  return (
    <div className="flex h-screen overflow-hidden bg-background">

      {/* SIDEBAR — fixed left, full height */}
      <aside className="hidden md:flex w-56 flex-shrink-0 flex-col border-r bg-surface">

        {/* Logo */}
        <div className="flex h-14 items-center gap-2 border-b px-4">
          <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-accent text-accent-foreground text-xs font-bold">TB</div>
          <span className="font-semibold text-sm">Trading Bot</span>
        </div>

        {/* Nav */}
        <nav className="flex-1 overflow-y-auto p-2 space-y-0.5">
          {navigation.map((item) => {
            const isActive = pathname === item.href
            return (
              <a
                key={item.name}
                href={item.href}
                className={cn(
                  "flex items-center gap-3 rounded-md px-3 py-2 text-sm transition-colors",
                  isActive
                    ? "bg-accent/10 text-accent font-medium"
                    : "text-muted-foreground hover:bg-muted hover:text-foreground"
                )}
              >
                <item.icon className="h-4 w-4 flex-shrink-0" />
                {item.name}
              </a>
            )
          })}
        </nav>

        {/* Footer */}
        <div className="border-t p-3">
          <div className="text-xs text-muted-foreground">Phase 2 · Paper Mode</div>
        </div>
      </aside>

      {/* MAIN */}
      <div className="flex flex-1 flex-col overflow-hidden">

        {/* HEADER — fixed top, full width of main area */}
        <header className="flex h-14 flex-shrink-0 items-center justify-between border-b bg-surface px-4 md:px-6">

          {/* Regime badge */}
          <div className="flex items-center gap-2">
            <span className={cn(
              "inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium",
              regime === 'RISK ON'  && "bg-green-500/10 text-green-500 ring-1 ring-green-500/20",
              regime === 'RISK OFF' && "bg-red-500/10 text-red-500 ring-1 ring-red-500/20",
              "bg-amber-500/10 text-amber-500 ring-1 ring-amber-500/20"  // default neutral
            )}>
              <span className="h-1.5 w-1.5 rounded-full bg-current" />
              {regime || 'NEUTRAL'}
            </span>
          </div>

          {/* Right controls */}
          <div className="flex items-center gap-3">

            {/* WS status */}
            <div className="flex items-center gap-1.5 text-xs">
              <span className={cn(
                "h-1.5 w-1.5 rounded-full",
                wsConnected ? "bg-green-500 animate-pulse" : "bg-red-500"
              )} />
              <span className="text-muted-foreground hidden sm:inline">
                {wsConnected ? 'Live' : 'Offline'}
              </span>
            </div>

            {/* Daily P&L */}
            <div className={cn(
              "text-sm font-mono font-medium tabular-nums",
              dailyPnl >= 0 ? "text-green-500" : "text-red-500"
            )}>
              {dailyPnl >= 0 ? '+' : ''}{dailyPnl.toFixed(2)}
            </div>

            {/* Theme toggle */}
            <ThemeToggle />

            {/* Kill switch */}
            <AlertDialog open={killSwitchDialogOpen} onOpenChange={setKillSwitchDialogOpen}>
              <AlertDialogTrigger asChild>
                <button
                  className={cn(
                    "rounded-md px-3 py-1.5 text-xs font-semibold transition-all",
                    killSwitchActive
                      ? "bg-red-600 text-white shadow-lg shadow-red-500/20 animate-pulse"
                      : "border border-red-500/50 text-red-500 hover:bg-red-500/10"
                  )}
                >
                  {killSwitchActive ? '⬛ ACTIVE' : 'Kill Switch'}
                </button>
              </AlertDialogTrigger>
              <AlertDialogContent>
                <AlertDialogHeader>
                  <AlertDialogTitle>Confirm Kill Switch</AlertDialogTitle>
                  <AlertDialogDescription>
                    {killSwitchActive 
                      ? "Resume signal processing and order placement?"
                      : "This will immediately halt all signal processing and order placement."
                    }
                  </AlertDialogDescription>
                </AlertDialogHeader>
                <AlertDialogFooter>
                  <AlertDialogCancel>Cancel</AlertDialogCancel>
                  <AlertDialogAction
                    onClick={toggleKillSwitch}
                    className={killSwitchActive ? "bg-blue-600 hover:bg-blue-700" : "bg-red-600 hover:bg-red-700"}
                  >
                    {killSwitchActive ? 'Resume' : 'Activate'}
                  </AlertDialogAction>
                </AlertDialogFooter>
              </AlertDialogContent>
            </AlertDialog>
          </div>
        </header>

        {/* PAGE CONTENT */}
        <main className="flex-1 overflow-y-auto p-4 md:p-6">
          {children}
        </main>
      </div>
    </div>
  )
}
