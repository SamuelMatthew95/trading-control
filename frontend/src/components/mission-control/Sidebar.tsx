import Link from 'next/link';
import { useRouter } from 'next/router';
import { 
  LayoutDashboard, 
  FileText,
  TrendingUp,
  Activity
} from 'lucide-react';
import { cn } from '@/lib/utils';
import { ThemeToggle } from '@/components/theme/ThemeToggle';

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
    <div className={cn('w-[220px] bg-card border-r border-border', className)}>
      <div className="flex h-full flex-col">
        {/* Logo/Brand */}
        <div className="flex h-16 items-center justify-between px-4 border-b border-border">
          <div className="flex items-center gap-3">
            <div className="flex h-8 w-8 items-center justify-center rounded-md bg-success">
              <Activity className="h-4 w-4 text-primary-foreground" />
            </div>
            <div className="leading-tight">
              <h1 className="text-[0.95rem] font-bold text-foreground">Mission Control</h1>
              <p className="text-[0.75rem] text-muted-foreground">Trading System</p>
              <p className="text-[0.7rem] text-slate-500 italic">by Matthew Samuel</p>
            </div>
          </div>
          <ThemeToggle />
        </div>

        {/* Navigation */}
        <nav className="flex-1 space-y-1 px-2 py-6">
          {navigation.map((item) => {
            const isActive = router.pathname === item.href;
            return (
              <Link
                key={item.name}
                href={item.href}
                className={cn(
                  'flex items-center gap-3 rounded-md px-3 py-2.5 text-sm font-medium transition-colors h-10',
                  isActive
                    ? 'bg-gray-900 text-white dark:bg-white dark:text-gray-900'
                    : 'text-gray-600 hover:bg-gray-100 dark:text-gray-400 dark:hover:bg-slate-800'
                )}
              >
                <item.icon className="h-4 w-4" />
                {item.name}
              </Link>
            );
          })}
        </nav>

        {/* Bottom */}
        <div className="border-t border-border p-4">
          <div className="text-[0.65rem] text-muted-foreground text-center">
            v1.0.0
          </div>
        </div>
      </div>
    </div>
  );
}
