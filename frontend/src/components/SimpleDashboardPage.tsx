'use client'

import { useEffect, useState } from 'react'
import { DashboardView } from '@/app/dashboard/DashboardView'

export default function SimpleDashboardPage({ section }: { section: string }) {
  const [isClient, setIsClient] = useState(false)

  useEffect(() => {
    setIsClient(true)
  }, [])

  if (!isClient) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-50">
        <div className="text-center">
          <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600 mx-auto"></div>
          <p className="mt-2 text-sm text-gray-600">Loading...</p>
        </div>
      </div>
    )
  }

  return <DashboardView section={section as 'overview' | 'agents' | 'learning' | 'system' | 'trading'} />
}
