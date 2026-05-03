import { UI_FALLBACK } from '@/lib/constants/ui'
export function formatCurrency(value?: number | null): string { if (value == null || !Number.isFinite(value)) return UI_FALLBACK; return `$${Math.abs(value).toFixed(2)}` }
