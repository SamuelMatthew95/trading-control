import { Activity, AlertTriangle, Bot } from 'lucide-react';

import { AgentView } from '@/types/dashboard';

import { StatusBadge } from './StatusBadge';

export function AgentCard({ agent, isDark }: { agent: AgentView; isDark: boolean }) {
  const card = isDark ? 'border-slate-700 bg-slate-900/80 text-slate-100' : 'border-slate-300 bg-white text-slate-900';
  const muted = isDark ? 'text-slate-300' : 'text-slate-600';

  return (
    <article className={`rounded-xl border p-4 ${card}`}>
      <header className="mb-3 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Bot className="h-4 w-4" />
          <h3 className="font-semibold">{agent.name}</h3>
        </div>
        <StatusBadge status={agent.status} />
      </header>
      <div className={`space-y-2 text-sm ${muted}`}>
        <p className="flex items-center gap-2"><Activity className="h-4 w-4 text-cyan-500" /> Current: {agent.current_task || 'Idle'}</p>
        <p>Last task: {agent.last_task || 'N/A'}</p>
        <p>Latency: {agent.latency_ms ? `${agent.latency_ms.toFixed(0)}ms` : 'N/A'}</p>
        {agent.error ? <p className="flex items-center gap-2 text-red-500"><AlertTriangle className="h-4 w-4" /> {agent.error}</p> : null}
      </div>
    </article>
  );
}
