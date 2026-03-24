'use client'

import Link from 'next/link'
import { usePathname } from 'next/navigation'
import {
  LayoutDashboard,
  CandlestickChart,
  Bot,
  TrendingUp,
  Settings2,
  Power,
  Menu,
  Activity
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
  { href: '/dashboard', label: 'Overview', Icon: LayoutDashboard },
  { href: '/dashboard/trading', label: 'Trading', Icon: CandlestickChart },
  { href: '/dashboard/agents', label: 'Agents', Icon: Bot },
  { href: '/dashboard/learning', label: 'Learning', Icon: TrendingUp },
  { href: '/dashboard/system', label: 'System', Icon: Settings2 },
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
    killSwitchActive, 
    orders, 
    positions, 
    systemMetrics,
    wsConnected,
    setKillSwitch
  } = useCodexStore()

  const { dailyPnl } = useMemo(() => {
    const realized = orders.reduce((sum, order) => sum + (order.pnl || 0), 0)
    const unrealized = positions.reduce((sum, pos) => sum + (pos.pnl || 0), 0)
    return realized + unrealized || 0
  }, [orders, positions])

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
    <div className="flex h-screen bg-white dark:bg-zinc-950">
      {/* Sidebar */}
      <Sidebar pathname={pathname} mobileOpen={sidebarOpen} onClose={() => setSidebarOpen(false)} />

      {/* Main Content */}
      <div className="flex flex-1 flex-col overflow-hidden">
        <Header 
          dailyPnl={dailyPnl}
          killSwitchActive={killSwitchActive}
          wsConnected={wsConnected}
          onToggleSidebar={() => setSidebarOpen(true)}
          onKillSwitch={handleKillSwitch}
        />
        <main className="flex-1 overflow-y-auto bg-slate-50 dark:bg-zinc-900">
          {children}
        </main>
      </div>
    </div>
  )
}

function Sidebar({ pathname, mobileOpen, onClose }: { 
  pathname: string; 
  mobileOpen: boolean; 
  onClose: () => void 
}) {
  return (
    <>
      {/* Mobile Overlay */}
      {mobileOpen && (
        <div 
          className="fixed inset-0 bg-black/50 z-40 md:hidden" 
          onClick={onClose}
        />
      )}
      
      {/* Sidebar */}
      <aside className={cn(
        "fixed md:relative w-64 h-screen bg-white dark:bg-zinc-950 border-r border-slate-200 dark:border-slate-800 z-50",
        "transform transition-transform duration-200",
        mobileOpen ? "translate-x-0" : "-translate-x-full md:translate-x-0"
      )}>
        {/* Logo */}
        <div className="flex h-14 items-center gap-3 px-6 border-b border-slate-200 dark:border-slate-800">
          <div className="h-6 w-6 bg-emerald-500 rounded" />
          <span className="text-sm font-semibold text-slate-900 dark:text-white">
            Trading Control
          </span>
        </div>

        {/* Navigation */}
        <nav className="flex-1 p-2">
          {NAV.map(({ href, label, Icon }) => {
            const active = href === '/dashboard' 
              ? pathname === '/dashboard' 
              : pathname.startsWith(href)
            
            return (
              <Link key={href} href={href} onClick={onClose}>
                <div className={cn(
                  "flex items-center gap-3 px-3 py-2 rounded-md text-sm font-medium transition-colors",
                  active
                    ? "bg-slate-100 dark:bg-slate-800 text-slate-900 dark:text-white"
                    : "text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-800"
                )}>
                  <Icon className="w-4 h-4" />
                  {label}
                </div>
              </Link>
            )
          })}
        </nav>

        {/* Footer */}
        <div className="p-4 border-t border-slate-200 dark:border-slate-800">
          <div className="flex items-center gap-2 text-xs text-slate-500">
            <Activity className="w-3 h-3" />
            Phase 2 · Paper Mode
          </div>
        </div>
      </aside>
    </>
  )
}

