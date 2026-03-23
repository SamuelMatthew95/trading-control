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
  const getStatusConfig = (statusType: StatusChipProps['status']) => {
    switch (statusType) {
      case 'active':
        return {
          bg: 'bg-emerald-500/20',
          text: 'text-emerald-400',
          border: 'border-emerald-500/30',
          iconBg: 'bg-emerald-500'
        }
      case 'inactive':
        return {
          bg: 'bg-slate-500/20',
          text: 'text-slate-400',
          border: 'border-slate-500/30',
          iconBg: 'bg-slate-500'
        }
      case 'warning':
        return {
          bg: 'bg-amber-500/20',
          text: 'text-amber-400',
          border: 'border-amber-500/30',
          iconBg: 'bg-amber-500'
        }
      case 'error':
        return {
          bg: 'bg-rose-500/20',
          text: 'text-rose-400',
          border: 'border-rose-500/30',
          iconBg: 'bg-rose-500'
        }
      case 'success':
        return {
          bg: 'bg-emerald-500/20',
          text: 'text-emerald-400',
          border: 'border-emerald-500/30',
          iconBg: 'bg-emerald-500'
        }
      case 'neutral':
      default:
        return {
          bg: 'bg-violet-500/20',
          text: 'text-violet-400',
          border: 'border-violet-500/30',
          iconBg: 'bg-violet-500'
        }
    }
  }

  const config = getStatusConfig(status)

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
