import { useEffect, useState } from 'react'
import axios from 'axios'

type Signal = {
  id: string
  priority: 'urgent' | 'review' | 'info'
  message: string
  action_label: string
  action_type: 'flag' | 'reinforce' | 'view_run' | 'dismiss'
}

export function SignalsSidebar() {
  const [open, setOpen] = useState(true)
  const [items, setItems] = useState<Signal[]>([])

  const load = async () => {
    const response = await axios.get('/signals')
    setItems(response.data.items || [])
  }

  useEffect(() => {
    load().catch(() => undefined)
    const timer = setInterval(() => load().catch(() => undefined), 60000)
    return () => clearInterval(timer)
  }, [])

  const dismiss = async (id: string) => {
    const previous = items
    setItems((current) => current.filter((signal) => signal.id !== id))
    try {
      await axios.post(`/signals/${id}/dismiss`)
    } catch {
      setItems(previous)
    }
  }

  if (!open) {
    return (
      <button
        className="fixed right-2 top-1/2 z-20 min-h-11 rounded-lg border border-slate-300 bg-white px-3 text-xs font-sans font-semibold text-slate-700 transition-colors hover:bg-slate-100 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200 dark:hover:bg-slate-800"
        onClick={() => setOpen(true)}
      >
        Signals
      </button>
    )
  }

  return (
    <aside className="fixed right-0 top-0 z-20 h-full w-72 overflow-y-auto border-l border-slate-200 bg-white p-3 dark:border-slate-800 dark:bg-slate-900">
      <div className="mb-3 flex items-center justify-between">
        <h3 className="text-sm font-sans font-bold uppercase tracking-widest text-slate-900 dark:text-slate-100">Signals</h3>
        <button className="min-h-11 min-w-11 rounded-lg text-slate-500 transition-colors hover:bg-slate-100 dark:text-slate-400 dark:hover:bg-slate-800" onClick={() => setOpen(false)}>×</button>
      </div>
      {(['urgent', 'review', 'info'] as const).map((priority) => (
        <section key={priority} className="mb-4">
          <h4 className="mb-2 text-xs font-sans font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">{priority}</h4>
          {items.filter((signal) => signal.priority === priority).map((signal) => (
            <div key={signal.id} className="mb-2 rounded-xl border border-slate-200 p-3 dark:border-slate-800">
              <p className="text-sm font-sans text-slate-700 dark:text-slate-300">{signal.message}</p>
              <button
                className="mt-2 min-h-11 rounded-lg border border-slate-200 px-3 text-xs font-sans font-semibold text-slate-600 transition-colors hover:bg-slate-100 dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800"
                onClick={() => dismiss(signal.id)}
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
