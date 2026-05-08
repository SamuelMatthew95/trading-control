'use client'

import { TradeFeedPanel } from './TradeFeedPanel'
import { AgentThoughtStream } from './AgentThoughtStream'
import { PositionsTable } from './PositionsTable'
import type { AgentLog, Position, TradeFeedItem } from '@/stores/useCodexStore'

interface TradingSectionProps {
  trades: TradeFeedItem[]
  agentLogs: AgentLog[]
  positions: Position[]
  onTraceClick: (traceId: string) => void
}

export function TradingSection({
  trades,
  agentLogs,
  positions,
  onTraceClick,
}: TradingSectionProps) {
  return (
    <div className="space-y-4">
      <TradeFeedPanel trades={trades} onTraceClick={onTraceClick} />
      <AgentThoughtStream logs={agentLogs} onTraceClick={onTraceClick} />
      <PositionsTable positions={positions} />
    </div>
  )
}
