import { useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/router';
import { LayoutGrid, BarChart3, Bot, Zap, Settings2, Power, AlertTriangle } from 'lucide-react';
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
  const [isConfirming, setIsConfirming] = useState(false);

  const handleKillSwitch = () => {
    if (!isConfirming) {
      setIsConfirming(true);
      setTimeout(() => setIsConfirming(false), 3000); // Reset after 3 seconds
      return;
    }
    console.log("EMERGENCY STOP EXECUTED");
    setIsConfirming(false);
  };

  return (
    <div className="w-[240px] flex flex-col h-screen bg-slate-950 border-r border-white/5 font-mono select-none">
      {/* Brand Header - Terminal Style */}
      <div className="p-6 mb-4">
        <div className="flex items-center gap-3">
          <div className="h-2 w-2 bg-indigo-500 shadow-[0_0_10px_rgba(99,102,241,1)]" />
          <h1 className="text-[10px] font-bold tracking-[0.3em] text-slate-200 uppercase font-mono">
            Trading Control
          </h1>
        </div>
      </div>

      {/* Navigation - Sharp Terminal Style */}
      <nav className="flex-1 px-3 space-y-0.5">
        {navigation.map((item) => {
          const isActive = router.pathname === item.href;
          return (
            <Link
              key={item.name}
              href={item.href}
              className={cn(
                'group flex items-center gap-3 px-4 py-2 text-[10px] font-mono uppercase tracking-widest transition-all border-l-2 rounded-none',
                isActive
                  ? 'bg-indigo-500/10 border-indigo-500 text-indigo-400'
                  : 'border-transparent text-slate-500 hover:text-slate-300 hover:bg-white/[0.03]'
              )}
            >
              <item.icon className={cn("w-4 h-4", isActive ? "text-indigo-400" : "text-slate-600 group-hover:text-slate-400")} />
              {item.name}
            </Link>
          );
        })}
      </nav>

      {/* CRITICAL ACTION KILL SWITCH */}
      <div className="p-4 border-t border-white/10 bg-black/30">
        <button 
          onClick={handleKillSwitch}
          className={cn(
            "w-full h-10 border-2 font-black uppercase tracking-widest text-[10px] font-mono transition-all rounded-none outline-none",
            isConfirming 
              ? "bg-red-600 border-red-500 text-white animate-pulse shadow-[0_0_15px_rgba(239,68,68,0.4)]" 
              : "bg-red-950/20 border-red-500 text-red-500 hover:bg-red-950/40 hover:shadow-[0_0_15px_rgba(239,68,68,0.4)]"
          )}
        >
          {isConfirming ? 'CONFIRM STOP' : 'KILL SWITCH'}
        </button>
        
        <div className="mt-4 flex items-center justify-center gap-2 opacity-40">
          <span className="text-[9px] text-slate-500 uppercase tracking-widest font-bold font-mono">
            PHASE 2 // PAPER_MODE
          </span>
        </div>
      </div>
    </div>
  );
}
