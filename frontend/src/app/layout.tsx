import type { Metadata } from 'next'
import { IBM_Plex_Mono, Inter } from 'next/font/google'
import { ThemeProvider } from 'next-themes'
import { Analytics } from '@vercel/analytics/react'
import { SpeedInsights } from '@vercel/speed-insights/next'
import '../styles/globals.css'
import { WebSocketProvider } from '@/components/WebSocketProvider'

// Load the typefaces the design system declares (Tailwind fontFamily). Without
// this they silently fell back to each device's system fonts, so the UI looked
// different from machine to machine. CSS variables feed Tailwind's sans/mono.
const inter = Inter({ subsets: ['latin'], variable: '--font-sans', display: 'swap' })
// IBM Plex Mono — a refined, institutional monospace for tabular numerics and
// IDs. Non-variable on Google Fonts, so the weights we actually use must be
// declared explicitly (400 body, 500/600 emphasis, 700 headline numbers).
const plexMono = IBM_Plex_Mono({
  subsets: ['latin'],
  weight: ['400', '500', '600', '700'],
  variable: '--font-mono',
  display: 'swap',
})

export const metadata: Metadata = {
  title: 'Trading Control',
  description: 'AI Trading Control Dashboard',
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning className={`${inter.variable} ${plexMono.variable}`}>
      <body className="min-h-screen bg-slate-100 font-sans text-slate-900 antialiased dark:bg-slate-950 dark:text-slate-100">
        <ThemeProvider attribute="class" defaultTheme="dark" enableSystem={false} disableTransitionOnChange>
          <WebSocketProvider>{children}</WebSocketProvider>
        </ThemeProvider>
        <Analytics />
        <SpeedInsights />
      </body>
    </html>
  )
}
