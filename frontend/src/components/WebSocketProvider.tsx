"use client";
// frontend/src/components/WebSocketProvider.tsx
// 'use client' — hooks are allowed here.
// Mounted once in app/layout.tsx so the WS connection survives navigation.

import { useGlobalWebSocket } from "@/hooks/useGlobalWebSocket";

export function WebSocketProvider({ children }: { children: React.ReactNode }) {
  const { isConnected } = useGlobalWebSocket(); // single persistent connection

  return (
    <>
      {/* WS status indicator — was in layout.tsx but needs hook data, so lives here */}
      <div className="fixed top-4 right-4 z-50">
        <div
          className={`flex items-center gap-2 px-3 py-1 rounded-lg text-xs font-medium ${
            isConnected
              ? "bg-emerald-500/10 text-emerald-400 border border-emerald-500/30"
              : "bg-slate-500/10 text-slate-400 border border-slate-500/30"
          }`}
        >
          <div
            className={`w-2 h-2 rounded-full ${
              isConnected ? "bg-emerald-400 animate-pulse" : "bg-slate-400"
            }`}
          />
          <span>{isConnected ? "Connected" : "Disconnected"}</span>
        </div>
      </div>

      {children}
    </>
  );
}
