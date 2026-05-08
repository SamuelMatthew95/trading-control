'use client'

import { useCallback, useEffect, useRef, useState } from 'react'

export type FetchState = 'idle' | 'loading' | 'ok' | 'error'

export interface PollingFetchResult<T> {
  data: T | null
  state: FetchState
  error: Error | null
  refetch: () => Promise<void>
}

/**
 * Generic polling hook for REST endpoints.
 *
 * Calls `fetcher` immediately on mount and then every `intervalMs`.
 * Reruns from scratch when any element of `deps` changes (typical use:
 * `[wsConnected]` to retry on WebSocket reconnect).
 *
 * Errors are surfaced via `state === 'error'` and the `error` field — they
 * are NEVER swallowed.  Callers can opt to ignore them (e.g. legacy "non-fatal
 * polling failures") by inspecting state explicitly.
 */
export function usePollingFetch<T>(
  fetcher: () => Promise<T>,
  intervalMs: number,
  deps: unknown[] = [],
): PollingFetchResult<T> {
  const [data, setData] = useState<T | null>(null)
  const [state, setState] = useState<FetchState>('idle')
  const [error, setError] = useState<Error | null>(null)
  const fetcherRef = useRef(fetcher)
  fetcherRef.current = fetcher

  const run = useCallback(async () => {
    setState('loading')
    try {
      const result = await fetcherRef.current()
      setData(result)
      setState('ok')
      setError(null)
    } catch (err) {
      setError(err instanceof Error ? err : new Error(String(err)))
      setState('error')
    }
  }, [])

  useEffect(() => {
    void run()
    if (intervalMs <= 0) return
    const id = setInterval(() => {
      void run()
    }, intervalMs)
    return () => clearInterval(id)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [run, intervalMs, ...deps])

  return { data, state, error, refetch: run }
}
