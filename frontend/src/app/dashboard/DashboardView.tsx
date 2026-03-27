'use client'

import { useState, useEffect, useMemo } from 'react'
import { useCodexStore } from '@/stores/useCodexStore'
import { 
  TrendingUp, 
  TrendingDown, 
  Power, 
  Sun, 
  Moon
} from 'lucide-react'
import { cn } from '@/lib/utils'
import { motion } from 'framer-motion'
import { EquityCurve } from '@/components/EquityCurve'
import { MobileNavigation } from '@/components/MobileNavigation'

// NUCLEAR RESET: Senior-Engineer Grade Helper Functions
const formatUSD = (value?: number | null): string => {
  return value != null && isFinite(value) ? `$${value.toFixed(2)}` : "$0.00";
};

const sanitizeValue = (value: any): string => {
  if (value === undefined || value === null || value === '') return '--';
  if (typeof value === 'number' && Number.isNaN(value)) return '--';
  if (typeof value === 'boolean') return value ? 'True' : 'False';
  return String(value);
};

export function DashboardView({ section }: { section: 'overview' | 'trading' | 'agents' | 'learning' | 'system' }) {
  const [isDarkMode, setIsDarkMode] = useState(true)
  const [previousPnl, setPreviousPnl] = useState(0)
  const [isAnimating, setIsAnimating] = useState(false)

  // SAFE DATA EXTRACTION WITH DEFAULTS
  const { 
    agentLogs = [], 
    killSwitchActive, 
    orders = [], 
    systemMetrics = [],
    wsConnected = false,
    setKillSwitch
  } = useCodexStore()

  // NUCLEAR RESET: Calculate metrics with NaN-proof logic
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

  const safeDailyPnl = dailyPnl || 0
  const safePnlChange = safeDailyPnl - 0
  const winRate = useMemo(() => {
    const validOrders = orders.filter(o => o && typeof o.pnl === 'number' && !isNaN(Number(o.pnl)))
    return validOrders.length > 0 ? (validOrders.filter(o => Number(o.pnl) > 0).length / validOrders.length) * 100 : 0
  }, [orders])
  const activePositions = orders.filter(o => o.side === 'long' || o.side === 'short').length

  // Market status
  const currentTime = new Date()
  const marketHours = { open: 9.5, close: 16 }
  const currentHour = currentTime.getHours() + currentTime.getMinutes() / 60
  const marketStatus = currentHour >= marketHours.open && currentHour <= marketHours.close

  // P&L Animation
  useEffect(() => {
    if (safeDailyPnl !== previousPnl) {
      setIsAnimating(true)
      setPreviousPnl(safeDailyPnl)
      setTimeout(() => setIsAnimating(false), 300)
    }
  }, [safeDailyPnl, previousPnl])

  // Mock agents data
  const agents = [
    { id: '1', name: 'SignalGenerator', tier: 'active', heartbeat: true, metrics: { 'Status': 'ACTIVE', 'NVDA': '1,247', 'SPY': '892', 'Latency': '12ms' } },
    { id: '2', name: 'ReasoningAgent', tier: 'active', heartbeat: true, metrics: { 'Provider': 'Groq', 'Decisions': '847', 'Latency': '45ms', 'Success': '94.2%' } },
    { id: '3', name: 'GradeAgent', tier: 'active', heartbeat: true, metrics: { 'Grade': 'A-', 'Action': 'Weight Cut', 'Accuracy': '94.2%', 'Weight': '0.82' } },
    { id: '4', name: 'ICUpdater', tier: 'challenger', heartbeat: false, metrics: { 'Correlation': '0.73', 'Metric': 'Spearman', 'Sync': '2m ago', 'Weights': 'Updated' } },
    { id: '5', name: 'ReflectionAgent', tier: 'active', heartbeat: true, metrics: { 'Hypotheses': '142', 'Next Run': '5m', 'Success': '68%', 'Insight': 'Volume' } },
    { id: '6', name: 'StrategyProposer', tier: 'active', heartbeat: true, metrics: { 'PRs': '3', 'Auto-Deploy': 'True', 'Strategies': '12', 'Deploy': '1h ago' } },
    { id: '7', name: 'HistoryAgent', tier: 'retired', heartbeat: false, metrics: { 'Cron': 'Success', 'Patterns': '28', 'Seasonality': 'Detected', 'Run': '6d ago' } },
    { id: '8', name: 'NotificationAgent', tier: 'active', heartbeat: true, metrics: { 'Stream': 'Redis', 'Severity': 'Normal', 'Queue': '0', 'Alerts': '2' } },
  ]

  // Mock ticker data
  const tickerData = [
    { symbol: 'NVDA', price: 875.28, change: 2.34, changePercent: 0.27 },
    { symbol: 'SPY', price: 512.43, change: -1.12, changePercent: -0.22 },
    { symbol: 'AAPL', price: 178.92, change: 0.85, changePercent: 0.48 },
    { symbol: 'BTC', price: 67234.56, change: 1234.78, changePercent: 1.87 },
    { symbol: 'ETH', price: 3456.78, change: -45.23, changePercent: -1.29 },
    { symbol: 'SOL', price: 145.67, change: 3.21, changePercent: 2.25 },
  ]

  // OVERVIEW PAGE - Nuclear Reset Implementation
  if (section === 'overview') {
    return (
      <div className={cn(
        "min-h-screen transition-colors duration-300",
        isDarkMode ? "bg-slate-950" : "bg-slate-50"
      )}>
        {/* NUCLEAR RESET: Professional Header */}
        <div className={cn(
          "h-10 border-b transition-colors duration-300",
          isDarkMode ? "bg-slate-900 border-slate-800" : "bg-white border-slate-200"
        )}>
          <div className="max-w-7xl mx-auto px-4 h-full flex items-center justify-between">
            {/* Left: Title + Connection Status */}
            <div className="flex items-center gap-4">
              <h1 className={cn(
                "text-sm font-bold uppercase tracking-wider font-['Inter']",
                isDarkMode ? "text-white" : "text-slate-900"
              )}>
                Trading Console
              </h1>
              <div className="flex items-center gap-2">
                <div className={cn(
                  "w-2 h-2 rounded-full animate-pulse",
                  wsConnected ? "bg-emerald-500" : "bg-slate-400"
                )} />
                <span className={cn(
                  "text-xs font-semibold uppercase tracking-wider font-['Inter']",
                  wsConnected ? "text-emerald-500" : "text-slate-400"
                )}>
                  {wsConnected ? 'LIVE' : 'OFFLINE'}
                </span>
              </div>
            </div>

            {/* Center: Daily P&L with NaN Guard */}
            <div className="flex items-center gap-6">
              <motion.div
                key={safeDailyPnl}
                initial={{ scale: 0.95, opacity: 0 }}
                animate={{ scale: 1, opacity: 1 }}
                className={cn(
                  "text-xl font-black tabular-nums font-['JetBrains_Mono'] transition-all duration-300",
                  isAnimating && "scale-105",
                  safeDailyPnl >= 0 ? "text-emerald-500" : "text-red-500",
                  !isDarkMode && safeDailyPnl >= 0 ? "text-emerald-600" : "",
                  !isDarkMode && safeDailyPnl < 0 ? "text-red-600" : ""
                )}
              >
                {formatUSD(safeDailyPnl)}
              </motion.div>
              <span className={cn(
                "text-xs font-semibold uppercase tracking-wider font-['Inter']",
                isDarkMode ? "text-slate-400" : "text-slate-500"
              )}>
                Daily P&L
              </span>
            </div>

            {/* Right: Dark Mode Toggle + Kill Switch */}
            <div className="flex items-center gap-3">
              {/* Dark Mode Toggle */}
              <button
                onClick={() => setIsDarkMode(!isDarkMode)}
                className={cn(
                  "w-8 h-8 rounded-lg flex items-center justify-center transition-all duration-200",
                  isDarkMode ? "bg-slate-800 hover:bg-slate-700" : "bg-slate-100 hover:bg-slate-200"
                )}
              >
                {isDarkMode ? (
                  <Sun className="w-4 h-4 text-slate-300" />
                ) : (
                  <Moon className="w-4 h-4 text-slate-600" />
                )}
              </button>

              {/* Kill Switch */}
              <button
                onClick={() => setKillSwitch(!killSwitchActive)}
                className={cn(
                  "px-4 py-2 rounded-lg flex items-center gap-2 transition-all duration-200 min-h-[44px] min-w-[44px]",
                  "text-xs font-bold uppercase tracking-wider font-['Inter']",
                  killSwitchActive 
                    ? "bg-red-600 hover:bg-red-700 text-white" 
                    : isDarkMode 
                      ? "bg-slate-800 hover:bg-slate-700 text-slate-300"
                      : "bg-slate-200 hover:bg-slate-300 text-slate-700"
                )}
              >
                <Power className="w-4 h-4" />
                {killSwitchActive ? 'HALT' : 'ACTIVE'}
              </button>
            </div>
          </div>
        </div>

        {/* NUCLEAR RESET: Bento Grid Layout */}
        <div className="max-w-7xl mx-auto px-4 py-6">
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-6">
            
            {/* P&L CARD - 2x2 Grid */}
            <div className="col-span-1 sm:col-span-2 lg:col-span-2 row-span-2">
              <div className={cn(
                "rounded-xl border p-6 h-full transition-colors duration-300",
                isDarkMode ? "bg-slate-900 border-slate-800" : "bg-white border-slate-200"
              )}>
                {/* Top-Left: Big Monospace P&L */}
                <div className="grid grid-cols-2 gap-6 h-full">
                  <div className="flex flex-col justify-center">
                    <motion.div
                      key={safeDailyPnl}
                      initial={{ scale: 0.8, opacity: 0 }}
                      animate={{ scale: 1, opacity: 1 }}
                      className={cn(
                        "text-4xl font-black tabular-nums font-['JetBrains_Mono'] transition-all duration-300",
                        isAnimating && "scale-105",
                        safeDailyPnl >= 0 ? "text-emerald-500" : "text-red-500",
                        !isDarkMode && safeDailyPnl >= 0 ? "text-emerald-600" : "",
                        !isDarkMode && safeDailyPnl < 0 ? "text-red-600" : ""
                      )}
                    >
                      {formatUSD(safeDailyPnl)}
                    </motion.div>
                    <div className="mt-4 space-y-2">
                      <div className="flex items-center gap-2">
                        {safePnlChange > 0 ? (
                          <TrendingUp className="w-4 h-4 text-emerald-500" />
                        ) : (
                          <TrendingDown className="w-4 h-4 text-red-500" />
                        )}
                        <span className={cn(
                          "text-sm font-mono tabular-nums font-['JetBrains_Mono']",
                          safePnlChange >= 0 ? "text-emerald-500" : "text-red-500",
                          !isDarkMode && safePnlChange >= 0 ? "text-emerald-600" : "",
                          !isDarkMode && safePnlChange < 0 ? "text-red-600" : ""
                        )}>
                          {formatUSD(safePnlChange)}
                        </span>
                      </div>
                      <div className="flex items-center justify-between">
                        <span className={cn(
                          "text-xs font-semibold uppercase tracking-wider font-['Inter']",
                          isDarkMode ? "text-slate-400" : "text-slate-500"
                        )}>
                          Win Rate
                        </span>
                        <span className={cn(
                          "text-sm font-mono tabular-nums font-['JetBrains_Mono']",
                          isDarkMode ? "text-slate-300" : "text-slate-700"
                        )}>
                          {winRate.toFixed(1)}%
                        </span>
                      </div>
                      <div className="flex items-center justify-between">
                        <span className={cn(
                          "text-xs font-semibold uppercase tracking-wider font-['Inter']",
                          isDarkMode ? "text-slate-400" : "text-slate-500"
                        )}>
                          Positions
                        </span>
                        <span className={cn(
                          "text-sm font-mono tabular-nums font-['JetBrains_Mono']",
                          isDarkMode ? "text-slate-300" : "text-slate-700"
                        )}>
                          {activePositions}
                        </span>
                      </div>
                    </div>
                  </div>

                  {/* Top-Right: Equity Curve */}
                  <div className="flex flex-col">
                    <h3 className={cn(
                      "text-sm font-bold uppercase tracking-wider font-['Inter'] mb-4",
                      isDarkMode ? "text-slate-300" : "text-slate-700"
                    )}>
                      Equity Curve
                    </h3>
                    <div className="flex-1 min-h-[120px]">
                      <EquityCurve />
                    </div>
                  </div>
                </div>
              </div>
            </div>

            {/* AGENT MATRIX CARD */}
            <div className="col-span-1 sm:col-span-2 lg:col-span-2">
              <div className={cn(
                "rounded-xl border p-6 transition-colors duration-300",
                isDarkMode ? "bg-slate-900 border-slate-800" : "bg-white border-slate-200"
              )}>
                <div className="flex items-center justify-between mb-4">
                  <h3 className={cn(
                    "text-sm font-bold uppercase tracking-wider font-['Inter']",
                    isDarkMode ? "text-slate-300" : "text-slate-700"
                  )}>
                    Agent Matrix
                  </h3>
                  <div className="flex items-center gap-2">
                    <div className="w-2 h-2 bg-emerald-500 rounded-full animate-pulse" />
                    <span className="text-xs font-medium text-emerald-500 font-['Inter'] uppercase tracking-wider">
                      8 Active
                    </span>
                  </div>
                </div>

                {/* High-Density Agent Grid */}
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                  {agents.map((agent) => (
                    <div
                      key={agent.id}
                      className={cn(
                        "relative p-3 rounded-lg border transition-all duration-200 hover:scale-105",
                        isDarkMode 
                          ? "bg-slate-800 border-slate-700 hover:border-slate-600" 
                          : "bg-slate-50 border-slate-200 hover:border-slate-300"
                      )}
                    >
                      {/* Status LED - Top Right */}
                      <div className="absolute top-2 right-2">
                        <div className={cn(
                          "w-1.5 h-1.5 rounded-full transition-all duration-300",
                          agent.heartbeat 
                            ? agent.tier === 'active' ? "bg-emerald-500 animate-pulse" :
                              agent.tier === 'challenger' ? "bg-amber-500 animate-pulse" :
                              "bg-slate-400"
                            : "bg-slate-400"
                        )} />
                      </div>

                      {/* Agent Name */}
                      <div className={cn(
                        "text-xs font-bold font-['Inter'] mb-2",
                        isDarkMode ? "text-slate-200" : "text-slate-800"
                      )}>
                        {agent.name}
                      </div>

                      {/* Key:Value Metrics */}
                      <div className="space-y-1">
                        {Object.entries(agent.metrics).slice(0, 2).map(([key, value]) => (
                          <div key={key} className="flex justify-between items-center">
                            <span className={cn(
                              "text-xs font-['Inter'] min-w-[40px]",
                              isDarkMode ? "text-slate-400" : "text-slate-600"
                            )}>
                              {key}
                            </span>
                            <span className={cn(
                              "text-xs font-mono tabular-nums font-['JetBrains_Mono'] text-right",
                              isDarkMode ? "text-slate-300" : "text-slate-700"
                            )}>
                              {sanitizeValue(value)}
                            </span>
                          </div>
                        ))}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </div>

            {/* LIVE TICKER BAR */}
            <div className="col-span-1 sm:col-span-2 lg:col-span-4">
              <div className={cn(
                "rounded-xl border p-4 transition-colors duration-300",
                isDarkMode ? "bg-slate-900 border-slate-800" : "bg-white border-slate-200"
              )}>
                <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-4 divide-x divide-slate-800">
                  {tickerData.map((ticker) => (
                    <div key={ticker.symbol} className="pl-4 first:pl-0">
                      <div className="flex items-center justify-between mb-1">
                        <span className={cn(
                          "text-xs font-bold font-['Inter'] uppercase tracking-wider",
                          isDarkMode ? "text-slate-400" : "text-slate-600"
                        )}>
                          {ticker.symbol}
                        </span>
                        <div className={cn(
                          "w-1.5 h-1.5 rounded-full",
                          ticker.change >= 0 ? "bg-emerald-500" : "bg-red-500"
                        )} />
                      </div>
                      <div className="text-right">
                        <div className={cn(
                          "text-sm font-mono tabular-nums font-['JetBrains_Mono']",
                          isDarkMode ? "text-slate-200" : "text-slate-800"
                        )}>
                          ${ticker.price.toFixed(2)}
                        </div>
                        <div className={cn(
                          "text-xs font-mono tabular-nums font-['JetBrains_Mono']",
                          ticker.change >= 0 ? "text-emerald-500" : "text-red-500",
                          !isDarkMode && ticker.change >= 0 ? "text-emerald-600" : "",
                          !isDarkMode && ticker.change < 0 ? "text-red-600" : ""
                        )}>
                          {ticker.change >= 0 ? '+' : ''}{ticker.change.toFixed(2)} ({ticker.changePercent >= 0 ? '+' : ''}{ticker.changePercent.toFixed(2)}%)
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </div>

          </div>
        </div>

        {/* Mobile Navigation */}
        <MobileNavigation activeSection={section} onSectionChange={() => {}} />
      </div>
    )
  }

  // Placeholder for other sections
  return (
    <div className={cn(
      "min-h-screen flex items-center justify-center",
      isDarkMode ? "bg-slate-950 text-white" : "bg-slate-50 text-slate-900"
    )}>
      <div className="text-center">
        <h1 className="text-2xl font-bold font-['Inter'] mb-4">
          {section.charAt(0).toUpperCase() + section.slice(1)} Page
        </h1>
        <p className="text-slate-500 font-['Inter']">
          Coming soon...
        </p>
      </div>
    </div>
  )
}
