import { cn } from '@/lib/utils'
import { getStateLabel, getStateTone } from '@/lib/status/stateTone'
export function StatusChip({ status }: { status: string }) { return <span className={cn('rounded px-2 py-0.5 text-xs font-semibold', getStateTone(status))}>{getStateLabel(status)}</span> }
