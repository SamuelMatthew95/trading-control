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
    <div className="w-[240px] flex flex-col h-screen bg-[#020617] border-r border-white/10 font-mono select-none">
      {/* Brand Header - Sharp Square Logo */}
      <div className="p-6 mb-4">
        <div className="flex items-center gap-3">
          {/* Square, not a circle */}
          <div className="h-4 w-4 bg-indigo-500 shadow-[0_0_10px_rgba(99,102,241,0.6)] rounded-none" />
          <h1 className="text-[11px] font-black tracking-[0.3em] text-white uppercase">
            Trading Control
          </h1>
        </div>
      </div>

      {/* Navigation - Sharp edges, high contrast */}
      <nav className="flex-1 px-0 space-y-0">
        {navigation.map((item) => {
          const isActive = router.pathname === item.href;
          return (
            <Link
              key={item.name}
              href={item.href}
              className={cn(
                'group flex items-center gap-4 px-6 py-4 text-[10px] uppercase tracking-[0.2em] transition-all border-l-4',
                isActive
                  ? 'bg-white/[0.03] border-indigo-500 text-white font-bold'
                  : 'border-transparent text-slate-500 hover:text-slate-200 hover:bg-white/[0.02]'
              )}
            >
              <item.icon className={cn("w-4 h-4", isActive ? "text-indigo-400" : "text-slate-600")} />
              {item.name}
            </Link>
          );
        })}
      </nav>

      {/* Kill Switch - Emergency Industrial Style */}
      <div className="p-4 border-t border-white/5 bg-black/40">
        <button 
          className="w-full group relative bg-red-950/20 border-2 border-red-900/50 hover:border-red-500 px-4 py-4 transition-all rounded-none"
          onClick={() => console.log("TERMINATE ALL")}
        >
          <div className="relative z-10 flex items-center justify-between">
            <div className="text-left">
              <p className="text-[9px] font-bold text-red-500/60 uppercase tracking-tighter">Emergency</p>
              <p className="text-[12px] font-black text-red-500 uppercase leading-none">Kill Switch</p>
            </div>
            <Power className="w-5 h-5 text-red-500" />
          </div>
          {/* Subtle Warning Pattern */}
          <div className="absolute inset-0 opacity-[0.03] group-hover:opacity-[0.05] pointer-events-none bg-[repeating-linear-gradient(45deg,transparent,transparent_10px,red_10px,red_20px)]" />
        </button>
      </div>
    </div>
  );
}
