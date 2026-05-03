import { UI_FALLBACK } from '@/lib/constants/ui'
export function formatPercent(value?: number | null, decimals = 2): string { if (value == null || !Number.isFinite(value)) return UI_FALLBACK; return `${value.toFixed(decimals)}%` }
