'use client'

import { useEffect, useMemo, useState, memo } from 'react'
import { motion } from 'framer-motion'
import { useCodexStore } from '@/stores/useCodexStore'
import {
  Zap,
  SignalLow,
  SignalMedium,
  SignalHigh,
} from 'lucide-react'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from '@/components/ui/alert-dialog'
import { cn } from '@/lib/utils'

// Import new Obsidian-Pro components
import { ProTradingCard } from './ProTradingCard'
import { SentimentGauge } from './SentimentGauge'
import { LogViewer } from './LogViewer'
import { StatusChip, AgentStatusChip, TrendChip } from './StatusChip'
import { MarketEmptyState } from './EmptyStates'
import { KillSwitchState } from './KillSwitchState'

const API_BASE = (process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000/api').replace(/\/$/, '')

// Memoized components for performance optimization
const PnLHero = memo(({ dailyPnl }: { dailyPnl: number }) => {
  const isPositive = dailyPnl >= 0
  
  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      className="glass-card p-8 relative overflow-hidden col-span-8"
    >
      {/* Background sparkline */}
      <div className="absolute inset-0 opacity-10">
        <svg viewBox="0 0 400 100" className="w-full h-full">
          <path
            d="M0,50 L50,45 L100,55 L150,30 L200,40 L250,25 L300,35 L350,20 L400,30"
            fill="none"
            stroke={isPositive ? "hsl(var(--bullish))" : "hsl(var(--bearish))"}
            strokeWidth="2"
          />
          <path
            d="M0,50 L50,45 L100,55 L150,30 L200,40 L250,25 L300,35 L350,20 L400,30 L400,100 L0,100 Z"
            fill={isPositive ? "hsl(var(--bullish))" : "hsl(var(--bearish))"}
            opacity="0.2"
          />
        </svg>
      </div>
      
      <div className="relative z-10">
        <h3 className="text-xs font-bold uppercase tracking-wider text-gray-600">TOTAL P&L</h3>
        <div className="mt-6">
          <motion.div
            key={dailyPnl}
            initial={{ scale: 0.8, opacity: 0 }}
            animate={{ scale: 1, opacity: 1 }}
            className={cn(
              "text-4xl font-black tabular-nums",
              isPositive ? "text-emerald-500" : "text-rose-500"
            )}
          >
            {isPositive ? '+' : ''}${dailyPnl.toFixed(2)}
          </motion.div>
          <p className="text-sm font-semibold text-gray-700 mt-3">24h Performance</p>
        </div>
      </div>
    </motion.div>
  )
}, (prevProps, nextProps) => {
  // Only re-render if P&L changed by more than $0.01
  return Math.abs(prevProps.dailyPnl - nextProps.dailyPnl) < 0.01
})

PnLHero.displayName = 'PnLHero'

const SentimentEngine = memo(() => {
  const [sentiment, _setSentiment] = useState(65) // 0 = Fear, 50 = Neutral, 100 = Greed
  void _setSentiment
  
  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: 0.1 }}
      className="glass-card p-6 col-span-4 "
    >
      <h3 className="section-header">MARKET SENTIMENT</h3>
      <div className="flex flex-col items-center justify-center mt-6">
        <SentimentGauge value={sentiment} size="lg" />
      </div>
    </motion.div>
  )
})

SentimentEngine.displayName = 'SentimentEngine'

