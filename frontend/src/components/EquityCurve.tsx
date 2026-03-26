'use client'

import { useEffect, useRef, useState } from 'react'
import { useCodexStore } from '@/stores/useCodexStore'

export function EquityCurve() {
  const { orders } = useCodexStore()
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const [equityData, setEquityData] = useState<{time: number, value: number}[]>([])

  // Calculate equity curve from orders
  useEffect(() => {
    if (!orders || orders.length === 0) {
      setEquityData([{time: Date.now(), value: 0}])
      return
    }

    // Sort orders by timestamp
    const sortedOrders = [...orders]
      .filter(o => o.timestamp && typeof o.pnl === 'number' && !isNaN(Number(o.pnl)))
      .sort((a, b) => new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime())

    // Calculate running equity
    let runningPnl = 0
    const equityPoints = sortedOrders.map(order => {
      runningPnl += Number(order.pnl)
      return {
        time: new Date(order.timestamp).getTime(),
        value: runningPnl
      }
    })

    // Add current point if no recent data
    if (equityPoints.length === 0 || Date.now() - equityPoints[equityPoints.length - 1].time > 60000) {
      equityPoints.push({time: Date.now(), value: runningPnl})
    }

    setEquityData(equityPoints)
  }, [orders])

  // Draw the chart
  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return

    const ctx = canvas.getContext('2d')
    if (!ctx) return

    // Set canvas size
    const rect = canvas.getBoundingClientRect()
    canvas.width = rect.width * window.devicePixelRatio
    canvas.height = rect.height * window.devicePixelRatio
    ctx.scale(window.devicePixelRatio, window.devicePixelRatio)

    // Clear canvas
    ctx.clearRect(0, 0, rect.width, rect.height)

    if (equityData.length < 2) return

    // Calculate bounds
    const values = equityData.map(d => d.value)
    const minValue = Math.min(...values)
    const maxValue = Math.max(...values)
    const valueRange = maxValue - minValue || 1

    const times = equityData.map(d => d.time)
    const minTime = Math.min(...times)
    const maxTime = Math.max(...times)
    const timeRange = maxTime - minTime || 1

    // Drawing parameters
    const padding = { top: 10, right: 10, bottom: 20, left: 40 }
    const chartWidth = rect.width - padding.left - padding.right
    const chartHeight = rect.height - padding.top - padding.bottom

    // Draw grid lines
    ctx.strokeStyle = '#374151'
    ctx.lineWidth = 0.5
    ctx.setLineDash([2, 2])

    // Horizontal grid lines
    for (let i = 0; i <= 4; i++) {
      const y = padding.top + (chartHeight / 4) * i
      ctx.beginPath()
      ctx.moveTo(padding.left, y)
      ctx.lineTo(padding.left + chartWidth, y)
      ctx.stroke()
    }

    // Vertical grid lines
    for (let i = 0; i <= 4; i++) {
      const x = padding.left + (chartWidth / 4) * i
      ctx.beginPath()
      ctx.moveTo(x, padding.top)
      ctx.lineTo(x, padding.top + chartHeight)
      ctx.stroke()
    }

    ctx.setLineDash([])

    // Draw zero line if in range
    if (minValue <= 0 && maxValue >= 0) {
      const zeroY = padding.top + chartHeight - ((0 - minValue) / valueRange) * chartHeight
      ctx.strokeStyle = '#6B7280'
      ctx.lineWidth = 1
      ctx.beginPath()
      ctx.moveTo(padding.left, zeroY)
      ctx.lineTo(padding.left + chartWidth, zeroY)
      ctx.stroke()
    }

    // Draw the equity curve
    ctx.strokeStyle = equityData[equityData.length - 1].value >= 0 ? '#10B981' : '#EF4444'
    ctx.lineWidth = 2
    ctx.beginPath()

    equityData.forEach((point, index) => {
      const x = padding.left + ((point.time - minTime) / timeRange) * chartWidth
      const y = padding.top + chartHeight - ((point.value - minValue) / valueRange) * chartHeight

      if (index === 0) {
        ctx.moveTo(x, y)
      } else {
        ctx.lineTo(x, y)
      }
    })

    ctx.stroke()

    // Fill area under curve
    ctx.lineTo(padding.left + chartWidth, padding.top + chartHeight)
    ctx.lineTo(padding.left, padding.top + chartHeight)
    ctx.closePath()

    const gradient = ctx.createLinearGradient(0, padding.top, 0, padding.top + chartHeight)
    if (equityData[equityData.length - 1].value >= 0) {
      gradient.addColorStop(0, 'rgba(16, 185, 129, 0.1)')
      gradient.addColorStop(1, 'rgba(16, 185, 129, 0)')
    } else {
      gradient.addColorStop(0, 'rgba(239, 68, 68, 0.1)')
      gradient.addColorStop(1, 'rgba(239, 68, 68, 0)')
    }
    ctx.fillStyle = gradient
    ctx.fill()

    // Draw current value
    const lastValue = equityData[equityData.length - 1].value
    ctx.fillStyle = lastValue >= 0 ? '#10B981' : '#EF4444'
    ctx.font = '11px JetBrains Mono'
    ctx.textAlign = 'right'
    ctx.fillText(`$${lastValue.toFixed(2)}`, padding.left - 5, padding.top + chartHeight / 2)

  }, [equityData])

  return (
    <div className="w-full h-16 bg-gray-900 rounded-lg overflow-hidden">
      <canvas 
        ref={canvasRef}
        className="w-full h-full"
        style={{ imageRendering: 'crisp-edges' }}
      />
    </div>
  )
}
