'use client'

import dynamic from 'next/dynamic'

const DashboardView = dynamic(() => import('@/app/dashboard/DashboardView').then(mod => ({ default: mod.DashboardView })), {
  ssr: false,
  loading: () => (
    <div className="min-h-screen flex items-center justify-center bg-gray-50">
      <div className="text-center">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600 mx-auto"></div>
        <p className="mt-2 text-sm text-gray-600">Loading...</p>
      </div>
    </div>
  )
})

export default function SimpleDashboardPage({ section }: { section: string }) {
  return <DashboardView section={section as 'overview' | 'agents' | 'learning' | 'system' | 'trading'} />
}