const MarketTicker = memo(({ prices }: { prices: Record<string, { price: number; change: number }> }) => {
  const [prevPrices, setPrevPrices] = useState<Record<string, { price: number; change: number }>>({})
  
  const getPriceChange = (symbol: string, currentPrice: number) => {
    const prevPrice = prevPrices[symbol]?.price
    if (prevPrice === undefined) return null
    return currentPrice > prevPrice ? 'up' : currentPrice < prevPrice ? 'down' : 'neutral'
  }
  
  // Update previous prices when prices change
  useEffect(() => {
    setPrevPrices(prices)
  }, [prices])
  
  // Check if markets are closed (simplified logic)
  const isMarketClosed = Object.keys(prices).length === 0
  
  if (isMarketClosed) {
    return <MarketEmptyState />
  }
  
  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: 0.2 }}
      className="glass-card p-4 col-span-12"
    >
      <h3 className="section-header">MARKET TICKER</h3>
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-6 mt-4">
        {Object.entries(prices).length === 0 ? (
          <div className="col-span-full flex items-center justify-center py-8">
            <p className="text-sm text-muted-foreground">Waiting for market data...</p>
          </div>
        ) : (
          Object.entries(prices).map(([symbol, record], index) => {
            const priceChange = getPriceChange(symbol, record.price)
            return (
              <motion.div
                key={symbol}
                initial={{ opacity: 0, x: -20 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ delay: 0.3 + index * 0.05 }}
                className={cn(
                  "glass-card-hover p-3 cursor-pointer",
                  priceChange === 'up' && "price-flash-emerald",
                  priceChange === 'down' && "price-flash-rose"
                )}
              >
                <p className="text-[10px] font-medium uppercase tracking-wide text-muted-foreground">{symbol}</p>
                <p className="mt-1.5 data-value">
                  ${record.price.toFixed(2)}
                </p>
                <div className="mt-1">
                  <TrendChip 
                    trend={record.change >= 0 ? 'up' : 'down'}
                    value={`${Math.abs(record.change).toFixed(2)}%`}
                    size="sm"
                  />
                </div>
              </motion.div>
            )
          })
        )}
      </div>
    </motion.div>
  )
}, (prevProps, nextProps) => {
  // Custom comparison: only re-render if prices actually changed
  const prevSymbols = Object.keys(prevProps.prices)
  const nextSymbols = Object.keys(nextProps.prices)
  
  if (prevSymbols.length !== nextSymbols.length) return false
  
  return prevSymbols.every(symbol => {
    const prevPrice = prevProps.prices[symbol]?.price
    const nextPrice = nextProps.prices[symbol]?.price
    return Math.abs(prevPrice - nextPrice) < 0.001 // Only re-render if price changed significantly
  })
})

MarketTicker.displayName = 'MarketTicker'

const AgentStatusPulse = memo(({ agentLogs: _agentLogs }: { agentLogs: unknown[] }) => {
  const agents = [
    { name: 'Reasoning Agent', status: 'running', lastAction: 'Analyzed BTC trend' },
    { name: 'Execution Engine', status: 'running', lastAction: 'Placed SPY order' },
    { name: 'Learning Service', status: 'idle', lastAction: 'Processing trade data' },
    { name: 'IC Updater', status: 'idle', lastAction: 'Updated confidence model' },
  ]
  
  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: 0.3 }}
      className="glass-card p-6 col-span-6"
    >
      <h3 className="section-header">AGENT STATUS</h3>
      <div className="grid grid-cols-2 gap-4 mt-4">
        {agents.map((agent, index) => (
          <motion.div
            key={agent.name}
            initial={{ opacity: 0, scale: 0.9 }}
            animate={{ opacity: 1, scale: 1 }}
            transition={{ delay: 0.4 + index * 0.1 }}
            className="glass-card-hover p-4"
          >
            <div className="flex items-center justify-between mb-2">
              <span className="text-sm font-medium text-foreground">{agent.name}</span>
              <AgentStatusChip 
                status={agent.status as 'running' | 'idle' | 'error'}
                label={agent.status}
                size="sm"
              />
            </div>
            <p className="text-xs text-muted-foreground truncate">{agent.lastAction}</p>
          </motion.div>
        ))}
      </div>
    </motion.div>
  )
})

AgentStatusPulse.displayName = 'AgentStatusPulse'

