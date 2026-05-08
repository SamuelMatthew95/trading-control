import { useMemo, useState } from 'react'
import { EmptyState } from '@/components/ui/empty-state'
import { Button } from '@/components/ui/button'
import { useSignals } from '@/hooks/useSignals'

const PRIORITIES = ['urgent', 'review', 'info'] as const

export function SignalsSidebar() {
  const [open, setOpen] = useState(true)
  const { items, dismiss } = useSignals()

  const groupedSignals = useMemo(() => {
    return PRIORITIES.map((priority) => ({
      priority,
      items: items.filter((signal) => signal.priority === priority),
    }))
  }, [items])

  if (!open) {
    return (
      <Button
        className="fixed right-2 top-1/2 z-20"
        variant="outline"
        size="sm"
        onClick={() => setOpen(true)}
      >
        Signals
      </Button>
    )
  }

  return (
    <aside className="fixed right-0 top-0 z-20 h-full w-72 overflow-y-auto border-l border-slate-200 bg-white p-3 dark:border-slate-800 dark:bg-slate-900">
      <div className="mb-3 flex items-center justify-between">
        <h3 className="text-sm font-sans font-bold uppercase tracking-widest text-slate-900 dark:text-slate-100">Signals</h3>
        <button className="min-h-11 min-w-11 rounded-lg text-slate-500 transition-colors hover:bg-slate-100 dark:text-slate-400 dark:hover:bg-slate-800" onClick={() => setOpen(false)}>×</button>
      </div>
      {groupedSignals.map((group) => (
        <section key={group.priority} className="mb-4">
          <h4 className="mb-2 text-xs font-sans font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">{group.priority}</h4>
          {group.items.length === 0 ? (
            <EmptyState message={`No ${group.priority} signals`} />
          ) : (
            group.items.map((signal) => (
              <div key={signal.id} className="mb-2 rounded-xl border border-slate-200 p-3 dark:border-slate-800">
                <p className="text-sm font-sans text-slate-700 dark:text-slate-300">{signal.message}</p>
                <Button className="mt-2" variant="outline" size="sm" onClick={() => dismiss(signal.id)}>
                  {signal.action_label}
                </Button>
              </div>
            ))
          )}
        </section>
      ))}
    </aside>
  )
}
