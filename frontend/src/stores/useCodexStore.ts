'use client'
import { create } from 'zustand'

// Type definitions for production safety
type DashboardData = {
  system_metrics?: any[]
  orders?: any[]
  agent_logs?: any[]
  learning_events?: any[]
  risk_alerts?: any[]
  signals?: any[]
  positions?: any[]
  prices?: Record<string, { price: number; change: number }>
  timestamp: string
}

type PriceRecord = Record<string, { price: number; change: number }>

type CodexState = {
  prices: PriceRecord
  orders: any[]
  positions: any[]
  signals: any[]
  agentLogs: any[]
  riskAlerts: any[]
  learningEvents: any[]
  systemMetrics: any[]
  dashboardData: DashboardData | null
  isLoading: boolean
  regime: string
  killSwitchActive: boolean
  wsConnected: boolean
  // Individual setters
  updatePrice: (symbol: string, price: number, change: number) => void
  addSignal: (signal: any) => void
  addOrder: (order: any) => void
  updateOrder: (order: any) => void
  addAgentLog: (log: any) => void
  addRiskAlert: (alert: any) => void
  addLearningEvent: (event: any) => void
  addSystemMetric: (metric: any) => void
  setDashboardData: (data: DashboardData | null) => void
  setLoading: (loading: boolean) => void
  setRegime: (regime: string) => void
  setKillSwitch: (active: boolean) => void
  setWsConnected: (connected: boolean) => void
  // Production-grade bulk operations
  hydrateDashboard: (data: DashboardData) => void
  bulkUpdate: (updates: Partial<CodexState>) => void
}

export const useCodexStore = create<CodexState>((set, get) => ({
  prices: {}, 
  orders: [], 
  positions: [], 
  signals: [],
  agentLogs: [], 
  riskAlerts: [], 
  learningEvents: [], 
  systemMetrics: [],
  dashboardData: null, 
  isLoading: true,
  regime: 'neutral', 
  killSwitchActive: false, 
  wsConnected: false,
  
  // Individual setters (keep for compatibility)
  updatePrice: (symbol, price, change) => set((state) => ({ 
    prices: { ...state.prices, [symbol]: { price, change } } 
  })),
  addSignal: (signal) => set((state) => ({ 
    signals: [signal, ...state.signals].slice(0, 50) 
  })),
  addOrder: (order) => set((state) => ({ 
    orders: [order, ...state.orders].slice(0, 100) 
  })),
  updateOrder: (order) => set((state) => ({ 
    orders: state.orders.some((e) => e.order_id === order.order_id) 
      ? state.orders.map((e) => e.order_id === order.order_id ? { ...e, ...order } : e)
      : [order, ...state.orders].slice(0, 100)
  })),
  addAgentLog: (log) => set((state) => ({ 
    agentLogs: [log, ...state.agentLogs].slice(0, 100) 
  })),
  addRiskAlert: (alert) => set((state) => ({ 
    riskAlerts: [alert, ...state.riskAlerts].slice(0, 50) 
  })),
  addLearningEvent: (event) => set((state) => ({ 
    learningEvents: [event, ...state.learningEvents].slice(0, 50) 
  })),
  addSystemMetric: (metric) => set((state) => ({ 
    systemMetrics: [metric, ...state.systemMetrics].slice(0, 100) 
  })),
  setDashboardData: (data) => set({ dashboardData: data }),
  setLoading: (isLoading) => set({ isLoading }),
  setRegime: (regime) => set({ regime }),
  setKillSwitch: (killSwitchActive) => set({ killSwitchActive }),
  setWsConnected: (wsConnected) => set({ wsConnected }),
  
  // Production-grade bulk operations
  hydrateDashboard: (data: DashboardData) => {
    const state = get()
    
    // Atomic bulk update to prevent re-render thrashing
    set((currentState) => {
      const updates: Partial<CodexState> = {
        dashboardData: data,
        isLoading: false // Only set loading false after successful hydration
      }
      
      // Batch all updates in a single transaction
      if (data.system_metrics) {
        updates.systemMetrics = [
          ...data.system_metrics, 
          ...currentState.systemMetrics
        ].slice(0, 100)
      }
      
      if (data.orders) {
        updates.orders = [
          ...data.orders,
          ...currentState.orders.filter(order => 
            !data.orders?.some(newOrder => newOrder.order_id === order.order_id)
          )
        ].slice(0, 100)
      }
      
      if (data.agent_logs) {
        updates.agentLogs = [
          ...data.agent_logs,
          ...currentState.agentLogs.filter(log => 
            !data.agent_logs?.some(newLog => newLog.id === log.id)
          )
        ].slice(0, 100)
      }
      
      if (data.learning_events) {
        updates.learningEvents = [
          ...data.learning_events,
          ...currentState.learningEvents.filter(event => 
            !data.learning_events?.some(newEvent => newEvent.id === event.id)
          )
        ].slice(0, 50)
      }
      
      if (data.risk_alerts) {
        updates.riskAlerts = [
          ...data.risk_alerts,
          ...currentState.riskAlerts.filter(alert => 
            !data.risk_alerts?.some(newAlert => newAlert.id === alert.id)
          )
        ].slice(0, 50)
      }
      
      if (data.signals) {
        updates.signals = [
          ...data.signals,
          ...currentState.signals.filter(signal => 
            !data.signals?.some(newSignal => newSignal.id === signal.id)
          )
        ].slice(0, 50)
      }
      
      if (data.positions) {
        updates.positions = data.positions
      }
      
      if (data.prices) {
        updates.prices = { ...currentState.prices, ...data.prices }
      }
      
      return updates
    })
  },
  
  bulkUpdate: (updates: Partial<CodexState>) => {
    set(updates)
  }
}))
