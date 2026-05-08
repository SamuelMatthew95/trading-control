import { useCallback, useEffect, useState } from 'react'
import { apiFetch } from '@/lib/apiClient'

export interface SignalItem {
  id: string
  priority: 'urgent' | 'review' | 'info'
  message: string
  action_label: string
  action_type: 'flag' | 'reinforce' | 'view_run' | 'dismiss'
}

interface SignalsResponse {
  items?: SignalItem[]
}

export function useSignals() {
  const [items, setItems] = useState<SignalItem[]>([])

  const load = useCallback(async () => {
    const data = await apiFetch<SignalsResponse>('/signals')
    setItems(data.items ?? [])
  }, [])

  useEffect(() => {
    load().catch(() => undefined)
    const timer = setInterval(() => load().catch(() => undefined), 60_000)
    return () => clearInterval(timer)
  }, [load])

  const dismiss = useCallback(async (id: string) => {
    let dismissed: SignalItem | undefined
    setItems((current) => {
      dismissed = current.find((item) => item.id === id)
      return current.filter((item) => item.id !== id)
    })

    try {
      await apiFetch(`/signals/${id}/dismiss`, { method: 'POST' })
    } catch {
      if (dismissed) {
        setItems((current) => [dismissed as SignalItem, ...current])
      }
    }
  }, [])

  return { items, dismiss }
}
