import { ReactNode } from 'react';

export function MetricCard({
  label,
  value,
  hint,
  icon,
  isDark,
}: {
  label: string;
  value: string;
  hint?: string;
  icon: ReactNode;
  isDark: boolean;
}) {
  const card = isDark ? 'border-slate-700 bg-slate-900/80 text-slate-100' : 'border-slate-300 bg-white text-slate-900';
  const muted = isDark ? 'text-slate-400' : 'text-slate-600';

  return (
    <div className={`rounded-xl border p-4 shadow-lg ${card}`}>
      <div className={`mb-2 flex items-center justify-between ${muted}`}>
        <span className="text-sm">{label}</span>
        {icon}
      </div>
      <div className="text-2xl font-semibold">{value}</div>
      {hint ? <p className={`mt-1 text-xs ${muted}`}>{hint}</p> : null}
    </div>
  );
}
