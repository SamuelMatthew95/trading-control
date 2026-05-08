export const MISSING = '—'

export const isFiniteNumber = (value: unknown): value is number => typeof value === 'number' && Number.isFinite(value)

export const toFiniteNumber = (value: unknown): number | null => {
  if (typeof value === 'number') return Number.isFinite(value) ? value : null
  if (typeof value === 'string') {
    const parsed = Number(value.trim())
    return Number.isFinite(parsed) ? parsed : null
  }
  return null
}

export const sanitizeValue = (value: string | number | boolean | null | undefined): string => {
  if (value === undefined || value === null || value === '') return MISSING
  if (typeof value === 'number' && (!Number.isFinite(value) || Number.isNaN(value))) return MISSING
  if (typeof value === 'boolean') return value ? 'True' : 'False'
  return String(value)
}

export const formatCurrency = (value?: number | null): string => {
  if (value == null || Number.isNaN(value) || !Number.isFinite(value)) return MISSING
  return `$${Math.abs(value).toFixed(2)}`
}

export const formatSignedCurrency = (value?: number | null): string => {
  if (value == null || Number.isNaN(value) || !Number.isFinite(value)) return MISSING
  const abs = Math.abs(value)
  if (abs < 0.005) return '$0.00'
  return `${value > 0 ? '+' : '-'}$${abs.toFixed(2)}`
}

export const formatPercent = (value?: number | null, digits = 2): string => {
  if (value == null || !Number.isFinite(value)) return MISSING
  return `${value.toFixed(digits)}%`
}

export const parseTimestamp = (value: unknown): Date | null => {
  if (value == null) return null
  if (value instanceof Date) return Number.isNaN(value.getTime()) ? null : value
  if (typeof value === 'number') {
    if (!Number.isFinite(value) || value <= 0) return null
    const ms = value > 10_000_000_000 ? value : value * 1000
    const d = new Date(ms)
    return Number.isNaN(d.getTime()) ? null : d
  }
  const d = new Date(String(value))
  return Number.isNaN(d.getTime()) ? null : d
}

export const formatTimeAgo = (date: Date): string => {
  const seconds = Math.max(0, Math.floor((Date.now() - date.getTime()) / 1000))
  if (seconds < 60) return `${seconds}s ago`
  const minutes = Math.floor(seconds / 60)
  if (minutes < 60) return `${minutes}m ago`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours}h ago`
  return `${Math.floor(hours / 24)}d ago`
}

export const formatTimestamp = (value?: string | null): string => {
  if (!value) return MISSING
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return MISSING
  return date.toLocaleTimeString()
}
