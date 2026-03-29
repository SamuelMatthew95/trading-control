'use client'
import { create } from 'zustand'
import { useEffect, useRef } from 'react'

// Types for the new API responses
export interface AgentStatus {
  status: 'ACTIVE' | 'WAITING' | 'STALE' | 'ERROR' | 'OFFLINE'
  last_event: string
  event_count: number
  last_seen: number
  seconds_ago: number
}

export interface PriceData {
  price: number
  change: number
  pct: number
  ts: number
}

export interface PriceState {
  prices: Record<string, PriceData>
  isLoading: boolean
  error: string | null
  connectionStatus: 'live' | 'reconnecting' | 'offline'
  lastUpdated: number | null
  fetchPrices: () => Promise<void>
  startSSE: () => void
  stopSSE: () => void
  setConnectionStatus: (status: 'live' | 'reconnecting' | 'offline') => void
  setError: (error: string | null) => void
}

export interface AgentState {
  agents: Record<string, AgentStatus>
  isLoading: boolean
  error: string | null
  lastUpdated: number | null
  fetchAgents: () => Promise<void>
  startPolling: () => void
  stopPolling: () => void
}

// Price store with SSE support
export const usePriceStore = create<PriceState>((set, _get) => {
  const eventSourceRef = useRef<EventSource | null>(null)
  const reconnectTimeoutRef = useRef<NodeJS.Timeout | null>(null)

  const startSSE = () => {
    // Stop existing connection
    if (eventSourceRef.current) {
      eventSourceRef.current.close()
    }
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current)
    }

    const baseUrl = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'
    const eventSource = new EventSource(`${baseUrl}/api/v1/prices/stream`)
    eventSourceRef.current = eventSource

    eventSource.onopen = () => {
      if (process.env.NODE_ENV === 'development') {
        console.log('SSE connection opened')
      }
      set({ connectionStatus: 'live', error: null })
    }

    eventSource.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data)
        
        if (data.type === 'connected') {
          set({ connectionStatus: 'live' })
          return
        }
        
        if (data.type === 'error') {
          set({ error: data.message })
          return
        }

        // Update price data
        set((state) => ({
          prices: {
            ...state.prices,
            [data.symbol]: {
              price: data.price,
              change: data.change,
              pct: data.pct,
              ts: Date.now() / 1000
            }
          },
          lastUpdated: Date.now(),
          connectionStatus: 'live',
          error: null
        }))
      } catch (error) {
        if (process.env.NODE_ENV === 'development') {
          console.error('Error parsing SSE message:', error)
        }
      }
    }

    eventSource.onerror = () => {
      if (process.env.NODE_ENV === 'development') {
        console.log('SSE connection error')
      }
      eventSource.close()
      set({ connectionStatus: 'reconnecting' })
      
      // Reconnect after 3 seconds
      reconnectTimeoutRef.current = setTimeout(() => {
        if (process.env.NODE_ENV === 'development') {
          console.log('Attempting to reconnect SSE...')
        }
        startSSE()
      }, 3000)
    }
  }

  const stopSSE = () => {
    if (eventSourceRef.current) {
      eventSourceRef.current.close()
      eventSourceRef.current = null
    }
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current)
      reconnectTimeoutRef.current = null
    }
    set({ connectionStatus: 'offline' })
  }

  const fetchPrices = async () => {
    try {
      set({ isLoading: true, error: null })
      const baseUrl = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'
      const response = await fetch(`${baseUrl}/api/v1/prices`)
      
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${response.statusText}`)
      }
      
      const data = await response.json()
      set({ 
        prices: data, 
        isLoading: false, 
        lastUpdated: Date.now() 
      })
    } catch (error) {
      if (process.env.NODE_ENV === 'development') {
        console.error('Error fetching prices:', error)
      }
      set({ 
        error: error instanceof Error ? error.message : 'Failed to fetch prices', 
        isLoading: false 
      })
    }
  }

  return {
    prices: {},
    isLoading: false,
    error: null,
    connectionStatus: 'offline',
    lastUpdated: null,
    fetchPrices,
    startSSE,
    stopSSE,
    setConnectionStatus: (status) => set({ connectionStatus: status }),
    setError: (error) => set({ error })
  }
})

// Agent store with polling
export const useAgentStore = create<AgentState>((set, _get) => {
  const intervalRef = useRef<NodeJS.Timeout | null>(null)

  const fetchAgents = async () => {
    try {
      set({ isLoading: true, error: null })
      const baseUrl = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'
      const response = await fetch(`${baseUrl}/api/v1/agents/status`)
      
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${response.statusText}`)
      }
      
      const data = await response.json()
      set({ 
        agents: data, 
        isLoading: false, 
        lastUpdated: Date.now() 
      })
    } catch (error) {
      if (process.env.NODE_ENV === 'development') {
        console.error('Error fetching agents:', error)
      }
      set({ 
        error: error instanceof Error ? error.message : 'Failed to fetch agents', 
        isLoading: false 
      })
    }
  }

  const startPolling = () => {
    // Initial fetch
    fetchAgents()
    
    // Poll every 10 seconds
    intervalRef.current = setInterval(fetchAgents, 10000)
  }

  const stopPolling = () => {
    if (intervalRef.current) {
      clearInterval(intervalRef.current)
      intervalRef.current = null
    }
  }

  return {
    agents: {},
    isLoading: false,
    error: null,
    lastUpdated: null,
    fetchAgents,
    startPolling,
    stopPolling
  }
})

// Hooks for component usage
export const usePrices = () => {
  const store = usePriceStore()
  
  useEffect(() => {
    // Fetch initial prices
    store.fetchPrices()
    
    // Start SSE connection
    store.startSSE()
    
    // Cleanup on unmount
    return () => {
      store.stopSSE()
    }
  }, [store])
  
  return store
}

export const useAgents = () => {
  const store = useAgentStore()
  
  useEffect(() => {
    // Start polling
    store.startPolling()
    
    // Cleanup on unmount
    return () => {
      store.stopPolling()
    }
  }, [store])
  
  return store
}
