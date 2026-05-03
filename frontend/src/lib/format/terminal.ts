export const MISSING_VALUE = 'Not available'
export function formatCurrency(value?: number | null): string { if (value == null || !Number.isFinite(value)) return MISSING_VALUE; return `$${Math.abs(value).toFixed(2)}` }
export function formatSignedCurrency(value?: number | null): string { if (value == null || !Number.isFinite(value)) return MISSING_VALUE; const abs=Math.abs(value); if (abs<0.005) return '$0.00'; return `${value>0?'+':'-'}$${abs.toFixed(2)}` }
export function formatPercent(value?: number | null, decimals = 2): string { if (value == null || !Number.isFinite(value)) return MISSING_VALUE; return `${value.toFixed(decimals)}%` }
export function formatSignedPercent(value?: number | null, decimals = 2): string { if (value == null || !Number.isFinite(value)) return MISSING_VALUE; const sign=value>0?'+':''; return `${sign}${value.toFixed(decimals)}%` }
