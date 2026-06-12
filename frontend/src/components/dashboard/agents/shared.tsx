import type { ReactNode } from 'react'

// Freshness of each agent data source (ages in ms), surfaced in diagnostics.
export interface WiringFreshness {
  heartbeatAgeMs: number | null
  instanceAgeMs: number | null
  logAgeMs: number | null
}

// Subtle section divider so the page reads as grouped zones, not one long stack.
export function GroupLabel({ children }: { children: ReactNode }) {
  return (
    <h2 className="px-0.5 text-2xs font-semibold uppercase tracking-caps-wide text-muted-foreground/70">
      {children}
    </h2>
  )
}
