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
  BarChart3,
  Power,
  Activity,
  ChevronDown,
  ChevronUp,
  Menu,
  X
} from 'lucide-react'
import { useCodexStore } from '@/stores/useCodexStore'
import { ThemeToggle } from '@/components/ThemeToggle'
import { useWebSocket } from '@/hooks/useWebSocket'
import { useMemo, useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
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
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const { 
    agentLogs, 
    killSwitchActive, 
    regime, 
    orders, 
    prices, 
    positions, 
    systemMetrics,
    wsConnected,
    setKillSwitch
  } = useCodexStore()

  const { dailyPnl } = useMemo(() => {
    const realized = orders.reduce((sum, order) => sum + (order.pnl || 0), 0)
    const unrealized = positions.reduce((sum, pos) => sum + (pos.pnl || 0), 0)
    return realized + unrealized
  }, [orders, positions])

  const regimeConfig = useMemo(() => {
    switch (regime) {
      case 'bullish':
        return { bg: 'bg-emerald-500/10', text: 'text-emerald-600', border: 'border-emerald-500/20', ring: 'ring-emerald-500/10' }
      case 'bearish':
        return { bg: 'bg-rose-500/10', text: 'text-rose-600', border: 'border-rose-500/20', ring: 'ring-rose-500/10' }
      default:
        return { bg: 'bg-slate-500/10', text: 'text-slate-600', border: 'border-slate-500/20', ring: 'ring-slate-500/10' }
    }
  }, [regime])

  const apiBase = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000/api'

  const handleKillSwitch = async (activate: boolean) => {
    try {
      const res = await fetch(`${apiBase}/v1/dashboard/kill_switch`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ active: activate }),
      })
      if (res.ok) setKillSwitch(activate)
    } catch {}
  }

  return (
    <div className="flex h-screen overflow-hidden bg-white dark:bg-zinc-950 text-slate-900 dark:text-slate-100">

      {/* Mobile Sidebar Overlay */}
      <AnimatePresence>
        {sidebarOpen && (
          <>
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              className="fixed inset-0 bg-black/50 z-40 md:hidden"
              onClick={() => setSidebarOpen(false)}
            />
            <motion.aside
              initial={{ x: -280 }}
              animate={{ x: 0 }}
              exit={{ x: -280 }}
              className="fixed top-0 left-0 z-50 w-64 h-full bg-white dark:bg-zinc-950 border-r border-slate-200 dark:border-slate-800 md:hidden"
            >
              <SidebarContent 
                pathname={pathname} 
                onClose={() => setSidebarOpen(false)} 
              />
            </motion.aside>
          </>
        )}
      </AnimatePresence>

      {/* Desktop Sidebar */}
      <aside className="hidden md:flex w-64 flex-shrink-0 flex-col bg-white dark:bg-zinc-950 border-r border-slate-200 dark:border-slate-800">
        <SidebarContent pathname={pathname} />
      </aside>

      {/* Main Column */}
      <div className="flex flex-1 flex-col overflow-hidden min-w-0 bg-white dark:bg-zinc-950">

        {/* Header - Single LIVE Status Only */}
        <header className="flex h-16 flex-shrink-0 items-center justify-between bg-white dark:bg-zinc-950 border-b border-slate-200 dark:border-slate-800 px-6 gap-4">

          {/* Mobile menu button */}
          <button
            onClick={() => setSidebarOpen(true)}
            className="md:hidden p-2 rounded-lg text-slate-400 hover:text-slate-600 dark:hover:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors"
          >
            <Menu className="h-5 w-5" />
          </button>

          {/* Left - Clean breadcrumb, no LIVE status */}
          <div className="flex items-center gap-4">
            <span className="text-sm font-medium text-slate-600 dark:text-slate-400">
              {pathname === '/dashboard' ? 'Overview' : (pathname.split('/').pop()?.charAt(0)?.toUpperCase() || '') + (pathname.split('/').pop()?.slice(1) || '')}
            </span>
          </div>

          {/* Right controls - Single LIVE status */}
          <div className="flex items-center gap-4 ml-auto">

            {/* Single LIVE status indicator */}
            <div className="flex items-center gap-2">
              <motion.div
                className={cn(
                  'w-2 h-2 rounded-full',
                  wsConnected ? 'bg-emerald-500' : 'bg-rose-500'
                )}
                animate={wsConnected ? {
                  scale: [1, 1.2, 1],
                  opacity: [1, 0.8, 1]
                } : {}}
                transition={{ duration: 2, repeat: Infinity }}
              />
              <span className="text-xs font-medium text-slate-600 dark:text-slate-400">
                {wsConnected ? 'LIVE' : 'OFFLINE'}
              </span>
            </div>

            {/* P&L - Monospace font */}
            <motion.div
              key={dailyPnl}
              initial={{ scale: 0.8, opacity: 0 }}
              animate={{ scale: 1, opacity: 1 }}
              className="text-sm font-mono font-semibold tabular-nums text-slate-900 dark:text-slate-100"
            >
              {dailyPnl >= 0 ? '+' : ''}${Math.abs(dailyPnl).toFixed(2)}
            </motion.div>

            {/* Theme toggle */}
            <ThemeToggle />

            {/* Kill Switch - High Contrast */}
            <AlertDialog>
              <AlertDialogTrigger asChild>
                <motion.button
                  whileHover={{ scale: 1.02 }}
                  whileTap={{ scale: 0.98 }}
                  className={cn(
                    'flex items-center gap-2 px-3 py-1.5 text-[10px] font-semibold uppercase tracking-[0.2em] rounded-lg border transition-all duration-200',
                    killSwitchActive
                      ? 'bg-slate-900 text-white dark:bg-red-600 dark:hover:bg-red-700 border-slate-300 dark:border-red-500'
                      : 'bg-slate-100 text-slate-900 dark:bg-slate-800 dark:text-slate-100 border-slate-300 dark:border-slate-600 hover:bg-slate-200 dark:hover:bg-slate-700'
                  )}
                >
                  <Power className="w-3 h-3" />
                  {killSwitchActive ? 'ACTIVE' : 'KILL SWITCH'}
                </motion.button>
              </AlertDialogTrigger>
              <AlertDialogContent className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-700">
                <AlertDialogHeader>
                  <AlertDialogTitle className="text-slate-900 dark:text-slate-100">
                    {killSwitchActive ? 'Deactivate Kill Switch?' : 'Activate Kill Switch?'}
                  </AlertDialogTitle>
                  <AlertDialogDescription className="text-slate-600 dark:text-slate-400">
                    {killSwitchActive
                      ? 'This will resume signal processing and order placement.'
                      : 'This will immediately halt all signal processing and order placement.'}
                  </AlertDialogDescription>
                </AlertDialogHeader>
                <AlertDialogFooter>
                  <AlertDialogCancel className="bg-slate-100 text-slate-900 dark:bg-slate-800 dark:text-slate-100 border border-slate-300 dark:border-slate-600 hover:bg-slate-200 dark:hover:bg-slate-700">
                    Cancel
                  </AlertDialogCancel>
                  <AlertDialogAction
                    onClick={() => handleKillSwitch(!killSwitchActive)}
                    className={cn(
                      killSwitchActive 
                        ? 'bg-slate-600 hover:bg-slate-700 text-white dark:bg-slate-700 dark:hover:bg-slate-800'
                        : 'bg-red-600 hover:bg-red-700 text-white'
                    )}
                  >
                    Confirm
                  </AlertDialogAction>
                </AlertDialogFooter>
              </AlertDialogContent>
            </AlertDialog>
          </div>
        </header>

        {/* Page Content */}
        <main className="flex-1 overflow-y-auto bg-white dark:bg-zinc-950">
          {children}
        </main>

        {/* Footer */}
        <footer className="flex h-10 flex-shrink-0 items-center justify-between bg-white dark:bg-zinc-950 border-t border-slate-200 dark:border-slate-800 px-6">
          <span className="text-xs text-slate-500 dark:text-slate-400">
            AI Trading Control · Phase 2 · Paper Mode
          </span>
          <span className="text-xs text-slate-500 dark:text-slate-400"> 2026</span>
        </footer>
      </div>
    </div>
  )
}

