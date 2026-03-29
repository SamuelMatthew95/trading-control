'use client'

import { useEffect, useState } from 'react'

export default function SimpleDashboardPage({ section }: { section: string }) {
  const [isReady, setIsReady] = useState(false)
  
  useEffect(() => {
    // Force client-side only
    setIsReady(true)
  }, [])
  
  if (!isReady) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-50">
        <div className="text-center">
          <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600 mx-auto"></div>
          <p className="mt-2 text-sm text-gray-600">Loading...</p>
        </div>
      </div>
    )
  }
  
  // Dynamic import to avoid SSR issues
  const DashboardView = require('@/app/dashboard/DashboardView').DashboardView
  
  return <DashboardView section={section as any} />
}
