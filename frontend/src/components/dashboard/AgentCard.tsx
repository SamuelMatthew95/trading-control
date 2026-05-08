import { Activity, AlertTriangle, Bot } from 'lucide-react'

import { AgentView } from '@/types/dashboard'
import { TerminalCard, SectionHeader } from '@/components/terminal'
import { TONE_CLASSES } from '@/lib/state'
import { cn } from '@/lib/utils'
import { UI_TEXT } from '@/lib/constants/ui'

import { StatusBadge } from './StatusBadge'

export function AgentCard({ agent }: { agent: AgentView }) {
  return (
    <TerminalCard>
      <SectionHeader title={agent.name} icon={Bot} right={<StatusBadge status={agent.status} />} />
      <div className={cn('space-y-2', UI_TEXT.body)}>
        <p className="flex items-center gap-2">
          <Activity className={cn('h-4 w-4', TONE_CLASSES.info.text)} /> Current:{' '}
          {agent.current_task || 'Idle'}
        </p>
        <p>Last task: {agent.last_task || 'N/A'}</p>
        <p>
          Latency:{' '}
          {typeof agent.latency_ms === 'number' ? `${agent.latency_ms.toFixed(0)}ms` : 'N/A'}
        </p>
        {agent.error ? (
          <p className={cn('flex items-center gap-2', TONE_CLASSES.neg.text)}>
            <AlertTriangle className="h-4 w-4" /> {agent.error}
          </p>
        ) : null}
      </div>
    </TerminalCard>
  )
}