const SystemHealthMetrics = memo(({ systemMetrics }: { systemMetrics: Array<{ metric_name?: string; value?: number }> }) => {
  const costToday = systemMetrics.find(m => m.metric_name === 'llm_cost_usd')?.value || 0
  const avgLag = systemMetrics
    .filter(m => m.metric_name?.startsWith('stream_lag:'))
    .reduce((sum, m) => sum + Number(m.value || 0), 0) / 
    Math.max(1, systemMetrics.filter(m => m.metric_name?.startsWith('stream_lag:')).length)
  
  const getSignalStrength = (lag: number) => {
    if (lag < 100) return { icon: SignalHigh, color: 'text-success', status: 'Excellent' }
    if (lag < 1000) return { icon: SignalMedium, color: 'text-warning', status: 'Good' }
    return { icon: SignalLow, color: 'text-error', status: 'Poor' }
  }
  
  const signalStatus = getSignalStrength(avgLag)
  const SignalIcon = signalStatus.icon
  
  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: 0.4 }}
      className="glass-card p-6 col-span-6"
    >
      <h3 className="section-header">SYSTEM HEALTH</h3>
      <div className="grid grid-cols-2 gap-6 mt-4">
        <ProTradingCard
          title="LLM Cost Today"
          value={`$${costToday.toFixed(2)}`}
          icon={Zap}
          size="sm"
          sparkle
        />
        <div className="flex flex-col justify-between">
          <div className="flex items-center justify-between mb-2">
            <span className="text-sm text-slate-400">Stream Lag</span>
            <SignalIcon className={`w-4 h-4 ${signalStatus.color}`} />
          </div>
          <div className="flex items-baseline gap-2">
            <span className="data-value text-slate-200">{Math.round(avgLag)}ms</span>
            <StatusChip
              status={avgLag < 100 ? 'success' : avgLag < 1000 ? 'warning' : 'error'}
              label={signalStatus.status}
              size="sm"
            />
          </div>
        </div>
      </div>
    </motion.div>
  )
})

SystemHealthMetrics.displayName = 'SystemHealthMetrics'

const KillSwitch = memo(({ killSwitchActive, onToggle }: { 
  killSwitchActive: boolean
  onToggle: () => void 
}) => {
  return (
    <AlertDialog>
      <AlertDialogTrigger asChild>
        <motion.button
          whileHover={{ scale: 1.02 }}
          whileTap={{ scale: 0.98 }}
          className={cn(
            "flex items-center gap-2 px-3 py-1.5 rounded-md text-sm font-medium transition-colors border",
            killSwitchActive 
              ? "bg-red-50 text-red-700 border-red-200 hover:bg-red-100 dark:bg-red-900/20 dark:text-red-400 dark:border-red-800/50"
              : "bg-slate-50 text-slate-700 border-slate-200 hover:bg-slate-100 dark:bg-slate-800 dark:text-slate-300 dark:border-slate-700"
          )}
        >
          <div className={cn(
            "w-2 h-2 rounded-full",
            killSwitchActive ? "bg-red-500" : "bg-amber-500"
          )} />
          {killSwitchActive ? 'STOP TRADING' : 'START TRADING'}
        </motion.button>
      </AlertDialogTrigger>
      <AlertDialogContent className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800">
        <AlertDialogHeader>
          <AlertDialogTitle className="text-slate-900 dark:text-white">
            {killSwitchActive ? 'Stop All Trading Activity?' : 'Start Trading System?'}
          </AlertDialogTitle>
          <AlertDialogDescription className="text-slate-500 dark:text-slate-400">
            {killSwitchActive 
              ? 'This will immediately halt all trading agents and cancel any pending orders.'
              : 'This will activate all trading agents and begin market analysis.'
            }
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel className="bg-slate-100 text-slate-700 hover:bg-slate-200 dark:bg-slate-800 dark:text-slate-300 dark:hover:bg-slate-700">
            Cancel
          </AlertDialogCancel>
          <AlertDialogAction
            onClick={onToggle}
            className={cn(
              "text-white font-medium",
              killSwitchActive ? "bg-red-600 hover:bg-red-700" : "bg-slate-900 hover:bg-slate-800"
            )}
          >
            {killSwitchActive ? 'Stop Trading' : 'Start Trading'}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  )
})

KillSwitch.displayName = 'KillSwitch'

