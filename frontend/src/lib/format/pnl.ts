import { UI_FALLBACK } from '@/lib/constants/ui'
export function formatPnl(value?: number | null): string { if (value == null || !Number.isFinite(value)) return UI_FALLBACK; const abs=Math.abs(value); const sign=value>0?'+':value<0?'-':''; return `${sign}$${abs.toFixed(2)}` }
