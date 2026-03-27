import * as React from 'react'
import { cva, type VariantProps } from 'class-variance-authority'
import { Slot } from 'radix-ui'

import { cn } from '@/lib/utils'

const buttonVariants = cva(
  'inline-flex min-h-11 shrink-0 items-center justify-center rounded-lg border text-sm font-sans font-semibold whitespace-nowrap transition-colors outline-none select-none disabled:pointer-events-none disabled:opacity-50 [&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg]:size-4',
  {
    variants: {
      variant: {
        default: 'border-indigo-600 bg-indigo-600 text-slate-100 hover:bg-indigo-700',
        outline: 'border-slate-200 bg-transparent text-slate-600 hover:bg-slate-100 dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800',
        secondary: 'border-slate-200 bg-slate-100 text-slate-700 hover:bg-slate-200 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-200 dark:hover:bg-slate-700',
        ghost: 'border-transparent bg-transparent text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800',
        destructive: 'border-rose-600 bg-rose-600 text-slate-100 hover:bg-rose-700',
        success: 'border-emerald-600 bg-emerald-600 text-slate-100 hover:bg-emerald-700',
        link: 'border-transparent text-indigo-600 underline-offset-4 hover:underline dark:text-indigo-400',
      },
      size: {
        default: 'h-11 gap-1.5 px-4',
        xs: 'h-11 gap-1 px-3 text-xs',
        sm: 'h-11 gap-1.5 px-3 text-sm',
        lg: 'h-11 gap-2 px-5 text-sm',
        icon: 'h-11 w-11',
        'icon-xs': 'h-11 w-11',
        'icon-sm': 'h-11 w-11',
        'icon-lg': 'h-11 w-11',
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
  ...props
}: React.ComponentProps<'button'> &
  VariantProps<typeof buttonVariants> & {
    asChild?: boolean
  }) {
  const Comp = asChild ? Slot.Root : 'button'

  return <Comp data-slot="button" className={cn(buttonVariants({ variant, size, className }))} {...props} />
}

export { Button, buttonVariants }
