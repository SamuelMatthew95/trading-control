'use client'

import { Panel } from './Panel'
import { fmtQty, type TapePrint } from './marketData'

/** Time & sales tape — latest prints, price coloured by aggressor side. */
export function Tape({ tape }: { tape: TapePrint[] }) {
  return (
    <Panel title="Time & Sales" count={tape.length} bodyClass="overflow-y-auto thin-scroll">
      <div className="grid grid-cols-[1fr_auto_auto] gap-x-1.5 px-3 pb-1 pt-1.5 text-[9px] font-semibold uppercase tracking-wider text-slate-600">
        <span>Price</span>
        <span className="text-right">Size</span>
        <span className="text-right">Time</span>
      </div>
      {tape.slice(0, 40).map((p, i) => (
        <div
          key={`${p.t}-${i}`}
          className="grid grid-cols-[1fr_auto_auto] gap-x-1.5 px-3 py-[3px] font-mono text-[10px] tabular-nums"
        >
          <span className={p.side === 'buy' ? 'txt-up' : 'txt-down'}>{p.price.toFixed(2)}</span>
          <span className="text-right text-slate-300">{fmtQty(p.size)}</span>
          <span className="text-right text-slate-600">
            {new Date(p.t).toLocaleTimeString('en', { hour12: false })}
          </span>
        </div>
      ))}
    </Panel>
  )
}
