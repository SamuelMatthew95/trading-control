'use client'

import { useState, useEffect, useMemo } from 'react'
import { useCodexStore } from '@/stores/useCodexStore'
import { TrendingUp, TrendingDown, Power, Sun, Moon, Activity, Brain, Zap, Award, Clock, FileCode, AlertTriangle } from 'lucide-react'
import { cn } from '@/lib/utils'
import { motion } from 'framer-motion'
import { EquityCurve } from '@/components/EquityCurve'
import { MobileNavigation } from '@/components/MobileNavigation'

// Helper functions
const sanitizeValue = (value: any): string => {
  if (value === undefined || value === null || value === '') return '--';
  if (typeof value === 'number' && Number.isNaN(value)) return '--';
  if (typeof value === 'boolean') return value ? 'True' : 'False';
  return String(value);
};

const formatUSD = (value?: number | null): string => {
  return value != null && isFinite(value) ? `$${value.toFixed(2)}` : "$0.00";
};

export function DashboardView({ section }: { section: 'overview' | 'trading' | 'agents' | 'learning' | 'system' }) {
  const [isDarkMode, setIsDarkMode] = useState(true)
  const [previousPnl, setPreviousPnl] = useState(0)
  const [isAnimating, setIsAnimating] = useState(false)

  // REAL DATA ONLY - Use WebSocket store
  const { 
    agentLogs = [], 
    killSwitchActive, 
    orders = [], 
    positions = [], 
    prices = {}, 
    systemMetrics = [],
    learningEvents = [],
    wsConnected = false,
    setKillSwitch,
    dashboardData = null,
    isLoading = false
  } = useCodexStore()

  // Calculate real P&L from actual orders
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
  const winRate = useMemo(() => {
    const validOrders = orders.filter(o => o && typeof o.pnl === 'number' && !isNaN(Number(o.pnl)))
    return validOrders.length > 0 ? (validOrders.filter(o => Number(o.pnl) > 0).length / validOrders.length) * 100 : 0
  }, [orders])

  const activePositions = positions.filter(p => p.side === 'long' || p.side === 'short').length

  // Real agent data from logs
  const realAgents = useMemo(() => {
    const agentMap = new Map()
    agentLogs.forEach(log => {
      if (log.agent_name) {
        if (!agentMap.has(log.agent_name)) {
          agentMap.set(log.agent_name, {
            name: log.agent_name,
            lastSeen: new Date(log.timestamp || Date.now()),
            heartbeat: true,
            events: 0,
            tier: 'active'
          })
        }
        const agent = agentMap.get(log.agent_name)
        agent.events++
        agent.lastSeen = new Date(log.timestamp || Date.now())
      }
    })
    return Array.from(agentMap.values())
  }, [agentLogs])

  // Real ticker data from prices
  const realTickerData = useMemo(() => {
    return Object.entries(prices).slice(0, 6).map(([symbol, priceData]) => ({
      symbol,
      price: priceData?.price || 0,
      change: priceData?.change || 0,
      changePercent: (priceData as any)?.changePercent || 0
    }))
  }, [prices])

  // Real learning metrics
  const learningMetrics = useMemo(() => {
    const evaluated = learningEvents.filter(e => e.type === 'trade_evaluated').length
    const reflections = learningEvents.filter(e => e.type === 'reflection').length
    const icUpdates = learningEvents.filter(e => e.type === 'ic_update').length
    
    // Calculate best/worst days from actual orders
    const dailyPnLs = new Map()
    orders.forEach(order => {
      if (order && order.timestamp && typeof order.pnl === 'number') {
        const date = new Date(order.timestamp).toDateString()
        const currentPnL = dailyPnLs.get(date) || 0
        dailyPnLs.set(date, currentPnL + order.pnl)
      }
    })
    
    const pnlValues = Array.from(dailyPnLs.values())
    const bestDay = pnlValues.length > 0 ? Math.max(...pnlValues) : 0
    const worstDay = pnlValues.length > 0 ? Math.min(...pnlValues) : 0
    
    return {
      tradesEvaluated: evaluated,
      reflectionsCompleted: reflections,
      icUpdates: icUpdates,
      strategiesTested: learningEvents.filter(e => e.type === 'strategy_tested').length,
      avgWinRate: winRate,
      totalPnl: safeDailyPnl,
      bestDay,
      worstDay,
    }
  }, [learningEvents, winRate, safeDailyPnl, orders])

  // Real system metrics
  const realSystemMetrics = useMemo(() => {
    const metrics = {
      marketTicks: 0,
      signals: 0,
      orders: orders.length,
      executions: 0,
      avgLatency: 0,
      errorRate: 0,
      uptime: 'N/A',
      memoryUsage: 'N/A',
      cpuUsage: 'N/A'
    }

    systemMetrics.forEach(metric => {
      if (metric.metric_name === 'market_ticks') metrics.marketTicks = metric.value || 0
      if (metric.metric_name === 'signals_generated') metrics.signals = metric.value || 0
      if (metric.metric_name === 'executions') metrics.executions = metric.value || 0
      if (metric.metric_name === 'avg_latency') metrics.avgLatency = metric.value || 0
      if (metric.metric_name === 'error_rate') metrics.errorRate = metric.value || 0
    })

    return metrics
  }, [systemMetrics, orders])

  // Animation
  useEffect(() => {
    if (safeDailyPnl !== previousPnl) {
      setIsAnimating(true)
      setPreviousPnl(safeDailyPnl)
      setTimeout(() => setIsAnimating(false), 300)
    }
  }, [safeDailyPnl, previousPnl])

  // Time formatting
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

  // Header Component
  const Header = () => (
    <div className="h-10 border-b bg-slate-900 border-slate-800">
      <div className="max-w-7xl mx-auto px-4 h-full flex items-center justify-between">
        <div className="flex items-center gap-4">
          <h1 className="text-sm font-bold uppercase tracking-wider text-white font-sans">
            Trading Console
          </h1>
          <div className="flex items-center gap-2">
            <div className={cn("w-2 h-2 rounded-full animate-pulse", wsConnected ? "bg-emerald-500" : "bg-slate-400")} />
            <span className={cn("text-xs font-semibold uppercase tracking-wider font-sans", wsConnected ? "text-emerald-500" : "text-slate-400")}>
              {wsConnected ? 'LIVE' : 'OFFLINE'}
            </span>
          </div>
        </div>
        <div className="flex items-center gap-6">
          <motion.div key={safeDailyPnl} className="text-xl font-black tabular-nums font-mono text-emerald-500">
            {formatUSD(safeDailyPnl)}
          </motion.div>
          <span className="text-xs font-semibold uppercase tracking-wider font-sans text-slate-400">
            Daily P&L
          </span>
        </div>
        <div className="flex items-center gap-3">
          <button onClick={() => setIsDarkMode(!isDarkMode)} className="w-8 h-8 rounded-lg flex items-center justify-center bg-slate-800 hover:bg-slate-700">
            {isDarkMode ? <Sun className="w-4 h-4 text-slate-300" /> : <Moon className="w-4 h-4 text-slate-600" />}
          </button>
          <button onClick={() => setKillSwitch(!killSwitchActive)} className="px-4 py-2 rounded-lg flex items-center gap-2 bg-red-600 hover:bg-red-700 text-white text-xs font-bold uppercase tracking-wider font-sans min-h-[44px] min-w-[44px]">
            <Power className="w-4 h-4" />
            {killSwitchActive ? 'HALT' : 'ACTIVE'}
          </button>
        </div>
      </div>
    </div>
  )

  // OVERVIEW PAGE - Real Data Only
  if (section === 'overview') {
    return (
      <div className="min-h-screen bg-slate-950">
        <Header />
        <div className="max-w-7xl mx-auto px-4 py-6">
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-6">
            {/* P&L CARD - Real Orders */}
            <div className="col-span-1 sm:col-span-2 lg:col-span-2 bg-slate-900 rounded-xl border border-slate-800 p-6">
              <div className="grid grid-cols-2 gap-6 h-full">
                <div className="flex flex-col justify-center">
                  <motion.div key={safeDailyPnl} className="text-4xl font-black tabular-nums font-mono text-emerald-500">
                    {formatUSD(safeDailyPnl)}
                  </motion.div>
                  <div className="mt-4 space-y-2">
                    <div className="flex items-center justify-between">
                      <span className="text-xs font-semibold uppercase tracking-wider font-sans text-slate-400">Win Rate</span>
                      <span className="text-sm font-mono tabular-nums text-slate-300">{sanitizeValue(winRate.toFixed(1))}%</span>
                    </div>
                    <div className="flex items-center justify-between">
                      <span className="text-xs font-semibold uppercase tracking-wider font-sans text-slate-400">Positions</span>
                      <span className="text-sm font-mono tabular-nums text-slate-300">{sanitizeValue(activePositions)}</span>
                    </div>
                  </div>
                </div>
                <div className="flex flex-col">
                  <h3 className="text-sm font-bold uppercase tracking-wider font-sans text-slate-300 mb-4">Equity Curve</h3>
                  <div className="flex-1 min-h-[120px]">
                    <EquityCurve />
                  </div>
                </div>
              </div>
            </div>

            {/* AGENT MATRIX - Real Agent Logs */}
            <div className="col-span-1 sm:col-span-2 lg:col-span-2 bg-slate-900 rounded-xl border border-slate-800 p-6">
              <div className="flex items-center justify-between mb-4">
                <h3 className="text-sm font-bold uppercase tracking-wider font-sans text-slate-300">Agent Matrix</h3>
                <div className="flex items-center gap-2">
                  <div className="w-2 h-2 bg-emerald-500 rounded-full animate-pulse" />
                  <span className="text-xs font-medium text-emerald-500 font-sans uppercase tracking-wider">{sanitizeValue(realAgents.length)} Active</span>
                </div>
              </div>
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                {realAgents.length > 0 ? realAgents.map((agent) => (
                  <div key={agent.name} className="relative p-3 rounded-lg border border-slate-700 hover:border-slate-600 transition-all duration-200 hover:scale-105 bg-slate-800">
                    <div className="absolute top-2 right-2">
                      <div className={cn("w-1.5 h-1.5 rounded-full", agent.heartbeat ? "bg-emerald-500 animate-pulse" : "bg-slate-400")} />
                    </div>
                    <div className="text-xs font-bold font-sans text-slate-200 mb-2">{agent.name}</div>
                    <div className="space-y-1">
                      <div className="flex justify-between items-center">
                        <span className="text-xs font-sans text-slate-400">Status</span>
                        <span className="text-xs font-mono tabular-nums text-slate-300">{sanitizeValue(agent.heartbeat ? 'ACTIVE' : 'IDLE')}</span>
                      </div>
                      <div className="flex justify-between items-center">
                        <span className="text-xs font-sans text-slate-400">Events</span>
                        <span className="text-xs font-mono tabular-nums text-slate-300">{sanitizeValue(agent.events)}</span>
                      </div>
                    </div>
                  </div>
                )) : (
                  <div className="col-span-full text-center py-8">
                    <span className="text-slate-400 text-sm font-sans">No agent data available</span>
                  </div>
                )}
              </div>
            </div>

            {/* TICKER STRIP - Real Prices */}
            <div className="col-span-1 sm:col-span-2 lg:col-span-4 bg-slate-900 rounded-xl border border-slate-800 p-4">
              <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-4 divide-x divide-slate-800">
                {realTickerData.length > 0 ? realTickerData.map((ticker) => (
                  <div key={ticker.symbol} className="pl-4 first:pl-0">
                    <div className="flex items-center justify-between mb-1">
                      <span className="text-xs font-bold font-sans uppercase tracking-wider text-slate-400">{ticker.symbol}</span>
                      <div className={cn("w-1.5 h-1.5 rounded-full", ticker.change >= 0 ? "bg-emerald-500" : "bg-red-500")} />
                    </div>
                    <div className="text-right">
                      <div className="text-sm font-mono tabular-nums text-slate-200">{formatUSD(ticker.price)}</div>
                      <div className={cn("text-xs font-mono tabular-nums", ticker.change >= 0 ? "text-emerald-500" : "text-red-500")}>
                        {ticker.change >= 0 ? '+' : ''}{sanitizeValue(ticker.change.toFixed(2))} ({ticker.changePercent >= 0 ? '+' : ''}{sanitizeValue(ticker.changePercent.toFixed(2))}%)
                      </div>
                    </div>
                  </div>
                )) : (
                  <div className="col-span-full text-center py-4">
                    <span className="text-slate-400 text-sm font-sans">N/A - No price data</span>
                  </div>
                )}
              </div>
            </div>
          </div>
        </div>
        <MobileNavigation activeSection={section} onSectionChange={() => {}} />
      </div>
    )
  }

  // TRADING PAGE - Real Data Only
  if (section === 'trading') {
    return (
      <div className="min-h-screen bg-slate-950">
        <Header />
        <div className="max-w-7xl mx-auto px-4 py-6 space-y-6">
          {/* AGENT THOUGHT STREAM - Real Agent Logs */}
          <div className="bg-slate-900 rounded-xl border border-slate-800 p-6">
            <div className="flex items-center justify-between mb-6">
              <h3 className="text-sm font-bold uppercase tracking-wider font-sans text-slate-300">Agent Thought Stream</h3>
              <div className="flex items-center gap-2">
                <div className="w-2 h-2 bg-emerald-500 rounded-full animate-pulse" />
                <span className="text-xs font-medium text-emerald-500 font-sans uppercase tracking-wider">Live</span>
              </div>
            </div>
            <div className="space-y-4 max-h-96 overflow-y-auto">
              {agentLogs.length > 0 ? agentLogs.slice(-10).reverse().map((log, index) => (
                <motion.div key={index} className="p-4 rounded-lg border border-slate-700 bg-slate-800">
                  <div className="flex items-start justify-between mb-2">
                    <div className="flex items-center gap-3">
                      <Brain className="w-4 h-4 text-emerald-500" />
                      <span className="text-xs font-bold font-sans text-slate-200">{sanitizeValue(log.agent_name || 'Unknown')}</span>
                    </div>
                    <div className="text-xs font-mono tabular-nums font-mono px-2 py-1 rounded bg-emerald-500/20 text-emerald-400">
                      {sanitizeValue(log.confidence ? `${(log.confidence * 100).toFixed(0)}%` : 'N/A')}
                    </div>
                  </div>
                  <p className="text-sm font-sans text-slate-300 leading-relaxed">{sanitizeValue(log.message || 'No message')}</p>
                </motion.div>
              )) : (
                <div className="text-center py-8">
                  <span className="text-slate-400 text-sm font-sans">No agent thoughts available</span>
                </div>
              )}
            </div>
          </div>

          {/* OPEN POSITIONS TABLE - Real Orders */}
          <div className="bg-slate-900 rounded-xl border border-slate-800 p-6">
            <div className="flex items-center justify-between mb-6">
              <h3 className="text-sm font-bold uppercase tracking-wider font-sans text-slate-300">Open Positions</h3>
              <span className="text-xs font-medium font-sans text-slate-400">{sanitizeValue(positions.length)} Active</span>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full">
                <thead>
                  <tr className="text-xs font-semibold uppercase tracking-wider font-sans text-slate-400">
                    <th className="text-left pb-3">Symbol</th>
                    <th className="text-center pb-3">Side</th>
                    <th className="text-right pb-3">Qty</th>
                    <th className="text-right pb-3">Entry</th>
                    <th className="text-right pb-3">Current</th>
                    <th className="text-right pb-3">P&L</th>
                  </tr>
                </thead>
                <tbody>
                  {positions.length > 0 ? positions.map((position, index) => (
                    <tr key={index} className="border-t border-slate-800">
                      <td className="py-3 font-mono tabular-nums font-mono font-bold text-slate-200">{sanitizeValue(position.symbol)}</td>
                      <td className="py-3 text-center">
                        <span className={cn("text-xs font-bold uppercase px-2 py-1 rounded", position.side === 'long' ? "bg-emerald-500/20 text-emerald-400" : "bg-red-500/20 text-red-400")}>
                          {sanitizeValue(position.side)}
                        </span>
                      </td>
                      <td className="py-3 text-right font-mono tabular-nums font-mono text-slate-300">{sanitizeValue(position.quantity)}</td>
                      <td className="py-3 text-right font-mono tabular-nums font-mono text-slate-300">{formatUSD(position.entry_price)}</td>
                      <td className="py-3 text-right font-mono tabular-nums font-mono text-slate-300">{formatUSD(position.current_price)}</td>
                      <td className={cn("py-3 text-right font-mono tabular-nums font-mono font-bold", (position.pnl || 0) >= 0 ? "text-emerald-500" : "text-red-500")}>
                        {(position.pnl || 0) >= 0 ? '+' : ''}{formatUSD(position.pnl)}
                        <div className="text-xs">({(position.pnl_percent || 0) >= 0 ? '+' : ''}{sanitizeValue((position.pnl_percent || 0).toFixed(2))}%)</div>
                      </td>
                    </tr>
                  )) : (
                    <tr>
                      <td colSpan={6} className="py-8 text-center">
                        <span className="text-slate-400 text-sm font-sans">No open positions</span>
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </div>
        <MobileNavigation activeSection={section} onSectionChange={() => {}} />
      </div>
    )
  }

  // AGENTS PAGE - Real Agent Data Only
  if (section === 'agents') {
    return (
      <div className="min-h-screen bg-slate-950">
        <Header />
        <div className="max-w-7xl mx-auto px-4 py-6">
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-6">
            {realAgents.length > 0 ? realAgents.map((agent, index) => (
              <div key={agent.name} className="bg-slate-900 rounded-xl border border-slate-800 p-6">
                <div className="flex items-center justify-between mb-4">
                  <h4 className="text-sm font-bold font-sans text-slate-200">{agent.name}</h4>
                  <div className="flex items-center gap-2">
                    <div className={cn("w-2 h-2 rounded-full", agent.heartbeat ? "bg-emerald-500 animate-pulse" : "bg-slate-400")} />
                    <span className={cn("text-xs font-medium uppercase font-sans", agent.tier === 'active' ? "text-emerald-500" : "text-slate-400")}>
                      {sanitizeValue(agent.tier)}
                    </span>
                  </div>
                </div>
                <div className="space-y-3">
                  <div className="flex justify-between items-center">
                    <span className="text-xs font-semibold uppercase tracking-wider font-sans text-slate-400">Events</span>
                    <span className="text-sm font-mono tabular-nums font-mono text-slate-300">{sanitizeValue(agent.events)}</span>
                  </div>
                  <div className="flex justify-between items-center">
                    <span className="text-xs font-semibold uppercase tracking-wider font-sans text-slate-400">Last Seen</span>
                    <span className="text-sm font-mono tabular-nums font-mono text-slate-300">{formatTimeAgo(agent.lastSeen)}</span>
                  </div>
                  <div className="flex justify-between items-center">
                    <span className="text-xs font-semibold uppercase tracking-wider font-sans text-slate-400">Status</span>
                    <span className={cn("text-xs font-bold uppercase", agent.heartbeat ? "text-emerald-500" : "text-slate-400")}>
                      {agent.heartbeat ? 'ACTIVE' : 'IDLE'}
                    </span>
                  </div>
                </div>
              </div>
            )) : (
              <div className="col-span-full text-center py-8">
                <span className="text-slate-400 text-sm font-sans">No agent data available</span>
              </div>
            )}
          </div>
        </div>
        <MobileNavigation activeSection={section} onSectionChange={() => {}} />
      </div>
    )
  }

  // LEARNING PAGE - Real Learning Events Only
  if (section === 'learning') {
    return (
      <div className="min-h-screen bg-slate-950">
        <Header />
        <div className="max-w-7xl mx-auto px-4 py-6">
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-6 mb-6">
            <div className="bg-slate-900 rounded-xl border border-slate-800 p-6">
              <div className="flex items-center justify-between mb-4">
                <FileCode className="w-5 h-5 text-emerald-500" />
                <span className="text-xs font-medium text-emerald-500 font-sans uppercase tracking-wider">Evaluated</span>
              </div>
              <div className="text-2xl font-black tabular-nums font-mono text-slate-200 mb-2">{sanitizeValue(learningMetrics.tradesEvaluated)}</div>
              <span className="text-xs font-semibold uppercase tracking-wider font-sans text-slate-400">Trades</span>
            </div>
            <div className="bg-slate-900 rounded-xl border border-slate-800 p-6">
              <div className="flex items-center justify-between mb-4">
                <Brain className="w-5 h-5 text-amber-500" />
                <span className="text-xs font-medium text-amber-500 font-sans uppercase tracking-wider">Completed</span>
              </div>
              <div className="text-2xl font-black tabular-nums font-mono text-slate-200 mb-2">{sanitizeValue(learningMetrics.reflectionsCompleted)}</div>
              <span className="text-xs font-semibold uppercase tracking-wider font-sans text-slate-400">Reflections</span>
            </div>
            <div className="bg-slate-900 rounded-xl border border-slate-800 p-6">
              <div className="flex items-center justify-between mb-4">
                <Activity className="w-5 h-5 text-indigo-500" />
                <span className="text-xs font-medium text-indigo-500 font-sans uppercase tracking-wider">Updated</span>
              </div>
              <div className="text-2xl font-black tabular-nums font-mono text-slate-200 mb-2">{sanitizeValue(learningMetrics.icUpdates)}</div>
              <span className="text-xs font-semibold uppercase tracking-wider font-sans text-slate-400">IC Values</span>
            </div>
            <div className="bg-slate-900 rounded-xl border border-slate-800 p-6">
              <div className="flex items-center justify-between mb-4">
                <Zap className="w-5 h-5 text-purple-500" />
                <span className="text-xs font-medium text-purple-500 font-sans uppercase tracking-wider">Tested</span>
              </div>
              <div className="text-2xl font-black tabular-nums font-mono text-slate-200 mb-2">{sanitizeValue(learningMetrics.strategiesTested)}</div>
              <span className="text-xs font-semibold uppercase tracking-wider font-sans text-slate-400">Strategies</span>
            </div>
          </div>
          <div className="bg-slate-900 rounded-xl border border-slate-800 p-6">
            <h3 className="text-sm font-bold uppercase tracking-wider font-sans text-slate-300 mb-6">Performance Summary</h3>
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-6">
              <div>
                <span className="text-xs font-semibold uppercase tracking-wider font-sans text-slate-400 block mb-2">Win Rate</span>
                <div className={cn("text-xl font-black tabular-nums font-mono", learningMetrics.avgWinRate >= 70 ? "text-emerald-500" : "text-amber-500")}>
                  {sanitizeValue(learningMetrics.avgWinRate.toFixed(1))}%
                </div>
              </div>
              <div>
                <span className="text-xs font-semibold uppercase tracking-wider font-sans text-slate-400 block mb-2">Total P&L</span>
                <div className={cn("text-xl font-black tabular-nums font-mono", learningMetrics.totalPnl >= 0 ? "text-emerald-500" : "text-red-500")}>
                  {formatUSD(learningMetrics.totalPnl)}
                </div>
              </div>
              <div>
                <span className="text-xs font-semibold uppercase tracking-wider font-sans text-slate-400 block mb-2">Best Day</span>
                <div className="text-xl font-black tabular-nums font-mono text-emerald-500">{formatUSD(learningMetrics.bestDay)}</div>
              </div>
              <div>
                <span className="text-xs font-semibold uppercase tracking-wider font-sans text-slate-400 block mb-2">Worst Day</span>
                <div className="text-xl font-black tabular-nums font-mono text-red-500">{formatUSD(learningMetrics.worstDay)}</div>
              </div>
            </div>
          </div>
        </div>
        <MobileNavigation activeSection={section} onSectionChange={() => {}} />
      </div>
    )
  }

  // SYSTEM PAGE - Real System Metrics Only
  if (section === 'system') {
    return (
      <div className="min-h-screen bg-slate-950">
        <Header />
        <div className="max-w-7xl mx-auto px-4 py-6">
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-4 mb-6">
            {[
              { label: 'Market Ticks', value: sanitizeValue(realSystemMetrics.marketTicks.toLocaleString()), icon: Activity, color: 'emerald' },
              { label: 'Signals', value: sanitizeValue(realSystemMetrics.signals.toLocaleString()), icon: Zap, color: 'amber' },
              { label: 'Orders', value: sanitizeValue(realSystemMetrics.orders.toLocaleString()), icon: FileCode, color: 'indigo' },
              { label: 'Executions', value: sanitizeValue(realSystemMetrics.executions.toLocaleString()), icon: Award, color: 'purple' },
              { label: 'Latency', value: `${sanitizeValue(realSystemMetrics.avgLatency)}ms`, icon: Clock, color: 'blue' },
              { label: 'Error Rate', value: `${sanitizeValue(realSystemMetrics.errorRate)}%`, icon: AlertTriangle, color: 'red' },
            ].map((metric, index) => (
              <div key={metric.label} className="bg-slate-900 rounded-xl border border-slate-800 p-4">
                <div className="flex items-center justify-between mb-2">
                  <metric.icon className={cn("w-4 h-4", metric.color === 'emerald' ? "text-emerald-500" : metric.color === 'amber' ? "text-amber-500" : metric.color === 'indigo' ? "text-indigo-500" : metric.color === 'purple' ? "text-purple-500" : metric.color === 'blue' ? "text-blue-500" : "text-red-500")} />
                  <span className={cn("text-xs font-medium uppercase font-sans", metric.color === 'emerald' ? "text-emerald-500" : metric.color === 'amber' ? "text-amber-500" : metric.color === 'indigo' ? "text-indigo-500" : metric.color === 'purple' ? "text-purple-500" : metric.color === 'blue' ? "text-blue-500" : "text-red-500")}>Live</span>
                </div>
                <div className="text-lg font-black tabular-nums font-mono text-slate-200 mb-1">{metric.value}</div>
                <span className="text-xs font-semibold uppercase tracking-wider font-sans text-slate-400">{metric.label}</span>
              </div>
            ))}
          </div>
          <div className="bg-slate-900 rounded-xl border border-slate-800 p-6">
            <div className="flex items-center justify-between mb-6">
              <h3 className="text-sm font-bold uppercase tracking-wider font-sans text-slate-300">Agent Status</h3>
              <span className="text-xs font-medium font-sans text-slate-400">{sanitizeValue(realAgents.length)} Total Agents</span>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full">
                <thead>
                  <tr className="text-xs font-semibold uppercase tracking-wider font-sans text-slate-400">
                    <th className="text-left pb-3">Agent</th>
                    <th className="text-center pb-3">Status</th>
                    <th className="text-right pb-3">Events</th>
                    <th className="text-right pb-3">Last Seen</th>
                  </tr>
                </thead>
                <tbody>
                  {realAgents.length > 0 ? realAgents.map((agent, index) => (
                    <tr key={agent.name} className="border-t border-slate-800">
                      <td className="py-3 font-mono tabular-nums font-mono font-bold text-slate-200">{agent.name}</td>
                      <td className="py-3 text-center">
                        <div className="flex items-center justify-center gap-2">
                          <div className={cn("w-2 h-2 rounded-full", agent.heartbeat ? "bg-emerald-500 animate-pulse" : "bg-slate-400")} />
                          <span className={cn("text-xs font-bold uppercase", agent.heartbeat ? "text-emerald-500" : "text-slate-400")}>
                            {agent.heartbeat ? 'ACTIVE' : 'IDLE'}
                          </span>
                        </div>
                      </td>
                      <td className="py-3 text-right font-mono tabular-nums font-mono text-slate-300">{sanitizeValue(agent.events)}</td>
                      <td className="py-3 text-right font-mono tabular-nums font-mono text-slate-300">{formatTimeAgo(agent.lastSeen)}</td>
                    </tr>
                  )) : (
                    <tr>
                      <td colSpan={4} className="py-8 text-center">
                        <span className="text-slate-400 text-sm font-sans">No agent data available</span>
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </div>
        <MobileNavigation activeSection={section} onSectionChange={() => {}} />
      </div>
    )
  }

  // Fallback removed - all pages should work with real data
  return null
}
