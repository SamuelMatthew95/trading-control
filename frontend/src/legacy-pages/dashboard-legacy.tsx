import { useEffect, useState, useRef } from 'react';
import { Sidebar } from '@/components/mission-control/Sidebar';
import { SystemVitals } from '@/components/mission-control/SystemVitals';
import { BotControl } from '@/components/mission-control/BotControl';
import { Header } from '@/components/layout/Header';
import { useHealthCheck } from '@/hooks/useHealthCheck';
import { AlertCircle } from 'lucide-react';

export default function ExecutiveDashboard() {
  const prevDataRef = useRef<unknown>(null);
  const [connectionIssue, setConnectionIssue] = useState(false);
  const { data: healthData, isLoading: healthLoading, error, refetch } = useHealthCheck();

  // Update ref when new data arrives
  useEffect(() => {
    if (healthData) {
      prevDataRef.current = healthData;
      setConnectionIssue(false);
    } else if (error) {
      setConnectionIssue(true);
    }
  }, [healthData, error]);

  const displayData = healthData || prevDataRef.current;

  const handleRetry = () => {
    refetch();
  };

  return (
    <div className="flex h-screen bg-background">
      <Sidebar />
      <div className="flex-1 flex flex-col">
        <Header title="Dashboard" subtitle="System vital signs and bot control" />
        <main className="flex-1 overflow-y-auto p-6">
          {/* System Vitals Grid */}
          <section className="mb-8">
            <div className="flex items-center justify-between mb-3">
              <h2 className="text-[0.7rem] uppercase tracking-widest text-slate-500">System Vital Signs</h2>
            </div>
            
            {/* Error State */}
            {connectionIssue && (
              <div className="mb-4 bg-red-50 border border-red-200 rounded-md px-4 py-2 dark:bg-red-950/30 dark:border-red-800">
                <div className="flex items-center">
                  <AlertCircle size={14} className="text-red-500 mr-2" />
                  <span className="text-red-600 dark:text-red-400 text-sm">Backend unreachable — showing cached data</span>
                  <button 
                    onClick={handleRetry}
                    className="ml-auto text-red-500 dark:text-red-400 text-xs underline hover:no-underline"
                  >
                    Retry
                  </button>
                </div>
              </div>
            )}
            
            <SystemVitals health={displayData} isLoading={healthLoading && !prevDataRef.current} />
          </section>

          {/* Bot Control */}
          <section className="mb-8">
            <BotControl health={displayData} error={error} onRetry={handleRetry} />
          </section>
        </main>
      </div>
    </div>
  );
}
