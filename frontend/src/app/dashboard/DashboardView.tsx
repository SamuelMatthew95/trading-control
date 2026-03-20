'use client'

import { useEffect, useMemo, useState } from 'react'
import { useWebSocket } from '@/hooks/useWebSocket'
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
  Trash2
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

const API_BASE = (process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000/api').replace(/\/$/, '')

export function DashboardView({ section }: { section: 'overview' | 'trading' | 'agents' | 'learning' | 'system' }) {
  useWebSocket()
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
    wsConnected, 
    setKillSwitch 
  } = useCodexStore()
  const [dlqItems, setDlqItems] = useState<any[]>([])

  useEffect(() => {
    if (section !== 'system') return
    fetch(`${API_BASE}/v1/events/dlq`).then((r) => r.json()).then((p) => setDlqItems(p.items || [])).catch(() => setDlqItems([]))
  }, [section])

  // Calculate stats
  const dailyPnl = useMemo(() => {
    return Object.values(positions).reduce((sum, pos) => {
      const currentPrice = prices[pos.symbol]?.price || pos.entry_price
      const pnl = (currentPrice - pos.entry_price) * pos.qty
      return sum + pnl
    }, 0)
  }, [positions, prices])

  const winRate = useMemo(() => {
    const recentOrders = orders.slice(0, 100)
    if (recentOrders.length === 0) return 0
    const wins = recentOrders.filter(o => (o.pnl || 0) > 0).length
    return (wins / recentOrders.length) * 100
  }, [orders])

  const openPositionsCount = Object.keys(positions).length

  const llmCostToday = useMemo(() => {
    const costMetric = systemMetrics.find(m => m.metric_name === 'llm_cost_usd')
    return parseFloat(costMetric?.value || '0')
  }, [systemMetrics])

  const replayDlq = async (eventId: string) => {
    const r = await fetch(`${API_BASE}/v1/events/dlq/${eventId}/replay`, { method: 'POST' })
    if (r.ok) setDlqItems((items) => items.filter((i) => i.event_id !== eventId))
  }

  const clearDlq = async (eventId: string) => {
    const r = await fetch(`${API_BASE}/v1/events/dlq/${eventId}/clear`, { method: 'POST' })
    if (r.ok) setDlqItems((items) => items.filter((i) => i.event_id !== eventId))
  }

  const getLagColor = (lag: number) => {
    if (lag < 100) return 'text-green-400'
    if (lag < 1000) return 'text-amber-400'
    return 'text-red-400'
  }

  const getLagDot = (lag: number) => {
    if (lag < 100) return 'bg-green-400'
    if (lag < 1000) return 'bg-amber-400'
    return 'bg-red-400'
  }

  if (section === 'overview') {
    return (
      <div className="space-y-6">
        {/* Row 1 - Stat Cards */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <Card className="rounded-xl border bg-white dark:bg-slate-800 p-5 shadow-sm">
            <div className="flex items-start justify-between">
              <div className="space-y-1">
                <p className="text-xs text-slate-500 dark:text-slate-400">Total P&L</p>
                <p className={`text-2xl font-bold font-mono ${dailyPnl >= 0 ? 'text-green-600 dark:text-green-400' : 'text-red-600 dark:text-red-400'}`}>
                  ${dailyPnl.toFixed(2)}
                </p>
              </div>
              <TrendingUp className="w-4 h-4 text-slate-400" />
            </div>
          </Card>

          <Card className="rounded-xl border bg-white dark:bg-slate-800 p-5 shadow-sm">
            <div className="flex items-start justify-between">
              <div className="space-y-1">
                <p className="text-xs text-slate-500 dark:text-slate-400">Win Rate</p>
                <p className="text-2xl font-bold font-mono text-slate-900 dark:text-slate-100">
                  {winRate.toFixed(1)}%
                </p>
              </div>
              <BarChart3 className="w-4 h-4 text-slate-400" />
            </div>
          </Card>

          <Card className="rounded-xl border bg-white dark:bg-slate-800 p-5 shadow-sm">
            <div className="flex items-start justify-between">
              <div className="space-y-1">
                <p className="text-xs text-slate-500 dark:text-slate-400">Open Positions</p>
                <p className="text-2xl font-bold font-mono text-slate-900 dark:text-slate-100">
                  {openPositionsCount}
                </p>
              </div>
              <Layers className="w-4 h-4 text-slate-400" />
            </div>
          </Card>

          <Card className="rounded-xl border bg-white dark:bg-slate-800 p-5 shadow-sm">
            <div className="flex items-start justify-between">
              <div className="space-y-1">
                <p className="text-xs text-slate-500 dark:text-slate-400">LLM Cost Today</p>
                <p className="text-2xl font-bold font-mono text-slate-900 dark:text-slate-100">
                  ${llmCostToday.toFixed(2)}
                </p>
              </div>
              <Zap className="w-4 h-4 text-slate-400" />
            </div>
          </Card>
        </div>

        {/* Row 2 - Price Grid */}
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-4">
          {Object.entries(prices).map(([symbol, data]) => {
            const change = data.change || 0
            const isPositive = change >= 0
            return (
              <Card key={symbol} className="rounded-xl border bg-white dark:bg-slate-800 p-4">
                <div className="space-y-2">
                  <div className="font-bold text-sm text-slate-900 dark:text-slate-100">{symbol}</div>
                  <div className="text-xl font-mono text-center text-slate-900 dark:text-slate-100">
                    ${data.price?.toFixed(2) || '0.00'}
                  </div>
                  <div className="flex justify-end">
                    <Badge 
                      variant="outline" 
                      className={`rounded-full px-2 py-0.5 text-xs ${
                        isPositive 
                          ? 'bg-green-500/15 text-green-400 border-green-500/20' 
                          : 'bg-red-500/15 text-red-400 border-red-500/20'
                      }`}
                    >
                      {isPositive ? '+' : ''}{change.toFixed(2)}%
                    </Badge>
                  </div>
                </div>
              </Card>
            )
          })}
        </div>

        {/* Row 3 - Risk Alerts & Agent Status */}
        <div className="grid lg:grid-cols-[3fr,2fr] gap-4">
          {/* Risk Alerts */}
          <Card className="rounded-xl border bg-white dark:bg-slate-800 p-4">
            <h3 className="font-medium text-slate-900 dark:text-slate-100 mb-3">Risk Alerts</h3>
            {riskAlerts.length === 0 ? (
              <div className="flex items-center gap-2 text-green-600 dark:text-green-400 py-4">
                <CheckCircle2 className="w-5 h-5" />
                <span>No active alerts</span>
              </div>
            ) : (
              <div className="space-y-3">
                {riskAlerts.slice(0, 5).map((alert, idx) => (
                  <div key={idx} className="rounded-lg bg-amber-500/10 border border-amber-500/20 p-3 flex items-start gap-3">
                    <AlertTriangle className="w-4 h-4 text-amber-400 mt-0.5" />
                    <div className="flex-1 min-w-0">
                      <p className="text-sm text-slate-900 dark:text-slate-100">{alert.message}</p>
                      <p className="text-xs text-slate-500 dark:text-slate-400 mt-1">{alert.timestamp}</p>
                    </div>
                    <Button variant="ghost" size="sm" className="w-6 h-6 p-0">
                      <X className="w-3 h-3" />
                    </Button>
                  </div>
                ))}
              </div>
            )}
          </Card>

          {/* Agent Status */}
          <Card className="rounded-xl border bg-white dark:bg-slate-800 p-4">
            <h3 className="font-medium text-slate-900 dark:text-slate-100 mb-3">Agent Status</h3>
            <div className="space-y-2">
              {['Reasoning Agent', 'Trade Evaluator', 'Reflection Service'].map((agentName, idx) => {
                const isRunning = Math.random() > 0.3 // Mock status
                return (
                  <div key={idx} className="flex items-center justify-between py-2 border-b border-slate-200 dark:border-slate-700 last:border-0">
                    <div className="flex items-center gap-3">
                      <div className={`w-2 h-2 rounded-full ${isRunning ? 'bg-green-400 animate-pulse' : 'bg-slate-500'}`} />
                      <span className="text-sm font-medium text-slate-900 dark:text-slate-100">{agentName}</span>
                    </div>
                    <span className="text-xs text-slate-500 dark:text-slate-400">
                      {isRunning ? 'Running' : 'Idle'}
                    </span>
                  </div>
                )
              })}
            </div>
          </Card>
        </div>

        {/* Row 4 - Stream Health */}
        <Card className="rounded-xl border bg-white dark:bg-slate-800 p-4">
          <h3 className="font-medium text-slate-900 dark:text-slate-100 mb-3">Stream Health</h3>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Stream</TableHead>
                <TableHead>Lag</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Messages</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {['market_ticks', 'signals', 'orders', 'executions'].map((stream) => {
                const lag = Math.random() * 2000 // Mock lag
                return (
                  <TableRow key={stream}>
                    <TableCell className="font-mono text-sm">{stream}</TableCell>
                    <TableCell className={`font-mono text-sm ${getLagColor(lag)}`}>
                      {lag.toFixed(0)}ms
                    </TableCell>
                    <TableCell>
                      <div className={`w-2 h-2 rounded-full ${getLagDot(lag)}`} />
                    </TableCell>
                    <TableCell className="font-mono text-sm">{Math.floor(Math.random() * 10000)}</TableCell>
                  </TableRow>
                )
              })}
            </TableBody>
          </Table>
        </Card>

        {/* Row 5 - Last Reasoning */}
        <Card className="rounded-xl border bg-white dark:bg-slate-800 p-4">
          <h3 className="font-medium text-slate-900 dark:text-slate-100 mb-3">Last Reasoning Summary</h3>
          {agentLogs.length === 0 ? (
            <div className="flex items-center gap-2 text-slate-500 dark:text-slate-400 py-8">
              <Bot className="w-5 h-5" />
              <span>Waiting for first agent decision...</span>
            </div>
          ) : (
            <div className="space-y-3">
              <div className="flex items-center gap-3">
                <span className="font-bold">BTC/USD</span>
                <Badge variant="outline" className="bg-blue-500/15 text-blue-400 border-blue-500/20">
                  BUY
                </Badge>
                <Badge variant="outline" className="bg-slate-500/15 text-slate-400 border-slate-500/20">
                  87% confidence
                </Badge>
              </div>
              <p className="text-sm italic text-slate-300 dark:text-slate-600">
                Strong momentum detected with increasing volume and positive RSI divergence
              </p>
              <div className="flex items-center gap-2 text-xs">
                <Badge variant="outline" className="rounded-full bg-slate-700 px-2 py-0.5 text-xs">momentum</Badge>
                <Badge variant="outline" className="rounded-full bg-slate-700 px-2 py-0.5 text-xs">volume</Badge>
                <Badge variant="outline" className="rounded-full bg-amber-500/15 text-amber-400 border-amber-500/20 px-2 py-0.5">
                  245ms latency
                </Badge>
                <Badge variant="outline" className="rounded-full bg-blue-500/15 text-blue-400 border-blue-500/20 px-2 py-0.5">
                  $0.12 cost
                </Badge>
              </div>
            </div>
          )}
        </Card>
      </div>
    )
  }

  if (section === 'system') {
    return (
      <div className="space-y-6">
        {/* Stream Health */}
        <Card className="rounded-xl border bg-white dark:bg-slate-800 p-4">
          <h3 className="font-medium text-slate-900 dark:text-slate-100 mb-3">Stream Health</h3>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Stream</TableHead>
                <TableHead>Lag</TableHead>
                <TableHead>Length</TableHead>
                <TableHead>Groups</TableHead>
                <TableHead>Status</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {['market_ticks', 'signals', 'orders', 'executions', 'risk_alerts', 'learning_events'].map((stream) => {
                const lag = Math.random() * 2000
                const length = Math.floor(Math.random() * 10000)
                const groups = Math.floor(Math.random() * 5)
                return (
                  <TableRow key={stream}>
                    <TableCell className="font-mono text-sm">{stream}</TableCell>
                    <TableCell className={`font-mono text-sm ${getLagColor(lag)}`}>
                      {lag.toFixed(0)}ms
                    </TableCell>
                    <TableCell className="font-mono text-sm">{length}</TableCell>
                    <TableCell className="font-mono text-sm">{groups}</TableCell>
                    <TableCell>
                      <div className={`w-2 h-2 rounded-full ${getLagDot(lag)}`} />
                    </TableCell>
                  </TableRow>
                )
              })}
            </TableBody>
          </Table>
        </Card>

        {/* DLQ Inspector */}
        <Card className="rounded-xl border bg-white dark:bg-slate-800 p-4">
          <div className="flex items-center justify-between mb-3">
            <h3 className="font-medium text-slate-900 dark:text-slate-100">Dead Letter Queue</h3>
            <Badge variant={dlqItems.length > 0 ? "destructive" : "outline"}>
              {dlqItems.length} items
            </Badge>
          </div>
          
          {dlqItems.length === 0 ? (
            <div className="flex items-center gap-2 text-green-600 dark:text-green-400 py-8">
              <CheckCircle2 className="w-5 h-5" />
              <span>No failed events</span>
            </div>
          ) : (
            <div className="space-y-2">
              {dlqItems.map((item) => (
                <div key={item.event_id} className="rounded-lg bg-slate-800/50 dark:bg-slate-700/50 p-3">
                  <div className="flex items-start justify-between">
                    <div className="flex-1 min-w-0">
                      <div className="font-medium text-sm text-slate-900 dark:text-slate-100">
                        {item.stream}
                      </div>
                      <div className="text-sm text-slate-400 truncate mt-1">{item.error}</div>
                      <div className="text-xs text-slate-500 mt-1">{item.timestamp}</div>
                      <Badge variant="outline" className="mt-2">
                        {item.retries} retries
                      </Badge>
                    </div>
                    <div className="flex items-center gap-2">
                      <AlertDialog>
                        <AlertDialogTrigger asChild>
                          <Button variant="outline" size="sm" className="border-blue-500 text-blue-400 px-3 py-1 text-xs">
                            <RotateCcw className="w-3 h-3 mr-1" />
                            Replay
                          </Button>
                        </AlertDialogTrigger>
                        <AlertDialogContent>
                          <AlertDialogHeader>
                            <AlertDialogTitle>Replay Event</AlertDialogTitle>
                            <AlertDialogDescription>
                              This will replay the failed event back to the {item.stream} stream. Continue?
                            </AlertDialogDescription>
                          </AlertDialogHeader>
                          <AlertDialogFooter>
                            <AlertDialogCancel>Cancel</AlertDialogCancel>
                            <AlertDialogAction onClick={() => replayDlq(item.event_id)}>
                              Replay
                            </AlertDialogAction>
                          </AlertDialogFooter>
                        </AlertDialogContent>
                      </AlertDialog>
                      
                      <AlertDialog>
                        <AlertDialogTrigger asChild>
                          <Button variant="outline" size="sm" className="border-red-500/50 text-red-400 px-3 py-1 text-xs">
                            <Trash2 className="w-3 h-3 mr-1" />
                            Clear
                          </Button>
                        </AlertDialogTrigger>
                        <AlertDialogContent>
                          <AlertDialogHeader>
                            <AlertDialogTitle>Clear Event</AlertDialogTitle>
                            <AlertDialogDescription>
                              This will permanently remove the failed event from the DLQ. This action cannot be undone.
                            </AlertDialogDescription>
                          </AlertDialogHeader>
                          <AlertDialogFooter>
                            <AlertDialogCancel>Cancel</AlertDialogCancel>
                            <AlertDialogAction onClick={() => clearDlq(item.event_id)} className="bg-red-600">
                              Clear
                            </AlertDialogAction>
                          </AlertDialogFooter>
                        </AlertDialogContent>
                      </AlertDialog>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </Card>

        {/* Audit Log */}
        <Card className="rounded-xl border bg-white dark:bg-slate-800 p-4">
          <h3 className="font-medium text-slate-900 dark:text-slate-100 mb-3">Audit Log</h3>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Timestamp</TableHead>
                <TableHead>Event Type</TableHead>
                <TableHead>Payload</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {Array.from({ length: 10 }, (_, i) => (
                <TableRow key={i}>
                  <TableCell className="font-mono text-xs">2024-01-20 14:30:{(50 - i).toString().padStart(2, '0')}</TableCell>
                  <TableCell>
                    <Badge variant="outline" className="text-xs">
                      {['order_placed', 'signal_received', 'position_updated'][i % 3]}
                    </Badge>
                  </TableCell>
                  <TableCell className="font-mono text-xs max-w-xs truncate">
                    {JSON.stringify({ symbol: 'BTC/USD', side: 'buy', qty: 0.1 }).slice(0, 60)}...
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </Card>
      </div>
    )
  }

  // Fallback for other sections
  return (
    <div className="space-y-6">
      <Card className="rounded-xl border bg-white dark:bg-slate-800 p-8">
        <div className="text-center">
          <Bot className="w-12 h-12 mx-auto text-slate-400 mb-4" />
          <h3 className="text-lg font-medium text-slate-900 dark:text-slate-100 mb-2">
            {section.charAt(0).toUpperCase() + section.slice(1)} Dashboard
          </h3>
          <p className="text-slate-500 dark:text-slate-400">
            This section is coming soon in the next update.
          </p>
        </div>
      </Card>
    </div>
  )
}
