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
      {/* Brand Header */}
      <div className="p-6 mb-4">
        <div className="flex items-center gap-3">
          <div className="h-2 w-2 bg-indigo-500 shadow-[0_0_10px_rgba(99,102,241,1)]" />
          <h1 className="text-[10px] font-bold tracking-[0.3em] text-slate-200 uppercase">
            Trading Control
          </h1>
        </div>
      </div>

      {/* Navigation */}
      <nav className="flex-1 px-3 space-y-0.5">
        {navigation.map((item) => {
          const isActive = router.pathname === item.href;
          return (
            <Link
              key={item.name}
              href={item.href}
              className={cn(
                'group flex items-center gap-3 px-4 py-2 text-[10px] uppercase tracking-widest transition-all border-l-2',
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

      {/* SAFETY KILL SWITCH */}
      <div className="p-4 border-t border-white/5 bg-black/20">
        <button 
          onClick={handleKillSwitch}
          className={cn(
            "w-full group relative overflow-hidden px-4 py-3 transition-all border outline-none",
            isConfirming 
              ? "bg-red-600 border-red-400 scale-[0.98] animate-pulse" 
              : "bg-red-950/20 border-red-900/50 hover:border-red-500"
          )}
        >
          <div className="relative z-10 flex items-center justify-between">
            <div className="text-left">
              <p className={cn(
                "text-[9px] font-bold uppercase tracking-tighter",
                isConfirming ? "text-white" : "text-red-500/70"
              )}>
                {isConfirming ? "ARE YOU SURE?" : "SYSTEM"}
              </p>
              <p className={cn(
                "text-[11px] font-black uppercase leading-none",
                isConfirming ? "text-white" : "text-red-500"
              )}>
                {isConfirming ? "CONFIRM STOP" : "KILL SWITCH"}
              </p>
            </div>
            {isConfirming ? (
              <AlertTriangle className="w-5 h-5 text-white" />
            ) : (
              <Power className="w-5 h-5 text-red-500 group-hover:rotate-90 transition-transform duration-300" />
            )}
          </div>
        </button>
        
        <div className="mt-4 flex items-center justify-center gap-2 opacity-40">
          <span className="text-[9px] text-slate-500 uppercase tracking-widest font-bold">
            PHASE 2 // PAPER_MODE
          </span>
        </div>
      </div>
    </div>
  );
}
