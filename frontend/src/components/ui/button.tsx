import * as React from 'react'
import { cva, type VariantProps } from 'class-variance-authority'
import { Slot } from 'radix-ui'

import { cn } from '@/lib/utils'

const buttonVariants = cva(
  'inline-flex h-7 shrink-0 items-center justify-center rounded-[4px] border px-3 font-mono text-[11px] font-medium uppercase tracking-[0.04em] whitespace-nowrap transition-colors outline-none select-none disabled:pointer-events-none [&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg]:size-4',
  {
    variants: {
      variant: {
        default: 'border-slate-200 bg-slate-100 text-slate-950 hover:bg-slate-200',
        outline: 'border-slate-400 bg-transparent text-slate-700 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800',
        secondary: 'border-slate-400 bg-transparent text-slate-700 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800',
        ghost: 'border-transparent bg-transparent text-slate-500 hover:text-slate-700 dark:text-slate-400 dark:hover:text-slate-200',
        destructive: 'border-rose-400 bg-transparent text-rose-400 hover:bg-rose-500/10',
        success: 'border-slate-200 bg-slate-100 text-slate-950 hover:bg-slate-200',
        link: 'border-transparent bg-transparent text-slate-500 underline-offset-4 hover:underline',
      },
      size: {
        default: 'h-7 gap-1.5 px-3',
        xs: 'h-7 gap-1 px-2',
        sm: 'h-7 gap-1.5 px-3',
        lg: 'h-7 gap-2 px-4',
        icon: 'h-7 w-7 px-0',
        'icon-xs': 'h-7 w-7 px-0',
        'icon-sm': 'h-7 w-7 px-0',
        'icon-lg': 'h-7 w-7 px-0',
      },
    },
    defaultVariants: {
      variant: 'default',
      size: 'default',
    },
  }
)

function Button({
  className,
  variant,
  size,
  asChild = false,
  children,
  shortcut,
  ...props
}: React.ComponentProps<'button'> &
  VariantProps<typeof buttonVariants> & {
    asChild?: boolean
    shortcut?: string
  }) {
  const Comp = asChild ? Slot.Root : 'button'

  return (
    <Comp data-slot="button" className={cn(buttonVariants({ variant, size, className }))} {...props}>
      <span>{children}</span>
      {shortcut ? (
        <kbd className="ml-1 border border-slate-500/40 px-1 font-mono text-[10px] font-normal normal-case tracking-normal text-slate-500/70">
          {shortcut}
        </kbd>
      ) : null}
    </Comp>
  )
}

export { Button, buttonVariants }
