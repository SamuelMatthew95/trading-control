import { AgentState } from '@/types/dashboard';

const statusStyles: Record<AgentState, string> = {
  running: 'bg-emerald-500/20 text-emerald-300 border-emerald-400/40',
  idle: 'bg-amber-500/20 text-amber-300 border-amber-400/40',
  failed: 'bg-red-500/20 text-red-300 border-red-400/40',
};

export function StatusBadge({ status }: { status: AgentState }) {
  return <span className={`rounded-full border px-2 py-1 text-xs font-semibold uppercase ${statusStyles[status]}`}>{status}</span>;
}
