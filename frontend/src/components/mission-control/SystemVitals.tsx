import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Progress } from '@/components/ui/progress';
import { Skeleton } from '@/components/ui/skeleton';
import { HealthResponse } from '@/types/health';
import { Activity, Database, Clock, TrendingUp, AlertTriangle } from 'lucide-react';
import { useState, useEffect, useRef } from 'react';

interface SystemVitalsProps {
  health: HealthResponse | undefined;
  isLoading: boolean;
}

export function SystemVitals({ health, isLoading }: SystemVitalsProps) {
  const prevDataRef = useRef<HealthResponse | null>(null);
  const [isInitialLoad, setIsInitialLoad] = useState(true);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [lastUpdated, setLastUpdated] = useState<string>('');

  useEffect(() => {
    if (health) {
      prevDataRef.current = health;
      setIsInitialLoad(false);
      setIsRefreshing(false);
      setLastUpdated(new Date().toLocaleTimeString());
    } else if (!prevDataRef.current && isInitialLoad) {
      // First load - keep skeleton
    } else if (prevDataRef.current && !health) {
      // Refresh in progress - keep showing old data
      setIsRefreshing(true);
    }
  }, [health, isInitialLoad]);

  if (isInitialLoad && !prevDataRef.current) {
    return (
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-4">
        {[...Array(4)].map((_, i) => (
          <Card key={i} className="bg-card border-border">
            <CardHeader className="pb-2">
              <Skeleton className="h-4 w-20" />
            </CardHeader>
            <CardContent>
              <Skeleton className="h-10 w-16 mb-2" />
              <Skeleton className="h-2 w-full" />
            </CardContent>
          </Card>
        ))}
      </div>
    );
  }

  const currentData = prevDataRef.current || health;
  const telemetry = currentData?.data?.telemetry;

  return (
    <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-4">
      {/* System Status */}
      <Card className="bg-card border-border hover:border-muted-foreground/20 transition-colors">
        <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-3">
          <CardTitle className="text-xs font-sans font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">System Status</CardTitle>
          <Activity className="h-4 w-4 text-muted-foreground" />
        </CardHeader>
        <CardContent>
          <div className="flex items-center gap-2">
            <Badge 
              variant={currentData?.data?.status === 'healthy' ? 'default' : 'secondary'}
              className="px-2 py-1 text-xs font-medium bg-slate-100 text-slate-600"
            >
              {currentData?.data?.status || 'Unknown'}
            </Badge>
          </div>
          <p className="text-xs font-sans text-slate-500 dark:text-slate-400 mt-2 leading-relaxed">
            {currentData?.data?.database_connected ? 'Database Connected' : 'Database Disconnected'}
          </p>
        </CardContent>
      </Card>

      {/* Latency */}
      <Card className="bg-card border-border hover:border-muted-foreground/20 transition-colors">
        <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-3">
          <CardTitle className="text-xs font-sans font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">Avg Latency</CardTitle>
          <Clock className="h-4 w-4 text-muted-foreground" />
        </CardHeader>
        <CardContent>
          <div className="text-2xl font-black font-mono tabular-nums text-slate-900 dark:text-slate-100 leading-none">
            {telemetry?.avg_latency_ms?.toFixed(2) || '—'}
            <span className="text-sm font-normal text-muted-foreground ml-2">ms</span>
          </div>
          <div className="mt-3">
            <Progress 
              value={telemetry ? Math.min((telemetry.avg_latency_ms || 0) / 100 * 100, 100) : 0}
              className="h-2" 
            />
            <p className="text-xs font-sans text-slate-500 dark:text-slate-400 mt-1 leading-relaxed">Target: &lt;50ms</p>
          </div>
        </CardContent>
      </Card>

      {/* Throughput */}
      <Card className="bg-card border-border hover:border-muted-foreground/20 transition-colors">
        <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-3">
          <CardTitle className="text-xs font-sans font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">Total Requests</CardTitle>
          <TrendingUp className="h-4 w-4 text-muted-foreground" />
        </CardHeader>
        <CardContent>
          <div className="text-2xl font-black font-mono tabular-nums text-slate-900 dark:text-slate-100 leading-none">
            {telemetry?.total_requests?.toLocaleString() || '—'}
          </div>
          <div className="flex items-center gap-2 mt-3">
            <Badge 
              variant={telemetry?.error_rate === 0 ? 'secondary' : 'destructive'}
              className="text-xs px-2 py-1 bg-slate-100 text-slate-500"
            >
              Error Rate: {telemetry ? ((telemetry.error_rate || 0) * 100).toFixed(2) : '—'}%
            </Badge>
          </div>
        </CardContent>
      </Card>

      {/* Queue Depth */}
      <Card className="bg-card border-border hover:border-muted-foreground/20 transition-colors">
        <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-3">
          <CardTitle className="text-xs font-sans font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">Queue Depth</CardTitle>
          <Database className="h-4 w-4 text-muted-foreground" />
        </CardHeader>
        <CardContent>
          <div className="space-y-3">
            <div className="flex justify-between items-center">
              <span className="text-xs font-sans text-slate-500 dark:text-slate-400">Feedback Jobs</span>
              <span className="text-sm font-mono tabular-nums text-slate-900 dark:text-slate-100">
                {currentData?.data?.feedback_jobs_pending ?? '—'}
              </span>
            </div>
            <div className="flex justify-between items-center">
              <span className="text-xs font-sans text-slate-500 dark:text-slate-400">Scoring Jobs</span>
              <span className="text-sm font-mono tabular-nums text-slate-900 dark:text-slate-100">
                {currentData?.data?.scoring_pending ?? '—'}
              </span>
            </div>
            {(currentData?.data?.feedback_jobs_failed || 0) > 0 && (
              <div className="flex items-center gap-1 text-rose-600 dark:text-rose-400">
                <AlertTriangle className="h-3 w-3" />
                <span className="text-xs leading-relaxed">
                  {currentData?.data?.feedback_jobs_failed ?? 0} failed jobs
                </span>
              </div>
            )}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
