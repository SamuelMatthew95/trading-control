'use client'

import { memo, useMemo } from 'react'
import { cn } from '@/lib/utils'

type AgentLogRecord = Record<string, unknown>

type GroupedLog = {
  key: string
  agentType: string
  message: string
  latest: AgentLogRecord
  count: number
  duplicates: AgentLogRecord[]
}

function canonicalType(value: string): string {
  return value.trim().toUpperCase().replace(/[\s-]+/g, '_')
}

function badgeStyle(agentType: string): string {
  const canonical = canonicalType(agentType)
  if (canonical.includes('REASONING')) return 'bg-blue-500/15 text-blue-400 border border-blue-500/40'
  if (canonical.includes('SIGNAL')) return 'bg-purple-500/15 text-purple-400 border border-purple-500/40'
  if (canonical.includes('EXECUTION')) return 'bg-emerald-500/15 text-emerald-400 border border-emerald-500/40'
  return 'bg-slate-500/15 text-slate-300 border border-slate-500/40'
}

function formatTimestamp(value: unknown): string {
  if (!value) return '--:--:--'
  const date = new Date(String(value))
  if (Number.isNaN(date.getTime())) return '--:--:--'
  return date.toLocaleTimeString()
}

function groupLogs(logs: AgentLogRecord[], formatMessage: (raw: unknown) => string): GroupedLog[] {
  const grouped: GroupedLog[] = []
  for (const entry of logs) {
    const rawType = String(entry.agent_type ?? entry.agent_name ?? entry.agent ?? 'Unknown Agent')
    const agentType = rawType.trim() || 'Unknown Agent'
    const message = formatMessage(entry.message ?? entry.summary ?? entry.primary_edge)
    const signature = `${canonicalType(agentType)}::${message.toLowerCase().trim()}`
    const last = grouped[grouped.length - 1]

    if (last && last.key === signature) {
      last.count += 1
      last.duplicates.push(entry)
      last.latest = entry
      continue
    }

    grouped.push({
      key: signature,
      agentType,
      message,
      latest: entry,
      count: 1,
      duplicates: [],
    })
  }
  return grouped
}

export const AgentStream = memo(function AgentStream({
  logs,
  formatMessage,
}: {
  logs: AgentLogRecord[]
  formatMessage: (raw: unknown) => string
}) {
  const grouped = useMemo(() => groupLogs(logs.slice(-25).reverse(), formatMessage), [logs, formatMessage])

  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900 p-4 sm:p-5">
      <div className="mb-3 flex items-center justify-between">
        <p className="text-xs font-semibold uppercase tracking-widest text-slate-400">Agent Thought Stream</p>
        <div className="flex items-center gap-2">
          <span className="h-2 w-2 animate-pulse rounded-full bg-emerald-500" />
          <span className="text-xs text-slate-400">LIVE</span>
        </div>
      </div>

      {grouped.length === 0 ? (
        <div className="space-y-2">
          {Array.from({ length: 6 }).map((_, index) => (
            <div key={index} className="h-8 rounded bg-slate-800/70" />
          ))}
        </div>
      ) : (
        <div className="max-h-[36rem] space-y-2 overflow-y-auto">
          {grouped.map((group, index) => (
            <div key={`${group.key}-${index}`} className="border-t border-slate-800 py-2 first:border-t-0">
              <div className="mb-1 flex flex-wrap items-center gap-2">
                <span className={cn('rounded px-2 py-0.5 text-xs font-semibold', badgeStyle(group.agentType))}>{group.agentType}</span>
                <span className="text-xs text-slate-400">{formatTimestamp(group.latest.timestamp ?? group.latest.created_at)}</span>
                {group.count > 1 ? (
                  <details className="text-xs text-slate-400">
                    <summary className="cursor-pointer list-none rounded bg-slate-800 px-2 py-0.5 hover:bg-slate-700">+{group.count - 1} similar events</summary>
                    <div className="mt-1 space-y-1 border-l border-slate-700 pl-2">
                      {group.duplicates.slice(0, 8).map((dup, duplicateIndex) => (
                        <p key={duplicateIndex}>{formatTimestamp(dup.timestamp ?? dup.created_at)}</p>
                      ))}
                    </div>
                  </details>
                ) : null}
              </div>
              <p className="text-sm text-slate-300">{group.message}</p>
            </div>
          ))}
        </div>
      )}
    </div>
  )
})
