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
    <div className="w-64 flex flex-col h-screen bg-[#020617] border-r border-white/10 font-mono select-none">
      {/* Brand Header - Clean Sharp Logo */}
      <div className="p-6 mb-4">
        <div className="flex items-center gap-3">
          {/* Clean square, no glow */}
          <div className="h-4 w-4 bg-slate-600 rounded-none" />
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
                  ? 'bg-white/[0.03] border-slate-400 text-white font-bold'
                  : 'border-transparent text-slate-300 hover:text-slate-200 hover:bg-white/[0.02]'
              )}
            >
              <item.icon className={cn("w-4 h-4", isActive ? "text-slate-400" : "text-slate-500")} />
              {item.name}
            </Link>
          );
        })}
      </nav>

      {/* Kill Switch - Clean Industrial Style */}
      <div className="p-4 border-t border-white/5 bg-black/40">
        <button 
          className="w-full bg-black/60 border-2 border-slate-600 hover:border-slate-500 px-4 py-4 transition-all rounded-none"
          onClick={() => console.log("TERMINATE ALL")}
        >
          <div className="flex items-center justify-between">
            <div className="text-left">
              <p className="text-[9px] font-bold text-slate-400 uppercase tracking-tighter">Emergency</p>
              <p className="text-[12px] font-black text-white uppercase leading-none">Kill Switch</p>
            </div>
            <Power className="w-5 h-5 text-slate-400" />
          </div>
        </button>
      </div>
    </div>
  );
}
