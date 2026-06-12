'use client'

import { useEffect, type ReactNode } from 'react'
import { X } from 'lucide-react'
import { cn } from '@/lib/utils'
import { sectionTitleClass } from '@/lib/dashboard-styles'
import { UI_COPY } from '@/constants/copy'

export type ModalSize = 'md' | 'lg'

const SIZE_CLASS: Record<ModalSize, string> = {
  md: 'max-w-2xl',
  lg: 'max-w-3xl',
}

export interface ModalProps {
  onClose: () => void
  /** Eyebrow/section label rendered in the header row. */
  title: string
  /** Optional content rendered under the title (headline, meta line). */
  subtitle?: ReactNode
  size?: ModalSize
  children: ReactNode
}

/**
 * Canonical modal shell — overlay, centered panel, header with close button,
 * Escape-to-close, and dialog ARIA semantics. Every dialog composes this;
 * never re-declare the fixed-overlay scaffolding.
 */
export function Modal({ onClose, title, subtitle, size = 'md', children }: ModalProps) {
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  return (
    <div
      role="presentation"
      className="fixed inset-0 z-modal flex animate-fade-in items-start justify-center bg-black/60 p-4 pt-16"
      onClick={onClose}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label={title}
        className={cn(
          'max-h-modal w-full animate-scale-in overflow-y-auto rounded-xl border bg-popover p-5 shadow-modal',
          SIZE_CLASS[size],
        )}
        onClick={(event) => event.stopPropagation()}
      >
        <div className="mb-4 flex items-start justify-between gap-3">
          <div className="min-w-0">
            <p className={sectionTitleClass}>{title}</p>
            {subtitle}
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label={UI_COPY.aria.closeDialog}
            className="-m-1 shrink-0 rounded-md p-1 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
        {children}
      </div>
    </div>
  )
}
