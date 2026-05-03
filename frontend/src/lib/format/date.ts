import { UI_FALLBACK } from '@/lib/constants/ui'
export function formatDateTime(value?: string | number | Date | null): string { if (!value) return UI_FALLBACK; const d = value instanceof Date ? value : new Date(value); return Number.isNaN(d.getTime()) ? UI_FALLBACK : d.toLocaleString() }
