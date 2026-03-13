import { useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import axios from 'axios';
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer } from 'recharts';
import { SignalsSidebar } from '@/components/dashboard/SignalsSidebar';

export default function ExecutiveDashboard() {
  const [pnl, setPnl] = useState<any>(null);
  const [learning, setLearning] = useState<any>(null);
  const [health, setHealth] = useState<any>({ items: [] });
  const [summary, setSummary] = useState<any>({ items: [] });

  const load = async () => {
    const [a, b, c, d] = await Promise.all([
      axios.get('/dashboard/pnl'),
      axios.get('/dashboard/learning-velocity'),
      axios.get('/dashboard/health-signals'),
      axios.get('/dashboard/run-summary'),
    ]);
    setPnl(a.data);
    setLearning(b.data);
    setHealth(c.data);
    setSummary(d.data);
  };

  useEffect(() => {
    load().catch(() => undefined);
    const t = setInterval(() => load().catch(() => undefined), 30000);
    return () => clearInterval(t);
  }, []);

  const chartData = useMemo(() => (learning?.passk_series || []).map((v: number | null, i: number) => ({ day: i + 1, passk: v, coherence: learning?.coherence_series?.[i] ?? null })), [learning]);

  return (
    <main className="min-h-screen bg-slate-950 p-6 pr-80 text-slate-100">
      <nav className="mb-4 flex gap-4"><Link href="/dashboard">Dashboard</Link><Link href="/film-room">Film Room</Link></nav>
      <section className="mb-6 grid grid-cols-1 gap-3 md:grid-cols-5">
        {[
          ['Total P&L', pnl?.total_pnl],
          ['P&L today', pnl?.pnl_today],
          ['Avg slippage saved', pnl?.avg_slippage_saved],
          ['Execution cost', pnl?.execution_cost],
          ['Net alpha', pnl?.net_alpha],
        ].map(([k,v]) => <div key={String(k)} className="rounded border border-slate-700 p-3"><div className="text-xs text-slate-400">{k}</div><div className="text-lg">{Number(v||0).toFixed(2)}</div></div>)}
      </section>

      <section className="mb-6 grid grid-cols-1 gap-4 md:grid-cols-2">
        <div className="rounded border border-slate-700 p-3"><div style={{ width: '100%', height: 240 }}><ResponsiveContainer><LineChart data={chartData}><XAxis dataKey="day" /><YAxis domain={[0,100]} /><Tooltip /><Line type="monotone" dataKey="passk" stroke="#22c55e" dot={false} /><Line type="monotone" dataKey="coherence" stroke="#3b82f6" dot={false} /></LineChart></ResponsiveContainer></div><div className="mt-2 text-xs">Trend: {learning?.passk_trend}</div></div>
        <div className="rounded border border-slate-700 p-3 text-sm">
          <div>Annotations this week: {learning?.annotations_this_week ?? 0}</div>
          <div>Avg sessions to correction: {learning?.avg_sessions_to_correction ?? 0}</div>
          <div>Memory guard effectiveness: {learning?.memory_guard_effectiveness_pct ?? 0}%</div>
        </div>
      </section>

      <section className="mb-6 grid grid-cols-1 gap-3 md:grid-cols-3">
        {(health.items || []).map((h: any) => <div key={h.key} className="rounded border border-slate-700 p-3"><div className="text-xs">{h.label}</div><div>{h.value}</div><div className="text-xs text-slate-400">{h.interpretation}</div></div>)}
      </section>

      <section className="rounded border border-slate-700 p-3">
        <table className="w-full text-sm"><thead><tr><th>Task</th><th>Runs</th><th>Win rate</th><th>Avg steps</th><th>Baseline</th><th>Avg pnl</th><th>Action</th></tr></thead><tbody>
          {(summary.items || []).map((r: any) => (
            <tr key={r.task_slug}>
              <td>{r.task_type}</td><td>{r.runs_7d}</td><td>{r.win_rate_pct}</td><td>{r.avg_steps}</td><td>{r.baseline_avg_steps}</td><td>{r.avg_pnl}</td>
              <td><Link href={`/film-room?task_type=${encodeURIComponent(r.task_slug)}`}>Drill in →</Link></td>
            </tr>
          ))}
        </tbody></table>
      </section>
      <SignalsSidebar />
    </main>
  );
}
