'use client'

import { create } from 'zustand'

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
  regime: string
  killSwitchActive: boolean
  wsConnected: boolean
  updatePrice: (symbol: string, price: number, change: number) => void
  addSignal: (signal: any) => void
  addOrder: (order: any) => void
  updateOrder: (order: any) => void
  addAgentLog: (log: any) => void
  addRiskAlert: (alert: any) => void
  addLearningEvent: (event: any) => void
  addSystemMetric: (metric: any) => void
  setRegime: (regime: string) => void
  setKillSwitch: (active: boolean) => void
  setWsConnected: (connected: boolean) => void
}

export const useCodexStore = create<CodexState>((set) => ({
  prices: {},
  orders: [],
  positions: [],
  signals: [],
  agentLogs: [],
  riskAlerts: [],
  learningEvents: [],
  systemMetrics: [],
  regime: 'neutral',
  killSwitchActive: false,
  wsConnected: false,
  updatePrice: (symbol, price, change) =>
    set((state) => ({ prices: { ...state.prices, [symbol]: { price, change } } })),
  addSignal: (signal) => set((state) => ({ signals: [signal, ...state.signals].slice(0, 50) })),
  addOrder: (order) => set((state) => ({ orders: [order, ...state.orders].slice(0, 100) })),
  updateOrder: (order) =>
    set((state) => ({
      orders: state.orders.some((existing) => existing.order_id === order.order_id)
        ? state.orders.map((existing) => existing.order_id === order.order_id ? { ...existing, ...order } : existing)
        : [order, ...state.orders].slice(0, 100),
    })),
  addAgentLog: (log) => set((state) => ({ agentLogs: [log, ...state.agentLogs].slice(0, 100) })),
  addRiskAlert: (alert) => set((state) => ({ riskAlerts: [alert, ...state.riskAlerts].slice(0, 50) })),
  addLearningEvent: (event) => set((state) => ({ learningEvents: [event, ...state.learningEvents].slice(0, 50) })),
  addSystemMetric: (metric) => set((state) => ({ systemMetrics: [metric, ...state.systemMetrics].slice(0, 100) })),
  setRegime: (regime) => set({ regime }),
  setKillSwitch: (killSwitchActive) => set({ killSwitchActive }),
  setWsConnected: (wsConnected) => set({ wsConnected }),
}))
