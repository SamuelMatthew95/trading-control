import '../styles/globals.css'
import type { Metadata } from 'next'

export const metadata: Metadata = {
  title: 'Trading Control Dashboard',
  description: 'Phase 2 dashboard for AI trading control',
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className="dark">
      <body className="min-h-screen bg-[#0F172A] text-slate-100">{children}</body>
    </html>
  )
}
