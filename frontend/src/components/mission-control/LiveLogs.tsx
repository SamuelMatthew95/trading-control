import { useState, useEffect, useRef } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Terminal, Download, Trash2, Pause, Play } from 'lucide-react';
import type { LogEntry } from '@/types/log-entry';

const mockLogs: LogEntry[] = [
  {
    id: '1',
    timestamp: new Date().toISOString(),
    level: 'info',
    message: 'Interacting with Agent...',
    source: 'trading-engine'
  },
  {
    id: '2',
    timestamp: new Date(Date.now() - 1000).toISOString(),
    level: 'success',
    message: 'Executing Trade: BUY AAPL @ 175.23',
    source: 'order-executor'
  },
  {
    id: '3',
    timestamp: new Date(Date.now() - 2000).toISOString(),
    level: 'warning',
    message: 'High latency detected: 125ms',
    source: 'monitor'
  },
  {
    id: '4',
    timestamp: new Date(Date.now() - 3000).toISOString(),
    level: 'info',
    message: 'Scoring feedback job completed successfully',
    source: 'feedback-processor'
  },
  {
    id: '5',
    timestamp: new Date(Date.now() - 4000).toISOString(),
    level: 'error',
    message: 'Database connection timeout',
    source: 'database'
  }
];

export function LiveLogs() {
  const [logs, setLogs] = useState<LogEntry[]>(mockLogs);
  const [isPaused, setIsPaused] = useState(false);
  const [autoScroll, setAutoScroll] = useState(true);
  const logsEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (isPaused) return;

    const interval = setInterval(() => {
      const newLog: LogEntry = {
        id: Date.now().toString(),
        timestamp: new Date().toISOString(),
        level: ['info', 'success', 'warning', 'error'][Math.floor(Math.random() * 4)] as LogEntry['level'],
        message: [
          'Interacting with Agent...',
          'Executing Trade: ' + (Math.random() > 0.5 ? 'BUY' : 'SELL') + ' ' + ['AAPL', 'GOOGL', 'MSFT', 'TSLA'][Math.floor(Math.random() * 4)] + ' @ ' + (Math.random() * 200 + 100).toFixed(2),
          'Scoring feedback job completed',
          'Health check passed',
          'Cache cleared successfully',
          'Market data updated'
        ][Math.floor(Math.random() * 6)],
        source: ['trading-engine', 'order-executor', 'monitor', 'feedback-processor', 'database'][Math.floor(Math.random() * 5)]
      };

      setLogs(prev => [...prev.slice(-49), newLog]);
    }, Math.random() * 3000 + 2000); // Random interval between 2-5 seconds

    return () => clearInterval(interval);
  }, [isPaused]);

  useEffect(() => {
    if (autoScroll) {
      logsEndRef.current?.scrollIntoView({ behavior: 'smooth' });
    }
  }, [logs, autoScroll]);

  const getLevelColor = (level: LogEntry['level']) => {
    switch (level) {
      case 'info': return 'text-info';
      case 'success': return 'text-success';
      case 'warning': return 'text-warning';
      case 'error': return 'text-destructive';
      default: return 'text-muted-foreground';
    }
  };

  const getLevelBadge = (level: LogEntry['level']) => {
    switch (level) {
      case 'info': return 'bg-info/10 text-info border border-info/20';
      case 'success': return 'bg-success/10 text-success border border-success/20';
      case 'warning': return 'bg-warning/10 text-warning border border-warning/20';
      case 'error': return 'bg-destructive/10 text-destructive border border-destructive/20';
      default: return 'bg-muted/10 text-muted-foreground border border-muted/20';
    }
  };

  const clearLogs = () => {
    setLogs([]);
  };

  const downloadLogs = () => {
    const logText = logs.map(log => 
      `[${log.timestamp}] ${log.level.toUpperCase()} [${log.source || 'system'}] ${log.message}`
    ).join('\n');
    
    const blob = new Blob([logText], { type: 'text/plain' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `trading-logs-${new Date().toISOString().split('T')[0]}.txt`;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <Card className="bg-card border-border">
      <CardHeader className="flex flex-row items-center justify-between space-y-0">
        <CardTitle className="text-base font-semibold text-foreground flex items-center gap-2">
          <Terminal className="h-5 w-5" />
          Live Logs
        </CardTitle>
        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={() => setIsPaused(!isPaused)}
            className="border-border text-muted-foreground hover:text-foreground"
          >
            {isPaused ? <Play className="h-4 w-4 mr-1" /> : <Pause className="h-4 w-4 mr-1" />}
            {isPaused ? 'Resume' : 'Pause'}
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={downloadLogs}
            className="border-border text-muted-foreground hover:text-foreground"
          >
            <Download className="h-4 w-4 mr-1" />
            Export
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={clearLogs}
            className="border-border text-muted-foreground hover:text-foreground"
          >
            <Trash2 className="h-4 w-4 mr-1" />
            Clear
          </Button>
        </div>
      </CardHeader>
      <CardContent>
        <div className="bg-[#0d0d0d] dark:bg-[#0d0d0d] rounded-lg p-0 font-mono text-sm h-96 overflow-y-auto border border-border">
          {logs.length === 0 ? (
            <div className="text-muted-foreground text-center py-8">
              No logs available. Start the bot to see real-time logs.
            </div>
          ) : (
            <div className="divide-y divide-border/20">
              {logs.map((log, index) => (
                <div 
                  key={log.id} 
                  className={`flex items-start gap-3 py-3 px-4 ${
                    index % 2 === 1 ? 'bg-muted/5' : ''
                  }`}
                >
                  <span className="text-muted-foreground text-xs font-mono shrink-0 w-16">
                    {new Date(log.timestamp).toLocaleTimeString()}
                  </span>
                  <Badge 
                    className={`text-xs font-mono uppercase w-[72px] justify-center ${getLevelBadge(log.level)}`}
                  >
                    {log.level}
                  </Badge>
                  {log.source && (
                    <span className="text-muted-foreground text-xs font-mono shrink-0">
                      [{log.source}]
                    </span>
                  )}
                  <span className={`flex-1 text-sm font-sans ${getLevelColor(log.level)}`}>
                    {log.message}
                  </span>
                </div>
              ))}
              <div ref={logsEndRef} />
            </div>
          )}
        </div>
        {logs.length > 0 && (
          <div className="mt-3 flex items-center justify-between">
            <span className="text-xs text-muted-foreground">
              Showing {logs.length} log entries
            </span>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setAutoScroll(!autoScroll)}
              className="text-xs text-muted-foreground hover:text-foreground"
            >
              Auto-scroll: {autoScroll ? 'ON' : 'OFF'}
            </Button>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
