'use client'
// Mounted once in app/layout.tsx so the WS connection survives navigation.

import { useGlobalWebSocket } from '@/hooks/useGlobalWebSocket'
import { Badge } from '@/components/ui/badge'
import { TONE_DOT } from '@/lib/design/sentiment'
import { UI_COPY } from '@/constants/copy'
import { cn } from '@/lib/utils'

export function WebSocketProvider({ children }: { children: React.ReactNode }) {
  const { isConnected } = useGlobalWebSocket() // single persistent connection

  return (
    <>
      {/* WS status indicator — needs hook data, so it lives with the provider. */}
      <div className="fixed right-4 top-4 z-toast">
        <Badge
          tone={isConnected ? 'success' : 'neutral'}
          variant="outlined"
          className="rounded-lg px-3 py-1"
        >
          <span
            className={cn(
              'h-2 w-2 rounded-full',
              isConnected ? `animate-pulse ${TONE_DOT.success}` : TONE_DOT.neutral,
            )}
          />
          {isConnected ? UI_COPY.status.connected : UI_COPY.status.disconnected}
        </Badge>
      </div>

      {children}
    </>
  )
}
