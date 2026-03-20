'use client'

import { useEffect, useMemo, useState } from 'react'
import { useCodexStore } from '@/stores/useCodexStore'
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
  Settings2
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

  // OVERVIEW PAGE
  if (section === 'overview') {
    const statCards = [
      { label: 'Total P&L', Icon: TrendingUp, value: `${dailyPnl >= 0 ? '+' : ''}$${dailyPnl.toFixed(2)}`, color: dailyPnl >= 0 ? 'text-emerald-500 dark:text-emerald-400' : 'text-red-500 dark:text-red-400' },
      { label: 'Win Rate', Icon: BarChart3, value: '0.0%', color: 'text-foreground' },
      { label: 'Open Positions', Icon: Layers, value: orders.length.toString(), color: 'text-foreground' },
      { label: 'LLM Cost Today', Icon: Zap, value: `$${costToday.toFixed(2)}`, color: 'text-foreground' },
    ]

    return (
      <div className="space-y-6">
        {/* Stat cards row */}
        <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
          {statCards.map((card, i) => (
            <div key={i} className="rounded-xl border border-border bg-surface p-5">
              <div className="flex items-center justify-between mb-3">
                <p className="text-xs font-medium uppercase tracking-widest text-muted-foreground">
                  {card.label}
                </p>
                <card.Icon className="h-3.5 w-3.5 text-muted-foreground" />
              </div>
              <p className={cn("text-2xl font-semibold font-mono tabular-nums text-foreground", card.color)}>
                {card.value}
              </p>
            </div>
          ))}
        </div>

        {/* Price grid */}
        <div>
          <h2 className="text-xs font-medium uppercase tracking-widest text-muted-foreground mb-4">Live Prices</h2>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
            {Object.entries(prices).length === 0 ? (
              <div className="flex items-center justify-center rounded-lg border border-dashed border-border py-10">
                <p className="text-sm text-muted-foreground">
                  Waiting for market data...
                </p>
              </div>
            ) : (
              Object.entries(prices).map(([symbol, record]) => (
                <div key={symbol} className="rounded-lg border border-border bg-muted/30 p-3 hover:bg-muted/50 transition-colors">
                  <p className="text-[10px] font-medium uppercase tracking-wide text-muted-foreground">{symbol}</p>
                  <p className="mt-1.5 text-base font-semibold font-mono tabular-nums">
                    ${record.price.toFixed(2)}
                  </p>
                  <span className={cn(
                    "mt-1 inline-flex items-center text-[11px] font-medium",
                    record.change >= 0 ? "text-emerald-500" : "text-red-500"
                  )}>
                    {record.change >= 0 ? "▲" : "▼"} {Math.abs(record.change).toFixed(2)}%
                  </span>
                </div>
              ))
            )}
          </div>
        </div>

        {/* Two-col row: Risk Alerts + Agent Status */}
        <div className="grid gap-6 lg:grid-cols-2">
          {/* Risk Alerts */}
          <div className="rounded-xl border border-border bg-surface p-5">
            <h2 className="text-xs font-medium uppercase tracking-widest text-muted-foreground mb-4">Risk Alerts</h2>
            {riskAlerts.length === 0 ? (
              <div className="flex items-center gap-2 py-2">
                <CheckCircle2 className="h-4 w-4 text-emerald-500 flex-shrink-0" />
                <span className="text-sm text-muted-foreground">No active alerts</span>
              </div>
            ) : (
              riskAlerts.slice(0, 5).map((alert, i) => (
                <div key={i} className="flex items-start gap-3 rounded-lg bg-amber-500/5 border border-amber-500/20 p-3 mb-2">
                  <AlertTriangle className="h-4 w-4 text-amber-500 mt-0.5 flex-shrink-0" />
                  <div className="flex-1 min-w-0">
                    <p className="text-sm text-foreground">{alert.message || alert.type}</p>
                    <p className="text-xs text-muted-foreground mt-0.5">{alert.timestamp || ''}</p>
                  </div>
                </div>
              ))
            )}
          </div>

          {/* Agent Status */}
          <div className="rounded-xl border border-border bg-surface p-5">
            <h2 className="text-xs font-medium uppercase tracking-widest text-muted-foreground mb-4">Agent Status</h2>
            <div className="space-y-px">
              {[
                { name: 'Reasoning Agent', status: 'Running' },
                { name: 'Execution Engine', status: 'Running' },
                { name: 'Learning Service', status: 'Idle' },
                { name: 'IC Updater', status: 'Idle' },
              ].map((agent, i) => (
                <div key={i} className="flex items-center justify-between py-2.5 border-b border-border last:border-0">
                  <span className="text-sm text-foreground">{agent.name}</span>
                  <div className="flex items-center gap-2">
                    <span className={cn(
                      "h-1.5 w-1.5 rounded-full flex-shrink-0",
                      agent.status === 'Running' ? "bg-emerald-500" : "bg-muted-foreground"
                    )} />
                    <span className="text-xs text-muted-foreground w-14 text-right">
                      {agent.status}
                    </span>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* Stream Health table */}
        <div className="rounded-xl border border-border bg-surface overflow-hidden">
          <div className="px-4 py-3 border-b border-border">
            <h2 className="text-xs font-medium uppercase tracking-widest text-muted-foreground">Stream Health</h2>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-muted/40">
                  <th className="px-4 py-2.5 text-left text-[10px] font-semibold uppercase tracking-widest text-muted-foreground">Stream</th>
                  <th className="px-4 py-2.5 text-left text-[10px] font-semibold uppercase tracking-widest text-muted-foreground">Lag</th>
                  <th className="px-4 py-2.5 text-left text-[10px] font-semibold uppercase tracking-widest text-muted-foreground">Status</th>
                  <th className="px-4 py-2.5 text-left text-[10px] font-semibold uppercase tracking-widest text-muted-foreground">Messages</th>
                </tr>
              </thead>
              <tbody>
                {systemMetrics.filter(m => m.metric_name?.startsWith('stream_lag:')).length === 0 ? (
                  <tr>
                    <td colSpan={4} className="px-4 py-8 text-center text-sm text-muted-foreground">
                      Waiting for stream data...
                    </td>
                  </tr>
                ) : (
                  systemMetrics.filter(m => m.metric_name?.startsWith('stream_lag:')).map((m, i) => {
                    const lag = Number(m.value || 0)
                    const lagColor = lag < 100 ? 'text-emerald-500 dark:text-emerald-400' : lag < 1000 ? 'text-amber-500 dark:text-amber-400' : 'text-red-500 dark:text-red-400'
                    return (
                      <tr key={i} className="hover:bg-muted/20 transition-colors divide-y divide-border">
                        <td className="px-4 py-3 font-mono text-xs">{m.metric_name?.replace('stream_lag:', '')}</td>
                        <td className={cn("px-4 py-3 font-mono text-xs tabular-nums", lagColor)}>{lag}ms</td>
                        <td className="px-4 py-3">
                          <span className={cn("h-1.5 w-1.5 rounded-full inline-block", lagColor.replace('text-', 'bg-'))} />
                        </td>
                        <td className="px-4 py-3 font-mono text-xs text-muted-foreground">{m.labels?.length || '—'}</td>
                      </tr>
                    )
                  })
                )}
              </tbody>
            </table>
          </div>
        </div>

        {/* Last reasoning summary */}
        {agentLogs[0] && (
          <div className="rounded-xl border border-border bg-surface p-5">
            <h2 className="text-xs font-medium uppercase tracking-widest text-muted-foreground mb-4">Last Reasoning Summary</h2>
            <div className="flex items-start gap-3">
              <span className={cn(
                "rounded-md px-2 py-1 text-xs font-semibold uppercase flex-shrink-0",
                agentLogs[0].action === 'buy' ? "bg-blue-500/10 text-blue-500" :
                agentLogs[0].action === 'sell' ? "bg-red-500/10 text-red-500" :
                "bg-muted text-muted-foreground"
              )}>
                {agentLogs[0].action || 'HOLD'}
              </span>
              <div className="flex-1 min-w-0">
                <p className="text-sm italic text-muted-foreground">
                  {agentLogs[0].primary_edge || 'No edge description'}
                </p>
                <div className="mt-2 flex flex-wrap gap-1.5">
                  {(agentLogs[0].risk_factors || []).map((rf, i) => (
                    <span key={i} className="rounded-full bg-muted px-2 py-0.5 text-xs text-muted-foreground">
                      {rf}
                    </span>
                  ))}
                </div>
                <div className="mt-2 flex items-center gap-3 text-xs text-muted-foreground">
                  <span>Confidence: {((agentLogs[0].confidence || 0) * 100).toFixed(0)}%</span>
                  <span>Latency: {agentLogs[0].latency_ms || 0}ms</span>
                  <span>Cost: ${agentLogs[0].cost_usd || '0.000'}</span>
                  {agentLogs[0].fallback && (
                    <span className="rounded-full bg-amber-500/10 px-2 py-0.5 text-amber-500">Fallback</span>
                  )}
                </div>
              </div>
            </div>
          </div>
        )}
      </div>
    )
  }

  // TRADING PAGE
  if (section === 'trading') {
    return (
      <div className="grid gap-6 lg:grid-cols-[1fr_360px]">
        {/* Left: Chart + Positions */}
        <div className="space-y-6">
          {/* Symbol + Timeframe */}
          <div className="flex items-center justify-between">
            <div className="flex gap-1">
              {['BTC/USD','ETH/USD','SOL/USD','SPY','AAPL','NVDA'].map(s => (
                <button
                  key={s}
                  className={cn(
                    "rounded-md px-3 py-1.5 text-xs font-medium transition-colors",
                    selected === s
                      ? "bg-accent text-accent-foreground"
                      : "text-muted-foreground hover:bg-muted"
                  )}
                  onClick={() => setSelected(s)}
                >
                  {s}
                </button>
              ))}
            </div>
            <div className="flex gap-1">
              {['1m','5m','15m','1h','4h'].map(tf => (
                <button
                  key={tf}
                  className={cn(
                    "rounded-md px-2.5 py-1 text-xs transition-colors",
                    selectedTf === tf ? "bg-muted text-foreground" : "text-muted-foreground hover:bg-muted/50"
                  )}
                  onClick={() => setSelectedTf(tf)}
                >
                  {tf}
                </button>
              ))}
            </div>
          </div>

          {/* Chart placeholder */}
          <div className="rounded-xl border border-border bg-surface flex items-center justify-center min-h-64">
            <div className="text-center">
              <CandlestickChart className="h-8 w-8 text-muted-foreground mx-auto mb-2" />
              <p className="text-sm text-muted-foreground">Chart — lightweight-charts integration</p>
              <p className="text-xs text-muted-foreground mt-1">{selected} · {selectedTf}</p>
            </div>
          </div>

          {/* Positions table */}
          <div className="rounded-xl border border-border bg-surface overflow-hidden">
            <div className="px-4 py-3 border-b border-border">
              <h2 className="text-xs font-medium uppercase tracking-widest text-muted-foreground">Open Positions</h2>
            </div>
            {orders.length === 0 ? (
              <div className="px-4 py-8 text-center text-sm text-muted-foreground">
                No open positions
              </div>
            ) : (
              <table className="w-full text-sm">
                <thead>
                  <tr className="bg-muted/40">
                    <th className="px-4 py-2.5 text-left text-[10px] font-semibold uppercase tracking-widest text-muted-foreground">Symbol</th>
                    <th className="px-4 py-2.5 text-left text-[10px] font-semibold uppercase tracking-widest text-muted-foreground">Side</th>
                    <th className="px-4 py-2.5 text-right text-[10px] font-semibold uppercase tracking-widest text-muted-foreground">Qty</th>
                    <th className="px-4 py-2.5 text-right text-[10px] font-semibold uppercase tracking-widest text-muted-foreground">P&L</th>
                  </tr>
                </thead>
                <tbody>
                  {orders.slice(0,10).map((o,i) => (
                    <tr key={i} className="hover:bg-muted/20 transition-colors divide-y divide-border">
                      <td className="px-4 py-3 font-medium">{o.symbol}</td>
                      <td className="px-4 py-3">
                        <span className={cn(
                          "rounded-full px-2 py-0.5 text-xs font-medium",
                          o.side === 'long' || o.side === 'buy'
                            ? "bg-blue-500/10 text-blue-500"
                            : "bg-red-500/10 text-red-500"
                        )}>
                          {(o.side || 'n/a').toUpperCase()}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-right font-mono text-xs">{o.qty || 0}</td>
                      <td className={cn(
                        "px-4 py-3 text-right font-mono text-xs tabular-nums",
                        Number(o.pnl) >= 0 ? "text-emerald-500 dark:text-emerald-400" : "text-red-500 dark:text-red-400"
                      )}>
                        {Number(o.pnl) >= 0 ? '+' : ''}{Number(o.pnl || 0).toFixed(2)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </div>

        {/* Right: Order Book + Entry Form */}
        <div className="space-y-6">
          {/* Order Book */}
          <div className="rounded-xl border border-border bg-surface p-5">
            <h3 className="text-xs font-medium uppercase tracking-widest text-muted-foreground mb-4">Order Book</h3>
            <div className="space-y-1">
              {[67510, 67505, 67500].map(p => (
                <div key={p} className="flex justify-between text-xs">
                  <span className="text-red-500 font-mono tabular-nums">{p.toLocaleString()}</span>
                  <span className="text-muted-foreground">0.42</span>
                </div>
              ))}
              <div className="my-2 border-y py-2 text-center font-mono text-base font-bold">
                {prices[selected]?.price.toLocaleString() || '—'}
              </div>
              {[67495, 67490, 67485].map(p => (
                <div key={p} className="flex justify-between text-xs">
                  <span className="text-emerald-500 font-mono tabular-nums">{p.toLocaleString()}</span>
                  <span className="text-muted-foreground">1.05</span>
                </div>
              ))}
            </div>
          </div>

          {/* Order Entry */}
          <div className="rounded-xl border border-border bg-surface p-5">
            <h3 className="text-xs font-medium uppercase tracking-widest text-muted-foreground mb-4">New Order</h3>
            <div className="space-y-3">
              <div>
                <label className="text-xs text-muted-foreground mb-1 block">Symbol</label>
                <div className="rounded-md border border-border bg-muted px-3 py-2 text-sm font-mono">{selected}</div>
              </div>
              <div>
                <label className="text-xs text-muted-foreground mb-1 block">Quantity</label>
                <input className="w-full rounded-md border border-border bg-transparent px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-accent/50" placeholder="0.00" />
              </div>
              <div>
                <label className="text-xs text-muted-foreground mb-1 block">Price</label>
                <input className="w-full rounded-md border border-border bg-transparent px-3 py-2 text-sm font-mono outline-none focus:ring-2 focus:ring-accent/50" placeholder="Market" />
              </div>
              <div className="grid grid-cols-2 gap-2 pt-1">
                <button className="rounded-md bg-blue-600 py-2 text-sm font-semibold text-white hover:bg-blue-500 transition-colors">LONG</button>
                <button className="rounded-md bg-red-600 py-2 text-sm font-semibold text-white hover:bg-red-500 transition-colors">SHORT</button>
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
      <div className="space-y-6">
        {/* Metrics strip */}
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          {[
            { label: 'Avg Latency', value: avgLatency + 'ms' },
            { label: 'Cost Today',  value: '$' + costToday.toFixed(2) },
            { label: 'Total Runs',  value: agentLogs.length },
            { label: 'Fallbacks',   value: agentLogs.filter(l => l.fallback).length },
          ].map((m, i) => (
            <div key={i} className="rounded-xl border border-border bg-surface p-5">
              <div className="flex items-center justify-between mb-3">
                <p className="text-xs font-medium uppercase tracking-widest text-muted-foreground">
                  {m.label}
                </p>
              </div>
              <p className="text-2xl font-semibold font-mono tabular-nums text-foreground">
                {m.value}
              </p>
            </div>
          ))}
        </div>

        {/* Log list */}
        <div className="space-y-px">
          {agentLogs.length === 0 ? (
            <div className="rounded-xl border border-dashed border-border p-12 text-center">
              <Bot className="h-8 w-8 text-muted-foreground mx-auto mb-2" />
              <p className="text-sm text-muted-foreground">No reasoning logs yet</p>
            </div>
          ) : (
            agentLogs.slice(0, 20).map((log, i) => (
              <div key={i} className={cn(
                "rounded-xl border border-border bg-surface p-5",
                "border-l-4",
                log.action === 'buy'  && "border-l-blue-500",
                log.action === 'sell' && "border-l-red-500",
                "border-l-border"
              )}>
                <div className="flex items-center justify-between gap-3 flex-wrap">
                  <div className="flex items-center gap-2">
                    <span className={cn(
                      "rounded px-2 py-0.5 text-xs font-semibold uppercase",
                      log.action === 'buy'  ? "bg-blue-500/10 text-blue-500" :
                      log.action === 'sell' ? "bg-red-500/10 text-red-500" :
                      "bg-muted text-muted-foreground"
                    )}>
                      {log.action || 'HOLD'}
                    </span>
                    <span className="text-sm font-medium">{log.symbol || '—'}</span>
                  </div>
                  <div className="flex items-center gap-3 text-xs text-muted-foreground">
                    <span>{log.latency_ms || 0}ms</span>
                    <span>${log.cost_usd || '0.000'}</span>
                    {log.fallback && <span className="rounded-full bg-amber-500/10 text-amber-500 px-2 py-0.5">Fallback</span>}
                  </div>
                </div>
                <div className="mt-1.5 w-full bg-muted rounded-full h-1">
                  <div className="bg-accent h-1 rounded-full" style={{ width: `${(log.confidence || 0) * 100}%` }} />
                </div>
                <p className="mt-2 text-sm italic text-muted-foreground">
                  {log.primary_edge || 'No edge description'}
                </p>
                {(log.risk_factors || []).length > 0 && (
                  <div className="mt-2 flex flex-wrap gap-1">
                    {log.risk_factors.map((rf, j) => (
                      <span key={j} className="rounded-full bg-muted px-2 py-0.5 text-xs text-muted-foreground">{rf}</span>
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
      <div className="space-y-6">
        {/* Stat cards */}
        <div className="grid grid-cols-3 gap-4">
          <div className="rounded-xl border border-border bg-surface p-5">
            <div className="flex items-center justify-between mb-3">
              <p className="text-xs font-medium uppercase tracking-widest text-muted-foreground">Trades Evaluated</p>
            </div>
            <p className="text-2xl font-semibold font-mono tabular-nums text-foreground">{learningEvents.length}</p>
          </div>
          <div className="rounded-xl border border-border bg-surface p-5">
            <div className="flex items-center justify-between mb-3">
              <p className="text-xs font-medium uppercase tracking-widest text-muted-foreground">Reflections</p>
            </div>
            <p className="text-2xl font-semibold font-mono tabular-nums text-foreground">
              {learningEvents.filter(e => e.event === 'reflection_completed').length}
            </p>
          </div>
          <div className="rounded-xl border border-border bg-surface p-5">
            <div className="flex items-center justify-between mb-3">
              <p className="text-xs font-medium uppercase tracking-widest text-muted-foreground">IC Updates</p>
            </div>
            <p className="text-2xl font-semibold font-mono tabular-nums text-foreground">0</p>
          </div>
        </div>

        {/* Trade timeline */}
        <div className="rounded-xl border border-border bg-surface overflow-hidden">
          <div className="px-4 py-3 border-b border-border">
            <h2 className="text-xs font-medium uppercase tracking-widest text-muted-foreground">Trade Timeline</h2>
          </div>
          {learningEvents.length === 0 ? (
            <div className="px-4 py-12 text-center">
              <TrendingUp className="h-8 w-8 text-muted-foreground mx-auto mb-2" />
              <p className="text-sm text-muted-foreground">Complete paper trades to see performance</p>
            </div>
          ) : (
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-muted/40">
                  <th className="px-4 py-2.5 text-left text-[10px] font-semibold uppercase tracking-widest text-muted-foreground">Symbol</th>
                  <th className="px-4 py-2.5 text-left text-[10px] font-semibold uppercase tracking-widest text-muted-foreground">Event</th>
                  <th className="px-4 py-2.5 text-right text-[10px] font-semibold uppercase tracking-widest text-muted-foreground">P&L</th>
                </tr>
              </thead>
              <tbody>
                {learningEvents.slice(0,20).map((e,i) => (
                  <tr key={i} className="hover:bg-muted/20 transition-colors divide-y divide-border">
                    <td className="px-4 py-3 font-medium">{e.symbol || '—'}</td>
                    <td className="px-4 py-3 text-xs text-muted-foreground">{e.event || e.type}</td>
                    <td className={cn(
                      "px-4 py-3 text-right font-mono text-xs tabular-nums",
                      Number(e.pnl) >= 0 ? "text-emerald-500 dark:text-emerald-400" : "text-red-500 dark:text-red-400"
                    )}>
                      {e.pnl != null ? `${Number(e.pnl) >= 0 ? '+' : ''}${Number(e.pnl).toFixed(2)}` : '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        {/* Reflection log */}
        <div className="rounded-xl border border-border bg-surface overflow-hidden">
          <div className="px-4 py-3 border-b border-border">
            <h2 className="text-xs font-medium uppercase tracking-widest text-muted-foreground">Reflection Log</h2>
          </div>
          {learningEvents.filter(e => e.event === 'reflection_completed').length === 0 ? (
            <div className="px-4 py-8 text-center text-sm text-muted-foreground">
              Reflections appear after every 20 trades
            </div>
          ) : (
            <div className="divide-y divide-border">
              {learningEvents.filter(e => e.event === 'reflection_completed').map((e,i) => (
                <div key={i} className="px-4 py-4">
                  <div className="flex items-center justify-between">
                    <p className="text-xs font-mono text-muted-foreground">{e.trace_id}</p>
                  </div>
                  <p className="mt-1 text-sm text-foreground">{e.summary || 'No summary'}</p>
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
    <div className="space-y-6">
      {/* Stream health full detail */}
      <div className="rounded-xl border border-border bg-surface overflow-hidden">
        <div className="px-4 py-3 border-b border-border">
          <h2 className="text-xs font-medium uppercase tracking-widest text-muted-foreground">Stream Health</h2>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-muted/40">
                <th className="px-4 py-2.5 text-left text-[10px] font-semibold uppercase tracking-widest text-muted-foreground">Stream</th>
                <th className="px-4 py-2.5 text-left text-[10px] font-semibold uppercase tracking-widest text-muted-foreground">Lag</th>
                <th className="px-4 py-2.5 text-left text-[10px] font-semibold uppercase tracking-widest text-muted-foreground">Status</th>
                <th className="px-4 py-2.5 text-left text-[10px] font-semibold uppercase tracking-widest text-muted-foreground">Messages</th>
              </tr>
            </thead>
            <tbody>
              {systemMetrics.filter(m => m.metric_name?.startsWith('stream_lag:')).length === 0 ? (
                <tr>
                  <td colSpan={4} className="px-4 py-8 text-center text-sm text-muted-foreground">
                    Waiting for stream data...
                  </td>
                </tr>
              ) : (
                systemMetrics.filter(m => m.metric_name?.startsWith('stream_lag:')).map((m, i) => {
                  const lag = Number(m.value || 0)
                  const lagColor = lag < 100 ? 'text-emerald-500 dark:text-emerald-400' : lag < 1000 ? 'text-amber-500 dark:text-amber-400' : 'text-red-500 dark:text-red-400'
                  return (
                    <tr key={i} className="hover:bg-muted/20 transition-colors divide-y divide-border">
                      <td className="px-4 py-3 font-mono text-xs">{m.metric_name?.replace('stream_lag:', '')}</td>
                      <td className={cn("px-4 py-3 font-mono text-xs tabular-nums", lagColor)}>{lag}ms</td>
                      <td className="px-4 py-3">
                        <span className={cn("h-1.5 w-1.5 rounded-full inline-block", lagColor.replace('text-', 'bg-'))} />
                      </td>
                      <td className="px-4 py-3 font-mono text-xs text-muted-foreground">{m.labels?.length || '—'}</td>
                    </tr>
                  )
                })
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* DLQ inspector */}
      <div className="rounded-xl border border-border bg-surface overflow-hidden">
        <div className="px-4 py-3 border-b border-border flex items-center justify-between">
          <h2 className="text-xs font-medium uppercase tracking-widest text-muted-foreground">Dead Letter Queue</h2>
          <span className={cn(
            "rounded-full px-2 py-0.5 text-xs font-medium",
            dlqItems.length > 0 ? "bg-red-500/10 text-red-500" : "bg-emerald-500/10 text-emerald-500"
          )}>
            {dlqItems.length} events
          </span>
        </div>
        {dlqItems.length === 0 ? (
          <div className="flex items-center gap-2 px-4 py-8 text-sm text-emerald-500">
            <CheckCircle2 className="h-4 w-4" />
            No failed events
          </div>
        ) : (
          <div className="divide-y divide-border">
            {dlqItems.map((item, i) => (
              <div key={i} className="flex items-center justify-between px-4 py-4 gap-4">
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium">{item.stream}</p>
                  <p className="text-xs text-muted-foreground truncate mt-0.5">{item.error}</p>
                  <p className="text-xs text-muted-foreground mt-0.5">Retries: {item.retries}</p>
                </div>
                <div className="flex gap-2 flex-shrink-0">
                  <button
                    onClick={() => replayDlq(item.event_id)}
                    className="rounded-md border border-accent/50 px-3 py-1.5 text-xs text-accent hover:bg-accent/5 transition-colors"
                  >
                    Replay
                  </button>
                  <button 
                    onClick={() => clearDlq(item.event_id)}
                    className="rounded-md border border-red-500/30 px-3 py-1.5 text-xs text-red-500 hover:bg-red-500/5 transition-colors"
                  >
                    Clear
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Audit log */}
      <div className="rounded-xl border border-border bg-surface overflow-hidden">
        <div className="px-4 py-3 border-b border-border">
          <h2 className="text-xs font-medium uppercase tracking-widest text-muted-foreground">Audit Log</h2>
        </div>
        <div className="divide-y divide-border">
          <div className="px-4 py-8 text-center text-sm text-muted-foreground">
            Audit events will appear here
          </div>
        </div>
      </div>
    </div>
  )
}
