'use client'

import { useEffect, useState, type ReactNode } from 'react'
import { cn } from '@/lib/utils'
import { formatUSD } from '@/lib/formatters'
import { Panel } from './Panel'
import type { OrderDraft, OrderSide, OrderType, TimeInForce } from './types'

const ORDER_TYPES: OrderType[] = ['market', 'limit', 'stop']
const TIFS: TimeInForce[] = ['DAY', 'GTC', 'IOC']
const PCT_PRESETS = [0.25, 0.5, 0.75, 1]

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1 block text-[10px] font-semibold uppercase tracking-wider text-slate-500">{label}</span>
      <div className="flex items-center rounded-lg border border-slate-800 bg-slate-950 focus-within:border-[var(--accent)]">
        {children}
      </div>
    </label>
  )
}

function SummaryRow({
  label,
  value,
  strong,
  dim,
  danger,
}: {
  label: string
  value: string
  strong?: boolean
  dim?: boolean
  danger?: boolean
}) {
  return (
    <div className="flex items-center justify-between gap-2">
      <span className="whitespace-nowrap text-slate-500">{label}</span>
      <span
        className={cn(
          'whitespace-nowrap',
          danger ? 'txt-down font-bold' : strong ? 'font-bold text-slate-100' : dim ? 'text-slate-400' : 'text-slate-300',
        )}
      >
        {value}
      </span>
    </div>
  )
}

export function OrderTicket({
  symbol,
  price,
  buyingPower,
  onSubmit,
  prefillPrice,
}: {
  symbol: string
  price: number
  buyingPower: number
  onSubmit: (draft: OrderDraft) => void
  prefillPrice: number | null
}) {
  const [side, setSide] = useState<OrderSide>('buy')
  const [type, setType] = useState<OrderType>('market')
  const [qty, setQty] = useState('10')
  const [limit, setLimit] = useState(price)
  const [tif, setTif] = useState<TimeInForce>('DAY')

  // Reset the limit to the live price when the symbol changes.
  useEffect(() => {
    setLimit(Number(price.toFixed(2)))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [symbol])

  // Clicking a book level prefills a limit order at that price.
  useEffect(() => {
    if (prefillPrice != null) {
      setType('limit')
      setLimit(Number(prefillPrice.toFixed(2)))
    }
  }, [prefillPrice])

  const qtyNum = Number(qty) || 0
  const execPx = type === 'market' ? price : Number(limit) || price
  const cost = execPx * qtyNum
  const exceeds = side === 'buy' && cost > buyingPower

  return (
    <Panel
      title="Order Ticket"
      right={<span className="font-mono text-[10px] text-slate-500">{symbol}</span>}
      bodyClass="flex flex-col gap-2.5 p-3"
    >
      <div className="grid grid-cols-2 gap-1 rounded-lg bg-slate-950 p-1">
        {(['buy', 'sell'] as OrderSide[]).map((s) => (
          <button
            key={s}
            type="button"
            onClick={() => setSide(s)}
            className={cn(
              'h-8 rounded-md text-xs font-bold uppercase tracking-wider transition-colors',
              side === s
                ? s === 'buy'
                  ? 'bg-[var(--up)] text-slate-950'
                  : 'bg-[var(--down)] text-slate-950'
                : 'text-slate-400 hover:text-slate-200',
            )}
          >
            {s}
          </button>
        ))}
      </div>

      <div className="flex gap-1">
        {ORDER_TYPES.map((tp) => (
          <button
            key={tp}
            type="button"
            onClick={() => setType(tp)}
            className={cn(
              'h-7 flex-1 rounded-md border text-[11px] font-semibold capitalize transition-colors',
              type === tp
                ? 'border-[var(--accent)] bg-[var(--accent-soft)] text-[var(--accent)]'
                : 'border-slate-800 text-slate-400 hover:border-slate-700',
            )}
          >
            {tp}
          </button>
        ))}
      </div>

      <Field label="Quantity">
        <input
          type="number"
          value={qty}
          min="0"
          onChange={(e) => setQty(e.target.value)}
          className="ticket-input"
        />
        <span className="px-2 font-mono text-[10px] text-slate-500">SH</span>
      </Field>

      {type !== 'market' && (
        <Field label={type === 'stop' ? 'Stop price' : 'Limit price'}>
          <span className="pl-2.5 font-mono text-[11px] text-slate-500">$</span>
          <input
            type="number"
            value={limit}
            step="0.01"
            onChange={(e) => setLimit(Number(e.target.value))}
            className="ticket-input"
          />
        </Field>
      )}

      <div className="flex gap-1">
        {PCT_PRESETS.map((p) => (
          <button
            key={p}
            type="button"
            onClick={() => setQty(String(Math.max(1, Math.floor((buyingPower * p) / (execPx || 1)))))}
            className="h-6 flex-1 rounded border border-slate-800 font-mono text-[10px] text-slate-400 hover:border-slate-700 hover:text-slate-200"
          >
            {p * 100}%
          </button>
        ))}
      </div>

      <div className="flex gap-1">
        {TIFS.map((t) => (
          <button
            key={t}
            type="button"
            onClick={() => setTif(t)}
            className={cn(
              'h-6 flex-1 rounded font-mono text-[10px] tracking-wide transition-colors',
              tif === t ? 'bg-slate-800 text-slate-200' : 'text-slate-500 hover:text-slate-300',
            )}
          >
            {t}
          </button>
        ))}
      </div>

      <div className="mt-auto space-y-1 border-t border-slate-800 pt-2.5 font-mono text-[11px] tabular-nums">
        <SummaryRow label="Est. price" value={formatUSD(execPx)} />
        <SummaryRow label="Est. cost" value={formatUSD(cost)} strong />
        <SummaryRow label="Buying power" value={formatUSD(buyingPower)} dim={!exceeds} danger={exceeds} />
      </div>

      <button
        type="button"
        disabled={exceeds || qtyNum <= 0}
        onClick={() => onSubmit({ symbol, side, type, qty: qtyNum, price: execPx, tif })}
        className={cn(
          'h-10 rounded-lg text-xs font-bold uppercase tracking-widest transition-all hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-40',
          side === 'buy' ? 'bg-[var(--up)] text-slate-950' : 'bg-[var(--down)] text-slate-950',
        )}
      >
        {exceeds ? 'Insufficient buying power' : `${side} ${qtyNum || 0} ${symbol}`}
      </button>
    </Panel>
  )
}
