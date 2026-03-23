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
  Activity
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

const API_BASE = (process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000/api').replace(/\/$/, '')

export function DashboardView({ section }: { section: 'overview' | 'trading' | 'agents' | 'learning' | 'system' }) {
  const { 
    agentLogs, 
    killSwitchActive, 
    learningEvents, 
    orders, 
    prices, 
    positions, 
    regime, 
    riskAlerts, 
    signals, 
    systemMetrics, 
    wsConnected 
  } = useCodexStore()

  const [dlqItems, setDlqItems] = useState<any[]>([])
  const [selectedDlqItem, setSelectedDlqItem] = useState(null)
  const [loading, setLoading] = useState(false)
  const [selected, setSelected] = useState('BTC/USD')
  const [selectedTf, setSelectedTf] = useState('1m')

  const dailyPnl = orders.reduce((sum, o) => sum + Number(o.pnl || 0), 0)
  const avgLatency = agentLogs.length > 0 ? Math.round(agentLogs.reduce((sum, l) => sum + (l.latency_ms || 0), 0) / agentLogs.length) : 0
  const costToday = systemMetrics.find(m => m.metric_name === 'llm_cost_usd')?.value || 0

  // Fetch DLQ items
  useEffect(() => {
    if (section === 'system') {
      fetchDlqItems()
    }
  }, [section])

  const fetchDlqItems = async () => {
    try {
      setLoading(true)
      const response = await fetch(`${API_BASE}/dlq`)
      if (response.ok) {
        const data = await response.json()
        setDlqItems(data.items || [])
      }
    } catch (error) {
      console.error('Failed to fetch DLQ items:', error)
    } finally {
      setLoading(false)
    }
  }

  const replayDlq = async (eventId: string) => {
    try {
      const response = await fetch(`${API_BASE}/dlq/${eventId}/replay`, { method: 'POST' })
      if (response.ok) {
        fetchDlqItems()
      }
    } catch (error) {
      console.error('Failed to replay DLQ item:', error)
    }
  }

  const clearDlq = async (eventId: string) => {
    try {
      const response = await fetch(`${API_BASE}/dlq/${eventId}`, { method: 'DELETE' })
      if (response.ok) {
        fetchDlqItems()
      }
    } catch (error) {
      console.error('Failed to clear DLQ item:', error)
    }
  }

  // OVERVIEW PAGE - Use Obsidian-Pro Dashboard
  if (section === 'overview') {
    return <ObsidianDashboard />
  }

  // TRADING PAGE
  if (section === 'trading') {
    return (
      <div className="p-6 space-y-6">
        {/* Header */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-4">
            <div className="flex items-center gap-2 text-slate-400">
              <span>System</span>
              <span className="text-slate-600">/</span>
              <span className="text-slate-200">Trading</span>
            </div>
          </div>
        </div>

        <div className="grid gap-6 lg:grid-cols-[1fr_360px]">
          {/* Left: Chart + Positions */}
          <div className="space-y-6">
            {/* Symbol + Timeframe */}
            <div className="glass-card p-4 shadow-[0_8px_30px_rgb(0,0,0,0.12)]">
              <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
                <div className="flex flex-wrap gap-2">
                  {['BTC/USD','ETH/USD','SOL/USD','SPY','AAPL','NVDA'].map(s => (
                    <button
                      key={s}
                      className={cn(
                        "px-3 py-1.5 text-xs font-medium rounded-lg transition-all duration-200",
                        selected === s
                          ? "bg-violet-500/20 text-violet-400 ring-1 ring-violet-500/50"
                          : "text-slate-400 hover:bg-slate-800/50 hover:text-slate-200"
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
                          ? "bg-slate-700 text-slate-100" 
                          : "text-slate-500 hover:bg-slate-800/50 hover:text-slate-300"
                      )}
                      onClick={() => setSelectedTf(tf)}
                    >
                      {tf}
                    </button>
                  ))}
                </div>
              </div>
            </div>

            {/* Chart placeholder */}
            <div className="glass-card p-8 flex items-center justify-center min-h-80 shadow-[0_8px_30px_rgb(0,0,0,0.12)]">
              <div className="text-center">
                <CandlestickChart className="h-12 w-12 text-slate-600 mx-auto mb-4" />
                <p className="text-sm text-slate-400 font-medium">Chart Integration</p>
                <p className="text-xs text-slate-500 mt-2">{selected} · {selectedTf} timeframe</p>
              </div>
            </div>

            {/* Positions table */}
            <div className="glass-card overflow-hidden shadow-[0_8px_30px_rgb(0,0,0,0.12)]">
              <div className="px-6 py-4 border-b border-slate-700">
                <h3 className="text-[10px] font-semibold uppercase tracking-[0.2em] text-slate-500">Open Positions</h3>
              </div>
              {orders.length === 0 ? (
                <div className="px-6 py-12 text-center">
                  <p className="text-sm text-slate-400">No open positions</p>
                </div>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full">
                    <thead>
                      <tr className="bg-slate-800/30">
                        <th className="px-6 py-3 text-left text-[10px] font-semibold uppercase tracking-[0.2em] text-slate-500">Symbol</th>
                        <th className="px-6 py-3 text-left text-[10px] font-semibold uppercase tracking-[0.2em] text-slate-500">Side</th>
                        <th className="px-6 py-3 text-right text-[10px] font-semibold uppercase tracking-[0.2em] text-slate-500">Qty</th>
                        <th className="px-6 py-3 text-right text-[10px] font-semibold uppercase tracking-[0.2em] text-slate-500">P&L</th>
                      </tr>
                    </thead>
                    <tbody>
                      {orders.slice(0,10).map((o,i) => (
                        <tr key={i} className="border-t border-slate-800/50 hover:bg-slate-800/20 transition-colors duration-150">
                          <td className="px-6 py-4 font-medium text-slate-200">{o.symbol}</td>
                          <td className="px-6 py-4">
                            <span className={cn(
                              "inline-flex px-2 py-1 text-xs font-medium rounded-md",
                              o.side === 'long' || o.side === 'buy'
                                ? "bg-emerald-500/10 text-emerald-400"
                                : "bg-rose-500/10 text-rose-400"
                            )}>
                              {(o.side || 'n/a').toUpperCase()}
                            </span>
                          </td>
                          <td className="px-6 py-4 text-right font-mono text-sm text-slate-300">{o.qty || 0}</td>
                          <td className={cn(
                            "px-6 py-4 text-right font-mono text-sm tabular-nums font-semibold",
                            Number(o.pnl) >= 0 ? "text-emerald-400" : "text-rose-400"
                          )}>
                            {Number(o.pnl) >= 0 ? '+' : ''}{Number(o.pnl || 0).toFixed(2)}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          </div>

          {/* Right: Order Book + Entry Form */}
          <div className="space-y-6">
            {/* Order Book */}
            <div className="glass-card p-6 shadow-[0_8px_30px_rgb(0,0,0,0.12)]">
              <h3 className="text-[10px] font-semibold uppercase tracking-[0.2em] text-slate-500 mb-4">Order Book</h3>
              <div className="space-y-1">
                {[67510, 67505, 67500].map(p => (
                  <div key={p} className="flex justify-between text-xs py-1">
                    <span className="text-rose-400 font-mono tabular-nums">{p.toLocaleString()}</span>
                    <span className="text-slate-500">0.42</span>
                  </div>
                ))}
                <div className="my-3 py-2 text-center border-t border-b border-slate-700">
                  <div className="font-mono text-lg font-bold text-slate-100">
                    {prices[selected]?.price.toLocaleString() || '—'}
                  </div>
                </div>
                {[67495, 67490, 67485].map(p => (
                  <div key={p} className="flex justify-between text-xs py-1">
                    <span className="text-emerald-400 font-mono tabular-nums">{p.toLocaleString()}</span>
                    <span className="text-slate-500">1.05</span>
                  </div>
                ))}
              </div>
            </div>

            {/* Order Entry */}
            <div className="glass-card p-6 shadow-[0_8px_30px_rgb(0,0,0,0.12)]">
              <h3 className="text-[10px] font-semibold uppercase tracking-[0.2em] text-slate-500 mb-4">New Order</h3>
              <div className="space-y-4">
                <div>
                  <label className="text-xs text-slate-500 mb-2 block font-medium uppercase tracking-[0.2em]">Symbol</label>
                  <div className="glass-card px-3 py-2 text-sm font-mono text-slate-200">{selected}</div>
                </div>
                <div>
                  <label className="text-xs text-slate-500 mb-2 block font-medium uppercase tracking-[0.2em]">Quantity</label>
                  <input 
                    className="w-full glass-card px-3 py-2 text-sm font-mono text-slate-200 bg-transparent outline-none focus:ring-2 focus:ring-violet-500/50 transition-all duration-200" 
                    placeholder="0.00" 
                  />
                </div>
                <div>
                  <label className="text-xs text-slate-500 mb-2 block font-medium uppercase tracking-[0.2em]">Price</label>
                  <input 
                    className="w-full glass-card px-3 py-2 text-sm font-mono text-slate-200 bg-transparent outline-none focus:ring-2 focus:ring-violet-500/50 transition-all duration-200" 
                    placeholder="Market" 
                  />
                </div>
                <div className="grid grid-cols-2 gap-3 pt-2">
                  <button className="bg-emerald-500/20 text-emerald-400 py-2.5 text-sm font-semibold rounded-lg border border-emerald-500/30 hover:bg-emerald-500/30 transition-all duration-200">
                    LONG
                  </button>
                  <button className="bg-rose-500/20 text-rose-400 py-2.5 text-sm font-semibold rounded-lg border border-rose-500/30 hover:bg-rose-500/30 transition-all duration-200">
                    SHORT
                  </button>
                </div>
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
      <div className="p-6 space-y-6">
        {/* Header */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-4">
            <div className="flex items-center gap-2 text-slate-400">
              <span>System</span>
              <span className="text-slate-600">/</span>
              <span className="text-slate-200">Agents</span>
            </div>
          </div>
        </div>

        {/* Metrics Strip */}
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
          {[
            { label: 'Avg Latency', value: avgLatency + 'ms', icon: Activity },
            { label: 'Cost Today', value: '$' + costToday.toFixed(2), icon: Zap },
            { label: 'Total Runs', value: agentLogs.length, icon: Bot },
            { label: 'Fallbacks', value: agentLogs.filter(l => l.fallback).length, icon: AlertTriangle },
          ].map((m, i) => (
            <div key={i} className="glass-card p-6 shadow-[0_8px_30px_rgb(0,0,0,0.12)]">
              <div className="flex items-center justify-between mb-3">
                <p className="text-[10px] font-semibold uppercase tracking-[0.2em] text-slate-500">
                  {m.label}
                </p>
                <m.icon className="h-4 w-4 text-slate-500" />
              </div>
              <p className="data-value-large text-slate-200">
                {m.value}
              </p>
            </div>
          ))}
        </div>

        {/* Log List */}
        <div className="space-y-3">
          {agentLogs.length === 0 ? (
            <div className="glass-card p-12 text-center shadow-[0_8px_30px_rgb(0,0,0,0.12)]">
              <Bot className="h-12 w-12 text-slate-600 mx-auto mb-4" />
              <p className="text-sm text-slate-400 font-medium">No reasoning logs yet</p>
            </div>
          ) : (
            agentLogs.slice(0, 20).map((log, i) => (
              <div key={i} className={cn(
                "glass-card p-6 shadow-[0_8px_30px_rgb(0,0,0,0.12)] border-l-4 transition-all duration-200 hover:shadow-[0_12px_40px_rgb(0,0,0,0.18)]",
                log.action === 'buy'  && "border-l-emerald-500",
                log.action === 'sell' && "border-l-rose-500",
                !log.action || log.action === 'hold' && "border-l-violet-500"
              )}>
                <div className="flex items-center justify-between gap-4 flex-wrap mb-3">
                  <div className="flex items-center gap-3">
                    <span className={cn(
                      "inline-flex px-2 py-1 text-xs font-semibold uppercase rounded-md",
                      log.action === 'buy'  ? "bg-emerald-500/10 text-emerald-400" :
                      log.action === 'sell' ? "bg-rose-500/10 text-rose-400" :
                      "bg-violet-500/10 text-violet-400"
                    )}>
                      {log.action || 'HOLD'}
                    </span>
                    <span className="text-sm font-medium text-slate-200">{log.symbol || '—'}</span>
                  </div>
                  <div className="flex items-center gap-4 text-xs text-slate-500">
                    <span className="font-mono">{log.latency_ms || 0}ms</span>
                    <span className="font-mono">${log.cost_usd || '0.000'}</span>
                    {log.fallback && (
                      <span className="inline-flex px-2 py-0.5 text-xs font-medium rounded-full bg-amber-500/10 text-amber-400">
                        Fallback
                      </span>
                    )}
                  </div>
                </div>
                
                {/* Confidence Bar */}
                <div className="mb-3">
                  <div className="w-full bg-slate-800 rounded-full h-2 overflow-hidden">
                    <div 
                      className="bg-gradient-to-r from-violet-500 to-violet-400 h-2 rounded-full transition-all duration-500 ease-out"
                      style={{ width: `${(log.confidence || 0) * 100}%` }} 
                    />
                  </div>
                  <div className="mt-1 text-xs text-slate-500 font-medium">
                    Confidence: {((log.confidence || 0) * 100).toFixed(0)}%
                  </div>
                </div>
                
                <p className="text-sm text-slate-300 italic mb-3 line-clamp-2">
                  {log.primary_edge || 'No edge description'}
                </p>
                
                {/* Risk Factors */}
                {(log.risk_factors || []).length > 0 && (
                  <div className="flex flex-wrap gap-2">
                    {log.risk_factors.map((rf, j) => (
                      <span key={j} className="inline-flex px-2 py-0.5 text-xs font-medium rounded-full bg-slate-700/50 text-slate-400 border border-slate-600/50">
                        {rf}
                      </span>
                    ))}
                  </div>
                )}
              </div>
            ))
          )}
        </div>
      </div>
    )
  }

  // LEARNING PAGE
  if (section === 'learning') {
    return (
      <div className="p-6 space-y-6">
        {/* Header */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-4">
            <div className="flex items-center gap-2 text-slate-400">
              <span>System</span>
              <span className="text-slate-600">/</span>
              <span className="text-slate-200">Learning</span>
            </div>
          </div>
        </div>

        {/* Stat Cards */}
        <div className="grid grid-cols-3 gap-4">
          <div className="glass-card p-6 shadow-[0_8px_30px_rgb(0,0,0,0.12)]">
            <div className="flex items-center justify-between mb-3">
              <p className="text-[10px] font-semibold uppercase tracking-[0.2em] text-slate-500">Trades Evaluated</p>
              <TrendingUp className="h-4 w-4 text-slate-500" />
            </div>
            <p className="data-value-large text-slate-200">{learningEvents.length}</p>
          </div>
          <div className="glass-card p-6 shadow-[0_8px_30px_rgb(0,0,0,0.12)]">
            <div className="flex items-center justify-between mb-3">
              <p className="text-[10px] font-semibold uppercase tracking-[0.2em] text-slate-500">Reflections</p>
              <BookOpen className="h-4 w-4 text-slate-500" />
            </div>
            <p className="data-value-large text-slate-200">
              {learningEvents.filter(e => e.event === 'reflection_completed').length}
            </p>
          </div>
          <div className="glass-card p-6 shadow-[0_8px_30px_rgb(0,0,0,0.12)]">
            <div className="flex items-center justify-between mb-3">
              <p className="text-[10px] font-semibold uppercase tracking-[0.2em] text-slate-500">IC Updates</p>
              <Settings2 className="h-4 w-4 text-slate-500" />
            </div>
            <p className="data-value-large text-slate-200">0</p>
          </div>
        </div>

        {/* Trade Timeline */}
        <div className="glass-card overflow-hidden shadow-[0_8px_30px_rgb(0,0,0,0.12)] mb-6">
          <div className="px-6 py-4 border-b border-slate-700">
            <h3 className="text-[10px] font-semibold uppercase tracking-[0.2em] text-slate-500">Trade Timeline</h3>
          </div>
          {learningEvents.length === 0 ? (
            <div className="px-6 py-12 text-center">
              <TrendingUp className="h-12 w-12 text-slate-700 mx-auto mb-4" />
              <p className="text-base text-slate-600 font-medium">Complete paper trades to see performance</p>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full">
                <thead>
                  <tr className="bg-slate-800/30">
                    <th className="px-6 py-3 text-left text-[10px] font-semibold uppercase tracking-[0.2em] text-slate-600 w-1/3">Symbol</th>
                    <th className="px-6 py-3 text-left text-[10px] font-semibold uppercase tracking-[0.2em] text-slate-600 w-1/3">Event</th>
                    <th className="px-6 py-3 text-right text-[10px] font-semibold uppercase tracking-[0.2em] text-slate-600 w-1/3">P&L</th>
                  </tr>
                </thead>
                <tbody>
                  {learningEvents.slice(0,20).map((e,i) => (
                    <tr key={i} className="border-t border-slate-800/50 hover:bg-slate-800/20 transition-colors duration-150">
                      <td className="px-6 py-4 font-medium text-slate-200">{e.symbol || '—'}</td>
                      <td className="px-6 py-4 text-sm text-slate-400">{e.event || e.type}</td>
                      <td className={cn(
                        "px-6 py-4 text-right font-mono text-sm tabular-nums font-semibold",
                        Number(e.pnl) >= 0 ? "text-emerald-400" : "text-rose-400"
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

        {/* Reflection Log */}
        <div className="glass-card overflow-hidden shadow-[0_8px_30px_rgb(0,0,0,0.12)]">
          <div className="px-6 py-4 border-b border-slate-700">
            <h3 className="text-[10px] font-semibold uppercase tracking-[0.2em] text-slate-500">Reflection Log</h3>
          </div>
          {learningEvents.filter(e => e.event === 'reflection_completed').length === 0 ? (
            <div className="px-6 py-8 text-center">
              <p className="text-sm text-slate-400">Reflections appear after every 20 trades</p>
            </div>
          ) : (
            <div className="divide-y divide-slate-800/50">
              {learningEvents.filter(e => e.event === 'reflection_completed').map((e,i) => (
                <div key={i} className="px-6 py-4">
                  <div className="flex items-center justify-between mb-2">
                    <p className="text-xs font-mono text-slate-500 truncate flex-1 mr-4">{e.trace_id}</p>
                    <p className="text-xs text-slate-400">
                      {new Date(e.timestamp || Date.now()).toLocaleDateString()}
                    </p>
                  </div>
                  <p className="text-sm text-slate-200 font-medium leading-relaxed">{e.summary || 'No summary'}</p>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    )
  }

  // SYSTEM PAGE
  return (
    <div className="p-6 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-4">
          <div className="flex items-center gap-2 text-slate-400">
            <span>System</span>
            <span className="text-slate-600">/</span>
            <span className="text-slate-200">System</span>
          </div>
        </div>
      </div>

      {/* Stream Health */}
      <div className="glass-card overflow-hidden shadow-[0_8px_30px_rgb(0,0,0,0.12)]">
        <div className="px-6 py-4 border-b border-slate-700">
          <h3 className="text-[10px] font-semibold uppercase tracking-[0.2em] text-slate-500">Stream Health</h3>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead>
              <tr className="bg-slate-800/30">
                <th className="px-6 py-3 text-left text-[10px] font-semibold uppercase tracking-[0.2em] text-slate-500 w-1/4">Stream</th>
                <th className="px-6 py-3 text-left text-[10px] font-semibold uppercase tracking-[0.2em] text-slate-500 w-1/4">Lag</th>
                <th className="px-6 py-3 text-left text-[10px] font-semibold uppercase tracking-[0.2em] text-slate-500 w-1/4">Status</th>
                <th className="px-6 py-3 text-left text-[10px] font-semibold uppercase tracking-[0.2em] text-slate-500 w-1/4">Messages</th>
              </tr>
            </thead>
            <tbody>
              {systemMetrics.filter(m => m.metric_name?.startsWith('stream_lag:')).length === 0 ? (
                <tr>
                  <td colSpan={4} className="px-6 py-12 text-center text-sm text-slate-400">
                    Waiting for stream data...
                  </td>
                </tr>
              ) : (
                systemMetrics.filter(m => m.metric_name?.startsWith('stream_lag:')).map((m, i) => {
                  const lag = Number(m.value || 0)
                  const getLagColor = (lag: number) => {
                    if (lag < 100) return {
                      text: 'text-emerald-400',
                      bg: 'bg-emerald-500',
                      label: 'Healthy'
                    }
                    if (lag < 1000) return {
                      text: 'text-amber-400', 
                      bg: 'bg-amber-500',
                      label: 'Slow'
                    }
                    return {
                      text: 'text-rose-400',
                      bg: 'bg-rose-500', 
                      label: 'Critical'
                    }
                  }
                  const lagStatus = getLagColor(lag)
                  
                  return (
                    <tr key={i} className="border-t border-slate-800/50 hover:bg-slate-800/20 transition-colors duration-150">
                      <td className="px-6 py-4 font-mono text-sm text-slate-200">{m.metric_name?.replace('stream_lag:', '')}</td>
                      <td className={cn("px-6 py-4 font-mono text-sm tabular-nums font-semibold", lagStatus.text)}>{lag}ms</td>
                      <td className="px-6 py-4">
                        <div className="flex items-center gap-2">
                          <span className={cn("w-2 h-2 rounded-full", lagStatus.bg)} />
                          <span className={cn("text-xs font-medium", lagStatus.text)}>{lagStatus.label}</span>
                        </div>
                      </td>
                      <td className="px-6 py-4 font-mono text-sm text-slate-400">{m.labels?.length || '—'}</td>
                    </tr>
                  )
                })
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* Dead Letter Queue */}
      <div className="glass-card overflow-hidden shadow-[0_8px_30px_rgb(0,0,0,0.12)] mb-6">
        <div className="px-6 py-4 border-b border-slate-700 flex items-center justify-between">
          <h3 className="text-[10px] font-semibold uppercase tracking-[0.2em] text-slate-500">Dead Letter Queue</h3>
          <span className={cn(
            "inline-flex px-2 py-1 text-xs font-medium rounded-full",
            dlqItems.length > 0 
              ? "bg-rose-500/10 text-rose-400 border border-rose-500/30" 
              : "bg-emerald-500/10 text-emerald-400 border border-emerald-500/30"
          )}>
            {dlqItems.length} events
          </span>
        </div>
        {dlqItems.length === 0 ? (
          <div className="flex items-center justify-center gap-3 px-6 py-12">
            <CheckCircle2 className="h-5 w-5 text-emerald-400" />
            <p className="text-sm text-emerald-400 font-medium">No failed events</p>
          </div>
        ) : (
          <div className="divide-y divide-slate-800/50">
            {dlqItems.map((item, i) => (
              <div key={i} className="flex items-center justify-between px-6 py-4 gap-4">
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium text-slate-200 mb-1">{item.stream}</p>
                  <p className="text-xs text-slate-400 truncate mb-1" title={item.error}>{item.error}</p>
                  <p className="text-xs text-slate-500">Retries: {item.retries}</p>
                </div>
                <div className="flex gap-2 flex-shrink-0">
                  <button
                    onClick={() => replayDlq(item.event_id)}
                    className="px-3 py-1.5 text-xs font-medium rounded-md bg-violet-500/10 text-violet-400 border border-violet-500/30 hover:bg-violet-500/20 transition-all duration-200"
                  >
                    <RotateCcw className="w-3 h-3 inline mr-1" />
                    Replay
                  </button>
                  <button 
                    onClick={() => clearDlq(item.event_id)}
                    className="px-3 py-1.5 text-xs font-medium rounded-md bg-rose-500/10 text-rose-400 border border-rose-500/30 hover:bg-rose-500/20 transition-all duration-200"
                  >
                    <Trash2 className="w-3 h-3 inline mr-1" />
                    Clear
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Audit Log */}
      <div className="glass-card overflow-hidden shadow-[0_8px_30px_rgb(0,0,0,0.12)]">
        <div className="px-6 py-4 border-b border-slate-700">
          <h3 className="text-[10px] font-semibold uppercase tracking-[0.2em] text-slate-500">Audit Log</h3>
        </div>
        <div className="divide-y divide-slate-800/50">
          <div className="px-6 py-12 text-center">
            <p className="text-sm text-slate-400">Audit events will appear here</p>
          </div>
        </div>
      </div>
    </div>
  )
}
