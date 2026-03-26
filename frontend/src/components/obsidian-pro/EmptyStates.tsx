'use client'

import { motion } from 'framer-motion'
import { Moon, Power, Activity, Clock, TrendingDown } from 'lucide-react'
import { cn } from '@/lib/utils'

interface EmptyStateProps {
  type: 'markets-closed' | 'bot-offline' | 'no-data' | 'loading'
  className?: string
}

export function EmptyState({ type, className }: EmptyStateProps) {
  const getEmptyStateConfig = (stateType: EmptyStateProps['type']) => {
    switch (stateType) {
      case 'markets-closed':
        return {
          icon: Moon,
          title: 'Markets Closed',
          description: 'Trading markets are currently closed. Check back during market hours.',
          color: 'text-gray-400',
          bgColor: 'bg-[#18181b]',
          borderColor: 'border-[#27272a]',
          iconBg: 'bg-[#09090b]'
        }
      case 'bot-offline':
        return {
          icon: Power,
          title: 'System Sleeping',
          description: 'The trading bot is currently offline. Start trading to activate the system.',
          color: 'text-amber-700',
          bgColor: 'bg-amber-50',
          borderColor: 'border-amber-200',
          iconBg: 'bg-amber-100'
        }
      case 'no-data':
        return {
          icon: TrendingDown,
          title: 'No Data Available',
          description: 'No trading data is available at the moment. Please check your connection.',
          color: 'text-muted-foreground',
          bgColor: 'bg-muted/30',
          borderColor: 'border-border',
          iconBg: 'bg-slate-100'
        }
      case 'loading':
        return {
          icon: Activity,
          title: 'Loading...',
          description: 'Initializing trading system and fetching market data.',
          color: 'text-primary',
          bgColor: 'bg-primary/10',
          borderColor: 'border-primary/30',
          iconBg: 'bg-primary/20'
        }
      default:
        return {
          icon: Clock,
          title: 'System Idle',
          description: 'The system is waiting for the next trading opportunity.',
          color: 'text-muted-foreground',
          bgColor: 'bg-muted/30',
          borderColor: 'border-border',
          iconBg: 'bg-slate-100'
        }
    }
  }

  const config = getEmptyStateConfig(type)
  const Icon = config.icon

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      className={cn(
        'p-6 text-center border rounded-lg',
        config.bgColor,
        config.borderColor,
        className
      )}
    >
      <div className="flex items-center gap-4">
        {/* Compact Icon */}
        <motion.div
          animate={
            type === 'loading' ? {
              scale: [1, 1.1, 1],
              rotate: [0, 180, 360],
            } : type === 'markets-closed' ? {
              scale: [1, 1.1, 1],
              opacity: [0.8, 1, 0.8]
            } : {}
          }
          transition={
            type === 'loading' ? {
              duration: 2,
              repeat: Infinity,
              ease: "linear"
            } : type === 'markets-closed' ? {
              duration: 4,
              repeat: Infinity,
              ease: "easeInOut"
            } : {}
          }
          className={cn(
            'w-10 h-10 rounded-full flex items-center justify-center',
            config.iconBg,
            'border',
            config.borderColor
          )}
        >
          <Icon className={cn('w-5 h-5', config.color)} />
        </motion.div>

        {/* Compact Content */}
        <div className="text-left">
          <motion.h3
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ delay: 0.2 }}
            className={cn('text-sm font-semibold', config.color)}
          >
            {config.title}
          </motion.h3>
          
          <motion.p
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ delay: 0.3 }}
            className="text-xs text-gray-400 max-w-md"
          >
            {config.description}
          </motion.p>
        </div>

        {/* Additional context for markets-closed */}
        {type === 'markets-closed' && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ delay: 0.4 }}
            className="text-xs font-medium text-gray-500 bg-[#27272a] px-3 py-1 rounded border border-[#27272a]"
          >
            <Clock className="w-3 h-3 inline-block mr-1" />
            9:30 AM - 4:00 PM EST
          </motion.div>
        )}
      </div>
    </motion.div>
  )
}

// Specialized empty states for different contexts
export function MarketEmptyState() {
  return (
    <EmptyState 
      type="markets-closed" 
      className="col-span-12"
    />
  )
}

export function BotEmptyState() {
  return (
    <EmptyState 
      type="bot-offline" 
      className="col-span-12"
    />
  )
}

export function DataEmptyState() {
  return (
    <EmptyState 
      type="no-data" 
      className="col-span-12"
    />
  )
}

export function LoadingState() {
  return (
    <EmptyState 
      type="loading" 
      className="col-span-12"
    />
  )
}
