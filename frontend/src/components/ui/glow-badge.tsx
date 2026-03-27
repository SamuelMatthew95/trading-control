import { Badge } from '@/components/ui/badge'
import { cn } from '@/lib/utils'

interface GlowBadgeProps {
  children: React.ReactNode
  variant?: 'healthy' | 'unhealthy' | 'warning'
  className?: string
}

export function GlowBadge({ children, variant = 'healthy', className }: GlowBadgeProps) {
  const variantClass =
    variant === 'healthy'
      ? 'bg-emerald-500/15 text-emerald-600 dark:text-emerald-400'
      : variant === 'unhealthy'
      ? 'bg-rose-500/15 text-rose-600 dark:text-rose-400'
      : 'bg-amber-500/15 text-amber-600 dark:text-amber-400'

  return <Badge className={cn(variantClass, className)}>{children}</Badge>
}
