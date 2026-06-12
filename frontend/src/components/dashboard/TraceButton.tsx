'use client'

import { Button } from '@/components/ui/button'
import { UI_COPY } from '@/constants/copy'

/** Micro "trace" drill-down button — one recipe for every feed row. */
export function TraceButton({ onClick }: { onClick: () => void }) {
  return (
    <Button
      variant="outline"
      size="xs"
      onClick={onClick}
      title={UI_COPY.actions.traceTitle}
      className="h-5 shrink-0 px-1.5 text-3xs font-semibold uppercase tracking-caps"
    >
      {UI_COPY.actions.trace}
    </Button>
  )
}
