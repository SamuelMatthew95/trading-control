'use client'

import { motion } from 'framer-motion'
import { cn } from '@/lib/utils'
import { LucideIcon } from 'lucide-react'

interface StatusChipProps {
  status: 'active' | 'inactive' | 'warning' | 'error' | 'success' | 'neutral'
  label: string
  size?: 'sm' | 'md' | 'lg'
  variant?: 'solid' | 'outline' | 'ghost'
  icon?: LucideIcon
  pulse?: boolean
  className?: string
}

export function StatusChip({
  status,
  label,
  size = 'md',
  variant = 'solid',
  icon: Icon,
  pulse = false,
  className
}: StatusChipProps) {
  const getStatusConfig = (status: StatusChipProps['status'], variant: StatusChipProps['variant'] = 'solid') => {
    const configs = {
      online: {
        solid: {
          color: 'text-emerald-700 dark:text-emerald-400',
          bgColor: 'bg-emerald-100 dark:bg-emerald-500/20',
          borderColor: 'border-emerald-200 dark:border-emerald-500/30',
          iconColor: 'text-emerald-600 dark:text-emerald-400'
        },
        outline: {
          color: 'text-emerald-600 dark:text-emerald-400',
          bgColor: 'bg-emerald-50 dark:bg-emerald-500/10',
          borderColor: 'border-emerald-200 dark:border-emerald-500/30',
          iconColor: 'text-emerald-500 dark:text-emerald-400'
        },
        ghost: {
          color: 'text-emerald-600 dark:text-emerald-400',
          bgColor: 'bg-emerald-50 dark:bg-emerald-500/10',
          borderColor: 'border-transparent dark:border-transparent',
          iconColor: 'text-emerald-500 dark:text-emerald-400'
        }
      },
      offline: {
        solid: {
          color: 'text-slate-600 dark:text-slate-400',
          bgColor: 'bg-slate-100 dark:bg-slate-500/20',
          borderColor: 'border-slate-200 dark:border-slate-500/30',
          iconColor: 'text-slate-500 dark:text-slate-400'
        },
        outline: {
          color: 'text-slate-500 dark:text-slate-400',
          bgColor: 'bg-slate-50 dark:bg-slate-500/10',
          borderColor: 'border-slate-200 dark:border-slate-500/30',
          iconColor: 'text-slate-400 dark:text-slate-400'
        },
        ghost: {
          color: 'text-slate-500 dark:text-slate-400',
          bgColor: 'bg-slate-50 dark:bg-slate-500/10',
          borderColor: 'border-transparent dark:border-transparent',
          iconColor: 'text-slate-400 dark:text-slate-400'
        }
      },
      warning: {
        solid: {
          color: 'text-amber-700 dark:text-amber-400',
          bgColor: 'bg-amber-100 dark:bg-amber-500/20',
          borderColor: 'border-amber-200 dark:border-amber-500/30',
          iconColor: 'text-amber-600 dark:text-amber-400'
        },
        outline: {
          color: 'text-amber-600 dark:text-amber-400',
          bgColor: 'bg-amber-50 dark:bg-amber-500/10',
          borderColor: 'border-amber-200 dark:border-amber-500/30',
          iconColor: 'text-amber-500 dark:text-amber-400'
        },
        ghost: {
          color: 'text-amber-600 dark:text-amber-400',
          bgColor: 'bg-amber-50 dark:bg-amber-500/10',
          borderColor: 'border-transparent dark:border-transparent',
          iconColor: 'text-amber-500 dark:text-amber-400'
        }
      },
      error: {
        solid: {
          color: 'text-rose-700 dark:text-rose-400',
          bgColor: 'bg-rose-100 dark:bg-rose-500/20',
          borderColor: 'border-rose-200 dark:border-rose-500/30',
          iconColor: 'text-rose-600 dark:text-rose-400'
        },
        outline: {
          color: 'text-rose-600 dark:text-rose-400',
          bgColor: 'bg-rose-50 dark:bg-rose-500/10',
          borderColor: 'border-rose-200 dark:border-rose-500/30',
          iconColor: 'text-rose-500 dark:text-rose-400'
        },
        ghost: {
          color: 'text-rose-600 dark:text-rose-400',
          bgColor: 'bg-rose-50 dark:bg-rose-500/10',
          borderColor: 'border-transparent dark:border-transparent',
          iconColor: 'text-rose-500 dark:text-rose-400'
        }
      },
      success: {
        solid: {
          color: 'text-emerald-700 dark:text-emerald-400',
          bgColor: 'bg-emerald-100 dark:bg-emerald-500/20',
          borderColor: 'border-emerald-200 dark:border-emerald-500/30',
          iconColor: 'text-emerald-600 dark:text-emerald-400'
        },
        outline: {
          color: 'text-emerald-600 dark:text-emerald-400',
          bgColor: 'bg-emerald-50 dark:bg-emerald-500/10',
          borderColor: 'border-emerald-200 dark:border-emerald-500/30',
          iconColor: 'text-emerald-500 dark:text-emerald-400'
        },
        ghost: {
          color: 'text-emerald-600 dark:text-emerald-400',
          bgColor: 'bg-emerald-50 dark:bg-emerald-500/10',
          borderColor: 'border-transparent dark:border-transparent',
          iconColor: 'text-emerald-500 dark:text-emerald-400'
        }
      }
    }

    return configs[status]?.[variant] || configs.offline.solid
  }

  const config = getStatusConfig(status, variant)

  const sizeStyles = {
    sm: 'px-2 py-1 text-[10px] gap-1',
    md: 'px-3 py-1.5 text-xs gap-2',
    lg: 'px-4 py-2 text-sm gap-2'
  }

  const iconSizes = {
    sm: 'w-3 h-3',
    md: 'w-3.5 h-3.5',
    lg: 'w-4 h-4'
  }

  const getVariantStyles = () => {
    switch (variant) {
      case 'solid':
        return config.bg
      case 'outline':
        return 'bg-transparent border'
      case 'ghost':
        return 'bg-transparent'
      default:
        return config.bg
    }
  }

  return (
    <motion.div
      initial={{ scale: 0.8, opacity: 0 }}
      animate={{ scale: 1, opacity: 1 }}
      whileHover={{ scale: 1.05 }}
      className={cn(
        'inline-flex items-center justify-center rounded-full font-medium transition-all duration-200',
        sizeStyles[size],
        getVariantStyles(),
        variant === 'outline' && `${config.border} ${config.text}`,
        variant === 'ghost' && config.text,
        variant === 'solid' && `${config.text} ${config.border}`,
        className
      )}
    >
      {Icon && (
        <div className="relative">
          <Icon className={cn(iconSizes[size], 'flex-shrink-0')} />
          {pulse && (
            <motion.div
              className={cn(
                'absolute inset-0 rounded-full',
                config.iconBg
              )}
              animate={{
                scale: [1, 1.5, 1],
                opacity: [0.8, 0, 0.8]
              }}
              transition={{
                duration: 2,
                repeat: Infinity,
                ease: "easeInOut"
              }}
            />
          )}
        </div>
      )}
      
      <span className="font-semibold uppercase tracking-[0.05em]">
        {label}
      </span>
    </motion.div>
  )
}

// Specialized chips for common use cases
export function AgentStatusChip({ 
  status, 
  label, 
  size = 'sm' 
}: { 
  status: 'running' | 'idle' | 'error' 
  label: string
  size?: 'sm' | 'md' | 'lg' 
}) {
  const statusMap = {
    running: 'active' as const,
    idle: 'inactive' as const,
    error: 'error' as const
  }
  
  return (
    <StatusChip
      status={statusMap[status]}
      label={label}
      size={size}
      pulse={status === 'running'}
    />
  )
}

export function TrendChip({ 
  trend, 
  value, 
  size = 'sm' 
}: { 
  trend: 'up' | 'down' | 'neutral'
  value: string
  size?: 'sm' | 'md' | 'lg' 
}) {
  const trendMap = {
    up: 'success' as const,
    down: 'error' as const,
    neutral: 'neutral' as const
  }
  
  return (
    <StatusChip
      status={trendMap[trend]}
      label={`${trend === 'up' ? '▲' : trend === 'down' ? '▼' : '→'} ${value}`}
      size={size}
    />
  )
}
