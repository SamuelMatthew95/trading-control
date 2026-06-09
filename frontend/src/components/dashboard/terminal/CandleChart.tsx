'use client'

import { useEffect, useMemo, useRef, useState } from 'react'
import type { Candle } from './marketData'
import type { Timeframe } from './SymbolHeader'

function cssVar(name: string, fallback: string): string {
  if (typeof window === 'undefined') return fallback
  const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim()
  return v || fallback
}

function hexAlpha(hex: string, a: number): string {
  const h = hex.replace('#', '')
  const full = h.length === 3 ? h.split('').map((x) => x + x).join('') : h
  const n = parseInt(full, 16)
  if (Number.isNaN(n)) return `rgba(148,163,184,${a})`
  return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${a})`
}

function roundRect(ctx: CanvasRenderingContext2D, x: number, y: number, w: number, h: number, r: number): void {
  ctx.beginPath()
  ctx.moveTo(x + r, y)
  ctx.arcTo(x + w, y, x + w, y + h, r)
  ctx.arcTo(x + w, y + h, x, y + h, r)
  ctx.arcTo(x, y + h, x, y, r)
  ctx.arcTo(x, y, x + w, y, r)
  ctx.closePath()
}

const TF_MINUTES: Record<Timeframe, number> = { '1m': 1, '5m': 5, '15m': 15, '1h': 60 }

/** Aggregate 1-minute base candles into the selected timeframe buckets. */
function aggregate(candles: Candle[], tfMin: number): Candle[] {
  if (tfMin <= 1) return candles
  const span = tfMin * 60_000
  const out: Candle[] = []
  let bucket: Candle | null = null
  for (const c of candles) {
    const b = Math.floor(c.t / span) * span
    if (!bucket || bucket.t !== b) {
      bucket = { t: b, o: c.o, h: c.h, l: c.l, c: c.c, v: c.v }
      out.push(bucket)
    } else {
      bucket.h = Math.max(bucket.h, c.h)
      bucket.l = Math.min(bucket.l, c.l)
      bucket.c = c.c
      bucket.v += c.v
    }
  }
  return out
}

interface HoverState {
  x: number
  y: number
}

/**
 * Canvas candlestick chart with a price scale, volume sub-pane, crosshair, and a
 * dashed last-price marker. Up candles are hollow, down candles filled. Colours
 * read from the shared CSS vars so the terminal theme applies.
 */
export function CandleChart({
  candles,
  lastPrice,
  timeframe,
}: {
  candles: Candle[]
  lastPrice: number
  timeframe: Timeframe
}) {
  const wrapRef = useRef<HTMLDivElement | null>(null)
  const canvasRef = useRef<HTMLCanvasElement | null>(null)
  const [hover, setHover] = useState<HoverState | null>(null)
  const [size, setSize] = useState({ w: 800, h: 420 })

  useEffect(() => {
    const el = wrapRef.current
    if (!el || typeof ResizeObserver === 'undefined') return
    const ro = new ResizeObserver((entries) => {
      for (const e of entries) {
        const cr = e.contentRect
        setSize({ w: Math.floor(cr.width), h: Math.floor(cr.height) })
      }
    })
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  const tfMin = TF_MINUTES[timeframe] ?? 1

  // Overlay the live price onto the forming (last) bar so the chart breathes
  // with the stream without rewriting the stable historical bars.
  const view = useMemo(() => {
    const agg = aggregate(candles, tfMin)
    if (agg.length === 0 || !Number.isFinite(lastPrice)) return agg
    const out = agg.slice()
    const last = { ...out[out.length - 1] }
    last.c = lastPrice
    last.h = Math.max(last.h, lastPrice)
    last.l = Math.min(last.l, lastPrice)
    out[out.length - 1] = last
    return out
  }, [candles, tfMin, lastPrice])

  useEffect(() => {
    const cv = canvasRef.current
    if (!cv) return
    const ctx = cv.getContext('2d')
    if (!ctx) return // jsdom / unsupported — skip drawing

    const dpr = window.devicePixelRatio || 1
    const { w, h } = size
    cv.width = w * dpr
    cv.height = h * dpr
    cv.style.width = `${w}px`
    cv.style.height = `${h}px`
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
    ctx.clearRect(0, 0, w, h)

    const up = cssVar('--up', '#10b981')
    const down = cssVar('--down', '#f43f5e')
    const accent = cssVar('--accent', '#00e5ff')
    const grid = 'rgba(148,163,184,0.09)'
    const labelColor = '#94a3b8'
    const snap = (v: number) => Math.round(v) + 0.5

    const priceGutter = 64 // right-hand price scale width
    const timeGutter = 22 // bottom time scale height
    const volH = 64
    const plotW = w - priceGutter
    const plotH = h - timeGutter - volH - 8

    const barCount = Math.min(view.length, Math.max(30, Math.floor(plotW / 13)))
    const data = view.slice(view.length - barCount)
    if (data.length === 0 || plotW <= 0 || plotH <= 0) return

    let hi = -Infinity
    let lo = Infinity
    let vMax = 0
    for (const c of data) {
      hi = Math.max(hi, c.h)
      lo = Math.min(lo, c.l)
      vMax = Math.max(vMax, c.v)
    }
    const pad = (hi - lo) * 0.08 || 1
    hi += pad
    lo -= pad

    const slot = plotW / data.length
    const xAt = (i: number) => (i + 0.5) * slot
    const yAt = (p: number) => plotH * (1 - (p - lo) / (hi - lo)) + 4
    const cw = Math.max(3, Math.min(18, slot * 0.68))

    // price scale gridlines + labels
    ctx.font = '11px "IBM Plex Mono", monospace'
    ctx.textBaseline = 'middle'
    const ticks = 6
    for (let i = 0; i <= ticks; i += 1) {
      const p = lo + (hi - lo) * (i / ticks)
      const yy = snap(yAt(p))
      ctx.strokeStyle = grid
      ctx.lineWidth = 1
      ctx.beginPath()
      ctx.moveTo(0, yy)
      ctx.lineTo(plotW, yy)
      ctx.stroke()
      ctx.fillStyle = labelColor
      ctx.textAlign = 'left'
      ctx.fillText(`$${p.toFixed(2)}`, plotW + 8, yAt(p))
    }

    // volume sub-pane
    const volTop = plotH + 8 + 12
    data.forEach((c, i) => {
      const bh = (c.v / (vMax || 1)) * (volH - 14)
      ctx.fillStyle = c.c >= c.o ? hexAlpha(up, 0.5) : hexAlpha(down, 0.5)
      ctx.fillRect(xAt(i) - cw / 2, volTop + (volH - 14) - bh, cw, bh)
    })
    ctx.fillStyle = labelColor
    ctx.textAlign = 'left'
    ctx.fillText('VOL', 4, volTop + 4)

    // candles
    data.forEach((c, i) => {
      const bull = c.c >= c.o
      const col = bull ? up : down
      const cx = snap(xAt(i))
      ctx.strokeStyle = col
      ctx.lineWidth = Math.max(1, Math.min(2, cw * 0.18))
      ctx.beginPath()
      ctx.moveTo(cx, snap(yAt(c.h)))
      ctx.lineTo(cx, snap(yAt(c.l)))
      ctx.stroke()
      const yo = yAt(c.o)
      const yc = yAt(c.c)
      const top = Math.round(Math.min(yo, yc))
      const bodyH = Math.max(2, Math.round(Math.abs(yc - yo)))
      const bx = Math.round(cx - cw / 2)
      if (bull) {
        ctx.fillStyle = '#0b1220'
        ctx.fillRect(bx, top, Math.round(cw), bodyH)
        ctx.strokeStyle = col
        ctx.lineWidth = 1.5
        ctx.strokeRect(bx + 0.75, top + 0.75, Math.round(cw) - 1.5, bodyH - 1.5)
      } else {
        ctx.fillStyle = col
        ctx.fillRect(bx, top, Math.round(cw), bodyH)
      }
    })

    // last-price line + tag
    const lp = Number.isFinite(lastPrice) ? lastPrice : data[data.length - 1].c
    const lpY = snap(yAt(lp))
    ctx.strokeStyle = accent
    ctx.lineWidth = 1.5
    ctx.setLineDash([5, 4])
    ctx.beginPath()
    ctx.moveTo(0, lpY)
    ctx.lineTo(plotW, lpY)
    ctx.stroke()
    ctx.setLineDash([])
    const tag = `$${lp.toFixed(2)}`
    ctx.font = '11px "IBM Plex Mono", monospace'
    const tagW = ctx.measureText(tag).width + 12
    ctx.fillStyle = accent
    roundRect(ctx, plotW + 2, lpY - 9, Math.min(tagW, priceGutter - 4), 18, 3)
    ctx.fill()
    ctx.fillStyle = '#04141a'
    ctx.textAlign = 'left'
    ctx.fillText(tag, plotW + 8, lpY)

    // time scale labels + faint vertical gridlines
    const labelEvery = Math.max(1, Math.ceil(data.length / 7))
    data.forEach((c, i) => {
      if (i % labelEvery !== 0) return
      const gx = snap(xAt(i))
      ctx.strokeStyle = grid
      ctx.lineWidth = 1
      ctx.beginPath()
      ctx.moveTo(gx, 0)
      ctx.lineTo(gx, plotH + 4)
      ctx.stroke()
      const d = new Date(c.t)
      const hh = String(d.getHours()).padStart(2, '0')
      const mm = String(d.getMinutes()).padStart(2, '0')
      ctx.fillStyle = labelColor
      ctx.textAlign = 'center'
      ctx.fillText(`${hh}:${mm}`, xAt(i), h - 8)
    })

    // crosshair
    if (hover) {
      ctx.strokeStyle = 'rgba(148,163,184,0.35)'
      ctx.setLineDash([3, 3])
      ctx.beginPath()
      const cx = Math.min(plotW, Math.max(0, hover.x))
      ctx.moveTo(cx, 0)
      ctx.lineTo(cx, plotH + 4)
      ctx.stroke()
      ctx.beginPath()
      ctx.moveTo(0, hover.y)
      ctx.lineTo(plotW, hover.y)
      ctx.stroke()
      ctx.setLineDash([])
      if (hover.y < plotH + 4) {
        const pAtY = lo + (hi - lo) * (1 - (hover.y - 4) / plotH)
        ctx.fillStyle = '#1e293b'
        roundRect(ctx, plotW + 2, hover.y - 9, priceGutter - 4, 18, 3)
        ctx.fill()
        ctx.fillStyle = '#e2e8f0'
        ctx.textAlign = 'left'
        ctx.font = '11px "IBM Plex Mono", monospace'
        ctx.fillText(`$${pAtY.toFixed(2)}`, plotW + 8, hover.y)
      }
    }
  })

  // O/H/L/C readout for the hovered (or latest) bar.
  const readout = useMemo(() => {
    if (view.length === 0) return null
    const barCount = Math.min(view.length, 200)
    const data = view.slice(view.length - barCount)
    let idx = data.length - 1
    if (hover) {
      const plotW = size.w - 64
      idx = Math.min(data.length - 1, Math.max(0, Math.round(hover.x / (plotW / data.length) - 0.5)))
    }
    return data[idx]
  }, [hover, view, size])

  const bull = readout ? readout.c >= readout.o : true

  function onMove(e: React.MouseEvent<HTMLCanvasElement>) {
    const cv = canvasRef.current
    if (!cv) return
    const r = cv.getBoundingClientRect()
    setHover({ x: e.clientX - r.left, y: e.clientY - r.top })
  }

  return (
    <div ref={wrapRef} className="relative h-full w-full">
      {readout && (
        <div className="pointer-events-none absolute left-3 top-2 z-10 flex flex-wrap items-center gap-x-3 gap-y-0.5 font-mono text-[11px] tabular-nums">
          {(['O', 'H', 'L', 'C'] as const).map((k) => {
            const val = k === 'O' ? readout.o : k === 'H' ? readout.h : k === 'L' ? readout.l : readout.c
            return (
              <span key={k} className="text-slate-500">
                {k}
                <span className="ml-1" style={{ color: bull ? 'var(--up)' : 'var(--down)' }}>
                  {val.toFixed(2)}
                </span>
              </span>
            )
          })}
          <span className="text-slate-600">
            VOL{' '}
            <span className="text-slate-400">
              {new Intl.NumberFormat('en', { notation: 'compact' }).format(readout.v)}
            </span>
          </span>
        </div>
      )}
      <canvas
        ref={canvasRef}
        onMouseMove={onMove}
        onMouseLeave={() => setHover(null)}
        className="block h-full w-full"
      />
    </div>
  )
}
