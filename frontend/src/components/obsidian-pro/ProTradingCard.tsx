'use client'

import { motion } from 'framer-motion'
import { cn } from '@/lib/utils'
import { LucideIcon } from 'lucide-react'

interface ProTradingCardProps {
  title: string
  value: string | number
  icon?: LucideIcon
  trend?: 'up' | 'down' | 'neutral'
  trendValue?: string
  size?: 'sm' | 'md' | 'lg' | 'xl'
  className?: string
  children?: React.ReactNode
  sparkle?: boolean
  glow?: boolean
}

export function ProTradingCard({
  title,
  value,
  icon: Icon,
  trend,
  trendValue,
  size = 'md',
  className,
  children,
  sparkle = false,
  glow = false
}: ProTradingCardProps) {
  const sizeStyles = {
    sm: 'p-4',
    md: 'p-6',
    lg: 'p-8',
    xl: 'p-10'
  }

  const valueSizes = {
    sm: 'text-lg font-semibold',
    md: 'text-xl font-bold',
    lg: 'text-2xl font-bold',
    xl: 'text-3xl font-bold'
  }

  const trendColors = {
    up: 'text-emerald-400',
    down: 'text-rose-400',
    neutral: 'text-slate-400'
  }

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      whileHover={{ 
        y: -2,
        boxShadow: glow ? '0 20px 40px rgb(0 0 0 / 0.3)' : '0 12px 24px rgb(0 0 0 / 0.2)'
      }}
      className={cn(
        'glass-card relative overflow-hidden',
        sizeStyles[size],
        glow && 'shadow-[0_8px_30px_rgb(0,0,0,0.12)]',
        className
      )}
    >
      {/* Sparkle effect */}
      {sparkle && (
        <div className="absolute inset-0 opacity-20">
          <div className="absolute top-0 right-0 w-32 h-32 bg-gradient-to-br from-white/10 to-transparent rounded-full blur-2xl" />
          <div className="absolute bottom-0 left-0 w-24 h-24 bg-gradient-to-tr from-gray-500/10 to-transparent rounded-full blur-xl" />
        </div>
      )}

      {/* Content */}
      <div className="relative z-10">
        {/* Header */}
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-[10px] font-semibold uppercase tracking-[0.2em] text-slate-500">
            {title}
          </h3>
          {Icon && (
            <Icon className="h-4 w-4 text-slate-500" />
          )}
        </div>

        {/* Main Value */}
        <div className="flex items-baseline gap-3 mb-2">
          <motion.div
            key={value}
            initial={{ scale: 0.8, opacity: 0 }}
            animate={{ scale: 1, opacity: 1 }}
            className={cn(
              'font-mono tabular-nums text-slate-200',
              valueSizes[size]
            )}
          >
            {value}
          </motion.div>
          
          {trend && trendValue && (
            <motion.div
              initial={{ opacity: 0, x: -10 }}
              animate={{ opacity: 1, x: 0 }}
              className={cn(
                'text-sm font-medium',
                trendColors[trend]
              )}
            >
              {trendValue}
            </motion.div>
          )}
        </div>

        {/* Additional content */}
        {children}
      </div>

      {/* Glow effect */}
      {glow && (
        <motion.div
          className="absolute inset-0 rounded-xl opacity-0 group-hover:opacity-100 transition-opacity duration-300"
          style={{
            background: 'linear-gradient(135deg, rgba(139, 92, 246, 0.1) 0%, rgba(59, 130, 246, 0.1) 100%)',
            filter: 'blur(20px)'
          }}
        />
      )}
    </motion.div>
  )
}
