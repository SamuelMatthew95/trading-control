'use client'

import { useEffect, useState } from 'react'
import { DashboardView } from '@/app/dashboard/DashboardView'
import { useGlobalWebSocket } from '@/hooks/useGlobalWebSocket'
import { useWebSocketEvents } from '@/hooks/useWebSocketEvents'

export default function DashboardPageWrapper({ section }: { section: string }) {
  const [isClient, setIsClient] = useState(false)
  
  // Ensure this only renders on client
  useEffect(() => {
    setIsClient(true)
  }, [])
  
  // Initialize WebSocket hooks only on client
  useGlobalWebSocket()
  useWebSocketEvents()
  
  if (!isClient) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <div className="text-center">
          <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600 mx-auto"></div>
          <p className="mt-4 text-gray-600">Loading dashboard...</p>
        </div>
      </div>
    )
  }
  
  return <DashboardView section={section as any} />
}
