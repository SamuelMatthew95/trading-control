'use client'
import { useEffect } from 'react'
import { useCodexStore } from '@/stores/useCodexStore'

const getWsUrl = () => {
  const base = process.env.NEXT_PUBLIC_WS_URL || 'ws://localhost:8000'
  return `${base.replace(/\/$/, '')}/ws/dashboard`
}

export function useWebSocket() {
  const { addAgentLog, addLearningEvent, addOrder, addRiskAlert, addSignal, addSystemMetric, setKillSwitch, setRegime, setWsConnected, updateOrder, updatePrice } = useCodexStore()

  useEffect(() => {
    // Only run on client side
    if (typeof window === 'undefined') return

    let socket: WebSocket | null = null
    let retry = 0
    let closed = false
    const connect = () => {
      socket = new WebSocket(getWsUrl())
      socket.onopen = () => { retry = 0; setWsConnected(true) }
      socket.onmessage = (event) => {
        const payload = JSON.parse(event.data)
        switch (payload.type) {
          case 'market_tick': updatePrice(payload.symbol, Number(payload.price || 0), Number(payload.change || 0)); break
          case 'signal': addSignal(payload); break
          case 'order_update': updateOrder(payload); break
          case 'agent_log': addAgentLog(payload); break
          case 'risk_alert': addRiskAlert(payload); break
          case 'regime_change': setRegime(payload.regime || 'neutral'); break
          case 'learning_event': addLearningEvent(payload); break
          case 'system_metric': addSystemMetric(payload); break
          case 'kill_switch': setKillSwitch(Boolean(payload.active)); break
        }
      }
      socket.onclose = () => {
        setWsConnected(false)
        if (closed) return
        const timeout = Math.min(1000 * (2 ** retry), 30000)
        retry += 1
        setTimeout(connect, timeout)
      }
    }
    connect()
    return () => { closed = true; socket?.close() }
  }, [addAgentLog, addLearningEvent, addOrder, addRiskAlert, addSignal, addSystemMetric, setKillSwitch, setRegime, setWsConnected, updateOrder, updatePrice])
}
