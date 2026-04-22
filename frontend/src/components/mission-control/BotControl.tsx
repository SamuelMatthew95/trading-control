import { useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { useBotControl } from "@/hooks/useHealthCheck";
import { HealthResponse } from "@/types/health";
import { Power, Play, Square, Loader2, AlertCircle } from "lucide-react";

interface BotControlProps {
  health: HealthResponse | undefined;
  error?: Error;
  onRetry?: () => void;
}

export function BotControl({ health, error, onRetry }: BotControlProps) {
  const [isConfirming, setIsConfirming] = useState(false);
  const { startBot, stopBot } = useBotControl();

  const isRunning = health?.data?.status === "healthy";
  const isLoading = startBot.isPending || stopBot.isPending;

  const handleStart = () => {
    startBot.mutate();
  };

  const handleStop = () => {
    if (isConfirming) {
      stopBot.mutate();
      setIsConfirming(false);
    } else {
      setIsConfirming(true);
    }
  };

  const handleCancel = () => {
    setIsConfirming(false);
  };

  return (
    <Card className="bg-card border-border">
      <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-4">
        <CardTitle className="text-base font-semibold text-foreground">
          Bot Control
        </CardTitle>
        <Badge
          variant={isRunning ? "default" : "secondary"}
          className="px-2.5 py-0.5 text-[0.75rem] font-medium rounded-full bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400"
        >
          {isRunning ? "Running" : "Stopped"}
        </Badge>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* Error State */}
        {error && (
          <div className="bg-red-50 border border-red-200 rounded-md px-4 py-2 dark:bg-red-950/30 dark:border-red-800">
            <div className="flex items-center">
              <AlertCircle size={14} className="text-red-500 mr-2" />
              <span className="text-red-600 dark:text-red-400 text-sm">
                Could not fetch bot status
              </span>
              <button
                onClick={onRetry}
                className="ml-auto text-red-500 dark:text-red-400 text-xs underline hover:no-underline"
              >
                Retry
              </button>
            </div>
          </div>
        )}

        {/* Status Display */}
        <div className="flex items-center justify-between p-4 rounded-lg bg-secondary/50">
          <div className="space-y-1">
            <div className="flex items-center gap-2">
              <div
                className={`w-2 h-2 rounded-full ${isRunning ? "bg-success" : "bg-warning"} animate-pulse`}
              />
              <span className="text-sm font-medium text-foreground">
                Trading Bot {isRunning ? "Active" : "Inactive"}
              </span>
            </div>
            <p className="text-xs text-muted-foreground leading-relaxed">
              {isRunning
                ? "The bot is currently processing trades and monitoring markets."
                : "The bot is stopped and not processing any trades."}
            </p>
          </div>

          {/* Control Buttons */}
          <div className="flex gap-2">
            {!isRunning ? (
              <Button
                onClick={handleStart}
                disabled={isLoading}
                className="bg-success hover:bg-success/90 text-primary-foreground rounded-md px-4 py-2"
              >
                {isLoading ? (
                  <Loader2 className="h-4 w-4 animate-spin mr-2" />
                ) : (
                  <Play className="h-4 w-4 mr-2" />
                )}
                Start Bot
              </Button>
            ) : (
              <>
                {!isConfirming ? (
                  <Button
                    onClick={handleStop}
                    disabled={isLoading}
                    variant="destructive"
                    className="rounded-md px-4 py-2"
                  >
                    {isLoading ? (
                      <Loader2 className="h-4 w-4 animate-spin mr-2" />
                    ) : (
                      <Square className="h-4 w-4 mr-2" />
                    )}
                    Stop Bot
                  </Button>
                ) : (
                  <div className="flex gap-2">
                    <Button
                      onClick={handleStop}
                      disabled={isLoading}
                      variant="destructive"
                      size="sm"
                      className="rounded-md px-3 py-2"
                    >
                      <Power className="h-4 w-4 mr-1" />
                      Confirm Stop
                    </Button>
                    <Button
                      onClick={handleCancel}
                      variant="outline"
                      size="sm"
                      className="border-border rounded-md px-3 py-2"
                    >
                      Cancel
                    </Button>
                  </div>
                )}
              </>
            )}
          </div>
        </div>

        {/* System Health Indicators */}
        <div className="grid grid-cols-2 gap-4">
          <div className="flex items-center justify-between p-3 rounded-lg bg-secondary/30">
            <span className="text-xs text-muted-foreground">Database</span>
            <Badge
              variant={
                health?.data?.database_connected ? "default" : "destructive"
              }
              className="px-2 py-1 text-xs"
            >
              {health?.data?.database_connected ? "Connected" : "Disconnected"}
            </Badge>
          </div>
          <div className="flex items-center justify-between p-3 rounded-lg bg-secondary/30">
            <span className="text-xs text-muted-foreground">Error Rate</span>
            <Badge
              variant={
                health?.data?.telemetry?.error_rate === 0
                  ? "default"
                  : "destructive"
              }
              className="px-2 py-1 text-xs"
            >
              {((health?.data?.telemetry?.error_rate || 0) * 100).toFixed(2)}%
            </Badge>
          </div>
        </div>

        {/* Warning Message */}
        {isConfirming && (
          <div className="p-3 rounded-lg bg-destructive/10 border border-destructive/20">
            <p className="text-sm text-destructive leading-relaxed">
              ⚠️ Stopping the bot will immediately halt all trading operations.
              Make sure this is what you want to do.
            </p>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
