import { useMemo, useState } from 'react'
import { EmptyState } from '@/components/ui/empty-state'
import { Button } from '@/components/ui/button'
import { useSignals } from '@/hooks/useSignals'
import { signalsSidebarStyles as styles } from '@/components/dashboard/dashboardStyles'

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
        className={styles.toggleButton}
        variant="outline"
        size="sm"
        onClick={() => setOpen(true)}
      >
        Signals
      </Button>
    )
  }

  return (
    <aside className={styles.aside}>
      <div className={styles.header}>
        <h3 className={styles.title}>Signals</h3>
        <button className={styles.closeButton} onClick={() => setOpen(false)}>×</button>
      </div>
      {groupedSignals.map((group) => (
        <section key={group.priority} className={styles.section}>
          <h4 className={styles.sectionTitle}>{group.priority}</h4>
          {group.items.length === 0 ? (
            <EmptyState message={`No ${group.priority} signals`} />
          ) : (
            group.items.map((signal) => (
              <div key={signal.id} className={styles.signalCard}>
                <p className={styles.signalMessage}>{signal.message}</p>
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
