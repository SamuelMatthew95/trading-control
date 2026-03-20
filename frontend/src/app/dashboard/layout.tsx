'use client'

import { useState } from 'react'
import { useTheme } from 'next-themes'
import { useCodexStore } from '@/stores/useCodexStore'
import {
  LayoutDashboard,
  CandlestickChart,
  Bot,
  TrendingUp,
  Settings2,
  Sun,
  Moon,
  Wifi,
  WifiOff,
  AlertTriangle,
  CheckCircle2,
  X
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
  const { theme, setTheme } = useTheme()
  const [isMobileMenuOpen, setIsMobileMenuOpen] = useState(false)
  
  const {
    wsConnected,
    killSwitchActive,
    prices,
    positions,
    riskAlerts,
    setKillSwitch
  } = useCodexStore()

  // Calculate daily P&L (simplified)
  const dailyPnL = Object.values(positions).reduce((sum, pos) => {
    const currentPrice = prices[pos.symbol]?.price || pos.entry_price
    const pnl = (currentPrice - pos.entry_price) * pos.qty
    return sum + pnl
  }, 0)

  // Determine regime status
  const getRegimeStatus = () => {
    if (riskAlerts.some(alert => alert.severity === 'high')) return 'RISK OFF'
    if (riskAlerts.some(alert => alert.severity === 'medium')) return 'NEUTRAL'
    return 'RISK ON'
  }

  const getRegimeColor = () => {
    const regime = getRegimeStatus()
    switch (regime) {
      case 'RISK ON': return 'bg-green-500/15 text-green-400 border-green-500/20'
      case 'RISK OFF': return 'bg-red-500/15 text-red-400 border-red-500/20'
      default: return 'bg-amber-500/15 text-amber-400 border-amber-500/20'
    }
  }

  return (
    <div className="min-h-screen bg-slate-50 dark:bg-slate-900">
      {/* Header */}
      <header className="h-14 sticky top-0 z-50 border-b border-slate-200 dark:border-slate-700 backdrop-blur-sm bg-white/80 dark:bg-slate-900/80">
        <div className="flex items-center justify-between h-full px-4">
          {/* Left: Logo */}
          <div className="flex items-center gap-2">
            <div className="w-6 h-6 bg-blue-500 rounded-sm flex items-center justify-center">
              <div className="w-3 h-0.5 bg-white"></div>
            </div>
            <span className="font-semibold text-slate-900 dark:text-slate-100">Trading Bot</span>
          </div>

          {/* Center: Regime Badge */}
          <div className="flex items-center">
            <Badge variant="outline" className={`${getRegimeColor()} border-current px-3 py-1 text-xs font-medium`}>
              <div className={`w-1.5 h-1.5 rounded-full mr-2 ${
                getRegimeStatus() === 'RISK ON' ? 'bg-green-400' :
                getRegimeStatus() === 'RISK OFF' ? 'bg-red-400' : 'bg-amber-400'
              }`} />
              {getRegimeStatus()}
            </Badge>
          </div>

          {/* Right: Status indicators */}
          <div className="flex items-center gap-3">
            {/* WS Status */}
            <div className="flex items-center gap-1">
              {wsConnected ? (
                <Wifi className="w-4 h-4 text-green-500" />
              ) : (
                <WifiOff className="w-4 h-4 text-slate-400" />
              )}
              <span className="text-xs text-slate-600 dark:text-slate-400">
                {wsConnected ? 'Live' : 'Offline'}
              </span>
            </div>

            {/* Daily P&L */}
            <div className={`text-sm font-mono ${
              dailyPnL >= 0 ? 'text-green-600 dark:text-green-400' : 'text-red-600 dark:text-red-400'
            }`}>
              ${dailyPnL.toFixed(2)}
            </div>

            {/* Theme Toggle */}
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}
              className="w-8 h-8 p-0"
            >
              {theme === 'dark' ? <Sun className="w-4 h-4" /> : <Moon className="w-4 h-4" />}
            </Button>

            {/* Kill Switch */}
            <AlertDialog>
              <AlertDialogTrigger asChild>
                <Button
                  variant={killSwitchActive ? "destructive" : "outline"}
                  size="sm"
                  className={`${killSwitchActive ? 'animate-pulse' : ''} ${
                    !killSwitchActive ? 'border-red-500 text-red-500 hover:bg-red-500 hover:text-white' : ''
                  }`}
                >
                  {killSwitchActive ? 'ACTIVE' : 'INACTIVE'}
                </Button>
              </AlertDialogTrigger>
              <AlertDialogContent>
                <AlertDialogHeader>
                  <AlertDialogTitle>
                    {killSwitchActive ? 'Deactivate Kill Switch?' : 'Activate Kill Switch?'}
                  </AlertDialogTitle>
                  <AlertDialogDescription>
                    {killSwitchActive 
                      ? 'This will resume all trading operations. Make sure systems are stable.'
                      : 'This will immediately stop all trading operations and prevent new orders.'
                    }
                  </AlertDialogDescription>
                </AlertDialogHeader>
                <AlertDialogFooter>
                  <AlertDialogCancel>Cancel</AlertDialogCancel>
                  <AlertDialogAction
                    onClick={() => setKillSwitch(!killSwitchActive)}
                    className={killSwitchActive ? 'bg-green-600 hover:bg-green-700' : ''}
                  >
                    {killSwitchActive ? 'Deactivate' : 'Activate'}
                  </AlertDialogAction>
                </AlertDialogFooter>
              </AlertDialogContent>
            </AlertDialog>
          </div>
        </div>
      </header>

      <div className="flex">
        {/* Sidebar */}
        <aside className="hidden md:block w-56 fixed left-0 top-14 h-full border-r border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900">
          <div className="p-4">
            <nav className="space-y-1">
              {navigation.map((item) => {
                const isActive = window.location.pathname === item.href
                const Icon = item.icon
                return (
                  <a
                    key={item.name}
                    href={item.href}
                    className={`flex items-center gap-3 px-3 py-2.5 text-sm rounded-lg transition-colors ${
                      isActive
                        ? 'bg-blue-500/10 text-blue-400 rounded-lg font-medium'
                        : 'text-slate-400 hover:text-slate-100 hover:bg-slate-800/60 rounded-lg'
                    }`}
                  >
                    <Icon className="w-4 h-4" />
                    {item.name}
                  </a>
                )
              })}
            </nav>
          </div>
        </aside>

        {/* Main Content */}
        <main className="flex-1 md:ml-56 p-6">
          {children}
        </main>
      </div>

      {/* Mobile Bottom Navigation */}
      <div className="md:hidden fixed bottom-0 left-0 right-0 h-14 border-t border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900">
        <nav className="flex h-full">
          {navigation.map((item) => {
            const isActive = window.location.pathname === item.href
            const Icon = item.icon
            return (
              <a
                key={item.name}
                href={item.href}
                className={`flex-1 flex flex-col items-center justify-center gap-1 text-xs ${
                  isActive ? 'text-blue-400' : 'text-slate-400'
                }`}
              >
                <Icon className="w-4 h-4" />
                {item.name}
              </a>
            )
          })}
        </nav>
      </div>
    </div>
  )
}
