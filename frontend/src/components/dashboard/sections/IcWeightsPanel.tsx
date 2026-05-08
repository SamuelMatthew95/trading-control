'use client'

import { TerminalCard, SectionHeader } from '@/components/terminal'

interface IcWeightsPanelProps {
  weights: Record<string, number>
}

export function IcWeightsPanel({ weights }: IcWeightsPanelProps) {
  const entries = Object.entries(weights)
  if (entries.length === 0) return null

  return (
    <TerminalCard>
      <SectionHeader title="IC Factor Weights" />
      <div className="space-y-2">
        {entries.map(([factor, weight]) => {
          // Weight comes from Redis JSON with no server-side validation;
          // guard against null/Infinity/NaN before using.
          const w =
            typeof weight === 'number' && Number.isFinite(weight)
              ? Math.max(0, Math.min(1, weight))
              : 0
          return (
            <div key={factor} className="flex items-center justify-between">
              <span className="text-sm text-slate-600 dark:text-slate-400">{factor}</span>
              <div className="flex items-center gap-2">
                <div className="h-2 w-24 rounded-full bg-slate-200 dark:bg-slate-700">
                  <div
                    className="h-2 rounded-full bg-slate-500"
                    style={{ width: `${Math.round(w * 100)}%` }}
                  />
                </div>
                <span className="w-10 text-right text-xs font-mono tabular-nums text-slate-700 dark:text-slate-300">
                  {(w * 100).toFixed(1)}%
                </span>
              </div>
            </div>
          )
        })}
      </div>
    </TerminalCard>
  )
}
