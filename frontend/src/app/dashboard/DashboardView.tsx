'use client'

import { useEffect, useMemo, useState } from 'react'
import { useCodexStore } from '@/stores/useCodexStore'
import { ObsidianDashboard } from '@/components/obsidian-pro/ObsidianDashboard'
import {
  TrendingUp,
  BarChart3,
  Layers,
  Zap,
  CheckCircle2,
  AlertTriangle,
  X,
  Bot,
  RotateCcw,
  Trash2,
  CandlestickChart,
  BookOpen,
  Settings2,
  Activity,
  Clock,
  Power,
  Play,
  Pause
} from 'lucide-react'
import { Card } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
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
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger } from '@/components/ui/dialog'
import { Skeleton } from '@/components/ui/skeleton'
import { cn } from '@/lib/utils'
import { motion, AnimatePresence } from 'framer-motion'
import { TrendingDown, ChevronUp, ChevronDown } from 'lucide-react'

const API_BASE = (process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000/api').replace(/\/$/, '')

export function DashboardView({ section }: { section: 'overview' | 'trading' | 'agents' | 'learning' | 'system' }) {
  const { 
    agentLogs, 
    killSwitchActive, 
    learningEvents, 
    orders, 
    prices, 
    positions, 
    systemMetrics,
    dashboardData,
    isLoading,
    wsConnected,
    setKillSwitch,
    addSystemMetric
  } = useCodexStore()

  const [selected, setSelected] = useState('BTC/USD')
  const [selectedTf, setSelectedTf] = useState('5m')
  const [dlqItems, setDlqItems] = useState<any[]>([])
  const [isCompactMode, setIsCompactMode] = useState(false)
  const [showToast, setShowToast] = useState(false)
  const [toastMessage, setToastMessage] = useState('')
  const [previousPnl, setPreviousPnl] = useState(0)
  const [isAnimating, setIsAnimating] = useState(false)

  // Calculate metrics with enhanced data
  const dailyPnl = useMemo(() => 
    orders.reduce((sum, o) => sum + Number(o.pnl || 0), 0), 
    [orders]
  )

  // Calculate secondary metrics
  const pnlChange = dailyPnl - previousPnl
  const pnlChangePercent = previousPnl !== 0 ? (pnlChange / Math.abs(previousPnl)) * 100 : 0
  const winRate = orders.length > 0 ? (orders.filter(o => Number(o.pnl) > 0).length / orders.length) * 100 : 0
  const activePositions = orders.filter(o => o.side === 'long' || o.side === 'short').length

  // Animate P&L changes
  useEffect(() => {
    if (dailyPnl !== previousPnl) {
      setIsAnimating(true)
      const timer = setTimeout(() => {
        setPreviousPnl(dailyPnl)
        setIsAnimating(false)
      }, 300)
      return () => clearTimeout(timer)
    }
  }, [dailyPnl, previousPnl])

  const avgLatency = useMemo(() => {
    const latencies = agentLogs.map(l => l.latency_ms || 0).filter(l => l > 0)
    return latencies.length > 0 ? Math.round(latencies.reduce((a, b) => a + b, 0) / latencies.length) : 0
  }, [agentLogs])

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
      
      // Only add mock data if we have real system metrics (indicating WebSocket is working)
      if (systemMetrics.length > 0) {
        mockStreamMetrics.forEach(metric => {
          addSystemMetric(metric)
        })
      }
    }
  }, [systemMetrics, addSystemMetric])

  const costToday = systemMetrics.find(m => m.metric_name === 'llm_cost_usd')?.value || 0

  // Market status (simplified - in real app this would check actual market hours)
  const currentTime = new Date()
  const marketHours = { open: 9.5, close: 16 } // 9:30 AM - 4:00 PM EST
  const currentHour = currentTime.getHours() + currentTime.getMinutes() / 60
  const marketStatus = currentHour >= marketHours.open && currentHour <= marketHours.close

  // OVERVIEW PAGE - Professional Trading Command Center
  if (section === 'overview') {
    return (
      <div className="min-h-screen bg-white dark:bg-zinc-950">
        {/* HIGH-PERFORMANCE TRADING TERMINAL HEADER */}
        <div className="h-16 bg-white dark:bg-zinc-950 border-b border-slate-200 dark:border-slate-800 flex items-center justify-between px-6">
          {/* LEFT - CLEAN SYSTEM STATUS */}
          <div className="flex items-center gap-6">
            <span className="text-sm font-medium text-slate-600 dark:text-slate-400">
              System / Overview
            </span>
            <div className="h-4 w-px bg-slate-200 dark:bg-slate-700" />
            
            {/* LATENCY - Monospace */}
            <span className="text-sm font-mono text-slate-600 dark:text-slate-400">
              {avgLatency}ms
            </span>
          </div>
          
          {/* RIGHT - CONTROLS */}
          <div className="flex items-center gap-4">
            {/* P&L DISPLAY - Monospace Data */}
            <div className="flex flex-col items-end">
              <span className={cn(
                "text-lg font-bold font-mono tabular-nums",
                dailyPnl >= 0 ? "text-slate-950 dark:text-slate-100" : "text-slate-700 dark:text-slate-300"
              )}>
                {dailyPnl >= 0 ? '+' : ''}${dailyPnl.toFixed(2)}
              </span>
              <span className="text-xs font-medium text-slate-600 dark:text-slate-400">
                24h P&L
              </span>
            </div>

            {/* EXPORT BUTTON - Clean Style */}
            <button className="h-10 bg-slate-100 dark:bg-slate-800 border-2 border-slate-300 dark:border-slate-600 px-4 text-[10px] font-semibold uppercase tracking-[0.2em] text-slate-900 dark:text-slate-100 transition-all hover:bg-slate-200 dark:hover:bg-slate-700 rounded-xl">
              Export Report
            </button>

            {/* TRADING CONTROL BUTTON */}
            <button 
              onClick={() => {
                setKillSwitch(!killSwitchActive)
                setToastMessage(killSwitchActive ? 'Trading Stopped' : 'Trading Started')
                setShowToast(true)
                setTimeout(() => setShowToast(false), 3000)
              }}
              className="h-10 bg-slate-100 dark:bg-slate-800 border-2 border-slate-300 dark:border-slate-600 px-4 text-[10px] font-semibold uppercase tracking-[0.2em] text-slate-900 dark:text-slate-100 transition-all hover:bg-slate-200 dark:hover:bg-slate-700 rounded-xl"
            >
              {killSwitchActive ? 'Stop Trading' : 'Start Trading'}
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

        {/* MAIN GRID - Professional Layout */}
        <div className={cn(
          "p-6 space-y-6 transition-all duration-300",
          isCompactMode ? "space-y-4" : "space-y-6"
        )}>
          {/* ROW 1 - PRIMARY SIGNALS */}
          <div className="grid grid-cols-12 gap-6">
            {/* P&L HERO CARD - MOST IMPORTANT */}
            <motion.div 
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.5 }}
              className="col-span-8"
            >
              <div className="bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-xl p-6 backdrop-blur-sm">
                <div className="flex items-center justify-between mb-4">
                  <p className="text-sm font-medium text-slate-600 dark:text-slate-400 uppercase tracking-[0.2em]">
                    TOTAL P&L
                  </p>
                  <button
                    onClick={() => setIsCompactMode(!isCompactMode)}
                    className="text-xs font-medium text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-slate-100 transition-colors"
                  >
                    {isCompactMode ? 'Expand' : 'Compact'}
                  </button>
                </div>

                <div className="flex items-center gap-4 mb-4">
                  <motion.h1 
                    key={dailyPnl}
                    initial={{ scale: 0.8, opacity: 0 }}
                    animate={{ scale: 1, opacity: 1 }}
                    className={cn(
                      "text-5xl font-black tracking-tight tabular-nums transition-all duration-300 font-mono",
                      isAnimating && "scale-105",
                      dailyPnl >= 0 ? "text-slate-950 dark:text-slate-100" : "text-slate-700 dark:text-slate-300"
                    )}
                  >
                    {dailyPnl >= 0 ? '+' : ''}${dailyPnl.toFixed(2)}
                  </motion.h1>
                  <span className="text-sm font-medium text-slate-600 dark:text-slate-400">
                    24h
                  </span>
                </div>

                {/* Secondary Metrics */}
                <div className="grid grid-cols-3 gap-4 mb-6">
                  <div className="text-center">
                    <p className="text-xs font-medium text-slate-600 dark:text-slate-400 uppercase tracking-[0.2em] mb-1">Change</p>
                    <div className={cn(
                      "flex items-center justify-center gap-1 text-sm font-semibold font-mono",
                      pnlChange > 0 ? "text-slate-950 dark:text-slate-100" : "text-slate-700 dark:text-slate-300"
                    )}>
                      {pnlChange > 0 ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
                      {pnlChange >= 0 ? '+' : ''}{pnlChange.toFixed(2)}
                    </div>
                  </div>
                  <div className="text-center">
                    <p className="text-xs font-medium text-slate-600 dark:text-slate-400 uppercase tracking-[0.2em] mb-1">Win Rate</p>
                    <p className="text-sm font-semibold text-slate-950 dark:text-slate-100 font-mono">
                      {winRate.toFixed(1)}%
                    </p>
                  </div>
                  <div className="text-center">
                    <p className="text-xs font-medium text-slate-600 dark:text-slate-400 uppercase tracking-[0.2em] mb-1">Positions</p>
                    <p className="text-sm font-semibold text-slate-950 dark:text-slate-100 font-mono">
                      {activePositions}
                    </p>
                  </div>
                </div>

                {/* Mini chart placeholder */}
                <div className="opacity-60">
                  <div className="h-16 bg-slate-100 dark:bg-slate-800 rounded-xl flex items-center justify-center border-2 border-dashed border-slate-300 dark:border-slate-600">
                    <TrendingUp className="w-6 h-6 text-slate-400 dark:text-slate-500 opacity-20" />
                  </div>
                </div>
              </div>
            </motion.div>

            {/* MARKET SENTIMENT - COMPACT */}
            <motion.div 
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.5, delay: 0.1 }}
              className="col-span-4"
            >
              <div className="bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-xl p-6 backdrop-blur-sm">
                <p className="text-sm font-medium text-slate-600 dark:text-slate-400 mb-4 uppercase tracking-[0.2em]">
                  MARKET SENTIMENT
                </p>

                <div className="flex flex-col items-center justify-center">
                  {/* Simple gauge */}
                  <div className="w-20 h-20 rounded-xl border border-slate-300 dark:border-slate-600 flex items-center justify-center mb-3">
                    <div className="w-16 h-16 rounded-xl bg-slate-100 dark:bg-slate-800 flex items-center justify-center">
                      <span className="text-lg font-semibold text-slate-950 dark:text-slate-100 font-mono">65</span>
                    </div>
                  </div>

                  <p className="text-lg font-semibold text-slate-950 dark:text-slate-100">
                    Neutral
                  </p>
                  <p className="text-sm text-slate-600 dark:text-slate-400 mt-1">
                    Fear & Greed Index
                  </p>
                </div>
              </div>
            </motion.div>
          </div>

          {/* ROW 2 - SYSTEM STATE */}
          <motion.div 
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.5, delay: 0.2 }}
          >
            {/* MARKET STATUS */}
            <div className="bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-xl p-6 backdrop-blur-sm">
              <div className="flex items-center justify-between">
                {/* LEFT */}
                <div className="flex items-center gap-4">
                  <div className="w-10 h-10 rounded-xl bg-slate-100 dark:bg-slate-800 flex items-center justify-center">
                    {marketStatus ? (
                      <Play className="w-5 h-5 text-slate-600 dark:text-slate-400" />
                    ) : (
                      <Pause className="w-5 h-5 text-slate-500" />
                    )}
                  </div>
                  <div>
                    <p className="text-lg font-semibold text-slate-950 dark:text-slate-100">
                      {marketStatus ? 'Markets Open' : 'Markets Closed'}
                    </p>
                    <p className="text-sm text-slate-600 dark:text-slate-400">
                      {marketStatus ? 'Trading Active' : `Opens 9:30 AM EST`}
                    </p>
                  </div>
                </div>

                {/* RIGHT */}
                <div className="text-sm font-medium text-slate-600 dark:text-slate-400">
                  9:30 AM – 4:00 PM EST
                </div>
              </div>
            </div>
          </motion.div>
        </div>
      </div>
    )
  }

  // TRADING PAGE
  if (section === 'trading') {
    return (
      <div className="min-h-screen bg-white dark:bg-slate-950">
        {/* TOP BAR */}
        <div className="flex items-center justify-between px-6 py-3 border-b border-gray-200 dark:border-slate-800 bg-white dark:bg-black">
          <div className="flex items-center gap-4">
            <span className="text-gray-600 dark:text-gray-400 text-sm">
              System / Trading
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
              New Order
            </button>
          </div>
        </div>

        <div className="p-6 space-y-8">
          {/* Symbol Selection */}
          <div className="bg-white dark:bg-slate-900 border border-gray-200 dark:border-slate-800 rounded-xl p-4 shadow-sm">
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
              <div className="flex flex-wrap gap-2">
                {['BTC/USD','ETH/USD','SOL/USD','SPY','AAPL','NVDA'].map(s => (
                  <button
                    key={s}
                    className={cn(
                      "px-3 py-1.5 text-xs font-medium rounded-lg transition-all duration-200",
                      selected === s
                        ? "bg-gray-900 text-white"
                        : "text-gray-600 hover:bg-gray-100 dark:text-gray-400 dark:hover:bg-slate-800"
                    )}
                    onClick={() => setSelected(s)}
                  >
                    {s}
                  </button>
                ))}
              </div>
              <div className="flex gap-2">
                {['1m','5m','15m','1h','4h'].map(tf => (
                  <button
                    key={tf}
                    className={cn(
                      "px-2.5 py-1 text-xs rounded-md transition-all duration-200",
                      selectedTf === tf 
                        ? "bg-gray-900 text-white" 
                        : "text-gray-600 hover:bg-gray-100 dark:text-gray-400 dark:hover:bg-slate-800"
                    )}
                    onClick={() => setSelectedTf(tf)}
                  >
                    {tf}
                  </button>
                ))}
              </div>
            </div>
          </div>

          {/* Trading Interface */}
          <div className="grid gap-6 lg:grid-cols-[1fr_360px]">
            {/* Chart Area */}
            <div className="bg-white dark:bg-slate-900 border border-gray-200 dark:border-slate-800 rounded-xl p-8 shadow-sm flex items-center justify-center min-h-96">
              <div className="text-center">
                <CandlestickChart className="h-16 w-16 text-gray-400 mx-auto mb-4" />
                <p className="text-lg text-gray-600 dark:text-gray-400 font-medium">Chart Integration</p>
                <p className="text-sm text-gray-500 dark:text-gray-500 mt-2">{selected} · {selectedTf} timeframe</p>
              </div>
            </div>

            {/* Order Panel */}
            <div className="space-y-6">
              <div className="bg-white dark:bg-slate-900 border border-gray-200 dark:border-slate-800 rounded-xl p-6 shadow-sm">
                <h3 className="text-sm font-semibold text-gray-900 dark:text-white mb-4">Order Entry</h3>
                <div className="space-y-4">
                  <div>
                    <label className="text-xs text-gray-600 dark:text-gray-400 mb-2 block font-medium uppercase">Symbol</label>
                    <div className="bg-gray-50 dark:bg-slate-800 border border-gray-200 dark:border-slate-700 px-3 py-2 text-sm font-mono text-gray-900 dark:text-white rounded-lg">
                      {selected}
                    </div>
                  </div>
                  <div>
                    <label className="text-xs text-gray-600 dark:text-gray-400 mb-2 block font-medium uppercase">Quantity</label>
                    <input 
                      className="w-full bg-gray-50 dark:bg-slate-800 border border-gray-200 dark:border-slate-700 px-3 py-2 text-sm font-mono text-gray-900 dark:text-white rounded-lg outline-none focus:ring-2 focus:ring-green-500/50 transition-all duration-200" 
                      placeholder="0.00" 
                    />
                  </div>
                  <div>
                    <label className="text-xs text-gray-600 dark:text-gray-400 mb-2 block font-medium uppercase">Price</label>
                    <input 
                      className="w-full bg-gray-50 dark:bg-slate-800 border border-gray-200 dark:border-slate-700 px-3 py-2 text-sm font-mono text-gray-900 dark:text-white rounded-lg outline-none focus:ring-2 focus:ring-green-500/50 transition-all duration-200" 
                      placeholder="Market" 
                    />
                  </div>
                  <div className="grid grid-cols-2 gap-3 pt-2">
                    <button className="bg-green-500 text-white py-2.5 text-sm font-semibold rounded-lg hover:bg-green-600 transition-all duration-200">
                      LONG
                    </button>
                    <button className="bg-red-500 text-white py-2.5 text-sm font-semibold rounded-lg hover:bg-red-600 transition-all duration-200">
                      SHORT
                    </button>
                  </div>
                </div>
              </div>

              {/* Positions */}
              <div className="bg-white dark:bg-slate-900 border border-gray-200 dark:border-slate-800 rounded-xl p-6 shadow-sm">
                <h3 className="text-sm font-semibold text-gray-900 dark:text-white mb-4">Open Positions</h3>
                {orders.length === 0 ? (
                  <div className="text-center py-8">
                    <p className="text-sm text-gray-600 dark:text-gray-400">No open positions</p>
                  </div>
                ) : (
                  <div className="space-y-3">
                    {orders.slice(0,3).map((o,i) => (
                      <div key={i} className="flex items-center justify-between p-3 bg-gray-50 dark:bg-slate-800 rounded-lg">
                        <div>
                          <p className="font-medium text-gray-900 dark:text-white">{o.symbol}</p>
                          <p className="text-xs text-gray-600 dark:text-gray-400">{(o.side || 'n/a').toUpperCase()}</p>
                        </div>
                        <p className={cn(
                          "font-semibold",
                          Number(o.pnl) >= 0 ? "text-green-600 dark:text-green-400" : "text-red-600 dark:text-red-400"
                        )}>
                          {Number(o.pnl) >= 0 ? '+' : ''}${Number(o.pnl || 0).toFixed(2)}
                        </p>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          </div>
        </div>
      </div>
    )
  }

  // AGENTS PAGE
  if (section === 'agents') {
    return (
      <div className="min-h-screen bg-white dark:bg-slate-950">
        {/* TOP BAR */}
        <div className="flex items-center justify-between px-6 py-3 border-b border-gray-200 dark:border-slate-800 bg-white dark:bg-black">
          <div className="flex items-center gap-4">
            <span className="text-gray-600 dark:text-gray-400 text-sm">
              System / Agents
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
              Configure Agents
            </button>
          </div>
        </div>

        <div className="p-6 space-y-8">
          {/* Metrics Strip */}
          <div className="grid grid-cols-4 gap-4">
            {[
              { label: 'Avg Latency', value: avgLatency + 'ms', icon: Activity, color: 'blue' },
              { label: 'Cost Today', value: '$' + costToday.toFixed(2), icon: Zap, color: 'yellow' },
              { label: 'Total Runs', value: agentLogs.length, icon: Bot, color: 'green' },
              { label: 'Fallbacks', value: agentLogs.filter(l => l.fallback).length, icon: AlertTriangle, color: 'red' },
            ].map((m, i) => (
              <motion.div
                key={i}
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: i * 0.1 }}
                className="bg-white dark:bg-slate-900 border border-gray-200 dark:border-slate-800 rounded-xl p-6 shadow-sm"
              >
                <div className="flex items-center justify-between mb-3">
                  <p className="text-xs font-semibold uppercase tracking-wider text-gray-600 dark:text-gray-400">
                    {m.label}
                  </p>
                  <m.icon className="h-4 w-4 text-gray-500" />
                </div>
                <p className="text-2xl font-bold text-gray-900 dark:text-white">
                  {m.value}
                </p>
              </motion.div>
            ))}
          </div>

          {/* Agent Activity */}
          <div className="bg-white dark:bg-slate-900 border border-gray-200 dark:border-slate-800 rounded-xl p-6 shadow-sm">
            <h3 className="text-sm font-semibold text-gray-900 dark:text-white mb-4">Agent Activity</h3>
            {agentLogs.length === 0 ? (
              <div className="text-center py-12">
                <Bot className="h-12 w-12 text-gray-400 mx-auto mb-4" />
                <p className="text-sm text-gray-600 dark:text-gray-400">No agent activity yet</p>
              </div>
            ) : (
              <div className="space-y-3">
                {agentLogs.slice(0,5).map((log, i) => (
                  <motion.div
                    key={i}
                    initial={{ opacity: 0, x: -20 }}
                    animate={{ opacity: 1, x: 0 }}
                    transition={{ delay: i * 0.1 }}
                    className={cn(
                      "p-4 rounded-lg border-l-4 transition-all duration-200 hover:shadow-md",
                      log.action === 'buy'  && "border-l-green-500 bg-green-50 dark:bg-green-950/20",
                      log.action === 'sell' && "border-l-red-500 bg-red-50 dark:bg-red-950/20",
                      !log.action || log.action === 'hold' && "border-l-gray-400 bg-gray-50 dark:bg-slate-800"
                    )}
                  >
                    <div className="flex items-center justify-between mb-2">
                      <div className="flex items-center gap-3">
                        <span className={cn(
                          "inline-flex px-2 py-1 text-xs font-semibold uppercase rounded-md",
                          log.action === 'buy'  ? "bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400" :
                          log.action === 'sell' ? "bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400" :
                          "bg-gray-100 text-gray-700 dark:bg-slate-700 dark:text-gray-300"
                        )}>
                          {log.action || 'HOLD'}
                        </span>
                        <span className="text-sm font-medium text-gray-900 dark:text-white">{log.symbol || '—'}</span>
                      </div>
                      <span className="text-xs text-gray-500 dark:text-gray-400">
                        {log.latency_ms || 0}ms
                      </span>
                    </div>
                    <p className="text-sm text-gray-600 dark:text-gray-400 line-clamp-2">
                      {log.primary_edge || 'No edge description'}
                    </p>
                  </motion.div>
                ))}
              </div>
            )}
          </div>
        </div>
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

      <div className="p-6 space-y-8">
        {/* STREAM COUNTS - Real-time from systemMetrics */}
        <div>
          <h3 className="text-sm font-semibold text-gray-600 dark:text-gray-400 mb-4 uppercase tracking-wider">
            Streams (last 5 min)
          </h3>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            {[
              { 
                name: 'market_ticks', 
                count: systemMetrics.filter(m => m.metric_name === 'market_tick_count').reduce((sum, m) => sum + Number(m.value || 0), 0),
                color: 'bg-emerald-500 text-white' 
              },
              { 
                name: 'signals', 
                count: systemMetrics.filter(m => m.metric_name === 'signal_count').reduce((sum, m) => sum + Number(m.value || 0), 0),
                color: 'bg-blue-500 text-white' 
              },
              { 
                name: 'orders', 
                count: systemMetrics.filter(m => m.metric_name === 'order_count').reduce((sum, m) => sum + Number(m.value || 0), 0),
                color: 'bg-purple-500 text-white' 
              },
              { 
                name: 'executions', 
                count: systemMetrics.filter(m => m.metric_name === 'execution_count').reduce((sum, m) => sum + Number(m.value || 0), 0),
                color: 'bg-orange-500 text-white' 
              },
            ].map((stream, i) => (
              <div key={i} className={cn("rounded-xl p-4 text-center", stream.color)}>
                <div className="text-2xl font-bold">{stream.count.toLocaleString()}</div>
                <div className="text-xs opacity-90">{stream.name}</div>
              </div>
            ))}
          </div>
        </div>

        {/* AGENTS GRID - Real-time from agentLogs */}
        <div>
          <h3 className="text-sm font-semibold text-gray-600 dark:text-gray-400 mb-4 uppercase tracking-wider">
            Agents
          </h3>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
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

                // Count events by type
                const eventType = log.event_type || log.action || log.type || 'unknown'
                agent.events[eventType] = (agent.events[eventType] || 0) + 1
                agent.totalEvents++

                // Track recent events (last 5 minutes)
                if (timestamp > fiveMinutesAgo) {
                  agent.recentEvents.push({ ...log, timestamp })
                }

                return acc
              }, {} as Record<string, AgentStats>)

              // Convert to array and determine status
              const agents = Object.values(agentStats).map((agent: AgentStats) => {
                const timeSinceLastEvent = now.getTime() - agent.lastTime.getTime()
                
                // Determine status based on last activity
                let status: 'active' | 'idle' | 'offline'
                if (timeSinceLastEvent < 20000) { // < 20 seconds
                  status = 'active'
                } else if (timeSinceLastEvent < 60000) { // < 1 minute
                  status = 'idle'
                } else {
                  status = 'offline'
                }

                // Determine tier based on activity level
                let tier: 'Active' | 'Challenger' | 'Retired'
                const recentEventCount = agent.recentEvents.length
                if (recentEventCount > 50) {
                  tier = 'Active'
                } else if (recentEventCount > 10) {
                  tier = 'Challenger'
                } else {
                  tier = 'Retired'
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
                  tier,
                  lastTimeFormatted: lastTimeStr,
                  recentCount: agent.recentEvents.length
                }
              })

              // Sort by activity (most recent first)
              agents.sort((a, b) => b.lastTime.getTime() - a.lastTime.getTime())

              return agents.map((agent, i) => {
                const getStatusIndicator = (status: string) => {
                  switch (status) {
                    case 'active': return '🟢 Active'
                    case 'idle': return '🟡 Idle'
                    case 'offline': return '🔴 Offline'
                    default: return '⚪ Unknown'
                  }
                }

                const getStatusColor = (status: string) => {
                  switch (status) {
                    case 'active': return 'border-green-200 bg-green-50 dark:bg-green-950/20 dark:border-green-800'
                    case 'idle': return 'border-yellow-200 bg-yellow-50 dark:bg-yellow-950/20 dark:border-yellow-800'
                    case 'offline': return 'border-red-200 bg-red-50 dark:bg-red-950/20 dark:border-red-800'
                    default: return 'border-gray-200 bg-gray-50 dark:bg-gray-950/20 dark:border-gray-800'
                  }
                }

                const getTierColor = (tier: string) => {
                  switch (tier) {
                    case 'Active': return 'text-green-600 dark:text-green-400'
                    case 'Challenger': return 'text-blue-600 dark:text-blue-400'
                    case 'Retired': return 'text-gray-600 dark:text-gray-400'
                    default: return 'text-gray-600 dark:text-gray-400'
                  }
                }

                const eventEntries = Object.entries(agent.events)
                const hasEvents = eventEntries.length > 0

                return (
                  <div key={i} className={cn(
                    "border rounded-xl p-4 transition-all duration-200 hover:shadow-md",
                    getStatusColor(agent.status)
                  )}>
                    {/* Agent Name */}
                    <div className="font-semibold text-gray-900 dark:text-white mb-2">
                      {agent.name}
                    </div>

                    {/* Status Indicator */}
                    <div className="text-sm font-medium mb-3">
                      {getStatusIndicator(agent.status)}
                    </div>

                    {/* Event Counts */}
                    {hasEvents ? (
                      <div className="space-y-1 mb-3">
                        {eventEntries.slice(0, 3).map(([eventType, count]) => (
                          <div key={eventType} className="text-sm text-gray-600 dark:text-gray-400">
                            {String(eventType).charAt(0).toUpperCase() + String(eventType).slice(1)}: {count} / 5m
                          </div>
                        ))}
                        {eventEntries.length > 3 && (
                          <div className="text-xs text-gray-500 dark:text-gray-500">
                            +{eventEntries.length - 3} more
                          </div>
                        )}
                      </div>
                    ) : (
                      <div className="text-sm text-gray-500 dark:text-gray-500 mb-3">
                        No events
                      </div>
                    )}

                    {/* Last Time */}
                    <div className="text-xs text-gray-500 dark:text-gray-500 mb-2">
                      Last: {agent.lastTimeFormatted}
                    </div>

                    {/* Tier */}
                    <div className={cn("text-xs font-semibold uppercase tracking-wider", getTierColor(agent.tier))}>
                      {agent.tier}
                    </div>
                  </div>
                )
              })
            })()}
          </div>
        </div>

        {/* LEGEND */}
        <div className="border-t border-gray-200 dark:border-slate-800 pt-4">
          <div className="flex flex-wrap gap-6 text-xs text-gray-600 dark:text-gray-400">
            <div className="flex items-center gap-2">
              <span>🟢</span>
              <span>Active (processing, last event &lt; 20s)</span>
            </div>
            <div className="flex items-center gap-2">
              <span>🟡</span>
              <span>Idle (last event &lt; 1min)</span>
            </div>
            <div className="flex items-center gap-2">
              <span>🔴</span>
              <span>Offline (no data in last 1min+)</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
