import { UI_FALLBACK } from '@/lib/constants/ui'
export function formatNumber(value?: number | null, decimals = 0): string { if (value == null || !Number.isFinite(value)) return UI_FALLBACK; return value.toFixed(decimals) }
