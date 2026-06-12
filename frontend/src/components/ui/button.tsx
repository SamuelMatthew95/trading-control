'use client'

import { forwardRef, type ButtonHTMLAttributes } from 'react'
import { cn } from '@/lib/utils'
import { TONE_BUTTON, type Tone } from '@/lib/design/sentiment'

export type ButtonVariant = 'outline' | 'ghost' | 'tonal' | 'solid'
export type ButtonSize = 'xs' | 'sm' | 'icon' | 'icon-sm'

const BASE_CLASS =
  'inline-flex items-center justify-center gap-1.5 whitespace-nowrap rounded-md font-medium transition-colors ' +
  'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring ' +
  'disabled:pointer-events-none disabled:opacity-50'

const VARIANT_CLASS: Record<ButtonVariant, string> = {
  outline: 'border text-muted-foreground hover:border-strong hover:text-foreground',
  ghost: 'text-muted-foreground hover:bg-muted hover:text-foreground',
  tonal: 'border', // colour comes from TONE_BUTTON
  solid: '', // colour comes from SOLID_TONE
}

const SOLID_TONE: Record<Tone, string> = {
  success: 'bg-success text-background hover:bg-success/90',
  danger: 'bg-danger text-background hover:bg-danger/90',
  warning: 'bg-warning text-background hover:bg-warning/90',
  neutral: 'bg-muted-foreground text-background hover:bg-muted-foreground/90',
}

const SIZE_CLASS: Record<ButtonSize, string> = {
  xs: 'h-6 px-2 text-2xs',
  sm: 'h-7 px-2.5 text-xs',
  icon: 'h-9 w-9',
  'icon-sm': 'h-7 w-7',
}

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant
  /** Colour recipe for `tonal` / `solid` variants — routed through the Tone maps. */
  tone?: Tone
  size?: ButtonSize
}

/**
 * Canonical button — every clickable control composes this instead of
 * re-declaring border/hover/disabled recipes. Colour always routes through
 * the Tone system; shape adjustments (font-mono, uppercase) compose via
 * className at the call site.
 */
export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = 'outline', tone = 'neutral', size = 'sm', className, type = 'button', ...props },
  ref,
) {
  return (
    <button
      ref={ref}
      type={type}
      className={cn(
        BASE_CLASS,
        VARIANT_CLASS[variant],
        variant === 'tonal' && TONE_BUTTON[tone],
        variant === 'solid' && SOLID_TONE[tone],
        SIZE_CLASS[size],
        className,
      )}
      {...props}
    />
  )
})
