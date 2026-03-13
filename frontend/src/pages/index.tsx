import { useEffect, useMemo, useState } from 'react';
import axios from 'axios';
import { Activity, BarChart3, Bot, ClipboardList, Gauge, Moon, Settings, Sun, TerminalSquare } from 'lucide-react';

import { AgentCard } from '@/components/dashboard/AgentCard';
import { LogPanel } from '@/components/dashboard/LogPanel';
import { MetricCard } from '@/components/dashboard/MetricCard';
import { TaskTable } from '@/components/dashboard/TaskTable';
import { getHealthyAgentRatio, getTokenAndCostTotals } from '@/utils/dashboard';
import { MonitoringOverview, TradeRow, TradingStats } from '@/types/dashboard';

type Section = 'dashboard' | 'agents' | 'tasks' | 'logs' | 'metrics' | 'settings';

const navItems: Array<{ id: Section; label: string; icon: React.ComponentType<{ className?: string }> }> = [
  { id: 'dashboard', label: 'Dashboard', icon: Gauge },
  { id: 'agents', label: 'Agents', icon: Bot },
  { id: 'tasks', label: 'Tasks', icon: ClipboardList },
  { id: 'logs', label: 'Logs', icon: TerminalSquare },
  { id: 'metrics', label: 'Metrics', icon: BarChart3 },
  { id: 'settings', label: 'Settings', icon: Settings },
];

export default function MonitoringDashboard() {
  const [active, setActive] = useState<Section>('dashboard');
  const [theme, setTheme] = useState<'dark' | 'light'>('dark');
  const [overview, setOverview] = useState<MonitoringOverview | null>(null);
  const [stats, setStats] = useState<TradingStats | null>(null);
  const [trades, setTrades] = useState<TradeRow[]>([]);

  const isDark = theme === 'dark';
  const textTheme = isDark ? 'bg-slate-950 text-slate-100' : 'bg-slate-100 text-slate-900';
  const cardTheme = isDark ? 'border-slate-700 bg-slate-900/80' : 'border-slate-300 bg-white';
  const muted = isDark ? 'text-slate-400' : 'text-slate-600';

  useEffect(() => {
    const fetchAll = async () => {
      const [overviewRes, statsRes, tradesRes] = await Promise.all([
        axios.get('/api/monitoring/overview'),
        axios.get('/api/statistics'),
        axios.get('/api/trades'),
      ]);
      setOverview(overviewRes.data);
      setStats(statsRes.data);
      setTrades(tradesRes.data.trades || []);
    };

    fetchAll().catch(() => undefined);
    const timer = setInterval(() => fetchAll().catch(() => undefined), 10000);
    return () => clearInterval(timer);
  }, []);

  const totals = useMemo(() => getTokenAndCostTotals(overview?.recent_events ?? []), [overview]);

  return (
    <main className={`min-h-screen p-6 transition-colors ${textTheme}`}>
      <div className="mx-auto max-w-7xl">
        <header className={`mb-4 flex flex-wrap items-center justify-between gap-4 rounded-xl border p-5 ${cardTheme}`}>
          <div>
            <h1 className="text-2xl font-bold">AI Agent Control Panel</h1>
            <p className={`text-sm ${muted}`}>Clear real-time operations view for agent health, tasks, logs, and performance.</p>
          </div>
          <button
            aria-label="toggle-theme"
            onClick={() => setTheme(isDark ? 'light' : 'dark')}
            className="rounded-lg border border-slate-500 px-3 py-2"
          >
            {isDark ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
          </button>
        </header>

        <section className={`mb-6 rounded-xl border p-4 ${cardTheme}`}>
          <h2 className="text-lg font-semibold">Main Landing Overview</h2>
          <p className={`mt-1 text-sm ${muted}`}>
            Start on <strong>Dashboard</strong> for live status, open <strong>Agents</strong> for per-agent health, and use <strong>Logs</strong> for failure debugging.
          </p>
        </section>

        <nav className="mb-6 grid grid-cols-2 gap-2 md:grid-cols-6">
          {navItems.map((item) => (
            <button
              key={item.id}
              onClick={() => setActive(item.id)}
              className={`flex items-center justify-center gap-2 rounded-lg border px-3 py-2 text-sm ${
                active === item.id
                  ? 'border-cyan-500 bg-cyan-500/10 text-cyan-500'
                  : isDark
                    ? 'border-slate-700 bg-slate-900/70'
                    : 'border-slate-300 bg-white'
              }`}
            >
              <item.icon className="h-4 w-4" /> {item.label}
            </button>
          ))}
        </nav>

        {(active === 'dashboard' || active === 'metrics') && (
          <section className="mb-6 grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-4">
            <MetricCard
              isDark={isDark}
              label="Agent Health"
              value={getHealthyAgentRatio(overview?.agent_status ?? [])}
              hint="healthy agents"
              icon={<Bot className="h-4 w-4" />}
            />
            <MetricCard isDark={isDark} label="Avg Latency" value={`${overview?.avg_latency_ms ?? 0}ms`} hint={`P95 ${overview?.p95_latency_ms ?? 0}ms`} icon={<Activity className="h-4 w-4" />} />
            <MetricCard isDark={isDark} label="Error Rate" value={`${overview?.error_rate ?? 0}%`} hint={`${overview?.total_errors ?? 0} errors`} icon={<BarChart3 className="h-4 w-4" />} />
            <MetricCard isDark={isDark} label="Token Cost" value={`$${totals.cost.toFixed(4)}`} hint={`${totals.tokenUsage} tokens`} icon={<Gauge className="h-4 w-4" />} />
          </section>
        )}

        {(active === 'dashboard' || active === 'agents') && (
          <section className="mb-6 grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-4">
            {overview?.agent_status.map((agent) => <AgentCard key={agent.name} agent={agent} isDark={isDark} />)}
          </section>
        )}

        {(active === 'dashboard' || active === 'tasks') && (
          <section className={`mb-6 rounded-xl border p-4 ${cardTheme}`}>
            <h2 className="mb-3 text-lg font-semibold">Task & Execution History</h2>
            {stats ? <p className={`mb-4 text-sm ${muted}`}>Win rate {stats.win_rate}% • Total PnL {stats.total_pnl}</p> : null}
            <TaskTable rows={trades} isDark={isDark} />
          </section>
        )}

        {(active === 'dashboard' || active === 'logs') && <LogPanel events={overview?.recent_events || []} isDark={isDark} />}

        {active === 'settings' && (
          <section className={`rounded-xl border p-4 text-sm ${cardTheme}`}>
            <h2 className="mb-2 text-lg font-semibold">Deployment Settings</h2>
            <p>Configure API key protection with <code>API_SECRET_KEY</code> and origin/host allowlists with <code>ALLOWED_ORIGINS</code> and <code>ALLOWED_HOSTS</code>.</p>
            <p className="mt-2">Monitoring and tracing are active through request IDs, telemetry snapshots, and agent/task event logs.</p>
          </section>
        )}
      </div>
    </main>
  );
}
