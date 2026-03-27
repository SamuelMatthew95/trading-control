import { useEffect, useState } from 'react';
import axios from 'axios';
import { Sidebar } from '@/components/mission-control/Sidebar';
import { Header } from '@/components/layout/Header';
import { AlertCircle } from 'lucide-react';

export default function PerformancePage() {
  const [pnl, setPnl] = useState<Record<string, unknown> | null>(null);
  const [summary, setSummary] = useState<{ items: Record<string, unknown>[] }>({ items: [] });
  const [error, setError] = useState<Error | null>(null);
  const [, setIsLoading] = useState(true);

  const load = async () => {
    try {
      setIsLoading(true);
      setError(null);
      const [a, d] = await Promise.all([
        axios.get('/api/dashboard/pnl'),
        axios.get('/api/dashboard/run-summary'),
      ]);
      setPnl(a.data);
      setSummary(d.data);
    } catch (err) {
      setError(err as Error);
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    load().catch(() => undefined);
    const t = setInterval(() => load().catch(() => undefined), 30000);
    return () => clearInterval(t);
  }, []);

  return (
    <div className="flex h-screen bg-background">
      <Sidebar />
      <div className="flex-1 flex flex-col">
        <Header title="Performance" subtitle="Trading metrics and task performance" />
        <main className="flex-1 overflow-y-auto p-6">
          {/* Performance Metrics */}
          <section className="mb-8">
            <h2 className="text-[0.7rem] uppercase tracking-widest text-slate-500 mb-3">Performance Metrics</h2>
            
            {/* Error State */}
            {error && (
              <div className="mb-4 bg-red-50 border border-red-200 rounded-md px-4 py-2 dark:bg-red-950/30 dark:border-red-800">
                <div className="flex items-center">
                  <AlertCircle size={14} className="text-red-500 mr-2" />
                  <span className="text-red-600 dark:text-red-400 text-sm">Could not fetch performance data</span>
                  <button 
                    onClick={load}
                    className="ml-auto text-red-500 dark:text-red-400 text-xs underline hover:no-underline"
                  >
                    Retry
                  </button>
                </div>
              </div>
            )}
            
            <div className="grid grid-cols-1 gap-4 md:grid-cols-5">
              {[
                ['Total P&L', pnl?.total_pnl, 'blue'],
                ['P&L today', pnl?.pnl_today, 'blue'],
                ['Avg slippage saved', pnl?.avg_slippage_saved, 'purple'],
                ['Execution cost', pnl?.execution_cost, 'purple'],
                ['Net alpha', pnl?.net_alpha, 'green'],
              ].map(([k, v, color]) => (
                <div key={String(k)} className={`bg-card border border-border rounded-lg p-5 hover:border-muted-foreground/20 transition-colors ${
                  color === 'blue' ? 'border-l-4 border-l-blue-500' :
                  color === 'purple' ? 'border-l-4 border-l-purple-500' :
                  'border-l-4 border-l-green-500'
                }`}>
                  <div className="text-[0.7rem] uppercase tracking-widest text-slate-500 mb-2">{k}</div>
                  <div className="text-[1.75rem] font-bold text-foreground">{Number(v||0).toFixed(2)}</div>
                </div>
              ))}
            </div>
          </section>

          {/* Task Performance Table */}
          <section className="mb-8">
            <h2 className="text-[0.7rem] uppercase tracking-widest text-slate-500 mb-3">Task Performance</h2>
            <div className="bg-card border border-border rounded-lg p-5">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-border">
                    <th className="text-left pb-3 font-medium text-foreground">Task</th>
                    <th className="text-left pb-3 font-medium text-foreground">Runs</th>
                    <th className="text-left pb-3 font-medium text-foreground">Win rate</th>
                    <th className="text-left pb-3 font-medium text-foreground">Avg steps</th>
                    <th className="text-left pb-3 font-medium text-foreground">Baseline</th>
                    <th className="text-left pb-3 font-medium text-foreground">Avg pnl</th>
                    <th className="text-left pb-3 font-medium text-foreground">Action</th>
                  </tr>
                </thead>
                <tbody>
                  {(summary.items || []).length > 0 ? (
                    (summary.items || []).map((r: Record<string, unknown>) => (
                      <tr key={r.task_slug} className="border-b border-border/50">
                        <td className="py-3 text-foreground">{r.task_type}</td>
                        <td className="py-3 text-foreground">{r.runs_7d}</td>
                        <td className="py-3 text-foreground">{r.win_rate_pct}</td>
                        <td className="py-3 text-foreground">{r.avg_steps}</td>
                        <td className="py-3 text-foreground">{r.baseline_avg_steps}</td>
                        <td className="py-3 text-foreground">{r.avg_pnl}</td>
                        <td className="py-3">
                          <a href={`/film-room?task_type=${encodeURIComponent(r.task_slug)}`} className="text-blue-500 hover:text-blue-600">
                            Drill in →
                          </a>
                        </td>
                      </tr>
                    ))
                  ) : (
                    <tr>
                      <td colSpan={7} className="py-12">
                        <div className="flex flex-col items-center justify-center text-center">
                          <div className="w-12 h-12 rounded-lg bg-muted/50 flex items-center justify-center mb-4">
                            <svg className="w-6 h-6 text-muted-foreground" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
                            </svg>
                          </div>
                          <h3 className="text-base font-medium text-muted-foreground mb-1">No tasks yet</h3>
                          <p className="text-sm text-muted-foreground">Task performance will appear here once the bot runs</p>
                        </div>
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </section>
        </main>
      </div>
    </div>
  );
}
