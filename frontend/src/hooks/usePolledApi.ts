'use client'

import { useEffect, useState } from 'react'
import { apiFetch } from '@/lib/apiClient'

export interface PolledApiState<T> {
  /** Last successfully fetched payload — kept through transient failures. */
  data: T | null
  /** Last fetch error message, cleared on the next success. */
  error: string | null
  /** True once the first fetch has settled (success or failure). */
  loaded: boolean
}

/**
 * Canonical REST polling pattern for dashboard panels: fetch on mount,
 * refresh on an interval, keep the last good payload through transient
 * failures, and clean up on unmount. Extracted because every panel used to
 * hand-roll this same useEffect + setInterval + cancelled-flag dance.
 */
export function usePolledApi<T>(path: string, intervalMs: number): PolledApiState<T> {
  const [state, setState] = useState<PolledApiState<T>>({ data: null, error: null, loaded: false })

  useEffect(() => {
    let cancelled = false
    const load = async () => {
      try {
        const data = await apiFetch<T>(path)
        if (!cancelled) setState({ data, error: null, loaded: true })
      } catch (err) {
        if (!cancelled)
          setState((prev) => ({
            data: prev.data,
            error: err instanceof Error ? err.message : 'fetch_failed',
            loaded: true,
          }))
      }
    }
    load()
    const id = window.setInterval(load, intervalMs)
    return () => {
      cancelled = true
      window.clearInterval(id)
    }
  }, [path, intervalMs])

  return state
}