function SidebarContent({ pathname, onClose }: { pathname: string; onClose?: () => void }) {
  return (
    <>
      {/* Logo - High Contrast Branding */}
      <div className="flex h-16 items-center gap-3 border-b border-slate-200 dark:border-slate-800 px-6">
        <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-indigo-600 text-white">
          <BarChart3 className="h-5 w-5" />
        </div>
        <span className="text-sm font-bold tracking-tighter text-slate-950 dark:text-white uppercase">
          Trading Control
        </span>
      </div>

      {/* Navigation - Deep Indigo Active State */}
      <nav className="flex-1 overflow-y-auto p-4 space-y-1">
        {NAV.map(({ href, label, Icon }) => {
          const active =
            href === '/dashboard'
              ? pathname === '/dashboard'
              : pathname.startsWith(href)
          return (
            <Link key={href} href={href} onClick={onClose}>
              <motion.div
                whileHover={{ x: 4 }}
                className={cn(
                  'flex items-center gap-3 rounded-lg px-4 py-3 text-sm font-medium transition-all duration-200 cursor-pointer',
                  active
                    ? 'bg-indigo-600 text-white shadow-lg'
                    : 'text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-slate-100 hover:bg-slate-100 dark:hover:bg-slate-800'
                )}
              >
                <Icon className={cn("h-5 w-5", active ? "text-white" : "text-slate-500")} />
                {label}
              </motion.div>
            </Link>
          )
        })}
      </nav>

      {/* Sidebar footer */}
      <div className="border-t border-slate-200 dark:border-slate-800 p-4">
        <div className="flex items-center gap-2 text-xs text-slate-500 dark:text-slate-400">
          <Activity className="h-4 w-4" />
          Phase 2 · Paper Mode
        </div>
      </div>
    </>
  )
}
