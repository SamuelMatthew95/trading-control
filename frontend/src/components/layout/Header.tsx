import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { ThemeToggle } from '@/components/theme/ThemeToggle';
import { Power } from 'lucide-react';

interface HeaderProps {
  title: string;
  subtitle?: string;
}

export function Header({ title, subtitle }: HeaderProps) {
  return (
    <header className="h-16 border-b border-border bg-card px-6 flex items-center justify-between">
      <div>
        <h1 className="text-[1.5rem] font-semibold text-foreground">{title}</h1>
        {subtitle && <p className="text-sm text-muted-foreground">{subtitle}</p>}
      </div>
      
      <div className="flex items-center gap-4">
        {/* Network Status */}
        <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
          <div className="w-1.5 h-1.5 rounded-full bg-green-500" />
          <span>Live</span>
          <span className="text-muted-foreground">Last updated: {new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</span>
        </div>

        {/* Emergency Stop */}
        <Button
          variant="outline"
          size="sm"
          className="border-red-500 text-red-500 hover:bg-red-50 dark:hover:bg-red-950 rounded-md px-3 py-1.5 text-sm font-medium"
        >
          <Power className="h-4 w-4 mr-1" />
          Emergency Stop
        </Button>

        {/* Theme Toggle */}
        <ThemeToggle />
      </div>
    </header>
  );
}
