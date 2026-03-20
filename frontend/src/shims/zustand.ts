'use client'
import { useSyncExternalStore } from 'react'

type Setter<T> = (partial: Partial<T> | ((state: T) => Partial<T>)) => void

export function create<T extends Record<string, any>>(initializer: (set: Setter<T>, get: () => T) => T) {
  let state: T
  const listeners = new Set<() => void>()
  const get = () => state
  const set: Setter<T> = (partial) => {
    const patch = typeof partial === 'function' ? partial(state) : partial
    state = { ...state, ...patch }
    listeners.forEach((l) => l())
  }
  state = initializer(set, get)
  const subscribe = (listener: () => void) => { listeners.add(listener); return () => listeners.delete(listener) }
  function useStore<U = T>(selector?: (state: T) => U): U {
    return useSyncExternalStore(subscribe, () => (selector ? selector(state) : (state as unknown as U)), () => (selector ? selector(state) : (state as unknown as U)))
  }
  ;(useStore as any).getState = get
  ;(useStore as any).setState = set
  return useStore as typeof useStore & { getState: () => T; setState: Setter<T> }
}
