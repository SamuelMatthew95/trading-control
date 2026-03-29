'use client'
import { useEffect, useCallback } from 'react'
import { useCodexStore } from '@/stores/useCodexStore'
import type {
  DashboardUpdateData,
  SystemMetricData,
  SignalData,
  OrderData,
  NotificationData,
  AgentEventData,
  SystemEventData,
  AgentLogsData,
  CustomEventType
} from '@/types/websocket'

// Hook to handle WebSocket events and update store
export function useWebSocketEvents() {
  const store = useCodexStore((state) => state)

  const handleDashboardUpdate = useCallback((event: CustomEventType) => {
    const data = event.detail?.data as DashboardUpdateData
    if (data) {
      store.hydrateDashboard(data as Parameters<typeof store.hydrateDashboard>[0])
      
      // Handle agent logs
      if (Array.isArray(data.agent_logs)) {
        for (const log of data.agent_logs) {
          const norm = {
            agent_name: log.agent_name || log.agent || log.source_agent || 'Unknown',
            event_type: log.action || log.type || 'processed',
            timestamp: log.timestamp || log.created_at || new Date().toISOString(),
            symbol: log.symbol,
            action: log.action,
            latency_ms: Number(log.latency_ms) || 0,
            primary_edge: log.primary_edge,
            stream: log.stream,
            message_id: log.message_id,
            data: log.data
          }
          store.addAgentLog(norm)
        }
      }
      
      // Handle system metrics
      if (Array.isArray(data.system_metrics)) {
        for (const metric of data.system_metrics) {
          const norm = {
            metric_name: metric.metric_name || metric.name || 'unknown',
            value: Number(metric.value) || 0,
            timestamp: metric.timestamp || metric.created_at || new Date().toISOString(),
            labels: metric.labels || {},
            unit: metric.unit,
            tags: metric.tags
          }
          store.addSystemMetric(norm)
        }
      }
    }
  }, [store])

  const handleSystemMetric = useCallback((event: CustomEventType) => {
    const data = event.detail?.data as SystemMetricData
    if (data) {
      const norm = {
        metric_name: data.metric_name || data.name || 'unknown',
        value: Number(data.value) || 0,
        timestamp: data.timestamp || data.created_at || new Date().toISOString(),
        labels: data.labels || {},
        unit: data.unit,
        tags: data.tags
      }
      store.addSystemMetric(norm)
    }
  }, [store])

  const handlePriceUpdate = useCallback((event: CustomEventType) => {
    const { symbol, price } = event.detail || {}
    if (symbol && price && Number.isFinite(price)) {
      const currentPrice = store.prices[symbol]?.price || 0
      const change = price - currentPrice
      store.updatePrice(symbol, price, change)
      store.trackMarketTick(symbol)
    }
  }, [store])

  const handleSignalReceived = useCallback((event: CustomEventType) => {
    const data = event.detail?.data as SignalData
    if (data) {
      store.addSignal({
        ...data,
        confidence: Number(data.confidence)
      })
    }
  }, [store])

  const handleOrderUpdate = useCallback((event: CustomEventType) => {
    const data = event.detail?.data as OrderData
    if (data) {
      store.updateOrder(data as Parameters<typeof store.updateOrder>[0])
    }
  }, [store])

  const handleNotificationReceived = useCallback((event: CustomEventType) => {
    const data = event.detail?.data as NotificationData
    if (data) {
      store.addRiskAlert(data)
    }
  }, [store])

  const handleAgentEvent = useCallback((event: CustomEventType) => {
    const data = event.detail?.data as AgentEventData
    if (data) {
      const norm = {
        agent_name: data.name || data.agent_name || 'Unknown',
        event_type: data.action || data.type || 'processed',
        timestamp: data.timestamp || data.updated_at || data.created_at || new Date().toISOString(),
        symbol: data.symbol,
        action: data.action,
        latency_ms: Number(data.latency_ms) || 0,
        primary_edge: data.primary_edge,
        stream: data.stream,
        message_id: data.message_id,
        data: data.data
      }
      store.addAgentLog(norm)
    }
  }, [store])

  const handleSystemEvent = useCallback((event: CustomEventType) => {
    const data = event.detail?.data as SystemEventData
    if (data) {
      // Handle various system events
      if (data.type === 'agent_logs') {
        for (const log of (data.data as AgentLogsData[]) || []) {
          const norm = {
            agent_name: log.agent_name || log.agent || log.source_agent || 'Unknown',
            event_type: log.action || log.type || 'processed',
            timestamp: log.timestamp || log.created_at || new Date().toISOString(),
            symbol: log.symbol,
            action: log.action,
            latency_ms: Number(log.latency_ms) || 0,
            primary_edge: log.primary_edge,
            stream: 'agent_logs',
            message_id: log.message_id,
            data: log.data
          }
          store.addAgentLog(norm as Parameters<typeof store.addAgentLog>[0])
        }
      }
    }
  }, [store])

  const handleAgentLogs = useCallback((event: CustomEventType) => {
    const data = event.detail?.data as AgentLogsData
    if (data) {
      const source = data
      const payloadObj = source.payload || {}
      const norm = {
        agent_name: source.agent || source.source || payloadObj.agent || source.agent_name,
        event_type: source.action || source.type || 'processed',
        timestamp: source.timestamp || source.created_at || new Date().toISOString(),
        symbol: source.symbol,
        action: source.action,
        latency_ms: Number(source.latency_ms) || 0,
        primary_edge: source.primary_edge,
        stream: 'agent_logs',
        message_id: source.message_id,
        data: source.data
      }
      store.addAgentLog(norm as Parameters<typeof store.addAgentLog>[0])
    }
  }, [store])

  // Set up event listeners
  useEffect(() => {
    window.addEventListener('dashboard-update', handleDashboardUpdate)
    window.addEventListener('system-metric', handleSystemMetric)
    window.addEventListener('price-update', handlePriceUpdate)
    window.addEventListener('signal-received', handleSignalReceived)
    window.addEventListener('order-update', handleOrderUpdate)
    window.addEventListener('notification-received', handleNotificationReceived)
    window.addEventListener('agent-event', handleAgentEvent)
    window.addEventListener('system-event', handleSystemEvent)
    window.addEventListener('agent-logs', handleAgentLogs)

    return () => {
      window.removeEventListener('dashboard-update', handleDashboardUpdate)
      window.removeEventListener('system-metric', handleSystemMetric)
      window.removeEventListener('price-update', handlePriceUpdate)
      window.removeEventListener('signal-received', handleSignalReceived)
      window.removeEventListener('order-update', handleOrderUpdate)
      window.removeEventListener('notification-received', handleNotificationReceived)
      window.removeEventListener('agent-event', handleAgentEvent)
      window.removeEventListener('system-event', handleSystemEvent)
      window.removeEventListener('agent-logs', handleAgentLogs)
    }
  }, [handleDashboardUpdate, handleSystemMetric, handlePriceUpdate, handleSignalReceived, handleOrderUpdate, handleNotificationReceived, handleAgentEvent, handleSystemEvent, handleAgentLogs])

  return {
    handleDashboardUpdate,
    handleSystemMetric,
    handlePriceUpdate,
    handleSignalReceived,
    handleOrderUpdate,
    handleNotificationReceived,
    handleAgentEvent,
    handleSystemEvent,
    handleAgentLogs
  }
}
