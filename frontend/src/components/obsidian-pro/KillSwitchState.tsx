'use client'

import { useEffect } from 'react'
import { motion } from 'framer-motion'
import { cn } from '@/lib/utils'

interface KillSwitchStateProps {
  isActive: boolean
  children: React.ReactNode
}

export function KillSwitchState({ isActive, children }: KillSwitchStateProps) {
  useEffect(() => {
    // Add/remove body class for kill switch state
    if (isActive) {
      document.body.classList.add('kill-switch-active')
    } else {
      document.body.classList.remove('kill-switch-active')
    }

    return () => {
      document.body.classList.remove('kill-switch-active')
    }
  }, [isActive])

  return (
    <>
      {/* Global overlay when kill switch is active */}
      {isActive && (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          className="fixed inset-0 pointer-events-none z-50"
          style={{
            background: 'radial-gradient(circle at center, transparent 0%, rgba(239, 68, 68, 0.1) 50%, rgba(239, 68, 68, 0.2) 100%)',
            animation: 'pulse-red 2s ease-in-out infinite'
          }}
        />
      )}

      {/* Red border glow around viewport */}
      {isActive && (
        <motion.div
          initial={{ opacity: 0, scale: 0.95 }}
          animate={{ opacity: 1, scale: 1 }}
          exit={{ opacity: 0, scale: 0.95 }}
          className="fixed inset-0 pointer-events-none z-50 border-4 border-rose-500/30"
          style={{
            boxShadow: 'inset 0 0 100px rgba(239, 68, 68, 0.3), 0 0 100px rgba(239, 68, 68, 0.2)',
            animation: 'glow-red 2s ease-in-out infinite'
          }}
        />
      )}

      {/* Status indicator in corner */}
      {isActive && (
        <motion.div
          initial={{ opacity: 0, y: -20 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: -20 }}
          className="fixed top-4 right-4 z-50"
        >
          <div className="flex items-center gap-2 px-3 py-2 bg-slate-900/90 border border-slate-700 rounded-lg backdrop-blur-sm shadow-lg">
            <div className="w-2 h-2 rounded-full bg-slate-600" />
            <span className="text-slate-300 text-xs font-medium uppercase tracking-[0.1em]">
              Trading Halted
            </span>
          </div>
        </motion.div>
      )}

      {/* Main content with conditional styling */}
      <div className={cn(
        'transition-all duration-500',
        isActive && 'opacity-90'
      )}>
        {children}
      </div>

      {/* CSS for animations */}
      <style jsx>{`
        @keyframes pulse-red {
          0%, 100% { opacity: 0.5; }
          50% { opacity: 0.8; }
        }

        @keyframes glow-red {
          0%, 100% { 
            box-shadow: inset 0 0 100px rgba(239, 68, 68, 0.3), 0 0 100px rgba(239, 68, 68, 0.2);
          }
          50% { 
            box-shadow: inset 0 0 150px rgba(239, 68, 68, 0.5), 0 0 150px rgba(239, 68, 68, 0.4);
          }
        }

        .kill-switch-active {
          filter: saturate(0.8) brightness(0.95);
        }
      `}</style>
    </>
  )
}
