/**
 * Presentational primitives for the System dashboard panels.
 */
import { cn } from "@/lib/utils";
import type { StatusTone } from "./types";
import type { DecisionAction } from "./derive";

export const LABEL_CLASS =
  "text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400";
export const VALUE_CLASS =
  "font-mono text-sm tabular-nums text-slate-900 dark:text-slate-100";
export const ROW_DIVIDER_CLASS = "border-slate-200 dark:border-slate-800/70";

export type HealthIndicator = {
  label: string;
  tone: StatusTone;
  value: string;
};

export function statusToneClass(tone: StatusTone): string {
  switch (tone) {
    case "ok":
      return "bg-success ring-success/30";
    case "warn":
      return "bg-warning ring-warning/30";
    case "err":
      return "bg-danger ring-danger/30";
    default:
      return "bg-slate-400 ring-slate-400/30 dark:bg-slate-500 dark:ring-slate-500/30";
  }
}

export function actionClass(action: DecisionAction): string {
  switch (action) {
    case "BUY":
      return "text-success bg-success/10 ring-success/30";
    case "SELL":
      return "text-danger bg-danger/10 ring-danger/30";
    case "SKIP":
      return "text-warning bg-warning/10 ring-warning/30";
    default:
      return "text-slate-600 bg-slate-400/10 ring-slate-400/30 dark:text-slate-300 dark:bg-slate-400/10";
  }
}

export function KpiStrip({
  label,
  value,
  tone = "neutral",
}: {
  label: string;
  value: string;
  tone?: StatusTone;
}) {
  return (
    <div
      className={cn(
        "border-b px-3 py-2 last:border-b-0",
        ROW_DIVIDER_CLASS,
      )}
    >
      <p className={LABEL_CLASS}>{label}</p>
      <p
        className={cn(
          VALUE_CLASS,
          tone === "ok" && "text-success",
          tone === "warn" && "text-warning",
          tone === "err" && "text-danger",
        )}
      >
        {value}
      </p>
    </div>
  );
}

export function StatePill({ label, tone, value }: HealthIndicator) {
  return (
    <div
      className={cn(
        "flex items-center justify-between gap-3 border-b px-3 py-2 last:border-b-0",
        ROW_DIVIDER_CLASS,
      )}
    >
      <div className="flex items-center gap-2">
        <span
          className={cn("h-2 w-2 rounded-full ring-4", statusToneClass(tone))}
          aria-hidden="true"
        />
        <span className="text-xs font-medium text-slate-700 dark:text-slate-200">
          {label}
        </span>
      </div>
      <span className="font-mono text-[11px] uppercase tracking-wide text-slate-500 dark:text-slate-400">
        {value}
      </span>
    </div>
  );
}

