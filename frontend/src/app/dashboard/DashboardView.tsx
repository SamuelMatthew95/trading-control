'use client'

import { useState, useEffect, useMemo } from 'react'
import { useCodexStore } from '@/stores/useCodexStore'
import { 
  TrendingUp, 
  TrendingDown, 
  Power, 
  Sun, 
  Moon,
  Activity,
  Brain,
  Zap,
  Award,
  Clock,
  FileCode,
  ChevronDown,
  ChevronUp
} from 'lucide-react'
import { cn } from '@/lib/utils'
import { motion } from 'framer-motion'
import { EquityCurve } from '@/components/EquityCurve'
import { MobileNavigation } from '@/components/MobileNavigation'

// FULL-STACK NUCLEAR RESET: Senior-Engineer Grade Helper Functions
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

  // Mock comprehensive data for all pages
  const agents = [
    { id: '1', name: 'SignalGenerator', tier: 'active', heartbeat: true, lastSeen: new Date(Date.now() - 12000), performance: 94.2, events: 847, metrics: { 'Status': 'ACTIVE', 'NVDA': '1,247', 'SPY': '892', 'Latency': '12ms' } },
    { id: '2', name: 'ReasoningAgent', tier: 'active', heartbeat: true, lastSeen: new Date(Date.now() - 45000), performance: 91.8, events: 523, metrics: { 'Provider': 'Groq', 'Decisions': '847', 'Latency': '45ms', 'Success': '94.2%' } },
    { id: '3', name: 'GradeAgent', tier: 'active', heartbeat: true, lastSeen: new Date(Date.now() - 30000), performance: 89.5, events: 291, metrics: { 'Grade': 'A-', 'Action': 'Weight Cut', 'Accuracy': '94.2%', 'Weight': '0.82' } },
    { id: '4', name: 'ICUpdater', tier: 'challenger', heartbeat: false, lastSeen: new Date(Date.now() - 120000), performance: 87.3, events: 156, metrics: { 'Correlation': '0.73', 'Metric': 'Spearman', 'Sync': '2m ago', 'Weights': 'Updated' } },
    { id: '5', name: 'ReflectionAgent', tier: 'active', heartbeat: true, lastSeen: new Date(Date.now() - 20000), performance: 68.0, events: 142, metrics: { 'Hypotheses': '142', 'Next Run': '5m', 'Success': '68%', 'Insight': 'Volume' } },
    { id: '6', name: 'StrategyProposer', tier: 'active', heartbeat: true, lastSeen: new Date(Date.now() - 60000), performance: 92.1, events: 89, metrics: { 'PRs': '3', 'Auto-Deploy': 'True', 'Strategies': '12', 'Deploy': '1h ago' } },
    { id: '7', name: 'HistoryAgent', tier: 'retired', heartbeat: false, lastSeen: new Date(Date.now() - 518400000), performance: 85.7, events: 28, metrics: { 'Cron': 'Success', 'Patterns': '28', 'Seasonality': 'Detected', 'Run': '6d ago' } },
    { id: '8', name: 'NotificationAgent', tier: 'active', heartbeat: true, lastSeen: new Date(Date.now() - 15000), performance: 99.9, events: 2, metrics: { 'Stream': 'Redis', 'Severity': 'Normal', 'Queue': '0', 'Alerts': '2' } },
  ]

  const tickerData = [
    { symbol: 'NVDA', price: 875.28, change: 2.34, changePercent: 0.27 },
    { symbol: 'SPY', price: 512.43, change: -1.12, changePercent: -0.22 },
    { symbol: 'AAPL', price: 178.92, change: 0.85, changePercent: 0.48 },
    { symbol: 'BTC', price: 67234.56, change: 1234.78, changePercent: 1.87 },
    { symbol: 'ETH', price: 3456.78, change: -45.23, changePercent: -1.29 },
    { symbol: 'SOL', price: 145.67, change: 3.21, changePercent: 2.25 },
  ]

  const openPositions = [
    { symbol: 'NVDA', side: 'long', quantity: 100, entryPrice: 865.50, currentPrice: 875.28, pnl: 978.00, pnlPercent: 1.13 },
    { symbol: 'SPY', side: 'short', quantity: 50, entryPrice: 515.00, currentPrice: 512.43, pnl: 128.50, pnlPercent: 0.50 },
    { symbol: 'AAPL', side: 'long', quantity: 75, entryPrice: 175.20, currentPrice: 178.92, pnl: 279.00, pnlPercent: 1.59 },
    { symbol: 'BTC', side: 'long', quantity: 0.5, entryPrice: 65000.00, currentPrice: 67234.56, pnl: 1117.28, pnlPercent: 3.44 },
  ]

  const agentThoughts = [
    { timestamp: new Date(Date.now() - 120000), agent: 'SignalGenerator', thought: 'NVDA showing strong momentum with RSI at 68. Volume increased 23% in last hour. Consider increasing position size.', confidence: 0.94 },
    { timestamp: new Date(Date.now() - 180000), agent: 'ReasoningAgent', thought: 'Market sentiment analysis indicates risk-off behavior. SPY approaching support at 510. Recommend hedging long positions.', confidence: 0.87 },
    { timestamp: new Date(Date.now() - 240000), agent: 'GradeAgent', thought: 'Recent trade performance: A- grade. Win rate 78%, avg hold time 2.3 hours. Suggest tightening stop losses to improve risk management.', confidence: 0.91 },
    { timestamp: new Date(Date.now() - 300000), agent: 'ICUpdater', thought: 'Information coefficient updated to 0.73. Recent signal strength decreased. Consider reducing exposure to high-beta assets.', confidence: 0.82 },
  ]

  const learningStats = {
    tradesEvaluated: 1247,
    reflectionsCompleted: 89,
    icUpdates: 156,
    strategiesTested: 23,
    avgWinRate: 68.4,
    totalPnl: 12478.92,
    bestDay: 2341.56,
    worstDay: -892.34,
  }

  const systemMetrics = {
    marketTicks: 1427847,
    signals: 892,
    orders: 156,
    executions: 142,
    avgLatency: 12,
    errorRate: 0.02,
    uptime: '14d 7h',
    memoryUsage: '6.2GB',
    cpuUsage: 42,
  }

  // Helper function for time formatting
  const formatTimeAgo = (date: Date): string => {
    const seconds = Math.floor((Date.now() - date.getTime()) / 1000)
    if (seconds < 60) return `${seconds}s ago`
    const minutes = Math.floor(seconds / 60)
    if (minutes < 60) return `${minutes}m ago`
    const hours = Math.floor(minutes / 60)
    if (hours < 24) return `${hours}h ago`
    const days = Math.floor(hours / 24)
    return `${days}d ago`
  }

  // Common Header Component
  const Header = () => (
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
  )

  // Common Ticker Strip Component
  const TickerStrip = () => (
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
  )

  // OVERVIEW PAGE - Bento Grid Layout
  if (section === 'overview') {
    return (
      <div className={cn(
        "min-h-screen transition-colors duration-300",
        isDarkMode ? "bg-slate-950" : "bg-slate-50"
      )}>
        <Header />
        
        <div className="max-w-7xl mx-auto px-4 py-6">
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-6">
            
            {/* P&L CARD - 2x2 Grid */}
            <div className="col-span-1 sm:col-span-2 lg:col-span-2 row-span-2">
              <div className={cn(
                "rounded-xl border p-6 h-full transition-colors duration-300",
                isDarkMode ? "bg-slate-900 border-slate-800" : "bg-white border-slate-200"
              )}>
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

                      <div className={cn(
                        "text-xs font-bold font-['Inter'] mb-2",
                        isDarkMode ? "text-slate-200" : "text-slate-800"
                      )}>
                        {agent.name}
                      </div>

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

            {/* TICKER STRIP */}
            <div className="col-span-1 sm:col-span-2 lg:col-span-4">
              <TickerStrip />
            </div>

          </div>
        </div>

        <MobileNavigation activeSection={section} onSectionChange={() => {}} />
      </div>
    )
  }

  // TRADING PAGE - Agent Thought Stream + Open Positions
  if (section === 'trading') {
    return (
      <div className={cn(
        "min-h-screen transition-colors duration-300",
        isDarkMode ? "bg-slate-950" : "bg-slate-50"
      )}>
        <Header />
        
        <div className="max-w-7xl mx-auto px-4 py-6 space-y-6">
          {/* AGENT THOUGHT STREAM */}
          <div className={cn(
            "rounded-xl border p-6 transition-colors duration-300",
            isDarkMode ? "bg-slate-900 border-slate-800" : "bg-white border-slate-200"
          )}>
            <div className="flex items-center justify-between mb-6">
              <h3 className={cn(
                "text-sm font-bold uppercase tracking-wider font-['Inter']",
                isDarkMode ? "text-slate-300" : "text-slate-700"
              )}>
                Agent Thought Stream
              </h3>
              <div className="flex items-center gap-2">
                <div className="w-2 h-2 bg-emerald-500 rounded-full animate-pulse" />
                <span className="text-xs font-medium text-emerald-500 font-['Inter'] uppercase tracking-wider">
                  Live
                </span>
              </div>
            </div>

            <div className="space-y-4 max-h-96 overflow-y-auto">
              {agentThoughts.map((thought, index) => (
                <motion.div
                  key={index}
                  initial={{ opacity: 0, y: 20 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ duration: 0.3, delay: index * 0.1 }}
                  className={cn(
                    "p-4 rounded-lg border transition-colors duration-200",
                    isDarkMode ? "bg-slate-800 border-slate-700" : "bg-slate-50 border-slate-200"
                  )}
                >
                  <div className="flex items-start justify-between mb-2">
                    <div className="flex items-center gap-3">
                      <Brain className="w-4 h-4 text-emerald-500" />
                      <span className={cn(
                        "text-xs font-bold font-['Inter']",
                        isDarkMode ? "text-slate-200" : "text-slate-800"
                      )}>
                        {thought.agent}
                      </span>
                      <span className={cn(
                        "text-xs font-mono tabular-nums font-['JetBrains_Mono']",
                        isDarkMode ? "text-slate-400" : "text-slate-600"
                      )}>
                        {formatTimeAgo(thought.timestamp)}
                      </span>
                    </div>
                    <div className={cn(
                      "text-xs font-mono tabular-nums font-['JetBrains_Mono'] px-2 py-1 rounded",
                      thought.confidence >= 0.9 
                        ? "bg-emerald-500/20 text-emerald-400"
                        : thought.confidence >= 0.8
                        ? "bg-amber-500/20 text-amber-400"
                        : "bg-slate-500/20 text-slate-400"
                    )}>
                      {(thought.confidence * 100).toFixed(0)}%
                    </div>
                  </div>
                  <p className={cn(
                    "text-sm font-['Inter'] leading-relaxed",
                    isDarkMode ? "text-slate-300" : "text-slate-700"
                  )}>
                    {thought.thought}
                  </p>
                </motion.div>
              ))}
            </div>
          </div>

          {/* OPEN POSITIONS TABLE */}
          <div className={cn(
            "rounded-xl border p-6 transition-colors duration-300",
            isDarkMode ? "bg-slate-900 border-slate-800" : "bg-white border-slate-200"
          )}>
            <div className="flex items-center justify-between mb-6">
              <h3 className={cn(
                "text-sm font-bold uppercase tracking-wider font-['Inter']",
                isDarkMode ? "text-slate-300" : "text-slate-700"
              )}>
                Open Positions
              </h3>
              <span className={cn(
                "text-xs font-medium font-['Inter']",
                isDarkMode ? "text-slate-400" : "text-slate-600"
              )}>
                {openPositions.length} Active
              </span>
            </div>

            <div className="overflow-x-auto">
              <table className="w-full">
                <thead>
                  <tr className={cn(
                    "text-xs font-semibold uppercase tracking-wider font-['Inter']",
                    isDarkMode ? "text-slate-400" : "text-slate-600"
                  )}>
                    <th className="text-left pb-3">Symbol</th>
                    <th className="text-center pb-3">Side</th>
                    <th className="text-right pb-3">Qty</th>
                    <th className="text-right pb-3">Entry</th>
                    <th className="text-right pb-3">Current</th>
                    <th className="text-right pb-3">P&L</th>
                  </tr>
                </thead>
                <tbody>
                  {openPositions.map((position, index) => (
                    <motion.tr
                      key={index}
                      initial={{ opacity: 0, x: -20 }}
                      animate={{ opacity: 1, x: 0 }}
                      transition={{ duration: 0.3, delay: index * 0.05 }}
                      className={cn(
                        "border-t transition-colors duration-200",
                        isDarkMode ? "border-slate-800" : "border-slate-200"
                      )}
                    >
                      <td className={cn(
                        "py-3 font-mono tabular-nums font-['JetBrains_Mono'] font-bold",
                        isDarkMode ? "text-slate-200" : "text-slate-800"
                      )}>
                        {position.symbol}
                      </td>
                      <td className="py-3 text-center">
                        <span className={cn(
                          "text-xs font-bold uppercase px-2 py-1 rounded",
                          position.side === 'long' 
                            ? "bg-emerald-500/20 text-emerald-400"
                            : "bg-red-500/20 text-red-400"
                        )}>
                          {position.side}
                        </span>
                      </td>
                      <td className={cn(
                        "py-3 text-right font-mono tabular-nums font-['JetBrains_Mono']",
                        isDarkMode ? "text-slate-300" : "text-slate-700"
                      )}>
                        {position.quantity}
                      </td>
                      <td className={cn(
                        "py-3 text-right font-mono tabular-nums font-['JetBrains_Mono']",
                        isDarkMode ? "text-slate-300" : "text-slate-700"
                      )}>
                        ${position.entryPrice.toFixed(2)}
                      </td>
                      <td className={cn(
                        "py-3 text-right font-mono tabular-nums font-['JetBrains_Mono']",
                        isDarkMode ? "text-slate-300" : "text-slate-700"
                      )}>
                        ${position.currentPrice.toFixed(2)}
                      </td>
                      <td className={cn(
                        "py-3 text-right font-mono tabular-nums font-['JetBrains_Mono'] font-bold",
                        position.pnl >= 0 ? "text-emerald-500" : "text-red-500",
                        !isDarkMode && position.pnl >= 0 ? "text-emerald-600" : "",
                        !isDarkMode && position.pnl < 0 ? "text-red-600" : ""
                      )}>
                        {position.pnl >= 0 ? '+' : ''}{formatUSD(position.pnl)}
                        <div className="text-xs">
                          ({position.pnlPercent >= 0 ? '+' : ''}{position.pnlPercent.toFixed(2)}%)
                        </div>
                      </td>
                    </motion.tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>

        <MobileNavigation activeSection={section} onSectionChange={() => {}} />
      </div>
    )
  }

  // AGENTS PAGE - Full 8-Agent Matrix
  if (section === 'agents') {
    return (
      <div className={cn(
        "min-h-screen transition-colors duration-300",
        isDarkMode ? "bg-slate-950" : "bg-slate-50"
      )}>
        <Header />
        
        <div className="max-w-7xl mx-auto px-4 py-6">
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-6">
            {agents.map((agent, index) => (
              <motion.div
                key={agent.id}
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.3, delay: index * 0.05 }}
                className={cn(
                  "rounded-xl border p-6 transition-all duration-200 hover:scale-105",
                  isDarkMode ? "bg-slate-900 border-slate-800" : "bg-white border-slate-200"
                )}
              >
                <div className="flex items-center justify-between mb-4">
                  <h4 className={cn(
                    "text-sm font-bold font-['Inter']",
                    isDarkMode ? "text-slate-200" : "text-slate-800"
                  )}>
                    {agent.name}
                  </h4>
                  <div className="flex items-center gap-2">
                    <div className={cn(
                      "w-2 h-2 rounded-full transition-all duration-300",
                      agent.heartbeat 
                        ? agent.tier === 'active' ? "bg-emerald-500 animate-pulse" :
                          agent.tier === 'challenger' ? "bg-amber-500 animate-pulse" :
                          "bg-slate-400"
                        : "bg-slate-400"
                    )} />
                    <span className={cn(
                      "text-xs font-medium font-['Inter'] uppercase",
                      agent.tier === 'active' ? "text-emerald-500" :
                      agent.tier === 'challenger' ? "text-amber-500" :
                      "text-slate-400"
                    )}>
                      {agent.tier}
                    </span>
                  </div>
                </div>

                <div className="space-y-3">
                  <div className="flex justify-between items-center">
                    <span className={cn(
                      "text-xs font-semibold uppercase tracking-wider font-['Inter']",
                      isDarkMode ? "text-slate-400" : "text-slate-600"
                    )}>
                      Performance
                    </span>
                    <span className={cn(
                      "text-sm font-mono tabular-nums font-['JetBrains_Mono']",
                      agent.performance >= 90 ? "text-emerald-500" :
                      agent.performance >= 80 ? "text-amber-500" :
                      "text-slate-400"
                    )}>
                      {agent.performance.toFixed(1)}%
                    </span>
                  </div>

                  <div className="flex justify-between items-center">
                    <span className={cn(
                      "text-xs font-semibold uppercase tracking-wider font-['Inter']",
                      isDarkMode ? "text-slate-400" : "text-slate-600"
                    )}>
                      Events
                    </span>
                    <span className={cn(
                      "text-sm font-mono tabular-nums font-['JetBrains_Mono']",
                      isDarkMode ? "text-slate-300" : "text-slate-700"
                    )}>
                      {agent.events}
                    </span>
                  </div>

                  <div className="flex justify-between items-center">
                    <span className={cn(
                      "text-xs font-semibold uppercase tracking-wider font-['Inter']",
                      isDarkMode ? "text-slate-400" : "text-slate-600"
                    )}>
                      Last Seen
                    </span>
                    <span className={cn(
                      "text-xs font-mono tabular-nums font-['JetBrains_Mono']",
                      isDarkMode ? "text-slate-300" : "text-slate-700"
                    )}>
                      {formatTimeAgo(agent.lastSeen)}
                    </span>
                  </div>

                  <div className="pt-3 border-t border-slate-800">
                    <div className="space-y-2">
                      {Object.entries(agent.metrics).slice(0, 3).map(([key, value]) => (
                        <div key={key} className="flex justify-between items-center">
                          <span className={cn(
                            "text-xs font-['Inter']",
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
                </div>
              </motion.div>
            ))}
          </div>
        </div>

        <MobileNavigation activeSection={section} onSectionChange={() => {}} />
      </div>
    )
  }

  // LEARNING PAGE - Learning Stats & Timeline
  if (section === 'learning') {
    return (
      <div className={cn(
        "min-h-screen transition-colors duration-300",
        isDarkMode ? "bg-slate-950" : "bg-slate-50"
      )}>
        <Header />
        
        <div className="max-w-7xl mx-auto px-4 py-6">
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-6 mb-6">
            {/* LEARNING STATS CARDS */}
            <motion.div
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              className={cn(
                "rounded-xl border p-6 transition-colors duration-300",
                isDarkMode ? "bg-slate-900 border-slate-800" : "bg-white border-slate-200"
              )}
            >
              <div className="flex items-center justify-between mb-4">
                <FileCode className="w-5 h-5 text-emerald-500" />
                <span className="text-xs font-medium text-emerald-500 font-['Inter'] uppercase tracking-wider">
                  Evaluated
                </span>
              </div>
              <div className={cn(
                "text-2xl font-black tabular-nums font-['JetBrains_Mono'] mb-2",
                isDarkMode ? "text-slate-200" : "text-slate-800"
              )}>
                {learningStats.tradesEvaluated.toLocaleString()}
              </div>
              <span className={cn(
                "text-xs font-semibold uppercase tracking-wider font-['Inter']",
                isDarkMode ? "text-slate-400" : "text-slate-600"
              )}>
                Trades
              </span>
            </motion.div>

            <motion.div
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.1 }}
              className={cn(
                "rounded-xl border p-6 transition-colors duration-300",
                isDarkMode ? "bg-slate-900 border-slate-800" : "bg-white border-slate-200"
              )}
            >
              <div className="flex items-center justify-between mb-4">
                <Brain className="w-5 h-5 text-amber-500" />
                <span className="text-xs font-medium text-amber-500 font-['Inter'] uppercase tracking-wider">
                  Completed
                </span>
              </div>
              <div className={cn(
                "text-2xl font-black tabular-nums font-['JetBrains_Mono'] mb-2",
                isDarkMode ? "text-slate-200" : "text-slate-800"
              )}>
                {learningStats.reflectionsCompleted}
              </div>
              <span className={cn(
                "text-xs font-semibold uppercase tracking-wider font-['Inter']",
                isDarkMode ? "text-slate-400" : "text-slate-600"
              )}>
                Reflections
              </span>
            </motion.div>

            <motion.div
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.2 }}
              className={cn(
                "rounded-xl border p-6 transition-colors duration-300",
                isDarkMode ? "bg-slate-900 border-slate-800" : "bg-white border-slate-200"
              )}
            >
              <div className="flex items-center justify-between mb-4">
                <Activity className="w-5 h-5 text-indigo-500" />
                <span className="text-xs font-medium text-indigo-500 font-['Inter'] uppercase tracking-wider">
                  Updated
                </span>
              </div>
              <div className={cn(
                "text-2xl font-black tabular-nums font-['JetBrains_Mono'] mb-2",
                isDarkMode ? "text-slate-200" : "text-slate-800"
              )}>
                {learningStats.icUpdates}
              </div>
              <span className={cn(
                "text-xs font-semibold uppercase tracking-wider font-['Inter']",
                isDarkMode ? "text-slate-400" : "text-slate-600"
              )}>
                IC Values
              </span>
            </motion.div>

            <motion.div
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.3 }}
              className={cn(
                "rounded-xl border p-6 transition-colors duration-300",
                isDarkMode ? "bg-slate-900 border-slate-800" : "bg-white border-slate-200"
              )}
            >
              <div className="flex items-center justify-between mb-4">
                <Zap className="w-5 h-5 text-purple-500" />
                <span className="text-xs font-medium text-purple-500 font-['Inter'] uppercase tracking-wider">
                  Tested
                </span>
              </div>
              <div className={cn(
                "text-2xl font-black tabular-nums font-['JetBrains_Mono'] mb-2",
                isDarkMode ? "text-slate-200" : "text-slate-800"
              )}>
                {learningStats.strategiesTested}
              </div>
              <span className={cn(
                "text-xs font-semibold uppercase tracking-wider font-['Inter']",
                isDarkMode ? "text-slate-400" : "text-slate-600"
              )}>
                Strategies
              </span>
            </motion.div>
          </div>

          {/* PERFORMANCE SUMMARY */}
          <div className={cn(
            "rounded-xl border p-6 transition-colors duration-300 mb-6",
            isDarkMode ? "bg-slate-900 border-slate-800" : "bg-white border-slate-200"
          )}>
            <h3 className={cn(
              "text-sm font-bold uppercase tracking-wider font-['Inter'] mb-6",
              isDarkMode ? "text-slate-300" : "text-slate-700"
            )}>
              Performance Summary
            </h3>

            <div className="grid grid-cols-2 sm:grid-cols-4 gap-6">
              <div>
                <span className={cn(
                  "text-xs font-semibold uppercase tracking-wider font-['Inter'] block mb-2",
                  isDarkMode ? "text-slate-400" : "text-slate-600"
                )}>
                  Win Rate
                </span>
                <div className={cn(
                  "text-xl font-black tabular-nums font-['JetBrains_Mono']",
                  learningStats.avgWinRate >= 70 ? "text-emerald-500" : "text-amber-500"
                )}>
                  {learningStats.avgWinRate.toFixed(1)}%
                </div>
              </div>

              <div>
                <span className={cn(
                  "text-xs font-semibold uppercase tracking-wider font-['Inter'] block mb-2",
                  isDarkMode ? "text-slate-400" : "text-slate-600"
                )}>
                  Total P&L
                </span>
                <div className={cn(
                  "text-xl font-black tabular-nums font-['JetBrains_Mono']",
                  learningStats.totalPnl >= 0 ? "text-emerald-500" : "text-red-500"
                )}>
                  {formatUSD(learningStats.totalPnl)}
                </div>
              </div>

              <div>
                <span className={cn(
                  "text-xs font-semibold uppercase tracking-wider font-['Inter'] block mb-2",
                  isDarkMode ? "text-slate-400" : "text-slate-600"
                )}>
                  Best Day
                </span>
                <div className={cn(
                  "text-xl font-black tabular-nums font-['JetBrains_Mono'] text-emerald-500"
                )}>
                  {formatUSD(learningStats.bestDay)}
                </div>
              </div>

              <div>
                <span className={cn(
                  "text-xs font-semibold uppercase tracking-wider font-['Inter'] block mb-2",
                  isDarkMode ? "text-slate-400" : "text-slate-600"
                )}>
                  Worst Day
                </span>
                <div className={cn(
                  "text-xl font-black tabular-nums font-['JetBrains_Mono'] text-red-500"
                )}>
                  {formatUSD(learningStats.worstDay)}
                </div>
              </div>
            </div>
          </div>

          {/* RECENT LEARNING TIMELINE */}
          <div className={cn(
            "rounded-xl border p-6 transition-colors duration-300",
            isDarkMode ? "bg-slate-900 border-slate-800" : "bg-white border-slate-200"
          )}>
            <h3 className={cn(
              "text-sm font-bold uppercase tracking-wider font-['Inter'] mb-6",
              isDarkMode ? "text-slate-300" : "text-slate-700"
            )}>
              Recent Learning Timeline
            </h3>

            <div className="space-y-4">
              {agentThoughts.map((thought, index) => (
                <motion.div
                  key={index}
                  initial={{ opacity: 0, x: -20 }}
                  animate={{ opacity: 1, x: 0 }}
                  transition={{ duration: 0.3, delay: index * 0.1 }}
                  className={cn(
                    "flex items-start gap-4 p-4 rounded-lg border",
                    isDarkMode ? "bg-slate-800 border-slate-700" : "bg-slate-50 border-slate-200"
                  )}
                >
                  <div className={cn(
                    "w-2 h-2 rounded-full mt-2",
                    thought.confidence >= 0.9 ? "bg-emerald-500" :
                    thought.confidence >= 0.8 ? "bg-amber-500" : "bg-slate-400"
                  )} />
                  <div className="flex-1">
                    <div className="flex items-center justify-between mb-2">
                      <span className={cn(
                        "text-xs font-bold font-['Inter']",
                        isDarkMode ? "text-slate-200" : "text-slate-800"
                      )}>
                        {thought.agent}
                      </span>
                      <span className={cn(
                        "text-xs font-mono tabular-nums font-['JetBrains_Mono']",
                        isDarkMode ? "text-slate-400" : "text-slate-600"
                      )}>
                        {formatTimeAgo(thought.timestamp)}
                      </span>
                    </div>
                    <p className={cn(
                      "text-sm font-['Inter'] leading-relaxed",
                      isDarkMode ? "text-slate-300" : "text-slate-700"
                    )}>
                      {thought.thought}
                    </p>
                  </div>
                </motion.div>
              ))}
            </div>
          </div>
        </div>

        <MobileNavigation activeSection={section} onSectionChange={() => {}} />
      </div>
    )
  }

  // SYSTEM PAGE - Real-time Metrics & Agent Status
  if (section === 'system') {
    return (
      <div className={cn(
        "min-h-screen transition-colors duration-300",
        isDarkMode ? "bg-slate-950" : "bg-slate-50"
      )}>
        <Header />
        
        <div className="max-w-7xl mx-auto px-4 py-6">
          {/* REAL-TIME METRICS OVERVIEW */}
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-4 mb-6">
            {[
              { label: 'Market Ticks', value: systemMetrics.marketTicks.toLocaleString(), icon: Activity, color: 'emerald' },
              { label: 'Signals', value: systemMetrics.signals.toLocaleString(), icon: Zap, color: 'amber' },
              { label: 'Orders', value: systemMetrics.orders.toLocaleString(), icon: FileCode, color: 'indigo' },
              { label: 'Executions', value: systemMetrics.executions.toLocaleString(), icon: Award, color: 'purple' },
              { label: 'Latency', value: `${systemMetrics.avgLatency}ms`, icon: Clock, color: 'blue' },
              { label: 'Error Rate', value: `${systemMetrics.errorRate}%`, icon: AlertTriangle, color: 'red' },
            ].map((metric, index) => (
              <motion.div
                key={metric.label}
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.3, delay: index * 0.05 }}
                className={cn(
                  "rounded-xl border p-4 transition-colors duration-300",
                  isDarkMode ? "bg-slate-900 border-slate-800" : "bg-white border-slate-200"
                )}
              >
                <div className="flex items-center justify-between mb-2">
                  <metric.icon className={cn(
                    "w-4 h-4",
                    metric.color === 'emerald' ? "text-emerald-500" :
                    metric.color === 'amber' ? "text-amber-500" :
                    metric.color === 'indigo' ? "text-indigo-500" :
                    metric.color === 'purple' ? "text-purple-500" :
                    metric.color === 'blue' ? "text-blue-500" :
                    "text-red-500"
                  )} />
                  <span className={cn(
                    "text-xs font-medium font-['Inter'] uppercase",
                    metric.color === 'emerald' ? "text-emerald-500" :
                    metric.color === 'amber' ? "text-amber-500" :
                    metric.color === 'indigo' ? "text-indigo-500" :
                    metric.color === 'purple' ? "text-purple-500" :
                    metric.color === 'blue' ? "text-blue-500" :
                    "text-red-500"
                  )}>
                    Live
                  </span>
                </div>
                <div className={cn(
                  "text-lg font-black tabular-nums font-['JetBrains_Mono'] mb-1",
                  isDarkMode ? "text-slate-200" : "text-slate-800"
                )}>
                  {metric.value}
                </div>
                <span className={cn(
                  "text-xs font-semibold uppercase tracking-wider font-['Inter']",
                  isDarkMode ? "text-slate-400" : "text-slate-600"
                )}>
                  {metric.label}
                </span>
              </motion.div>
            ))}
          </div>

          {/* SYSTEM HEALTH METRICS */}
          <div className={cn(
            "rounded-xl border p-6 transition-colors duration-300 mb-6",
            isDarkMode ? "bg-slate-900 border-slate-800" : "bg-white border-slate-200"
          )}>
            <h3 className={cn(
              "text-sm font-bold uppercase tracking-wider font-['Inter'] mb-6",
              isDarkMode ? "text-slate-300" : "text-slate-700"
            )}>
              System Health
            </h3>

            <div className="grid grid-cols-1 sm:grid-cols-3 gap-6">
              <div>
                <span className={cn(
                  "text-xs font-semibold uppercase tracking-wider font-['Inter'] block mb-2",
                  isDarkMode ? "text-slate-400" : "text-slate-600"
                )}>
                  Uptime
                </span>
                <div className={cn(
                  "text-xl font-black tabular-nums font-['JetBrains_Mono'] text-emerald-500"
                )}>
                  {systemMetrics.uptime}
                </div>
              </div>

              <div>
                <span className={cn(
                  "text-xs font-semibold uppercase tracking-wider font-['Inter'] block mb-2",
                  isDarkMode ? "text-slate-400" : "text-slate-600"
                )}>
                  Memory Usage
                </span>
                <div className={cn(
                  "text-xl font-black tabular-nums font-['JetBrains_Mono'] text-amber-500"
                )}>
                  {systemMetrics.memoryUsage}
                </div>
              </div>

              <div>
                <span className={cn(
                  "text-xs font-semibold uppercase tracking-wider font-['Inter'] block mb-2",
                  isDarkMode ? "text-slate-400" : "text-slate-600"
                )}>
                  CPU Usage
                </span>
                <div className={cn(
                  "text-xl font-black tabular-nums font-['JetBrains_Mono'] text-blue-500"
                )}>
                  {systemMetrics.cpuUsage}%
                </div>
              </div>
            </div>
          </div>

          {/* AGENT STATUS TABLE */}
          <div className={cn(
            "rounded-xl border p-6 transition-colors duration-300",
            isDarkMode ? "bg-slate-900 border-slate-800" : "bg-white border-slate-200"
          )}>
            <div className="flex items-center justify-between mb-6">
              <h3 className={cn(
                "text-sm font-bold uppercase tracking-wider font-['Inter']",
                isDarkMode ? "text-slate-300" : "text-slate-700"
              )}>
                Agent Status
              </h3>
              <span className={cn(
                "text-xs font-medium font-['Inter']",
                isDarkMode ? "text-slate-400" : "text-slate-600"
              )}>
                {agents.length} Total Agents
              </span>
            </div>

            <div className="overflow-x-auto">
              <table className="w-full">
                <thead>
                  <tr className={cn(
                    "text-xs font-semibold uppercase tracking-wider font-['Inter']",
                    isDarkMode ? "text-slate-400" : "text-slate-600"
                  )}>
                    <th className="text-left pb-3">Agent</th>
                    <th className="text-center pb-3">Status</th>
                    <th className="text-right pb-3">Performance</th>
                    <th className="text-right pb-3">Events</th>
                    <th className="text-right pb-3">Last Activity</th>
                    <th className="text-right pb-3">Tier</th>
                  </tr>
                </thead>
                <tbody>
                  {agents.map((agent, index) => (
                    <motion.tr
                      key={agent.id}
                      initial={{ opacity: 0, x: -20 }}
                      animate={{ opacity: 1, x: 0 }}
                      transition={{ duration: 0.3, delay: index * 0.05 }}
                      className={cn(
                        "border-t transition-colors duration-200",
                        isDarkMode ? "border-slate-800" : "border-slate-200"
                      )}
                    >
                      <td className={cn(
                        "py-3 font-mono tabular-nums font-['JetBrains_Mono'] font-bold",
                        isDarkMode ? "text-slate-200" : "text-slate-800"
                      )}>
                        {agent.name}
                      </td>
                      <td className="py-3 text-center">
                        <div className="flex items-center justify-center gap-2">
                          <div className={cn(
                            "w-2 h-2 rounded-full",
                            agent.heartbeat 
                              ? agent.tier === 'active' ? "bg-emerald-500 animate-pulse" :
                                agent.tier === 'challenger' ? "bg-amber-500 animate-pulse" :
                                "bg-slate-400"
                              : "bg-slate-400"
                          )} />
                          <span className={cn(
                            "text-xs font-bold uppercase",
                            agent.heartbeat 
                              ? agent.tier === 'active' ? "text-emerald-500" :
                                agent.tier === 'challenger' ? "text-amber-500" :
                                "text-slate-400"
                              : "text-slate-400"
                          )}>
                            {agent.heartbeat ? 'ACTIVE' : 'IDLE'}
                          </span>
                        </div>
                      </td>
                      <td className={cn(
                        "py-3 text-right font-mono tabular-nums font-['JetBrains_Mono'] font-bold",
                        agent.performance >= 90 ? "text-emerald-500" :
                        agent.performance >= 80 ? "text-amber-500" :
                        "text-slate-400"
                      )}>
                        {agent.performance.toFixed(1)}%
                      </td>
                      <td className={cn(
                        "py-3 text-right font-mono tabular-nums font-['JetBrains_Mono']",
                        isDarkMode ? "text-slate-300" : "text-slate-700"
                      )}>
                        {agent.events}
                      </td>
                      <td className={cn(
                        "py-3 text-right font-mono tabular-nums font-['JetBrains_Mono']",
                        isDarkMode ? "text-slate-300" : "text-slate-700"
                      )}>
                        {formatTimeAgo(agent.lastSeen)}
                      </td>
                      <td className="py-3 text-right">
                        <span className={cn(
                          "text-xs font-bold uppercase px-2 py-1 rounded",
                          agent.tier === 'active' ? "bg-emerald-500/20 text-emerald-400" :
                          agent.tier === 'challenger' ? "bg-amber-500/20 text-amber-400" :
                          "bg-slate-500/20 text-slate-400"
                        )}>
                          {agent.tier}
                        </span>
                      </td>
                    </motion.tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>

        <MobileNavigation activeSection={section} onSectionChange={() => {}} />
      </div>
    )
  }

  // Fallback
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
