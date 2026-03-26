'use client'

import { useEffect, useState } from 'react'
import { useCodexStore } from '@/stores/useCodexStore'
import { TrendingUp, TrendingDown } from 'lucide-react'
import { cn } from '@/lib/utils'

interface TickerData {
  symbol: string
  price: number
  change: number
  changePercent: number
  agentBias: 'long' | 'short' | 'neutral'
}

const TICKER_SYMBOLS = ['NVDA', 'SPY', 'AAPL', 'BTC', 'ETH', 'SOL']

export function LiveTicker() {
  const { prices } = useCodexStore()
  const [tickerData, setTickerData] = useState<TickerData[]>([])

  // Initialize ticker data with mock values if no real data available
  useEffect(() => {
    const mockData: TickerData[] = TICKER_SYMBOLS.map(symbol => {
      // Get agent bias from recent logs for this symbol
      const recentLogs = useCodexStore.getState().agentLogs.filter(log => 
        log.symbol === symbol && (log.action === 'buy' || log.action === 'sell')
      ).slice(0, 5)
      
      let agentBias: 'long' | 'short' | 'neutral' = 'neutral'
      if (recentLogs.length > 0) {
        const buyCount = recentLogs.filter(log => log.action === 'buy').length
        const sellCount = recentLogs.filter(log => log.action === 'sell').length
        if (buyCount > sellCount) agentBias = 'long'
        else if (sellCount > buyCount) agentBias = 'short'
      }

      return {
        symbol,
        price: prices[symbol]?.price || Math.random() * 1000 + 50,
        change: prices[symbol]?.change || (Math.random() - 0.5) * 20,
        changePercent: prices[symbol]?.change ? (prices[symbol].change / (prices[symbol].price - prices[symbol].change)) * 100 : (Math.random() - 0.5) * 5,
        agentBias
      }
    })
    setTickerData(mockData)
  }, [prices])

  return (
    <div className="bg-[#09090b] border-b border-[#27272a] overflow-hidden">
      <div className="flex items-center h-14">
        {/* Scrolling ticker - responsive with proper spacing */}
        <div className="flex items-center gap-4 animate-scroll whitespace-nowrap min-w-0 px-4">
          {tickerData.map((item, index) => (
            <div 
              key={item.symbol} 
              className="flex items-center gap-4 flex-shrink-0 border-r border-[#27272a] pr-4 last:border-r-0"
            >
              {/* Symbol */}
              <span className="text-sm sm:text-base font-bold text-white min-w-[3rem] font-['Inter']">
                {item.symbol}
              </span>
              
              {/* Price */}
              <span className="text-sm sm:text-base font-mono text-gray-300 min-w-[5rem] text-right font-['JetBrains_Mono']">
                ${item.price.toFixed(2)}
              </span>
              
              {/* 24h Delta */}
              <div className="flex items-center gap-2">
                {item.changePercent >= 0 ? (
                  <TrendingUp className="w-4 h-4 text-[#10b981]" />
                ) : (
                  <TrendingDown className="w-4 h-4 text-[#ef4444]" />
                )}
                <span className={cn(
                  "text-xs sm:text-sm font-mono font-['JetBrains_Mono']",
                  item.changePercent >= 0 ? "text-[#10b981]" : "text-[#ef4444]"
                )}>
                  {item.changePercent >= 0 ? '+' : ''}{item.changePercent.toFixed(2)}%
                </span>
              </div>

              {/* Agent Bias */}
              <div className="flex items-center gap-2">
                <span className="text-xs text-gray-500 font-['Inter']">Bias:</span>
                <span className={cn(
                  "text-xs font-bold px-3 py-1 rounded font-['Inter'] border",
                  item.agentBias === 'long' ? "bg-[#10b981]/20 text-[#10b981] border-[#10b981]/30" :
                  item.agentBias === 'short' ? "bg-[#ef4444]/20 text-[#ef4444] border-[#ef4444]/30" :
                  "bg-gray-500/20 text-gray-400 border-gray-500/30"
                )}>
                  {item.agentBias.toUpperCase()}
                </span>
              </div>
            </div>
          ))}
          
          {/* Duplicate for seamless scroll */}
          {tickerData.map((item, index) => (
            <div 
              key={`${item.symbol}-duplicate`} 
              className="flex items-center gap-4 flex-shrink-0 border-r border-[#27272a] pr-4 last:border-r-0"
            >
              {/* Symbol */}
              <span className="text-sm sm:text-base font-bold text-white min-w-[3rem] font-['Inter']">
                {item.symbol}
              </span>
              
              {/* Price */}
              <span className="text-sm sm:text-base font-mono text-gray-300 min-w-[5rem] text-right font-['JetBrains_Mono']">
                ${item.price.toFixed(2)}
              </span>
              
              {/* 24h Delta */}
              <div className="flex items-center gap-2">
                {item.changePercent >= 0 ? (
                  <TrendingUp className="w-4 h-4 text-[#10b981]" />
                ) : (
                  <TrendingDown className="w-4 h-4 text-[#ef4444]" />
                )}
                <span className={cn(
                  "text-xs sm:text-sm font-mono font-['JetBrains_Mono']",
                  item.changePercent >= 0 ? "text-[#10b981]" : "text-[#ef4444]"
                )}>
                  {item.changePercent >= 0 ? '+' : ''}{item.changePercent.toFixed(2)}%
                </span>
              </div>

              {/* Agent Bias */}
              <div className="flex items-center gap-2">
                <span className="text-xs text-gray-500 font-['Inter']">Bias:</span>
                <span className={cn(
                  "text-xs font-bold px-3 py-1 rounded font-['Inter'] border",
                  item.agentBias === 'long' ? "bg-[#10b981]/20 text-[#10b981] border-[#10b981]/30" :
                  item.agentBias === 'short' ? "bg-[#ef4444]/20 text-[#ef4444] border-[#ef4444]/30" :
                  "bg-gray-500/20 text-gray-400 border-gray-500/30"
                )}>
                  {item.agentBias.toUpperCase()}
                </span>
              </div>
            </div>
          ))}
        </div>
      </div>
      
      <style jsx>{`
        @keyframes scroll {
          0% {
            transform: translateX(0);
          }
          100% {
            transform: translateX(-50%);
          }
        }
        
        .animate-scroll {
          animation: scroll 25s linear infinite;
        }
        
        @media (max-width: 640px) {
          .animate-scroll {
            animation: scroll 20s linear infinite;
          }
        }
      `}</style>
    </div>
  )
}
