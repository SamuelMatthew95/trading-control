'use client'

import { cn } from '@/lib/utils'
import { usePrices } from '@/hooks/useRealtimeData'

const SYMBOLS = ['BTC/USD', 'ETH/USD', 'SOL/USD', 'AAPL', 'TSLA', 'SPY'] as const

function PriceCardSkeleton() {
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4 transition-colors duration-150 hover:border-slate-300 dark:border-slate-800 dark:bg-slate-900 dark:hover:border-slate-600 sm:p-5">
      <div className="mb-1 h-3 w-16 animate-pulse rounded bg-slate-200 dark:bg-slate-700" />
      <div className="mt-1 h-6 w-24 animate-pulse rounded bg-slate-200 dark:bg-slate-700" />
      <div className="mt-2 flex items-center justify-between">
        <div className="h-3 w-16 animate-pulse rounded bg-slate-200 dark:bg-slate-700" />
        <div className="h-3 w-12 animate-pulse rounded bg-slate-200 dark:bg-slate-700" />
      </div>
    </div>
  )
}

function ConnectionStatus({ status }: { status: 'live' | 'reconnecting' | 'offline' }) {
  const getStatusConfig = () => {
    switch (status) {
      case 'live':
        return {
          dot: 'bg-green-500',
          text: 'Live',
          textColor: 'text-green-700 dark:text-green-400'
        }
      case 'reconnecting':
        return {
          dot: 'bg-amber-500',
          text: 'Reconnecting...',
          textColor: 'text-amber-700 dark:text-amber-400'
        }
      case 'offline':
        return {
          dot: 'bg-red-500',
          text: 'Offline',
          textColor: 'text-red-700 dark:text-red-400'
        }
    }
  }

  const config = getStatusConfig()

  return (
    <div className="flex items-center gap-2">
      <div className={cn('h-2 w-2 rounded-full', config.dot)} />
      <span className={cn('text-xs font-medium', config.textColor)}>{config.text}</span>
    </div>
  )
}

function FreshnessDot({ timestamp }: { timestamp: number }) {
  const now = Date.now() / 1000
  const age = now - timestamp
  
  let dotColor = 'bg-red-500'
  if (age < 15) {
    dotColor = 'bg-green-500'
  } else if (age < 60) {
    dotColor = 'bg-amber-500'
  }

  return (
    <div className={cn('h-2 w-2 rounded-full', dotColor)} />
  )
}

export function LiveMarketPrices() {
  const { 
    prices, 
    isLoading, 
    error, 
    connectionStatus, 
    lastUpdated 
  } = usePrices()

  if (error && !isLoading) {
    return (
      <div className="space-y-4">
        <div className="flex items-center justify-between">
          <h3 className="text-xs font-semibold uppercase tracking-widest font-sans text-slate-500 dark:text-slate-400">
            Live Market Prices
          </h3>
          <ConnectionStatus status={connectionStatus} />
        </div>
        <div className="rounded-lg border border-red-200 bg-red-50 p-4 dark:border-red-800 dark:bg-red-950/50">
          <div className="flex items-center gap-2">
            <div className="text-red-500">
              <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
            </div>
            <div>
              <p className="text-sm font-medium text-red-800 dark:text-red-200">Connection Error</p>
              <p className="text-xs text-red-600 dark:text-red-400">{error}</p>
            </div>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="text-xs font-semibold uppercase tracking-widest font-sans text-slate-500 dark:text-slate-400">
          Live Market Prices
        </h3>
        <div className="flex items-center gap-3">
          {lastUpdated && (
            <span className="text-xs text-slate-500 dark:text-slate-400">
              Updated {new Date(lastUpdated).toLocaleTimeString()}
            </span>
          )}
          <ConnectionStatus status={connectionStatus} />
        </div>
      </div>

      {connectionStatus === 'reconnecting' && (
        <div className="flex items-center gap-2 rounded-lg border border-amber-200 bg-amber-50 p-2 dark:border-amber-800 dark:bg-amber-950/50">
          <div className="h-2 w-2 animate-pulse rounded-full bg-amber-500" />
          <span className="text-xs text-amber-700 dark:text-amber-400">Reconnecting...</span>
        </div>
      )}

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {isLoading && Object.keys(prices).length === 0 ? (
          Array.from({ length: 6 }).map((_, index) => (
            <PriceCardSkeleton key={index} />
          ))
        ) : (
          SYMBOLS.map((symbol) => {
            const priceData = prices[symbol]
            
            if (!priceData && !isLoading) {
              return (
                <div key={symbol} className="rounded-xl border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900 sm:p-5">
                  <div className="mb-1 flex items-center justify-between">
                    <span className="text-xs font-semibold uppercase tracking-widest font-sans text-slate-500 dark:text-slate-400">
                      {symbol}
                    </span>
                    <div className="h-2 w-2 rounded-full bg-red-500" />
                  </div>
                  <div className="text-2xl font-black font-mono tabular-nums text-slate-950 dark:text-slate-100">
                    --
                  </div>
                  <div className="mt-2 flex items-center justify-between">
                    <span className="text-xs text-slate-500 dark:text-slate-400">No data</span>
                  </div>
                </div>
              )
            }

            if (!priceData) {
              return <PriceCardSkeleton key={symbol} />
            }

            const isPositive = priceData.change >= 0
            const changeColor = isPositive ? 'text-green-600 dark:text-green-400' : 'text-red-600 dark:text-red-400'
            
            return (
              <div 
                key={symbol} 
                className="rounded-xl border border-slate-200 bg-white p-4 transition-all duration-150 hover:border-slate-300 dark:border-slate-800 dark:bg-slate-900 dark:hover:border-slate-600 sm:p-5"
              >
                <div className="mb-1 flex items-center justify-between">
                  <span className="text-xs font-semibold uppercase tracking-widest font-sans text-slate-500 dark:text-slate-400">
                    {symbol}
                  </span>
                  <FreshnessDot timestamp={priceData.ts} />
                </div>
                <div className="text-2xl font-black font-mono tabular-nums text-slate-950 dark:text-slate-100">
                  ${priceData.price.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                </div>
                <div className="mt-2 flex items-center justify-between">
                  <div className={cn('text-sm font-mono tabular-nums', changeColor)}>
                    {isPositive ? '+' : ''}{priceData.change.toFixed(2)}
                  </div>
                  <div className={cn('text-xs font-mono tabular-nums', changeColor)}>
                    ({isPositive ? '+' : ''}{priceData.pct.toFixed(2)}%)
                  </div>
                </div>
              </div>
            )
          })
        )}
      </div>
    </div>
  )
}
