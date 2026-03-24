import Link from 'next/link';
import { useRouter } from 'next/router';
import { LayoutGrid, BarChart3, Bot, Zap, Settings2, Power } from 'lucide-react';
import { cn } from '@/lib/utils';

const navigation = [
  { name: 'Overview', href: '/dashboard', icon: LayoutGrid },
  { name: 'Trading', href: '/dashboard/trading', icon: BarChart3 },
  { name: 'Agents', href: '/dashboard/agents', icon: Bot },
  { name: 'Learning', href: '/dashboard/learning', icon: Zap },
  { name: 'System', href: '/dashboard/system', icon: Settings2 },
];

export function Sidebar() {
  const router = useRouter();

  return (
    <div className="w-[240px] flex flex-col h-screen bg-slate-950 border-r border-white/5 font-mono">
      {/* Brand - Sharp and Professional */}
      <div className="p-6 mb-4">
        <div className="flex items-center gap-3">
          <div className="h-2 w-2 bg-indigo-500 shadow-[0_0_8px_rgba(99,102,241,0.8)]" />
          <h1 className="text-xs font-bold tracking-[0.2em] text-white uppercase">
            Trading Control
          </h1>
        </div>
      </div>

      {/* Navigation - No more "bubbly" curves */}
      <nav className="flex-1 px-3 space-y-1">
        {navigation.map((item) => {
          const isActive = router.pathname === item.href;
          return (
            <Link
              key={item.name}
              href={item.href}
              className={cn(
                'group flex items-center gap-3 px-3 py-2 text-[11px] uppercase tracking-wider transition-all duration-150 border-l-2',
                isActive
                  ? 'bg-indigo-500/10 border-indigo-500 text-white'
                  : 'border-transparent text-slate-500 hover:text-slate-300 hover:bg-white/5'
              )}
            >
              <item.icon className={cn("w-4 h-4", isActive ? "text-indigo-400" : "text-slate-600")} />
              {item.name}
            </Link>
          );
        })}
      </nav>

      {/* THE KILL SWITCH - Actually looks dangerous now */}
      <div className="p-4 border-t border-white/5 bg-slate-900/50">
        <button 
          className="w-full group relative overflow-hidden bg-red-950/30 border border-red-500/50 px-4 py-3 transition-all hover:bg-red-600 active:scale-95"
          onClick={() => console.log("EMERGENCY STOP")}
        >
          <div className="relative z-10 flex items-center justify-between">
            <div className="text-left">
              <p className="text-[10px] font-bold text-red-500 group-hover:text-white uppercase">Manual</p>
              <p className="text-[12px] font-black text-red-500 group-hover:text-white uppercase leading-none">Kill Switch</p>
            </div>
            <Power className="w-5 h-5 text-red-500 group-hover:text-white" />
          </div>
          {/* Subtle Red Glow Background */}
          <div className="absolute inset-0 bg-red-600/10 group-hover:bg-transparent" />
        </button>
        
        <div className="mt-4 flex items-center justify-center gap-2">
          <div className="h-1.5 w-1.5 rounded-full bg-indigo-500 shadow-[0_0_5px_rgba(99,102,241,1)]" />
          <span className="text-[10px] text-slate-500 uppercase tracking-tighter">Phase 2 · Paper Mode</span>
        </div>
      </div>
    </div>
  );
}
