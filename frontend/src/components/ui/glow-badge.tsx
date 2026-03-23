import { Badge } from '@/components/ui/badge';
import { cn } from '@/lib/utils';

interface GlowBadgeProps {
  children: React.ReactNode;
  variant?: 'healthy' | 'unhealthy' | 'warning';
  className?: string;
}

export function GlowBadge({ children, variant = 'healthy', className }: GlowBadgeProps) {
  const getGlowClass = () => {
    switch (variant) {
      case 'healthy':
        return 'bg-green-500/20 text-green-400 border-green-500/50 shadow-lg shadow-green-500/25';
      case 'unhealthy':
        return 'bg-red-500/20 text-red-400 border-red-500/50 shadow-lg shadow-red-500/25';
      case 'warning':
        return 'bg-yellow-500/20 text-yellow-400 border-yellow-500/50 shadow-lg shadow-yellow-500/25';
      default:
        return 'bg-gray-500/20 text-gray-400 border-gray-500/50';
    }
  };

  return (
    <Badge className={cn(getGlowClass(), 'animate-pulse', className)}>
      {children}
    </Badge>
  );
}
