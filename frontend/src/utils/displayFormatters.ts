export const FALLBACK_TEXT = {
  missingValue: 'Not available',
  missingTimestamp: 'No timestamp available',
} as const

export function sanitizeValue(value: string | number | boolean | null | undefined): string {
  if (value === undefined || value === null || value === '') return FALLBACK_TEXT.missingValue
  if (typeof value === 'number' && (!Number.isFinite(value) || Number.isNaN(value))) return FALLBACK_TEXT.missingValue
  if (typeof value === 'boolean') return value ? 'True' : 'False'
  return String(value)
}

export function formatTimestamp(value?: string | null): string {
  if (!value) return FALLBACK_TEXT.missingTimestamp
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return FALLBACK_TEXT.missingTimestamp
  return date.toLocaleTimeString()
}
