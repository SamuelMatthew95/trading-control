import { useCallback, useEffect, useState } from 'react'
import { apiFetch } from '@/lib/apiClient'

type Signal = {
  id: string
  priority: 'urgent' | 'review' | 'info'
  message: string
  action_label: string
  action_type: 'flag' | 'reinforce' | 'view_run' | 'dismiss'
}

interface SignalsResponse {
  items?: Signal[]
}

export function SignalsSidebar() {
  const [open, setOpen] = useState(true)
  const [items, setItems] = useState<Signal[]>([])

  const load = useCallback(async () => {
    try {
      const data = await apiFetch<SignalsResponse>('/signals')
      setItems(data.items ?? [])
    } catch {
      // Non-fatal: leave the previous list in place so a transient backend
      // outage does not flash an empty sidebar.
    }
  }, [])

  useEffect(() => {
    void load()
    const timer = setInterval(() => void load(), 60000)
    return () => clearInterval(timer)
  }, [load])

  const dismiss = async (id: string) => {
    // Optimistic remove. On failure re-insert just this one signal rather than
    // restoring the whole snapshot, preserving anything load() added during await.
    const dismissed = items.find((s) => s.id === id)
    setItems((current) => current.filter((s) => s.id !== id))
    const rollback = () => {
      if (dismissed) setItems((current) => [dismissed, ...current])
    }
    try {
      await apiFetch(`/signals/${id}/dismiss`, { method: 'POST' })
    } catch {
      rollback()
    }
  }

  if (!open) {
    return (
      <button
        className="fixed right-2 top-1/2 z-20 min-h-11 rounded-[6px] border border-slate-300 bg-white px-3 text-xs font-semibold text-slate-700 transition-colors hover:bg-slate-100 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200 dark:hover:bg-slate-800"
        onClick={() => setOpen(true)}
      >
        Signals
      </button>
    )
  }

  return (
    <aside className="fixed right-0 top-0 z-20 h-full w-72 overflow-y-auto border-l border-slate-200 bg-white p-3 dark:border-slate-800 dark:bg-slate-900">
      <div className="mb-3 flex items-center justify-between">
        <h3 className="text-sm font-bold uppercase tracking-widest text-slate-900 dark:text-slate-100">
          Signals
        </h3>
        <button
          className="min-h-11 min-w-11 rounded-[6px] text-slate-500 transition-colors hover:bg-slate-100 dark:text-slate-400 dark:hover:bg-slate-800"
          onClick={() => setOpen(false)}
        >
          ×
        </button>
      </div>
      {(['urgent', 'review', 'info'] as const).map((priority) => (
        <section key={priority} className="mb-4">
          <h4 className="mb-2 text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">
            {priority}
          </h4>
          {items
            .filter((signal) => signal.priority === priority)
            .map((signal) => (
              <div key={signal.id} className="mb-2 rounded-[6px] border border-slate-200 p-3 dark:border-slate-800">
                <p className="text-sm text-slate-700 dark:text-slate-300">{signal.message}</p>
                <button
                  className="mt-2 min-h-11 rounded-[6px] border border-slate-200 px-3 text-xs font-semibold text-slate-600 transition-colors hover:bg-slate-100 dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800"
                  onClick={() => void dismiss(signal.id)}
                >
                  {signal.action_label}
                </button>
              </div>
            ))}
        </section>
      ))}
    </aside>
  )
}
