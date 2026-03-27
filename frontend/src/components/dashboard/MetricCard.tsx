import { ReactNode } from 'react'

export function MetricCard({
  label,
  value,
  hint,
  icon,
  isDark,
}: {
  label: string
  value: string
  hint?: string
  icon: ReactNode
  isDark: boolean
}) {
  const card = isDark ? 'border-slate-800 bg-slate-900 text-slate-100' : 'border-slate-200 bg-white text-slate-900'
  const muted = isDark ? 'text-slate-400' : 'text-slate-500'

  return (
    <div className={`rounded-xl border p-4 sm:p-5 transition-colors ${card}`}>
      <div className={`mb-2 flex items-center justify-between ${muted}`}>
        <span className="text-xs font-sans font-semibold uppercase tracking-wider">{label}</span>
        {icon}
      </div>
      <div className="text-2xl font-black font-mono tabular-nums">{value}</div>
      {hint ? <p className={`mt-1 text-xs font-sans ${muted}`}>{hint}</p> : null}
    </div>
  )
}