const LogTerminal = memo(({ agentLogs, isExpanded: _isExpanded, onToggle: _onToggle }: {
  agentLogs: Array<Record<string, unknown>>
  isExpanded: boolean
  onToggle: () => void
}) => {
  // Convert agent logs to LogViewer format
  const logs = agentLogs.slice(0, 10).map((log, index) => {
    const timestamp = String(log.timestamp || Date.now())
    const action = typeof log.action === 'string' ? log.action : 'hold'
    const symbol = typeof log.symbol === 'string' ? log.symbol : 'UNKNOWN'
    const primaryEdge = typeof log.primary_edge === 'string' ? log.primary_edge : 'No edge description'
    const confidence = typeof log.confidence === 'number' ? log.confidence : 0
    const latencyMs = typeof log.latency_ms === 'number' ? log.latency_ms : 0
    const costUsd = typeof log.cost_usd === 'number' ? log.cost_usd : 0
    return {
      id: `log-${index}`,
      timestamp: new Date(timestamp).toLocaleTimeString(),
      level: (action === 'buy' || action === 'sell') ? 'success' as const : 'info' as const,
      message: `${action.toUpperCase()} ${symbol} - ${primaryEdge}`,
      details: `Confidence: ${(confidence * 100).toFixed(0)}% | Latency: ${latencyMs}ms | Cost: $${costUsd || '0.000'}`
    }
  })
  
  return (
    <LogViewer
      logs={logs}
      title="AGENT LOGS"
      maxHeight="300px"
      className="col-span-12"
    />
  )
})

LogTerminal.displayName = 'LogTerminal'

export function ObsidianDashboard() {
  const { 
    agentLogs, 
    killSwitchActive, 
    orders, 
    prices, 
    systemMetrics, 
    wsConnected 
  } = useCodexStore()

  const handleKillSwitch = async () => {
    try {
      const response = await fetch(`${API_BASE}/kill-switch`, { method: 'POST' })
      if (response.ok) {
        // Force refresh
        window.location.reload()
      }
    } catch (error) {
      console.error('Failed to toggle kill switch:', error)
    }
  }

  const dailyPnl = useMemo(() => 
    orders.reduce((sum, o) => sum + Number(o.pnl || 0), 0), 
    [orders]
  )

  return (
    <KillSwitchState isActive={killSwitchActive}>
      <div className="p-6 space-y-6">
        {/* Header */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-4">
            <div className="flex items-center gap-2 text-gray-600 dark:text-gray-400">
              <span>System</span>
              <span className="text-gray-500 dark:text-gray-500">/</span>
              <span className="bg-gray-900 dark:bg-white text-white dark:text-gray-900 px-3 py-1 rounded-md font-bold">Overview</span>
            </div>
            <div className="flex items-center gap-2">
              <motion.div
                className={cn(
                  "w-2 h-2 rounded-full",
                  wsConnected ? "bg-green-500" : "bg-red-500"
                )}
                animate={wsConnected ? {
                  scale: [1, 1.2, 1],
                  opacity: [1, 0.8, 1]
                } : {}}
                transition={{ duration: 2, repeat: Infinity }}
              />
              <span className="text-xs text-gray-500 dark:text-gray-500">
                {wsConnected ? 'LIVE' : 'OFFLINE'}
              </span>
            </div>
          </div>
          
          <KillSwitch 
            killSwitchActive={killSwitchActive} 
            onToggle={handleKillSwitch}
          />
        </div>

        {/* Bento Grid */}
        <div className="grid grid-cols-12 gap-4 auto-rows-min">
          {/* Row 1: P&L Hero + Sentiment */}
          <PnLHero dailyPnl={dailyPnl} />
          <SentimentEngine />
          
          {/* Row 2: Market Ticker */}
          <MarketTicker prices={prices} />
          
          {/* Row 3: Agent Status + System Health */}
          <AgentStatusPulse agentLogs={agentLogs} />
          <SystemHealthMetrics systemMetrics={systemMetrics} />
          
          {/* Row 4: Log Terminal */}
          <LogTerminal 
            agentLogs={agentLogs}
            isExpanded={true}
            onToggle={() => {}}
          />
        </div>
      </div>
    </KillSwitchState>
  )
}
