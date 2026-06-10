'use client'

/** 50×20 sparkline of recent closes, coloured up/down via terminal CSS vars. */
export function Spark({ data, up }: { data: number[]; up: boolean }) {
  if (!data || data.length < 2) return null
  const w = 50
  const h = 20
  const lo = Math.min(...data)
  let hi = Math.max(...data)
  if (hi === lo) hi += 1
  const points = data
    .map((v, i) => `${(i / (data.length - 1)) * w},${h - 2 - ((v - lo) / (hi - lo)) * (h - 4)}`)
    .join(' ')
  return (
    <svg width={w} height={h} className="block" aria-hidden="true">
      <polyline
        points={points}
        fill="none"
        strokeWidth="1.5"
        stroke={up ? 'var(--up)' : 'var(--down)'}
        strokeLinejoin="round"
        strokeLinecap="round"
      />
    </svg>
  )
}
