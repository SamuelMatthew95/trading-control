import type { ComponentType, ReactNode } from 'react'

import { MetricTile } from '@/components/terminal'

interface MetricCardProps {
  label: string
  value: string
  hint?: ReactNode
  icon?: ReactNode
}

/**
 * Backwards-compatible wrapper around the shared MetricTile primitive.
 * The legacy `isDark` prop is no longer needed — Tailwind's `dark:` variants
 * handle theming, and lib/constants/ui already encodes the operator-grade
 * typography. Renders any pre-built icon node by wrapping it in a tiny adapter
 * so MetricTile's `icon` prop (which expects a component, not an element)
 * stays the canonical contract.
 */
export function MetricCard({ label, value, hint, icon }: MetricCardProps) {
  const IconAdapter: ComponentType<{ className?: string }> | undefined = icon
    ? ({ className }: { className?: string }) => <span className={className}>{icon}</span>
    : undefined

  return <MetricTile label={label} value={value} hint={hint} icon={IconAdapter} />
}
