import Link from 'next/link';
import { useRouter } from 'next/router';
import { 
  LayoutDashboard, 
  FileText,
  TrendingUp,
  Activity
} from 'lucide-react';
import { cn } from '@/lib/utils';

const navigation = [
  { name: 'Dashboard', href: '/dashboard', icon: LayoutDashboard },
  { name: 'Trading', href: '/dashboard/trading', icon: FileText },
  { name: 'Agents', href: '/dashboard/agents', icon: TrendingUp },
  { name: 'Learning', href: '/dashboard/learning', icon: Activity },
  { name: 'System', href: '/dashboard/system', icon: Activity },
];

interface SidebarProps {
  className?: string;
}

export function Sidebar({ className }: SidebarProps) {
  const router = useRouter();

  return (
    <div className={cn('w-[220px] bg-white dark:bg-slate-950 border-r border-slate-200 dark:border-slate-800', className)}>
      <div className="flex h-full flex-col">
        {/* Logo/Brand */}
        <div className="flex h-12 items-center justify-between px-6 border-b border-slate-200 dark:border-slate-800">
          <div className="flex items-center gap-3">
            <div className="flex h-8 w-8 items-center justify-center bg-slate-900 dark:bg-white">
              <Activity className="w-5 h-5 text-white dark:text-slate-900" />
            </div>
            <div className="leading-tight">
              <h1 className="text-sm font-bold text-slate-900 dark:text-white">Trading Control</h1>
              <p className="text-xs text-slate-500 dark:text-slate-400">System Interface</p>
            </div>
          </div>
        </div>

        {/* Navigation */}
        <nav className="flex-1 px-6 py-4">
          <div className="space-y-1">
            {navigation.map((item) => {
              const isActive = router.pathname === item.href;
              return (
                <Link
                  key={item.name}
                  href={item.href}
                  className={cn(
                    'flex items-center gap-3 px-3 h-10 text-sm font-medium transition-colors rounded-md',
                    isActive
                      ? 'bg-slate-100 dark:bg-slate-800 text-slate-900 dark:text-white border-l-2 border-indigo-600'
                      : 'text-slate-500 dark:text-slate-400 hover:bg-slate-50 dark:hover:bg-slate-900'
                  )}
                >
                  <item.icon className="w-5 h-5 flex-shrink-0" />
                  <span className="font-medium">{item.name}</span>
                </Link>
              );
            })}
          </div>
        </nav>

        {/* Footer */}
        <div className="border-t border-slate-200 dark:border-slate-800 px-6 py-4">
          <div className="text-xs text-slate-500 dark:text-slate-400 text-center">
            Phase 2 · Paper Mode
          </div>
        </div>
      </div>
    </div>
  );
}
