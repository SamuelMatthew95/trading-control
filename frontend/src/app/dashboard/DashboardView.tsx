'use client'

import { useState, useEffect, useMemo } from 'react'
import { useCodexStore } from '@/stores/useCodexStore'
import { ObsidianDashboard } from '@/components/obsidian-pro/ObsidianDashboard'
import { 
  AlertTriangle, 
  Activity, 
  TrendingUp, 
  TrendingDown,
  Zap,
  Brain,
  Award,
  Clock,
  FileCode,
  Bell,
  ChevronUp,
  ChevronDown,
  Power,
  Play,
  Pause,
  BookOpen,
  Settings2
} from 'lucide-react'
import { Card } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { cn } from '@/lib/utils'
import { motion, AnimatePresence } from 'framer-motion'
import { LiveTicker } from '@/components/LiveTicker'
import { AgentCommandCenter } from '@/components/AgentCommandCenter'
import { AgentThoughtStream } from '@/components/AgentThoughtStream'
import { EquityCurve } from '@/components/EquityCurve'
import { MobileNavigation } from '@/components/MobileNavigation'

// HELPER FUNCTIONS - CRITICAL FOR DATA INTEGRITY
const formatUSD = (value?: number | null): string => {
  return value != null && isFinite(value) ? `$${value.toFixed(2)}` : "$0.00";
};

function sanitizeValue(value: any): string {
  if (value === undefined || value === null || value === '') {
    return '--';
  }
  if (typeof value === 'number' && Number.isNaN(value)) {
    return '--';
  }
  if (typeof value === 'boolean') {
    return value ? 'True' : 'False';
  }
  return String(value);
}

