"use client";

import { useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Copy, Trash2, ChevronDown, ChevronUp, Terminal } from "lucide-react";
import { cn } from "@/lib/utils";

interface LogEntry {
  id: string;
  timestamp: string;
  level: "info" | "warning" | "error" | "success";
  message: string;
  details?: string;
}

interface LogViewerProps {
  logs: LogEntry[];
  title?: string;
  maxHeight?: string;
  showTimestamp?: boolean;
  className?: string;
}

export function LogViewer({
  logs,
  title = "System Logs",
  maxHeight = "400px",
  showTimestamp = true,
  className,
}: LogViewerProps) {
  const [isExpanded, setIsExpanded] = useState(false);
  const [copiedId, setCopiedId] = useState<string | null>(null);

  const getLevelConfig = (level: LogEntry["level"]) => {
    switch (level) {
      case "error":
        return {
          bg: "bg-rose-500/10",
          text: "text-rose-400",
          border: "border-rose-500/30",
          icon: "●",
        };
      case "warning":
        return {
          bg: "bg-amber-500/10",
          text: "text-amber-400",
          border: "border-amber-500/30",
          icon: "▲",
        };
      case "success":
        return {
          bg: "bg-emerald-500/10",
          text: "text-emerald-400",
          border: "border-emerald-500/30",
          icon: "✓",
        };
      default:
        return {
          bg: "bg-slate-500/10",
          text: "text-slate-400",
          border: "border-slate-500/30",
          icon: "○",
        };
    }
  };

  const copyToClipboard = async (log: LogEntry) => {
    const text = `[${log.timestamp}] [${log.level.toUpperCase()}] ${log.message}${log.details ? `\n${log.details}` : ""}`;
    try {
      await navigator.clipboard.writeText(text);
      setCopiedId(log.id);
      setTimeout(() => setCopiedId(null), 2000);
    } catch (err) {
      console.error("Failed to copy log:", err);
    }
  };

  const clearLogs = () => {
    // This would typically be handled by a parent component
    if (process.env.NODE_ENV !== "production")
      console.warn("Clear logs requested");
  };

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      className={cn("glass-card overflow-hidden", className)}
    >
      {/* Header */}
      <div
        className="flex items-center justify-between p-4 cursor-pointer hover:bg-slate-800/30 transition-colors"
        onClick={() => setIsExpanded(!isExpanded)}
      >
        <div className="flex items-center gap-3">
          <Terminal className="h-4 w-4 text-slate-400" />
          <h3 className="text-[10px] font-semibold uppercase tracking-[0.2em] text-slate-500">
            {title}
          </h3>
          <motion.div
            className="w-2 h-2 rounded-full bg-emerald-500"
            animate={{
              scale: [1, 1.2, 1],
              opacity: [1, 0.8, 1],
            }}
            transition={{
              duration: 2,
              repeat: Infinity,
            }}
          />
        </div>

        <div className="flex items-center gap-2">
          <span className="text-xs text-slate-500 font-mono">
            {logs.length} entries
          </span>
          {isExpanded ? (
            <ChevronUp className="h-4 w-4 text-slate-400" />
          ) : (
            <ChevronDown className="h-4 w-4 text-slate-400" />
          )}
        </div>
      </div>

      {/* Log Content */}
      <AnimatePresence>
        {isExpanded && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.3 }}
            className="border-t border-slate-800/60"
          >
            <div
              className="p-4 font-mono text-xs overflow-y-auto"
              style={{ maxHeight }}
            >
              {logs.length === 0 ? (
                <div className="text-center py-8">
                  <Terminal className="h-8 w-8 text-slate-600 mx-auto mb-2" />
                  <p className="text-slate-500">No logs available</p>
                </div>
              ) : (
                <div className="space-y-2">
                  {logs.map((log, index) => {
                    const config = getLevelConfig(log.level);
                    return (
                      <motion.div
                        key={log.id}
                        initial={{ opacity: 0, x: -20 }}
                        animate={{ opacity: 1, x: 0 }}
                        transition={{ delay: index * 0.05 }}
                        className={cn(
                          "group rounded-lg border p-3 transition-all duration-200",
                          config.bg,
                          config.border,
                        )}
                      >
                        <div className="flex items-start justify-between gap-3">
                          <div className="flex-1 min-w-0">
                            {/* Header line */}
                            <div className="flex items-center gap-2 mb-1">
                              <span
                                className={cn(
                                  "text-xs",
                                  config.icon,
                                  config.text,
                                )}
                              />
                              {showTimestamp && (
                                <span className="text-slate-500 font-mono text-[10px]">
                                  {log.timestamp}
                                </span>
                              )}
                              <span
                                className={cn(
                                  "text-xs font-semibold uppercase",
                                  config.text,
                                )}
                              >
                                {log.level}
                              </span>
                            </div>

                            {/* Message */}
                            <div className="text-slate-300 leading-relaxed break-words">
                              {log.message}
                            </div>

                            {/* Details */}
                            {log.details && (
                              <motion.div
                                initial={{ opacity: 0, height: 0 }}
                                animate={{ opacity: 1, height: "auto" }}
                                className="mt-2 text-slate-500 text-[10px] bg-slate-900/50 p-2 rounded border border-slate-700/50"
                              >
                                <pre className="whitespace-pre-wrap">
                                  {log.details}
                                </pre>
                              </motion.div>
                            )}
                          </div>

                          {/* Actions */}
                          <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                            <button
                              onClick={(e) => {
                                e.stopPropagation();
                                copyToClipboard(log);
                              }}
                              className="p-1.5 rounded hover:bg-slate-700/50 transition-colors"
                              title="Copy log"
                            >
                              <Copy className="h-3 w-3 text-slate-400" />
                            </button>
                          </div>
                        </div>

                        {/* Copy confirmation */}
                        <AnimatePresence>
                          {copiedId === log.id && (
                            <motion.div
                              initial={{ opacity: 0, y: -10 }}
                              animate={{ opacity: 1, y: 0 }}
                              exit={{ opacity: 0, y: -10 }}
                              className="absolute right-2 top-2 text-xs text-emerald-400 bg-slate-900 px-2 py-1 rounded"
                            >
                              Copied!
                            </motion.div>
                          )}
                        </AnimatePresence>
                      </motion.div>
                    );
                  })}
                </div>
              )}
            </div>

            {/* Footer actions */}
            {logs.length > 0 && (
              <div className="border-t border-slate-800/60 p-3 flex justify-between items-center">
                <span className="text-xs text-slate-500">
                  Showing {logs.length} most recent entries
                </span>
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    clearLogs();
                  }}
                  className="flex items-center gap-2 px-3 py-1.5 text-xs rounded-lg bg-rose-500/10 text-rose-400 border border-rose-500/30 hover:bg-rose-500/20 transition-colors"
                >
                  <Trash2 className="h-3 w-3" />
                  Clear All
                </button>
              </div>
            )}
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  );
}
