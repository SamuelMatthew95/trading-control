'use client'

import { Menu } from 'lucide-react'
import { cn } from '@/lib/utils'
import { SystemStatus, type SystemStatusState } from '@/components/dashboard/SystemStatus'

const formatUSD = (value?: number | null): string => {
  if (value == null || Number.isNaN(value) || !Number.isFinite(value)) return '$0.00'
  return `$${Math.abs(value).toFixed(2)}`
}

export function TopBar({
  onOpenSidebar,
  pnl,
  marketTickCount,
  systemStatus,
}: {
  onOpenSidebar: () => void
  pnl: number
  marketTickCount: number
  systemStatus: SystemStatusState
}) {
  return (
    <header className="sticky top-0 z-50 h-12 border-b border-slate-800 bg-slate-950">
      <div className="flex h-full items-center px-4">
        <div className="flex flex-1 items-center gap-2">
          <button
            onClick={onOpenSidebar}
            className="flex h-9 w-9 items-center justify-center rounded-lg text-slate-400 transition-colors hover:bg-slate-800 hover:text-slate-100 md:hidden"
          >
            <Menu className="h-4 w-4" />
          </button>
          <span className="text-sm font-bold uppercase tracking-widest text-white">Trading Console</span>
        </div>

        <div className="flex items-center gap-3">
          <div className="hidden items-center gap-2 rounded-lg border border-slate-800 bg-slate-900 px-2.5 py-1 sm:flex">
            <span className="text-[10px] font-semibold uppercase tracking-[0.08em] text-slate-400">Market Ticks</span>
            <span className="min-w-12 text-right font-mono text-xs tabular-nums text-slate-100">{marketTickCount}</span>
          </div>

          <SystemStatus state={systemStatus} />

          <div className="rounded-lg border border-slate-800 bg-slate-900 px-2.5 py-1">
            <p className="text-[10px] font-semibold uppercase tracking-[0.08em] text-slate-400">Total P&amp;L</p>
            <p
              className={cn(
                'text-base font-bold tabular-nums',
                pnl > 0 ? 'text-[#22c55e]' : pnl < 0 ? 'text-[#ef4444]' : 'text-slate-300'
              )}
            >
              {pnl > 0 ? `+${formatUSD(pnl)}` : pnl < 0 ? `-${formatUSD(pnl)}` : formatUSD(pnl)}
            </p>
          </div>
        </div>
      </div>
    </header>
  )
}
