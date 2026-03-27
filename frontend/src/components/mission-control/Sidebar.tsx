import Link from 'next/link';
import { LayoutGrid, BarChart3, Bot, Zap, Settings2, Power } from 'lucide-react';

const navigation = [
  { name: 'Overview', href: '/dashboard', icon: LayoutGrid },
  { name: 'Trading', href: '/dashboard/trading', icon: BarChart3 },
  { name: 'Agents', href: '/dashboard/agents', icon: Bot },
  { name: 'Learning', href: '/dashboard/learning', icon: Zap },
  { name: 'System', href: '/dashboard/system', icon: Settings2 },
];

export function Sidebar() {
  return (
    <div className="w-64 flex flex-col h-screen bg-white dark:bg-zinc-950 border-r border-slate-200 dark:border-slate-800 font-sans select-none">
      {/* Brand Header - Clean Professional */}
      <div className="p-6 mb-4">
        <div className="flex items-center gap-3">
          {/* Clean logo */}
          <div className="h-4 w-4 bg-slate-600 rounded-none" />
          <h1 className="text-[11px] font-bold tracking-tighter text-slate-950 dark:text-white uppercase">
            Trading Control
          </h1>
        </div>
      </div>

      {/* Navigation - All items identical, no active states */}
      <nav className="flex-1 px-0 space-y-0">
        {navigation.map((item) => (
          <Link
            key={item.name}
            href={item.href}
            className="group flex items-center gap-4 px-6 py-4 text-[10px] uppercase tracking-[0.2em] transition-all rounded-lg text-slate-500 dark:text-slate-400 hover:text-slate-700 dark:hover:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-800"
          >
            <item.icon className="w-4 h-4" />
            {item.name}
          </Link>
        ))}
      </nav>

      {/* Kill Switch - Clean Industrial */}
      <div className="p-4 border-t border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-900">
        <button 
          className="w-full bg-slate-900 text-white dark:bg-red-600 border-2 border-slate-300 dark:border-red-500 hover:bg-slate-800 dark:hover:bg-red-700 px-4 py-4 transition-all rounded-lg"
          onClick={() => console.warn("TERMINATE ALL")}
        >
          <div className="flex items-center justify-between">
            <div className="text-left">
              <p className="text-[9px] font-bold text-slate-300 dark:text-slate-200 uppercase tracking-tighter">Emergency</p>
              <p className="text-[12px] font-black text-white uppercase leading-none">Kill Switch</p>
            </div>
            <Power className="w-5 h-5 text-white" />
          </div>
        </button>
      </div>
    </div>
  );
}
