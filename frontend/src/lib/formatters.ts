export const sanitizeValue = (value: string | number | boolean | null | undefined): string => {
  if (value === undefined || value === null || value === '') return '--'
  if (typeof value === 'number' && (!Number.isFinite(value) || Number.isNaN(value))) return '--'
  if (typeof value === 'boolean') return value ? 'True' : 'False'
  return String(value)
}

export const formatCurrency = (value?: number | null): string => {
  if (value == null || Number.isNaN(value) || !Number.isFinite(value)) return '$0.00'
  return `$${Math.abs(value).toFixed(2)}`
}

export const formatSignedCurrency = (value?: number | null): string => {
  if (value == null || Number.isNaN(value) || !Number.isFinite(value)) return '--'
  const abs = Math.abs(value)
  if (abs < 0.005) return '$0.00'
  return `${value > 0 ? '+' : '-'}$${abs.toFixed(2)}`
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
  if (!value) return '--'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '--'
  return date.toLocaleTimeString()
}