function Header({ 
  dailyPnl, 
  killSwitchActive, 
  wsConnected, 
  onToggleSidebar,
  onKillSwitch 
}: {
  dailyPnl: number
  killSwitchActive: boolean
  wsConnected: boolean
  onToggleSidebar: () => void
  onKillSwitch: (active: boolean) => void
}) {
  const pathname = usePathname()
  
  const pageTitle = useMemo(() => {
    const path = typeof window !== 'undefined' ? window.location.pathname : pathname
    if (path === '/dashboard') return 'Overview'
    const segments = path.split('/').pop()
    if (!segments) return 'Overview'
    return segments.charAt(0)?.toUpperCase() + segments.slice(1)
  }, [pathname])

  return (
    <header className="flex items-center justify-between px-6 h-14 bg-white dark:bg-zinc-950 border-b border-slate-200 dark:border-slate-800">
      {/* Left - Page Title */}
      <div className="flex items-center gap-4">
        <button
          onClick={onToggleSidebar}
          className="md:hidden p-2 rounded-md text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-800"
        >
          <Menu className="w-4 h-4" />
        </button>
        <h1 className="text-lg font-semibold text-slate-900 dark:text-slate-100">
          {pageTitle}
        </h1>
      </div>

      {/* Right - Controls */}
      <div className="flex items-center gap-4">
        {/* System Status */}
        <div className="flex items-center gap-2">
          <div className={cn(
            "w-2 h-2 rounded-full",
            wsConnected ? "bg-emerald-500" : "bg-red-500"
          )} />
          <span className="text-sm text-slate-500">
            {wsConnected ? 'Online' : 'Offline'}
          </span>
        </div>

        {/* P&L */}
        <div className="text-sm font-mono text-slate-900 dark:text-slate-100">
          {dailyPnl ? (dailyPnl >= 0 ? '+' : '') + dailyPnl.toFixed(2) : '$0.00'}
        </div>

        {/* Kill Switch */}
        <AlertDialog>
          <AlertDialogTrigger asChild>
            <button className={cn(
              "h-9 px-3 rounded-md text-sm font-medium transition-colors",
              killSwitchActive
                ? "bg-slate-100 text-slate-700 hover:bg-slate-200 dark:bg-slate-800 dark:text-slate-300 dark:hover:bg-slate-700"
                : "bg-red-500 text-white hover:bg-red-600"
            )}>
              <Power className="w-3 h-3 mr-2" />
              {killSwitchActive ? 'Active' : 'Halted'}
            </button>
          </AlertDialogTrigger>
          <AlertDialogContent className="bg-white dark:bg-zinc-900 border border-slate-200 dark:border-slate-800">
            <AlertDialogHeader>
              <AlertDialogTitle className="text-slate-900 dark:text-slate-100">
                {killSwitchActive ? 'Halt Trading System?' : 'Resume Trading System?'}
              </AlertDialogTitle>
              <AlertDialogDescription className="text-slate-600 dark:text-slate-400">
                {killSwitchActive
                  ? 'This will immediately halt all signal processing and order placement.'
                  : 'This will resume signal processing and order placement.'}
              </AlertDialogDescription>
            </AlertDialogHeader>
            <AlertDialogFooter>
              <AlertDialogCancel className="bg-slate-100 text-slate-900 dark:bg-slate-800 dark:text-slate-100 border border-slate-300 dark:border-slate-600 hover:bg-slate-200 dark:hover:bg-slate-700">
                Cancel
              </AlertDialogCancel>
              <AlertDialogAction
                onClick={() => onKillSwitch(!killSwitchActive)}
                className={cn(
                  killSwitchActive 
                    ? 'bg-red-500 hover:bg-red-600 text-white'
                    : 'bg-emerald-500 hover:bg-emerald-600 text-white'
                )}
              >
                {killSwitchActive ? 'Halt' : 'Resume'}
              </AlertDialogAction>
            </AlertDialogFooter>
          </AlertDialogContent>
        </AlertDialog>

        {/* Theme Toggle */}
        <ThemeToggle />
      </div>
    </header>
  )
}
