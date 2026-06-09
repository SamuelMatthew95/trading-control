'use client'

import { cn } from '@/lib/utils'
import { Panel } from './Panel'
import { fmtCompact, fmtQty, type Book, type BookLevel } from './marketData'

/** Level-2 depth ladder. Click a level to prefill a limit price in the ticket. */
export function OrderBook({
  book,
  mid,
  onPick,
}: {
  book: Book | null
  mid: number
  onPick?: (price: number) => void
}) {
  if (!book || !book.bids?.length) return null
  const max = book.maxCum || 1
  const spread = book.asks[0] && book.bids[0] ? book.asks[0].price - book.bids[0].price : 0
  const asks = book.asks.slice(0, 9).reverse()
  const bids = book.bids.slice(0, 9)

  const Row = ({ lvl, side }: { lvl: BookLevel; side: 'ask' | 'bid' }) => {
    const pct = (lvl.cum / max) * 100
    const isAsk = side === 'ask'
    return (
      <button
        type="button"
        onClick={() => onPick?.(lvl.price)}
        className="relative grid w-full cursor-pointer grid-cols-3 px-3 py-[3px] text-left font-mono text-[11px] tabular-nums hover:bg-slate-800/40"
      >
        <span
          className="book-depth absolute inset-y-0 right-0"
          style={{ width: `${pct}%`, background: isAsk ? 'var(--down-soft)' : 'var(--up-soft)' }}
        />
        <span className={cn('relative z-10', isAsk ? 'txt-down' : 'txt-up')}>{lvl.price.toFixed(2)}</span>
        <span className="relative z-10 text-right text-slate-300">{fmtQty(lvl.size)}</span>
        <span className="relative z-10 text-right text-slate-500">{fmtCompact(lvl.cum)}</span>
      </button>
    )
  }

  return (
    <Panel
      title="Order Book"
      right={<span className="font-mono text-[10px] text-slate-500">L2</span>}
      bodyClass="flex flex-col overflow-hidden"
    >
      <div className="grid grid-cols-3 px-3 pb-1 pt-1.5 text-[9px] font-semibold uppercase tracking-wider text-slate-600">
        <span>Price</span>
        <span className="text-right">Size</span>
        <span className="text-right">Total</span>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto thin-scroll">
        {asks.map((l, i) => (
          <Row key={`a${i}`} lvl={l} side="ask" />
        ))}
        <div className="flex items-center justify-between border-y border-slate-800 bg-slate-800/40 px-3 py-1.5">
          <span className="font-mono text-sm font-bold tabular-nums text-slate-100">{mid.toFixed(2)}</span>
          <span className="font-mono text-[10px] text-slate-500">spread {spread.toFixed(2)}</span>
        </div>
        {bids.map((l, i) => (
          <Row key={`b${i}`} lvl={l} side="bid" />
        ))}
      </div>
    </Panel>
  )
}
