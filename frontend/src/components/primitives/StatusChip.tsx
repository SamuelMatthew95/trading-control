import { cn } from '@/lib/utils'
import { STATE_TONE } from '@/lib/status/stateTone'
export function StatusChip({ status }: { status: string }) { const key=status.toLowerCase(); return <span className={cn('rounded px-2 py-0.5 text-xs font-semibold', STATE_TONE[key] ?? 'bg-slate-500/10 text-slate-500')}>{status}</span> }
