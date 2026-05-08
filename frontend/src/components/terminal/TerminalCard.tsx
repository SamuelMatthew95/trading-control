import type { ReactNode } from 'react'
import { cn } from '@/lib/utils'
import { UI_PAD, UI_RADIUS, UI_SURFACE } from '@/lib/constants/ui'

interface TerminalCardProps {
  children: ReactNode
  className?: string
  /** Pass `false` to remove inner padding (use this when wrapping a table). */
  padded?: boolean
}

/**
 * Base surface for all dashboard panels — neutral border, no gradients,
 * controlled small radius. Composes the design tokens defined in lib/constants/ui.
 */
export function TerminalCard({ children, className, padded = true }: TerminalCardProps) {
  return (
    <div
      className={cn(
        UI_RADIUS.card,
        UI_SURFACE.card,
        UI_SURFACE.cardHover,
        'transition-colors duration-150',
        padded && UI_PAD.card,
        className,
      )}
    >
      {children}
    </div>
  )
}
