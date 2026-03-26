'use client'

import { cn } from '@/lib/utils'
import { Home, TrendingUp, Users, Brain } from 'lucide-react'

interface MobileNavigationProps {
  activeSection: string
  onSectionChange: (section: string) => void
}

export function MobileNavigation({ activeSection, onSectionChange }: MobileNavigationProps) {
  const navItems = [
    {
      id: 'overview',
      label: 'Overview',
      icon: Home
    },
    {
      id: 'trading',
      label: 'Trading',
      icon: TrendingUp
    },
    {
      id: 'agents',
      label: 'Agents',
      icon: Users
    },
    {
      id: 'learning',
      label: 'Learning',
      icon: Brain
    }
  ]

  return (
    <div className="fixed bottom-0 left-0 right-0 bg-[#18181b] border-t border-[#27272a] z-50 md:hidden">
      <div className="flex items-center justify-around h-16 px-2">
        {navItems.map((item) => {
          const Icon = item.icon
          const isActive = activeSection === item.id
          
          return (
            <button
              key={item.id}
              onClick={() => onSectionChange(item.id)}
              className={cn(
                "flex flex-col items-center justify-center gap-1 px-3 py-2 rounded-lg transition-all duration-200 min-h-[44px] min-w-[44px]",
                isActive 
                  ? "bg-[#10b981]/20 text-[#10b981]" 
                  : "text-gray-400 hover:text-gray-300"
              )}
            >
              <Icon className="w-5 h-5" />
              <span className="text-xs font-medium font-['Inter']">
                {item.label}
              </span>
            </button>
          )
        })}
      </div>
    </div>
  )
}