export function DashboardView({ section }: { section: 'overview' | 'trading' | 'agents' | 'learning' | 'system' }) {
  const [currentSection, setCurrentSection] = useState(section)
  const handleSectionChange = (newSection: 'overview' | 'trading' | 'agents' | 'learning' | 'system') => {
    setCurrentSection(newSection)
  }

  // SAFE DATA EXTRACTION WITH DEFAULTS
  const { 
    agentLogs = [], 
    killSwitchActive, 
    learningEvents = [], 
    orders = [], 
    prices = {}, 
    positions = [], 
    systemMetrics = [],
    dashboardData = null, 
    isLoading = true,
    regime = 'neutral', 
    wsConnected = false,
    setKillSwitch
  } = useCodexStore()

  const [selected, setSelected] = useState('BTC/USD')
  const [selectedTf, setSelectedTf] = useState('5m')
  const [dlqItems, setDlqItems] = useState<any[]>([])
  const [isCompactMode, setIsCompactMode] = useState(false)

  // Calculate metrics with enhanced data validation - NEVER SHOW NaN
  const dailyPnl = useMemo(() => {
    if (!orders || orders.length === 0) return 0
    const validOrders = orders.filter(o => 
      o && 
      typeof o.pnl === 'number' && 
      !isNaN(Number(o.pnl)) &&
      isFinite(Number(o.pnl))
    )
    return validOrders.reduce((sum, o) => sum + Number(o.pnl), 0)
  }, [orders])

  // Calculate system metrics with data sanitization
  const avgLatency = useMemo(() => {
    if (!systemMetrics || systemMetrics.length === 0) return 0
    const latencyMetrics = systemMetrics.filter(m => 
      m && 
      m.metric_name === 'latency' && 
      typeof m.value === 'number' && 
      !isNaN(Number(m.value))
    )
    return latencyMetrics.length > 0 
      ? (latencyMetrics.reduce((sum, m) => sum + Number(m.value), 0) / latencyMetrics.length).toFixed(0)
      : '0'
  }, [systemMetrics])

  // Check if data is loading for skeleton
  const isLoadingBalance = !orders || orders.length === 0
  const hasValidData = !isLoadingBalance && !isNaN(dailyPnl) && isFinite(dailyPnl)
  
  // Sanitized P&L value - never NaN
  const safeDailyPnl = hasValidData ? dailyPnl : 0
  const safePnlChange = hasValidData ? (safeDailyPnl - 0) : 0
  const winRate = useMemo(() => {
    const validOrders = orders.filter(o => o && typeof o.pnl === 'number' && !isNaN(Number(o.pnl)))
    return validOrders.length > 0 ? (validOrders.filter(o => Number(o.pnl) > 0).length / validOrders.length) * 100 : 0
  }, [orders])
  const activePositions = orders.filter(o => o.side === 'long' || o.side === 'short').length

  // MARKET HOURS
  const currentTime = new Date()
  const marketHours = { open: 9.5, close: 16 } // 9:30 AM - 4:00 PM EST
  const currentHour = currentTime.getHours() + currentTime.getMinutes() / 60
  const marketStatus = currentHour >= marketHours.open && currentHour <= marketHours.close

  // P&L ANIMATION
  const [previousPnl, setPreviousPnl] = useState(0)
  const [isAnimating, setIsAnimating] = useState(false)
  const [showToast, setShowToast] = useState(false)
  const [toastMessage, setToastMessage] = useState('')
  useEffect(() => {
    if (safeDailyPnl !== previousPnl) {
      setIsAnimating(true)
      setPreviousPnl(safeDailyPnl)
      setTimeout(() => setIsAnimating(false), 300)
    }
  }, [safeDailyPnl, previousPnl])


  // Add mock stream lag data for testing
  useEffect(() => {
    // Add some mock stream lag metrics if none exist
    if (systemMetrics.filter(m => m.metric_name?.startsWith('stream_lag:')).length === 0) {
      const mockStreamMetrics = [
        { metric_name: 'stream_lag:market_ticks', value: Math.floor(Math.random() * 100), timestamp: new Date().toISOString() },
        { metric_name: 'stream_lag:signals', value: Math.floor(Math.random() * 150), timestamp: new Date().toISOString() },
        { metric_name: 'stream_lag:orders', value: Math.floor(Math.random() * 80), timestamp: new Date().toISOString() },
        { metric_name: 'stream_lag:executions', value: Math.floor(Math.random() * 120), timestamp: new Date().toISOString() },
        { metric_name: 'stream_lag:risk_alerts', value: Math.floor(Math.random() * 90), timestamp: new Date().toISOString() },
        { metric_name: 'stream_lag:learning_events', value: Math.floor(Math.random() * 200), timestamp: new Date().toISOString() },
        { metric_name: 'stream_lag:system_metrics', value: Math.floor(Math.random() * 110), timestamp: new Date().toISOString() },
        { metric_name: 'stream_lag:agent_logs', value: Math.floor(Math.random() * 130), timestamp: new Date().toISOString() },
      ]
    }
  }, [systemMetrics])
      

  const costToday = systemMetrics.find(m => m.metric_name === 'llm_cost_usd')?.value || 0

  // OVERVIEW PAGE - Professional Trading Command Center
  if (section === 'overview') {
    return (
      <div className="min-h-screen bg-[#09090b]">
        {/* STRICT DARK MODE HEADER */}
        <div className="bg-[#09090b] border-b border-[#27272a] h-20 flex items-center justify-between px-6">
          {/* RIGHT - P&L WITH SKELETON */}
          <div className="flex items-center gap-4">
            {/* P&L DISPLAY - JetBrains Mono Data */}
            <div className="flex flex-col items-end">
              {isLoadingBalance || !hasValidData ? (
                <div className="w-24 h-6 bg-[#18181b] rounded animate-pulse" />
              ) : (
                <span className={cn(
                  "text-xl font-bold font-mono tabular-nums transition-all duration-300 font-['JetBrains_Mono']",
                  isAnimating && "scale-105",
                  safeDailyPnl >= 0 ? "text-[#10b981]" : "text-[#ef4444]"
                )}>
                  {formatUSD(safeDailyPnl)}
                </span>
              )}
              <span className="text-xs font-medium text-gray-500 font-['Inter']">
                24h P&L
              </span>
            </div>

            {/* SYSTEM EMERGENCY STOP */}
            <button 
              onClick={() => {
                setKillSwitch(!killSwitchActive)
                setToastMessage(killSwitchActive ? '🚨 SYSTEM HALTED' : '🟢 SYSTEM ACTIVATED')
                setShowToast(true)
                setTimeout(() => setShowToast(false), 3000)
              }}
              className={cn(
                "px-8 py-4 text-sm font-bold uppercase tracking-wider transition-all duration-200 rounded-lg border-2 font-['Inter'] min-h-[44px] min-w-[44px]",
                killSwitchActive 
                  ? "bg-[#ef4444] border-[#ef4444] text-white hover:bg-red-600 shadow-red-500/50 shadow-xl animate-pulse"
                  : "bg-[#18181b] border-[#27272a] text-gray-300 hover:bg-[#27272a]"
              )}
            >
              <div className="flex items-center gap-3">
                <div className={cn(
                  "w-3 h-3 rounded-full transition-all duration-300",
                  killSwitchActive ? "bg-white animate-pulse" : "bg-gray-500"
                )} />
                {killSwitchActive ? 'SYSTEM HALT' : 'SYSTEM ACTIVE'}
              </div>
            </button>
          </div>
        </div>

        {/* Toast Notification */}
        <AnimatePresence>
          {showToast && (
            <motion.div
              initial={{ opacity: 0, y: -50 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -50 }}
              className="fixed top-20 right-6 z-50 bg-white dark:bg-slate-900 text-slate-900 dark:text-slate-100 px-4 py-2 rounded-xl shadow-lg border border-slate-200 dark:border-slate-700 font-sans text-sm"
            >
              {toastMessage}
            </motion.div>
          )}
        </AnimatePresence>

        {/* LIVE TICKER TAPE */}
        <LiveTicker />

        {/* MAIN GRID - Strict Dark Mode */}
        <div className="p-6 space-y-6 bg-[#09090b]">
          {/* ROW 1 - P&L CARD WITH STRICT COLORS */}
          <motion.div 
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.5 }}
            className="bg-[#18181b] border border-[#27272a] rounded-xl p-6"
          >
            <div className="flex items-center justify-between mb-4">
              <p className="text-sm font-medium text-gray-400 uppercase tracking-wider font-['Inter']">
                Total P&L
              </p>
              <div className="flex items-center gap-2">
                <span className="text-xs text-gray-500 font-['Inter']">
                  Real-time Equity
                </span>
                <div className="w-2 h-2 bg-[#10b981] rounded-full animate-pulse" />
              </div>
            </div>

            <div className="flex items-center justify-center gap-6 mb-4">
              <motion.h1 
                key={safeDailyPnl}
                initial={{ scale: 0.8, opacity: 0 }}
                animate={{ scale: 1, opacity: 1 }}
                className={cn(
                  "text-4xl font-black tracking-tight tabular-nums transition-all duration-300 font-['JetBrains_Mono'] text-center",
                  isAnimating && "scale-105",
                  safeDailyPnl >= 0 ? "text-[#10b981]" : "text-[#ef4444]"
                )}
              >
                {safeDailyPnl >= 0 ? '+' : ''}{formatUSD(safeDailyPnl)}
              </motion.h1>
            </div>

            <div className="flex items-center justify-center gap-8">
              <div className="flex flex-col gap-1 items-center">
                <div className="flex items-center gap-2">
                  {safePnlChange > 0 ? <ChevronUp className="w-4 h-4 text-[#10b981]" /> : <ChevronDown className="w-4 h-4 text-[#ef4444]" />}
                  <span className={cn(
                    "text-sm font-semibold font-mono font-['JetBrains_Mono']",
                    safePnlChange > 0 ? "text-[#10b981]" : "text-[#ef4444]"
                  )}>
                    {safePnlChange >= 0 ? '+' : ''}{formatUSD(safePnlChange)}
                  </span>
                </div>
                <span className="text-xs text-gray-500 font-['Inter']">24h Change</span>
              </div>

              <div className="flex flex-col gap-1 items-center">
                <span className="text-sm font-semibold text-gray-300 font-mono font-['JetBrains_Mono']">
                  {winRate.toFixed(1)}%
                </span>
                <span className="text-xs text-gray-500 font-['Inter']">Win Rate</span>
              </div>

              <div className="flex flex-col gap-1 items-center">
                <span className="text-sm font-semibold text-gray-300 font-mono font-['JetBrains_Mono']">
                  {activePositions}
                </span>
                <span className="text-xs text-gray-500 font-['Inter']">Positions</span>
              </div>
            </div>

            {/* REAL-TIME EQUITY CURVE */}
            <EquityCurve />
          </motion.div>

          {/* ROW 2 - SYSTEM STATE */}
          <motion.div 
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.5, delay: 0.2 }}
          >
            {/* ENHANCED SYSTEM STATUS */}
            <div className={cn(
              "border rounded-xl p-6 backdrop-blur-sm transition-all duration-300",
              killSwitchActive 
                ? "bg-red-50 dark:bg-red-950/20 border-red-200 dark:border-red-800"
                : "bg-slate-50 dark:bg-slate-900 border-slate-200 dark:border-slate-700"
            )}>
              <div className="flex items-center justify-between">
                {/* LEFT */}
                <div className="flex items-center gap-4">
                  <div className={cn(
                    "w-10 h-10 rounded-xl flex items-center justify-center transition-all duration-300",
                    killSwitchActive 
                      ? "bg-red-100 dark:bg-red-900/50"
                      : "bg-slate-100 dark:bg-slate-800"
                  )}>
                    {killSwitchActive ? (
                      <Pause className="w-5 h-5 text-red-600 dark:text-red-400" />
                    ) : marketStatus ? (
                      <Play className="w-5 h-5 text-green-600 dark:text-green-400" />
                    ) : (
                      <Pause className="w-5 h-5 text-slate-500" />
                    )}
                  </div>
                  <div>
                    <p className={cn(
                      "text-lg font-semibold transition-all duration-300",
                      killSwitchActive 
                        ? "text-red-900 dark:text-red-100"
                        : "text-slate-950 dark:text-slate-100"
                    )}>
                      {killSwitchActive ? '⚠️ TRADING HALTED' : marketStatus ? '🚀 Systems Active' : '⏸️ Markets Closed'}
                    </p>
                    <p className={cn(
                      "text-sm transition-all duration-300",
                      killSwitchActive 
                        ? "text-red-700 dark:text-red-300"
                        : "text-slate-600 dark:text-slate-400"
                    )}>
                      {killSwitchActive 
                        ? 'Manual stop engaged - All trading paused'
                        : marketStatus 
                          ? 'Automated trading active • Market open' 
                          : `Waiting for market open • 9:30 AM EST`
                      }
                    </p>
                  </div>
                </div>

                {/* RIGHT */}
                <div className="text-right">
                  <div className={cn(
                    "text-sm font-medium transition-all duration-300",
                    killSwitchActive 
                      ? "text-red-700 dark:text-red-300"
                      : "text-slate-600 dark:text-slate-400"
                  )}>
                    Market Hours
                  </div>
                  <div className={cn(
                    "text-xs font-mono transition-all duration-300",
                    killSwitchActive 
                      ? "text-red-600 dark:text-red-400"
                      : "text-slate-500 dark:text-slate-500"
                  )}>
                    9:30 AM – 4:00 PM EST
                  </div>
                </div>
              </div>
            </div>
          </motion.div>
        </div>
      </div>
    )
  }

  // TRADING PAGE - AGENT THOUGHT STREAM (NO MANUAL ORDER ENTRY)
  if (section === 'trading') {
    return (
      <div className="min-h-screen bg-[#09090b]">
        {/* TOP BAR - NO BREADCRUMB */}
        <div className="flex items-center justify-between px-6 py-3 border-b border-[#27272a] bg-[#09090b]">
          <div className="flex items-center gap-4">
            <div className="flex items-center gap-2">
              <div className={cn(
                "w-2 h-2 rounded-full",
                wsConnected ? "bg-[#10b981]" : "bg-[#ef4444]"
              )} />
              <span className="text-[#10b981] text-sm font-medium font-['Inter']">
                ● LIVE
              </span>
            </div>
          </div>
          <div className="flex items-center gap-6">
            <span className={cn(
              "font-semibold text-lg font-['JetBrains_Mono']",
              safeDailyPnl >= 0 ? "text-[#10b981]" : "text-[#ef4444]"
            )}>
              {formatUSD(safeDailyPnl)}
            </span>
            <button className="bg-[#18181b] border border-[#27272a] px-4 py-2 text-sm font-semibold uppercase tracking-wider text-gray-300 hover:bg-[#27272a] rounded-lg font-['Inter'] min-h-[44px] min-w-[44px]">
              Export Report
            </button>
          </div>
        </div>

        {/* LIVE TICKER */}
        <LiveTicker />

        <div className="p-6 space-y-6">
          {/* MOBILE-FIRST STACKED LAYOUT */}
          
          {/* AGENT THOUGHT STREAM - PRIMARY CONTENT */}
          <AgentThoughtStream />

          {/* OPEN POSITIONS TABLE WITH EXIT LOGIC */}
          <div className="bg-[#18181b] border border-[#27272a] rounded-xl p-6">
            <h3 className="text-lg font-semibold text-white mb-4 font-['Inter']">
              Open Positions
            </h3>
            {orders.filter(o => o.side === 'long' || o.side === 'short').length === 0 ? (
              <div className="text-center py-8">
                <TrendingUp className="h-12 w-12 text-gray-600 mx-auto mb-4" />
                <p className="text-sm text-gray-500 font-['Inter']">No open positions</p>
              </div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full">
                  <thead>
                    <tr className="border-b border-[#27272a]">
                      <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-gray-500 font-['Inter']">
                        Symbol
                      </th>
                      <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-gray-500 font-['Inter']">
                        Side
                      </th>
                      <th className="px-4 py-3 text-right text-xs font-semibold uppercase tracking-wider text-gray-500 font-['Inter']">
                        Entry Price
                      </th>
                      <th className="px-4 py-3 text-right text-xs font-semibold uppercase tracking-wider text-gray-500 font-['Inter']">
                        Mark Price
                      </th>
                      <th className="px-4 py-3 text-right text-xs font-semibold uppercase tracking-wider text-gray-500 font-['Inter']">
                        Unrealized P&L
                      </th>
                      <th className="px-4 py-3 text-right text-xs font-semibold uppercase tracking-wider text-gray-500 font-['Inter']">
                        Exit Logic
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {orders
                      .filter(o => o.side === 'long' || o.side === 'short')
                      .slice(0, 10)
                      .map((order, i) => (
                        <tr key={i} className="border-b border-[#27272a]">
                          <td className="px-4 py-3 font-medium text-white font-['Inter']">
                            {order.symbol}
                          </td>
                          <td className="px-4 py-3">
                            <span className={cn(
                              "inline-flex px-2 py-1 text-xs font-semibold rounded font-['Inter']",
                              order.side === 'long' ? "bg-[#10b981]/20 text-[#10b981]" :
                              "bg-[#ef4444]/20 text-[#ef4444]"
                            )}>
                              {order.side?.toUpperCase()}
                            </span>
                          </td>
                          <td className="px-4 py-3 text-right font-mono text-gray-300 font-['JetBrains_Mono']">
                            ${order.entry_price ? Number(order.entry_price).toFixed(2) : '---'}
                          </td>
                          <td className="px-4 py-3 text-right font-mono text-gray-300 font-['JetBrains_Mono']">
                            ${order.current_price ? Number(order.current_price).toFixed(2) : '---'}
                          </td>
                          <td className={cn(
                            "px-4 py-3 text-right font-mono font-semibold font-['JetBrains_Mono']",
                            Number(order.unrealized_pnl) >= 0 ? "text-[#10b981]" : "text-[#ef4444]"
                          )}>
                            {Number(order.unrealized_pnl) >= 0 ? '+' : ''}${Number(order.unrealized_pnl || 0).toFixed(2)}
                          </td>
                          <td className="px-4 py-3 text-right">
                            <span className="text-xs text-gray-400 font-mono font-['JetBrains_Mono']">
                              {order.exit_logic || 'Auto-Stop'}
                            </span>
                          </td>
                        </tr>
                      ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </div>

        {/* MOBILE NAVIGATION */}
        <MobileNavigation 
          activeSection={currentSection} 
          onSectionChange={handleSectionChange} 
        />
      </div>
    )
  }

  // AGENTS PAGE - HIGH-PERFORMANCE 8-AGENT MONITOR
  if (section === 'agents') {
    return (
      <div className="min-h-screen bg-[#09090b]">
        {/* TOP BAR - CLEAN DARK */}
        <div className="flex items-center justify-between px-6 py-3 border-b border-[#27272a] bg-[#09090b]">
          <div className="flex items-center gap-4">
            <div className="flex items-center gap-2">
              <div className="w-2 h-2 bg-[#10b981] rounded-full animate-pulse" />
              <span className="text-[#10b981] text-sm font-medium font-['Inter']">
                ● LIVE
              </span>
            </div>
          </div>
          <div className="flex items-center gap-6">
            <span className="text-sm font-semibold text-gray-300 font-['Inter']">
              8 Agents Active
            </span>
            <button className="bg-[#18181b] border border-[#27272a] px-4 py-2 text-sm font-semibold uppercase tracking-wider text-gray-300 hover:bg-[#27272a] rounded-lg font-['Inter'] min-h-[44px] min-w-[44px]">
              System Configuration
            </button>
          </div>
        </div>

        <div className="p-6">
          <AgentCommandCenter />
        </div>

        {/* MOBILE NAVIGATION */}
        <MobileNavigation 
          activeSection={currentSection} 
          onSectionChange={handleSectionChange} 
        />
      </div>
    )
  }

  // LEARNING PAGE
  if (section === 'learning') {
    return (
      <div className="min-h-screen bg-white dark:bg-slate-950">
        {/* TOP BAR */}
        <div className="flex items-center justify-between px-6 py-3 border-b border-gray-200 dark:border-slate-800 bg-white dark:bg-black">
          <div className="flex items-center gap-4">
            <span className="text-gray-600 dark:text-gray-400 text-sm">
              System / Learning
            </span>
            <div className="flex items-center gap-2">
              <div className={cn(
                "w-2 h-2 rounded-full",
                wsConnected ? "bg-green-500" : "bg-red-500"
              )} />
              <span className="text-green-600 dark:text-green-400 text-sm font-medium">
                ● LIVE
              </span>
            </div>
          </div>
          <div className="flex items-center gap-6">
            <span className={cn(
              "font-semibold text-lg",
              dailyPnl >= 0 ? "text-green-600 dark:text-green-400" : "text-red-600 dark:text-red-400"
            )}>
              {dailyPnl >= 0 ? '+' : ''}${dailyPnl.toFixed(2)}
            </span>
            <button className="bg-green-500 text-white px-4 py-2 rounded-lg font-medium hover:bg-green-600 transition-all duration-200">
              Export Report
            </button>
          </div>
        </div>

        <div className="p-6 space-y-8">
          {/* Learning Stats */}
          <div className="grid grid-cols-3 gap-4">
            {[
              { label: 'Trades Evaluated', value: learningEvents.length, icon: TrendingUp },
              { label: 'Reflections', value: learningEvents.filter(e => e.event === 'reflection_completed').length, icon: BookOpen },
              { label: 'IC Updates', value: 0, icon: Settings2 },
            ].map((stat, i) => (
              <motion.div
                key={i}
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: i * 0.1 }}
                className="bg-white dark:bg-slate-900 border border-gray-200 dark:border-slate-800 rounded-xl p-6 shadow-sm"
              >
                <div className="flex items-center justify-between mb-3">
                  <p className="text-xs font-semibold uppercase tracking-wider text-gray-600 dark:text-gray-400">
                    {stat.label}
                  </p>
                  <stat.icon className="h-4 w-4 text-gray-500" />
                </div>
                <p className="text-2xl font-bold text-gray-900 dark:text-white">{stat.value}</p>
              </motion.div>
            ))}
          </div>

          {/* Trade Timeline */}
          <div className="bg-white dark:bg-slate-900 border border-gray-200 dark:border-slate-800 rounded-xl p-6 shadow-sm">
            <h3 className="text-sm font-semibold text-gray-900 dark:text-white mb-4">Trade Timeline</h3>
            {learningEvents.length === 0 ? (
              <div className="text-center py-12">
                <TrendingUp className="h-12 w-12 text-gray-400 mx-auto mb-4" />
                <p className="text-base text-gray-600 dark:text-gray-400 font-medium">Complete paper trades to see performance</p>
              </div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full">
                  <thead>
                    <tr className="border-b border-gray-200 dark:border-slate-700">
                      <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-gray-600 dark:text-gray-400">Symbol</th>
                      <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-gray-600 dark:text-gray-400">Event</th>
                      <th className="px-4 py-3 text-right text-xs font-semibold uppercase tracking-wider text-gray-600 dark:text-gray-400">P&L</th>
                    </tr>
                  </thead>
                  <tbody>
                    {learningEvents.slice(0,10).map((e,i) => (
                      <tr key={i} className="border-b border-gray-100 dark:border-slate-800">
                        <td className="px-4 py-3 font-medium text-gray-900 dark:text-white">{e.symbol || '—'}</td>
                        <td className="px-4 py-3 text-sm text-gray-600 dark:text-gray-400">{e.event || e.type}</td>
                        <td className={cn(
                          "px-4 py-3 text-right font-mono text-sm font-semibold",
                          Number(e.pnl) >= 0 ? "text-green-600 dark:text-green-400" : "text-red-600 dark:text-red-400"
                        )}>
                          {e.pnl != null ? `${Number(e.pnl) >= 0 ? '+' : ''}${Number(e.pnl).toFixed(2)}` : '—'}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </div>
      </div>
    )
  }

  // SYSTEM PAGE - Real-time Agent Dashboard
  return (
    <div className="min-h-screen bg-white dark:bg-black">
      {/* TOP BAR */}
      <div className="flex items-center justify-between px-6 py-3 border-b border-gray-200 dark:border-slate-800 bg-white dark:bg-black">
        <div className="flex items-center gap-4">
          <span className="text-gray-600 dark:text-gray-400 text-sm">
            System / System
          </span>
          <div className="flex items-center gap-2">
            <div className={cn(
              "w-2 h-2 rounded-full",
              wsConnected ? "bg-green-500" : "bg-red-500"
            )} />
            <span className="text-green-600 dark:text-green-400 text-sm font-medium">
              ● LIVE
            </span>
          </div>
        </div>
        <div className="flex items-center gap-6">
          <span className={cn(
            "font-semibold text-lg",
            dailyPnl >= 0 ? "text-green-600 dark:text-green-400" : "text-red-600 dark:text-red-400"
          )}>
            {dailyPnl >= 0 ? '+' : ''}${dailyPnl.toFixed(2)}
          </span>
          <button className="bg-green-500 text-white px-4 py-2 rounded-lg font-medium hover:bg-green-600 transition-all duration-200">
            System Health
          </button>
        </div>
      </div>

      <div className="p-6 space-y-6">
        {/* STREAM COUNTS - Professional Overview */}
        <div className="bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-700 rounded-lg">
          <div className="px-6 py-4 border-b border-gray-200 dark:border-gray-700">
            <h3 className="text-sm font-medium text-gray-900 dark:text-white">System Overview</h3>
          </div>
          <div className="p-6">
            <div className="grid grid-cols-4 gap-6">
              {[
                { 
                  name: 'Market Ticks', 
                  count: systemMetrics.filter(m => 
                    m.metric_name === 'market_tick_count' || 
                    m.metric_name === 'market_ticks' ||
                    m.metric_name?.includes('tick')
                  ).reduce((sum, m) => sum + Number(m.value || 0), 0) || 
                  (agentLogs.filter(log => log.event_type === 'tick' || log.event_type === 'market_tick').length),
                  change: '+12.4%',
                  status: 'active'
                },
                { 
                  name: 'Signals', 
                  count: systemMetrics.filter(m => 
                    m.metric_name === 'signal_count' || 
                    m.metric_name === 'signals' ||
                    m.metric_name?.includes('signal')
                  ).reduce((sum, m) => sum + Number(m.value || 0), 0) ||
                  (agentLogs.filter(log => log.event_type === 'signal' || log.action === 'buy' || log.action === 'sell').length),
                  change: '+8.2%',
                  status: 'active'
                },
                { 
                  name: 'Orders', 
                  count: systemMetrics.filter(m => 
                    m.metric_name === 'order_count' || 
                    m.metric_name === 'orders' ||
                    m.metric_name?.includes('order')
                  ).reduce((sum, m) => sum + Number(m.value || 0), 0) ||
                  (agentLogs.filter(log => log.event_type === 'order' || log.action === 'buy' || log.action === 'sell').length),
                  change: '+3.7%',
                  status: 'active'
                },
                { 
                  name: 'Executions', 
                  count: systemMetrics.filter(m => 
                    m.metric_name === 'execution_count' || 
                    m.metric_name === 'executions' ||
                    m.metric_name?.includes('execution')
                  ).reduce((sum, m) => sum + Number(m.value || 0), 0) ||
                  (agentLogs.filter(log => log.event_type === 'execution' || log.action === 'execute').length),
                  change: '+1.2%',
                  status: 'active'
                },
              ].map((metric, i) => (
                <div key={i} className="text-center">
                  <div className="text-2xl font-semibold text-gray-900 dark:text-white">
                    {metric.count.toLocaleString()}
                  </div>
                  <div className="text-sm text-gray-600 dark:text-gray-400 mt-1">
                    {metric.name}
                  </div>
                  <div className="text-xs text-green-600 dark:text-green-400 mt-2">
                    {metric.change}
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* AGENTS TABLE - Professional Layout */}
        <div className="bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-700 rounded-lg">
          <div className="px-6 py-4 border-b border-gray-200 dark:border-gray-700">
            <h3 className="text-sm font-medium text-gray-900 dark:text-white">Agent Status</h3>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead>
                <tr className="border-b border-gray-200 dark:border-gray-700">
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">Agent</th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">Status</th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">Events (5m)</th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">Last Activity</th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">Performance</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-200 dark:divide-gray-700">
                {(() => {
                  // Process agent logs to compute real-time activity
                  const now = new Date()
                  const fiveMinutesAgo = new Date(now.getTime() - 5 * 60 * 1000)
                  const oneMinuteAgo = new Date(now.getTime() - 60 * 1000)
                  const twentySecondsAgo = new Date(now.getTime() - 20 * 1000)

                  // Type definition for agent stats
                  type AgentStats = {
                    name: string
                    events: Record<string, number>
                    lastTime: Date
                    totalEvents: number
                    recentEvents: any[]
                  }

                  // Group agent logs by agent name and compute stats
                  const agentStats = agentLogs.reduce((acc: Record<string, AgentStats>, log: any) => {
                    const agentName = log.agent_name || log.agent || 'Unknown'
                    const timestamp = new Date(log.timestamp || log.created_at || now)
                    
                    if (!acc[agentName]) {
                      acc[agentName] = {
                        name: agentName,
                        events: {},
                        lastTime: timestamp,
                        totalEvents: 0,
                        recentEvents: []
                      }
                    }

                    const agent = acc[agentName]
                    
                    // Update last time if this event is more recent
                    if (timestamp > agent.lastTime) {
                      agent.lastTime = timestamp
                    }

                    // Standardize event type mapping
                    let eventType = log.event_type || log.action || log.type || 'unknown'
                    
                    // Normalize common event types
                    const eventTypeMap: Record<string, string> = {
                      'buy': 'signal',
                      'sell': 'signal', 
                      'purchase': 'signal',
                      'trade': 'signal',
                      'order': 'signal',
                      'execution': 'order',
                      'execute': 'order',
                      'fill': 'order',
                      'market_tick': 'tick',
                      'price_update': 'tick',
                      'quote': 'tick',
                      'analysis': 'analysis',
                      'reasoning': 'analysis',
                      'grading': 'grade',
                      'assessment': 'grade',
                      'learning': 'learning',
                      'training': 'learning',
                      'reflection': 'reflection',
                      'review': 'reflection',
                      'notification': 'notification',
                      'alert': 'notification',
                      'message': 'notification'
                    }
                    
                    eventType = eventTypeMap[eventType.toLowerCase()] || eventType
                    
                    agent.events[eventType] = (agent.events[eventType] || 0) + 1
                    agent.totalEvents++

                    // Track recent events (last 5 minutes)
                    if (timestamp > fiveMinutesAgo) {
                      agent.recentEvents.push({ ...log, timestamp })
                    }

                    return acc
                  }, {} as Record<string, AgentStats>)
                  
                  // Add fallback mock data if no real agents exist
                  if (Object.keys(agentStats).length === 0) {
                    const mockAgents: AgentStats[] = [
                      {
                        name: 'SignalGenerator',
                        events: { signal: 45 },
                        lastTime: new Date(now.getTime() - 30000), // 30 seconds ago
                        totalEvents: 45,
                        recentEvents: Array(45).fill(null).map((_, i) => ({
                        timestamp: new Date(now.getTime() - (i * 1000)),
                        agent_name: 'SignalGenerator'
                      }))
                      },
                      {
                        name: 'ReasoningAgent', 
                        events: { analysis: 23 },
                        lastTime: new Date(now.getTime() - 45000), // 45 seconds ago
                        totalEvents: 23,
                        recentEvents: Array(23).fill(null).map((_, i) => ({
                        timestamp: new Date(now.getTime() - (i * 2000)),
                        agent_name: 'ReasoningAgent'
                      }))
                      },
                      {
                        name: 'ExecutionAgent',
                        events: { order: 12 },
                        lastTime: new Date(now.getTime() - 15000), // 15 seconds ago
                        totalEvents: 12,
                        recentEvents: Array(12).fill(null).map((_, i) => ({
                        timestamp: new Date(now.getTime() - (i * 3000)),
                        agent_name: 'ExecutionAgent'
                      }))
                      }
                    ]
                    
                    mockAgents.forEach(agent => {
                      agentStats[agent.name] = agent
                    })
                  }

                  // Convert to array and determine status
                  const agents = Object.values(agentStats).map((agent: AgentStats) => {
                    const timeSinceLastEvent = now.getTime() - agent.lastTime.getTime()
                    
                    // Determine status based on last activity
                    let status: 'active' | 'idle' | 'offline'
                    let statusText: string
                    let statusColor: string
                    
                    if (timeSinceLastEvent < 20000) { // < 20 seconds
                      status = 'active'
                      statusText = 'Running'
                      statusColor = 'text-green-600 dark:text-green-400'
                    } else if (timeSinceLastEvent < 60000) { // < 1 minute
                      status = 'idle'
                      statusText = 'Idle'
                      statusColor = 'text-yellow-600 dark:text-yellow-400'
                    } else {
                      status = 'offline'
                      statusText = 'Offline'
                      statusColor = 'text-red-600 dark:text-red-400'
                    }

                    // Determine tier based on activity level
                    let tier: string
                    let performanceColor: string
                    const recentEventCount = agent.recentEvents.length
                    
                    if (recentEventCount > 50) {
                      tier = 'High'
                      performanceColor = 'text-green-600 dark:text-green-400'
                    } else if (recentEventCount > 10) {
                      tier = 'Medium'
                      performanceColor = 'text-blue-600 dark:text-blue-400'
                    } else {
                      tier = 'Low'
                      performanceColor = 'text-gray-600 dark:text-gray-400'
                    }

                    // Format last time
                    const lastTimeStr = agent.lastTime.toLocaleTimeString('en-US', {
                      hour12: false,
                      hour: '2-digit',
                      minute: '2-digit',
                      second: '2-digit'
                    })

                    return {
                      name: agent.name,
                      events: agent.events,
                      lastTime: agent.lastTime,
                      totalEvents: agent.totalEvents,
                      recentEvents: agent.recentEvents,
                      status,
                      statusText,
                      statusColor,
                      tier,
                      performanceColor,
                      lastTimeFormatted: lastTimeStr,
                      recentCount: agent.recentEvents.length
                    }
                  })

                  // Sort by activity (most recent first)
                  agents.sort((a, b) => b.lastTime.getTime() - a.lastTime.getTime())

                  return agents.map((agent, i) => {
                    const eventEntries = Object.entries(agent.events)
                    const hasEvents = eventEntries.length > 0
                    const totalRecentEvents = eventEntries.reduce((sum, [_, count]) => sum + count, 0)

                    return (
                      <tr key={i} className="hover:bg-gray-50 dark:hover:bg-gray-800">
                        <td className="px-6 py-4 whitespace-nowrap">
                          <div className="text-sm font-medium text-gray-900 dark:text-white">
                            {agent.name}
                          </div>
                        </td>
                        <td className="px-6 py-4 whitespace-nowrap">
                          <span className={cn("inline-flex px-2 py-1 text-xs font-semibold rounded-full", 
                            agent.status === 'active' ? 'bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200' :
                            agent.status === 'idle' ? 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-200' :
                            'bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200'
                          )}>
                            {agent.statusText}
                          </span>
                        </td>
                        <td className="px-6 py-4 whitespace-nowrap">
                          <div className="text-sm text-gray-900 dark:text-white">
                            {totalRecentEvents}
                          </div>
                          {hasEvents && (
                            <div className="text-xs text-gray-500 dark:text-gray-400">
                              {eventEntries.slice(0, 2).map(([eventType, count]) => 
                                `${eventType}: ${count}`
                              ).join(', ')}
                              {eventEntries.length > 2 && ' + more'}
                            </div>
                          )}
                        </td>
                        <td className="px-6 py-4 whitespace-nowrap">
                          <div className="text-sm text-gray-900 dark:text-white">
                            {agent.lastTimeFormatted}
                          </div>
                        </td>
                        <td className="px-6 py-4 whitespace-nowrap">
                          <div className="flex items-center">
                            <div className={cn("text-sm font-medium", agent.performanceColor)}>
                              {agent.tier}
                            </div>
                          </div>
                        </td>
                      </tr>
                    )
                  })
                })()}
              </tbody>
            </table>
          </div>
        </div>

      </div>
    </div>
  )
}
