'use client'

import { motion } from 'framer-motion'
import { cn } from '@/lib/utils'

interface SentimentGaugeProps {
  value: number // 0-100
  size?: 'sm' | 'md' | 'lg'
  showLabel?: boolean
  className?: string
}

export function SentimentGauge({ 
  value, 
  size = 'md', 
  showLabel = true,
  className 
}: SentimentGaugeProps) {
  const getSentimentConfig = (val: number) => {
    if (val < 33) {
      return {
        label: 'FEAR',
        gradient: 'from-rose-400 to-red-500',
        ringColor: 'border-rose-200',
        glowColor: 'bg-rose-100',
        lightMode: {
          gradient: 'from-rose-300 to-red-400',
          ringColor: 'border-rose-200',
          glowColor: 'bg-rose-50'
        }
      }
    }
    if (val < 67) {
      return {
        label: 'NEUTRAL',
        gradient: 'from-amber-400 to-yellow-500',
        ringColor: 'border-amber-200',
        glowColor: 'bg-amber-100',
        lightMode: {
          gradient: 'from-amber-300 to-yellow-400',
          ringColor: 'border-amber-200',
          glowColor: 'bg-amber-50'
        }
      }
    }
    return {
      label: 'GREED',
      gradient: 'from-emerald-400 to-green-500',
      ringColor: 'border-emerald-200',
      glowColor: 'bg-emerald-100',
      lightMode: {
        gradient: 'from-emerald-300 to-green-400',
        ringColor: 'border-emerald-200',
        glowColor: 'bg-emerald-50'
      }
    }
  }

  const config = getSentimentConfig(value)

  const sizeStyles = {
    sm: { width: 80, height: 40, strokeWidth: 6 },
    md: { width: 120, height: 60, strokeWidth: 8 },
    lg: { width: 160, height: 80, strokeWidth: 10 }
  }

  const { width, height, strokeWidth } = sizeStyles[size]

  return (
    <div className={cn('flex flex-col items-center', className)}>
      <motion.div
        initial={{ scale: 0.8, opacity: 0 }}
        animate={{ scale: 1, opacity: 1 }}
        whileHover={{ scale: 1.05 }}
        className="relative"
      >
        {/* Solid border instead of blur for clean appearance */}
        <div
          className={cn(
            'absolute inset-0 rounded-full border-2',
            config.ringColor
          )}
        />

        {/* SVG Gauge */}
        <svg
          width={width}
          height={height}
          viewBox={`0 0 ${width} ${height}`}
          className="relative z-10"
        >
          {/* Background arc */}
          <path
            d={`M ${strokeWidth} ${height/2} A ${width/2 - strokeWidth} ${width/2 - strokeWidth} 0 0 1 ${width - strokeWidth} ${height/2}`}
            fill="none"
            stroke="hsl(var(--border))"
            strokeWidth={strokeWidth}
            strokeLinecap="round"
          />

          {/* Colored arc */}
          <motion.path
            d={`M ${strokeWidth} ${height/2} A ${width/2 - strokeWidth} ${width/2 - strokeWidth} 0 0 1 ${width - strokeWidth} ${height/2}`}
            fill="none"
            stroke="hsl(var(--neutral))"
            strokeWidth={strokeWidth}
            strokeLinecap="round"
            initial={{ pathLength: 0 }}
            animate={{ pathLength: value / 100 }}
            transition={{ duration: 1, ease: "easeOut" }}
          />

          {/* Gradient definition */}
          <defs>
            <linearGradient id={`gradient-${value}`} x1="0%" y1="0%" x2="100%" y2="0%">
              <stop offset="0%" stopColor={config.gradient.includes('rose') ? '#f43f5e' : config.gradient.includes('gray') ? '#6b7280' : '#10b981'} />
              <stop offset="100%" stopColor={config.gradient.includes('orange') ? '#f97316' : config.gradient.includes('gray') ? '#4b5563' : '#22c55e'} />
            </linearGradient>
          </defs>

          {/* Center dot */}
          <motion.circle
            cx={width / 2}
            cy={height / 2}
            r={strokeWidth / 2}
            className={cn('fill-white', config.glowColor)}
            animate={{
              scale: [1, 1.2, 1],
              opacity: [0.8, 1, 0.8]
            }}
            transition={{
              duration: 2,
              repeat: Infinity,
              ease: "easeInOut"
            }}
          />
        </svg>

        {/* Value text */}
        <div className="absolute inset-0 flex items-center justify-center mt-2">
          <motion.div
            key={value}
            initial={{ scale: 0.8, opacity: 0 }}
            animate={{ scale: 1, opacity: 1 }}
            className="text-center"
          >
            <div className="text-lg font-bold text-slate-200 font-mono tabular-nums">
              {Math.round(value)}%
            </div>
          </motion.div>
        </div>
      </motion.div>

      {/* Label */}
      {showLabel && (
        <motion.div
          key={config.label}
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          className="mt-3"
        >
          <span className={cn(
            'text-xs font-semibold uppercase tracking-[0.2em]',
            config.gradient.includes('rose') ? 'text-rose-400' :
            config.gradient.includes('gray') ? 'text-gray-400' :
            'text-emerald-400'
          )}>
            {config.label}
          </span>
        </motion.div>
      )}
    </div>
  )
}
