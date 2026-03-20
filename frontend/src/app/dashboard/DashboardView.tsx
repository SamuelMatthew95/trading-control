'use client'
import Link from 'next/link'
import { useEffect, useMemo, useState } from 'react'
import { useWebSocket } from '@/hooks/useWebSocket'
import { useCodexStore } from '@/stores/useCodexStore'

const NAV_ITEMS = [
  { href: '/dashboard', label: 'Overview' },
  { href: '/dashboard/trading', label: 'Trading' },
  { href: '/dashboard/agents', label: 'Agents' },
  { href: '/dashboard/learning', label: 'Learning' },
  { href: '/dashboard/system', label: 'System' },
]

const API_BASE = (process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000/api').replace(/\/$/, '')

export function DashboardView({ section }: { section: 'overview' | 'trading' | 'agents' | 'learning' | 'system' }) {
  useWebSocket()
  const { agentLogs, killSwitchActive, learningEvents, orders, prices, regime, riskAlerts, signals, systemMetrics, wsConnected, setKillSwitch } = useCodexStore()
  const [dlqItems, setDlqItems] = useState<any[]>([])

  useEffect(() => {
    if (section !== 'system') return
    fetch(`${API_BASE}/v1/events/dlq`).then((r) => r.json()).then((p) => setDlqItems(p.items || [])).catch(() => setDlqItems([]))
  }, [section])

  const dailyPnl = useMemo(() => orders.reduce((t, o) => t + Number(o.pnl || 0), 0), [orders])

  const toggleKillSwitch = async () => {
    const next = !killSwitchActive
    if (!window.confirm(`${next ? 'Enable' : 'Disable'} kill switch?`)) return
    const r = await fetch(`${API_BASE}/v1/dashboard/kill_switch`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ active: next }) })
    if (r.ok) setKillSwitch(next)
  }

  const replayDlq = async (eventId: string) => {
    const r = await fetch(`${API_BASE}/v1/events/dlq/${eventId}/replay`, { method: 'POST' })
    if (r.ok) setDlqItems((items) => items.filter((i) => i.event_id !== eventId))
  }

  return (
    <div className="min-h-screen bg-[#0F172A] px-6 py-6 text-slate-100">
      <div className="mx-auto flex max-w-7xl flex-col gap-6">
        <header className="flex flex-col gap-4 rounded-2xl border border-slate-800 bg-slate-900/70 p-5 md:flex-row md:items-center md:justify-between">
          <div><p className="text-sm text-slate-400">AI Trading Bot Control</p><h1 className="text-2xl font-semibold">Mission Dashboard</h1></div>
          <div className="flex flex-wrap items-center gap-3">
            <span className="rounded-full border border-slate-700 px-3 py-1 text-sm">Regime: {regime}</span>
            <span className={`rounded-full px-3 py-1 text-sm ${wsConnected ? 'bg-emerald-500/20 text-emerald-300' : 'bg-rose-500/20 text-rose-300'}`}>WS {wsConnected ? 'Connected' : 'Disconnected'}</span>
            <span className="rounded-full border border-slate-700 px-3 py-1 text-sm">Daily P&L: ${dailyPnl.toFixed(2)}</span>
            <button onClick={toggleKillSwitch} className={`rounded-full px-4 py-2 text-sm font-medium transition ${killSwitchActive ? 'animate-pulse bg-red-600 text-white' : 'bg-slate-800 text-slate-100 hover:bg-slate-700'}`}>{killSwitchActive ? 'Kill Switch Active' : 'Enable Kill Switch'}</button>
          </div>
        </header>
        <nav className="flex flex-wrap gap-2 rounded-2xl border border-slate-800 bg-slate-900/60 p-3">
          {NAV_ITEMS.map((item) => (<Link key={item.href} href={item.href} className="rounded-xl px-4 py-2 text-sm text-slate-300 transition hover:bg-slate-800 hover:text-white">{item.label}</Link>))}
        </nav>
        {section === 'overview' && (
          <div className="grid gap-6 lg:grid-cols-[2fr,1fr]">
            <section className="rounded-2xl border border-slate-800 bg-slate-900/60 p-5">
              <h2 className="mb-4 text-lg font-semibold">Price Grid</h2>
              <div className="grid gap-3 md:grid-cols-3">
                {Object.entries(prices).length === 0 && <p className="text-sm text-slate-400">Waiting for market ticks...</p>}
                {Object.entries(prices).map(([symbol, record]) => (<div key={symbol} className="rounded-xl border border-slate-800 bg-slate-950/50 p-4"><div className="text-sm text-slate-400">{symbol}</div><div className="mt-2 text-xl font-semibold">${record.price.toFixed(2)}</div><div className={`text-sm ${record.change >= 0 ? 'text-emerald-300' : 'text-rose-300'}`}>{record.change.toFixed(2)}%</div></div>))}
              </div>
            </section>
            <section className="space-y-6">
              <div className="rounded-2xl border border-slate-800 bg-slate-900/60 p-5"><h2 className="mb-3 text-lg font-semibold">Risk Alerts</h2><div className="space-y-3">{riskAlerts.length === 0 ? <p className="text-sm text-slate-400">No active alerts.</p> : riskAlerts.slice(0, 5).map((a, i) => <div key={i} className="rounded-xl bg-amber-500/10 p-3 text-sm text-amber-200">{a.message || a.type || 'risk_alert'}</div>)}</div></div>
              <div className="rounded-2xl border border-slate-800 bg-slate-900/60 p-5"><h2 className="mb-3 text-lg font-semibold">Last Reasoning Summary</h2>{agentLogs[0] ? <pre className="overflow-auto text-xs text-slate-300">{JSON.stringify(agentLogs[0], null, 2)}</pre> : <p className="text-sm text-slate-400">No agent logs yet.</p>}</div>
            </section>
          </div>
        )}
        {section === 'trading' && (
          <div className="grid gap-6 lg:grid-cols-2">
            <section className="rounded-2xl border border-slate-800 bg-slate-900/60 p-5"><h2 className="mb-4 text-lg font-semibold">Candlestick Chart</h2><div className="h-72 rounded-xl border border-dashed border-slate-700 bg-slate-950/40 p-4 text-sm text-slate-400">Chart placeholder for lightweight-charts integration.</div></section>
            <section className="rounded-2xl border border-slate-800 bg-slate-900/60 p-5"><h2 className="mb-4 text-lg font-semibold">Open Positions</h2><div className="space-y-3 text-sm text-slate-300">{orders.slice(0, 10).map((o, i) => (<div key={i} className="flex items-center justify-between rounded-xl bg-slate-950/40 p-3"><span>{o.symbol || 'Unknown'}</span><span>{o.side || o.type || 'n/a'}</span><span>{o.qty || 0}</span></div>))}{orders.length === 0 && <p className="text-slate-400">No positions or orders yet.</p>}</div></section>
          </div>
        )}
        {section === 'agents' && (
          <div className="grid gap-6 lg:grid-cols-[280px,1fr]">
            <aside className="rounded-2xl border border-slate-800 bg-slate-900/60 p-5"><h2 className="mb-4 text-lg font-semibold">Agent Status</h2><div className="space-y-3 text-sm text-slate-300">{['ReasoningAgent', 'ExecutionEngine', 'LearningAgent'].map((n) => (<div key={n} className="rounded-xl bg-slate-950/40 p-3">{n}: online</div>))}</div></aside>
            <section className="rounded-2xl border border-slate-800 bg-slate-900/60 p-5"><h2 className="mb-4 text-lg font-semibold">Reasoning Log</h2><div className="space-y-3">{agentLogs.length === 0 && <p className="text-sm text-slate-400">Waiting for agent logs...</p>}{agentLogs.slice(0, 12).map((log, i) => (<div key={i} className="rounded-xl border border-slate-800 bg-slate-950/40 p-4 text-sm"><div className="font-medium">{log.action || 'unknown action'}</div><div className="mt-2 text-slate-400">confidence: {log.confidence ?? 'n/a'} · cost: ${log.cost_usd ?? 0}</div><div className="mt-2 text-slate-300">{log.primary_edge || 'No primary edge supplied.'}</div></div>))}</div></section>
          </div>
        )}
        {section === 'learning' && (
          <div className="grid gap-6 lg:grid-cols-2">
            <section className="rounded-2xl border border-slate-800 bg-slate-900/60 p-5"><h2 className="mb-4 text-lg font-semibold">Trade Timeline</h2><div className="space-y-3 text-sm text-slate-300">{signals.slice(0, 10).map((s, i) => <div key={i} className="rounded-xl bg-slate-950/40 p-3">{s.symbol || 'signal'} · {s.signal_type || s.type || 'unknown'}</div>)}{signals.length === 0 && <p className="text-slate-400">No learning timeline data yet.</p>}</div></section>
            <section className="rounded-2xl border border-slate-800 bg-slate-900/60 p-5"><h2 className="mb-4 text-lg font-semibold">Reflection Log</h2><div className="space-y-3 text-sm text-slate-300">{learningEvents.slice(0, 10).map((e, i) => <div key={i} className="rounded-xl bg-slate-950/40 p-3">{e.summary || e.type || 'learning_event'}</div>)}{learningEvents.length === 0 && <p className="text-slate-400">No reflections yet.</p>}</div></section>
          </div>
        )}
        {section === 'system' && (
          <div className="grid gap-6 lg:grid-cols-2">
            <section className="rounded-2xl border border-slate-800 bg-slate-900/60 p-5"><h2 className="mb-4 text-lg font-semibold">Stream Metrics</h2><div className="space-y-3 text-sm text-slate-300">{systemMetrics.length === 0 && <p className="text-slate-400">No stream metrics yet.</p>}{systemMetrics.slice(0, 10).map((m, i) => (<div key={i} className="flex items-center justify-between rounded-xl bg-slate-950/40 p-3"><span>{m.metric_name || m.type || 'metric'}</span><span>{m.value ?? m.lag ?? 'n/a'}</span></div>))}</div></section>
            <section className="rounded-2xl border border-slate-800 bg-slate-900/60 p-5"><h2 className="mb-4 text-lg font-semibold">DLQ Inspector</h2><div className="space-y-3 text-sm text-slate-300">{dlqItems.length === 0 && <p className="text-slate-400">DLQ empty.</p>}{dlqItems.map((item) => (<div key={item.event_id} className="rounded-xl border border-slate-800 bg-slate-950/40 p-4"><div className="font-medium">{item.stream}</div><div className="mt-1 text-slate-400">{item.error}</div><button onClick={() => replayDlq(item.event_id)} className="mt-3 rounded-lg bg-sky-600 px-3 py-2 text-xs font-medium text-white">Replay</button></div>))}</div></section>
          </div>
        )}
      </div>
    </div>
  )
}
