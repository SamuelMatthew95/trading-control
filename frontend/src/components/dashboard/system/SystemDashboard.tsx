"use client";

import { useMemo } from "react";

import { cn } from "@/lib/utils";
import {
  formatPercent,
  formatTimestamp,
  signedUSD,
  toFiniteNum as toFiniteNumber,
} from "@/lib/formatters";
import {
  consoleHeaderClass,
  consolePanelClass,
  sectionTitleClass,
} from "@/lib/dashboard-styles";
import {
  ALL_AGENT_NAMES,
  agentDisplayName,
  canonicalAgentKey,
} from "@/constants/agents";
import type {
  AgentLog,
  AgentStatus,
  Notification,
  Order,
  Proposal,
} from "@/stores/useCodexStore";

import { computePipeline } from "./helpers";
import type { StatusTone, SystemDashboardProps } from "./types";

type DecisionAction = "BUY" | "SELL" | "SKIP" | "HOLD";

type DecisionFeedItem = {
  id: string;
  timestamp: string | null;
  action: DecisionAction;
  symbol: string;
  confidence: number | null;
  reason: string[];
  traceId: string | null;
  source: "decision" | "order" | "notification";
};

type HealthIndicator = {
  label: string;
  tone: StatusTone;
  value: string;
};

type AgentActivityRow = {
  key: string;
  label: string;
  status?: AgentStatus;
  relatedLog?: AgentLog;
};

const SURFACED_DECISION_LIMIT = 48;
const TRACE_COLUMNS = [
  "Signal",
  "Reasoning",
  "Risk Evaluation",
  "Position Sizing",
  "Execution",
  "Outcome",
] as const;

// Dual-theme surface classes shared with the rest of the dashboard. Light is the
// base utility; the dark "operator console" look is the `dark:` variant so the
// System page renders coherently in either theme (next-themes / ThemeToggle).
const PANEL_CLASS = consolePanelClass;
const PANEL_HEADER_CLASS = consoleHeaderClass;
const PANEL_TITLE_CLASS = sectionTitleClass;
const LABEL_CLASS =
  "text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400";
const VALUE_CLASS =
  "font-mono text-sm tabular-nums text-slate-900 dark:text-slate-100";
const ROW_DIVIDER_CLASS = "border-slate-200 dark:border-slate-800/70";

function parseTimestamp(value: unknown): Date | null {
  if (value == null) return null;
  if (value instanceof Date)
    return Number.isNaN(value.getTime()) ? null : value;
  if (typeof value === "number") {
    if (!Number.isFinite(value) || value <= 0) return null;
    const date = new Date(value > 10_000_000_000 ? value : value * 1000);
    return Number.isNaN(date.getTime()) ? null : date;
  }
  const raw = String(value).trim();
  if (!raw) return null;
  const date = new Date(raw);
  return Number.isNaN(date.getTime()) ? null : date;
}

function timestampMs(value: unknown): number {
  return parseTimestamp(value)?.getTime() ?? 0;
}

// Start of the current UTC trading day. Used to scope the Daily PnL headline to
// today's orders instead of summing the whole recent-orders window.
function startOfUtcDayMs(now: number): number {
  const date = new Date(now);
  return Date.UTC(date.getUTCFullYear(), date.getUTCMonth(), date.getUTCDate());
}

function formatClock(value: string | null): string {
  const date = parseTimestamp(value);
  if (!date) return "--:--:--";
  return new Intl.DateTimeFormat("en-US", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  }).format(date);
}

function formatAge(secondsAgo: number | null | undefined): string {
  const seconds = toFiniteNumber(secondsAgo);
  if (seconds == null || seconds < 0) return "--";
  if (seconds < 60) return `${Math.round(seconds)}s ago`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  return `${Math.floor(minutes / 60)}h ago`;
}

function normalizeAction(value: unknown): DecisionAction {
  const raw = String(value ?? "").toUpperCase();
  if (raw === "BUY" || raw === "LONG") return "BUY";
  if (raw === "SELL" || raw === "SHORT" || raw === "EXIT") return "SELL";
  if (raw === "SKIP" || raw === "REJECT") return "SKIP";
  return "HOLD";
}

function compactReason(value: unknown, fallback: string): string[] {
  if (Array.isArray(value)) {
    return value
      .map((item) => String(item).trim())
      .filter(Boolean)
      .slice(0, 4);
  }
  const text = String(value ?? "").trim();
  if (!text) return [fallback];
  return text
    .split(/\n|;|•|\. /)
    .map((part) => part.replace(/^-\s*/, "").trim())
    .filter(Boolean)
    .slice(0, 4);
}

function statusToneClass(tone: StatusTone): string {
  switch (tone) {
    case "ok":
      return "bg-emerald-500 ring-emerald-500/30 dark:bg-emerald-400 dark:ring-emerald-400/30";
    case "warn":
      return "bg-amber-500 ring-amber-500/30 dark:bg-amber-400 dark:ring-amber-400/30";
    case "err":
      return "bg-rose-500 ring-rose-500/30 dark:bg-rose-400 dark:ring-rose-400/30";
    default:
      return "bg-slate-400 ring-slate-400/30 dark:bg-slate-500 dark:ring-slate-500/30";
  }
}

function actionClass(action: DecisionAction): string {
  switch (action) {
    case "BUY":
      return "text-emerald-700 bg-emerald-500/10 ring-emerald-500/30 dark:text-emerald-300 dark:bg-emerald-400/10 dark:ring-emerald-400/30";
    case "SELL":
      return "text-rose-700 bg-rose-500/10 ring-rose-500/30 dark:text-rose-300 dark:bg-rose-400/10 dark:ring-rose-400/30";
    case "SKIP":
      return "text-amber-700 bg-amber-500/10 ring-amber-500/30 dark:text-amber-300 dark:bg-amber-400/10 dark:ring-amber-400/30";
    default:
      return "text-slate-600 bg-slate-400/10 ring-slate-400/30 dark:text-slate-300 dark:bg-slate-400/10";
  }
}

function resolveHealthTone(status: string | null | undefined): StatusTone {
  const value = String(status ?? "").toLowerCase();
  if (
    ["running", "live", "active", "ok", "healthy", "connected"].some((token) =>
      value.includes(token),
    )
  )
    return "ok";
  if (
    ["failed", "error", "down", "offline"].some((token) =>
      value.includes(token),
    )
  )
    return "err";
  if (
    ["stale", "warn", "degraded", "idle"].some((token) => value.includes(token))
  )
    return "warn";
  return "neutral";
}

function deriveDecisionFeed({
  agentLogs,
  notifications,
  orders,
}: {
  agentLogs: AgentLog[];
  notifications: Notification[];
  orders: Order[];
}): DecisionFeedItem[] {
  const fromLogs = agentLogs
    .filter((log) => {
      const event = String(log.event_type ?? log.stream ?? "").toLowerCase();
      return (
        event.includes("decision") ||
        log.action != null ||
        log.symbol != null ||
        log.primary_edge != null
      );
    })
    .map(
      (log, index): DecisionFeedItem => ({
        id: `log-${String(log.id ?? log.trace_id ?? index)}`,
        timestamp: String(log.timestamp ?? log.created_at ?? ""),
        action: normalizeAction(log.action ?? log.event_type),
        symbol: String(
          log.symbol ??
            (log.data as Record<string, unknown> | null)?.symbol ??
            "SYSTEM",
        ),
        confidence: toFiniteNumber(log.confidence),
        reason: compactReason(
          log.primary_edge ?? log.message,
          "Agent recorded a decision event.",
        ),
        traceId: log.trace_id ? String(log.trace_id) : null,
        source: "decision",
      }),
    );

  const fromOrders = orders.map(
    (order, index): DecisionFeedItem => ({
      id: `order-${String(order.order_id ?? index)}`,
      timestamp: String(
        order.timestamp ?? order.filled_at ?? order.created_at ?? "",
      ),
      action: normalizeAction(order.side === "short" ? "SELL" : order.side),
      symbol: String(order.symbol ?? "ORDER"),
      confidence: toFiniteNumber(order.confidence),
      reason: compactReason(
        order.reason ?? order.primary_edge,
        order.pnl != null
          ? `Execution updated P&L to ${signedUSD(order.pnl)}.`
          : "Execution state changed.",
      ),
      traceId: order.trace_id ? String(order.trace_id) : null,
      source: "order",
    }),
  );

  const fromNotifications = notifications
    .filter(
      (notification) =>
        notification.action || notification.symbol || notification.trace_id,
    )
    .map(
      (notification): DecisionFeedItem => ({
        id: `notification-${notification.id}`,
        timestamp: notification.timestamp,
        action: normalizeAction(
          notification.action ?? notification.notification_type,
        ),
        symbol: notification.symbol ?? "SYSTEM",
        confidence: null,
        reason: compactReason(
          notification.message,
          "Operator notification emitted.",
        ),
        traceId: notification.trace_id ?? null,
        source: "notification",
      }),
    );

  return [...fromLogs, ...fromOrders, ...fromNotifications]
    .sort((a, b) => timestampMs(b.timestamp) - timestampMs(a.timestamp))
    .slice(0, SURFACED_DECISION_LIMIT);
}

// Build one activity row per canonical agent (plus any extra agent seen in live
// statuses), matched to heartbeats and logs by canonical key. This replaces the
// previous hardcoded news/macro/proposal/risk labels that matched no real agent.
function deriveAgentActivity({
  agentStatuses,
  agentLogs,
}: {
  agentStatuses: AgentStatus[];
  agentLogs: AgentLog[];
}): AgentActivityRow[] {
  const canonicalStatuses = agentStatuses.map((status) => ({
    key: canonicalAgentKey(String(status.name ?? "")),
    status,
  }));

  const keys: string[] = [...ALL_AGENT_NAMES];
  canonicalStatuses.forEach(({ key }) => {
    if (key && !keys.includes(key)) keys.push(key);
  });

  return keys.map((key) => {
    const status = canonicalStatuses.find((entry) => entry.key === key)?.status;
    const relatedLog = agentLogs.find(
      (log) =>
        canonicalAgentKey(String(log.agent_name ?? log.agent ?? "")) === key,
    );
    return {
      key,
      label: agentDisplayName(key),
      status,
      relatedLog,
    };
  });
}

function proposalLabel(proposal: Proposal): string {
  return (
    proposal.content ||
    proposal.strategy_name ||
    proposal.proposal_type.replace(/_/g, " ")
  );
}

function KpiStrip({
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
          tone === "ok" && "text-emerald-600 dark:text-emerald-300",
          tone === "warn" && "text-amber-600 dark:text-amber-300",
          tone === "err" && "text-rose-600 dark:text-rose-300",
        )}
      >
        {value}
      </p>
    </div>
  );
}

function StatePill({ label, tone, value }: HealthIndicator) {
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

export function SystemDashboard(props: SystemDashboardProps) {
  const pipeline = useMemo(
    () =>
      computePipeline({
        streamStats: props.streamStats,
        recentEvents: props.recentEvents,
        wsLastMessageTimestamp: props.wsLastMessageTimestamp,
        wsMessageRate: props.wsDiagnostics.messageRate,
      }),
    [
      props.streamStats,
      props.recentEvents,
      props.wsLastMessageTimestamp,
      props.wsDiagnostics.messageRate,
    ],
  );

  const decisionFeed = useMemo(
    () =>
      deriveDecisionFeed({
        agentLogs: props.agentLogs,
        notifications: props.notifications,
        orders: props.orders,
      }),
    [props.agentLogs, props.notifications, props.orders],
  );

  const agentActivity = useMemo(
    () =>
      deriveAgentActivity({
        agentStatuses: props.agentStatuses,
        agentLogs: props.agentLogs,
      }),
    [props.agentStatuses, props.agentLogs],
  );

  const selectedDecision = decisionFeed[0] ?? null;
  const netPnl =
    props.resolvedPerformanceSummary?.total_pnl ??
    props.orders.reduce(
      (sum, order) => sum + (toFiniteNumber(order.pnl) ?? 0),
      0,
    );
  const dayStartMs = startOfUtcDayMs(Date.now());
  const dailyPnl = props.orders.reduce((sum, order) => {
    const orderMs = timestampMs(
      order.timestamp ?? order.filled_at ?? order.created_at,
    );
    if (orderMs < dayStartMs) return sum;
    return sum + (toFiniteNumber(order.pnl) ?? 0);
  }, 0);
  const openExposure = props.positions.reduce((sum, position) => {
    const quantity = Math.abs(toFiniteNumber(position.quantity) ?? 0);
    const price =
      toFiniteNumber(position.current_price) ??
      toFiniteNumber(position.entry_price) ??
      0;
    return sum + quantity * price;
  }, 0);
  const activePositions = props.positions.filter(
    (position) => position.side === "long" || position.side === "short",
  ).length;
  const recentRiskAlert = props.riskAlerts[0];
  const riskState = recentRiskAlert
    ? String(recentRiskAlert.severity ?? recentRiskAlert.status ?? "Review")
    : pipeline.pipelineStatus === "Healthy"
      ? "Acceptable"
      : "Review";

  // Dashboard read-path health: a `/dashboard/state` failure surfaces as
  // systemFeedError / apiHealth.dashboardState='error'. Surface it explicitly so
  // an outage is not masked by otherwise-generic indicators.
  const dashboardApiDown =
    Boolean(props.systemFeedError) || props.apiHealth.dashboardState === "error";

  const healthIndicators: HealthIndicator[] = [
    {
      label: "Kill Switch",
      tone: props.killSwitchActive ? "err" : "ok",
      value: props.killSwitchActive ? "Engaged" : "Clear",
    },
    {
      label: "Trading Enabled",
      tone: props.killSwitchActive ? "err" : "ok",
      value: props.killSwitchActive ? "Disabled" : "Enabled",
    },
    {
      label: "Market Open",
      tone: pipeline.hasMarketData ? "ok" : "warn",
      value: pipeline.hasMarketData ? "Streaming" : "No ticks",
    },
    {
      label: "Data Health",
      tone:
        pipeline.pipelineStatus === "Healthy"
          ? "ok"
          : pipeline.pipelineStatus === "Degraded"
            ? "warn"
            : "err",
      value: pipeline.pipelineStatus,
    },
    {
      label: "LLM Health",
      tone:
        props.llmAvailable === false
          ? "warn"
          : props.llmAvailable === true
            ? "ok"
            : "neutral",
      value:
        props.llmAvailable === false
          ? "Fallback"
          : props.llmProvider || "Unknown",
    },
  ];

  const systemHealth: HealthIndicator[] = [
    {
      label: "Market Data",
      tone: pipeline.hasMarketData ? "ok" : "warn",
      value: `${pipeline.marketStageCount} ticks`,
    },
    {
      label: "WebSocket",
      tone: props.wsConnected ? "ok" : "err",
      value: props.wsConnected
        ? `${props.wsMessageCount} msgs`
        : "Disconnected",
    },
    {
      label: "Dashboard API",
      tone: dashboardApiDown
        ? "err"
        : props.apiHealth.dashboardState === "ok"
          ? "ok"
          : "warn",
      value: dashboardApiDown
        ? "Unreachable"
        : props.apiHealth.dashboardState === "ok"
          ? "Live"
          : props.apiHealth.dashboardState,
    },
    {
      label: "Broker",
      tone: props.streamStats.orders?.count ? "ok" : "neutral",
      value: `${props.streamStats.orders?.count ?? 0} orders`,
    },
    {
      label: "Database",
      tone: props.isInMemoryMode
        ? "warn"
        : props.apiHealth.eventHistory === "ok"
          ? "ok"
          : "err",
      value: props.isInMemoryMode ? "Memory" : props.apiHealth.eventHistory,
    },
    {
      label: "Redis",
      tone: props.wsConnected ? "ok" : "warn",
      value: props.wsConnected ? "Event bus" : "No stream",
    },
    {
      label: "LLM",
      tone:
        props.llmAvailable === false
          ? "warn"
          : props.llmAvailable === true
            ? "ok"
            : "neutral",
      value: props.llmProvider || "Unknown",
    },
  ];

  const approvedProposals = props.proposals.filter(
    (proposal) => proposal.status === "approved",
  );
  const rejectedProposals = props.proposals.filter(
    (proposal) => proposal.status === "rejected",
  );
  const proposalSuccessRate =
    props.proposals.length > 0
      ? approvedProposals.length / props.proposals.length
      : null;

  return (
    <div className="space-y-3 text-slate-900 dark:text-slate-100">
      {dashboardApiDown && (
        <div
          className="flex items-center gap-2 rounded-xl border border-rose-300 bg-rose-50 px-3 py-2 text-xs font-semibold text-rose-700 dark:border-rose-900/50 dark:bg-rose-950/40 dark:text-rose-300"
          role="alert"
        >
          <span className="h-2 w-2 rounded-full bg-rose-500" aria-hidden="true" />
          <span>
            Dashboard API unreachable
            {props.systemFeedError ? ` — ${props.systemFeedError}` : ""}. Live
            data may be stale.
          </span>
        </div>
      )}
      <section
        className="grid grid-cols-1 gap-3 xl:grid-cols-[minmax(0,1fr)_360px]"
        aria-label="Command Center overview"
      >
        {/* self-start: size this card to its single KPI row instead of letting
            the grid stretch it to match the taller Operator Controls panel,
            which left a large empty band of card below the metrics. */}
        <div className={cn(PANEL_CLASS, "self-start")}>
          <div className={PANEL_HEADER_CLASS}>
            <div className="flex items-center justify-between gap-3">
              <div>
                <p className={PANEL_TITLE_CLASS}>Command Center</p>
                <h1 className="mt-1 text-xl font-semibold tracking-tight text-slate-900 dark:text-white">
                  Decisions, risk, execution
                </h1>
              </div>
              <span className="rounded-full border border-slate-300 px-2 py-1 font-mono text-[10px] uppercase tracking-[0.18em] text-slate-500 dark:border-slate-700 dark:text-slate-400">
                {props.isInMemoryMode ? "Paper / memory" : "Live capable"}
              </span>
            </div>
          </div>
          <div
            className={cn(
              "grid grid-cols-2 divide-x divide-y md:grid-cols-3 xl:grid-cols-6 xl:divide-y-0",
              "divide-slate-200 dark:divide-slate-800/70",
            )}
          >
            <KpiStrip
              label="Net PnL"
              value={signedUSD(netPnl)}
              tone={netPnl >= 0 ? "ok" : "err"}
            />
            <KpiStrip
              label="Daily PnL"
              value={signedUSD(dailyPnl)}
              tone={dailyPnl >= 0 ? "ok" : "err"}
            />
            <KpiStrip label="Open Exposure" value={signedUSD(openExposure)} />
            <KpiStrip
              label="Active Positions"
              value={String(activePositions)}
            />
            <KpiStrip
              label="Current Regime"
              value={props.regime || "Unknown"}
            />
            <KpiStrip
              label="Risk State"
              value={riskState}
              tone={
                riskState.toLowerCase().includes("acceptable") ? "ok" : "warn"
              }
            />
          </div>
        </div>
        <div className={PANEL_CLASS} aria-label="Operational controls">
          <div className={PANEL_HEADER_CLASS}>
            <p className={PANEL_TITLE_CLASS}>Operator controls</p>
          </div>
          <div>
            {healthIndicators.map((indicator) => (
              <StatePill key={indicator.label} {...indicator} />
            ))}
          </div>
        </div>
      </section>

      <section className="grid grid-cols-1 gap-3 xl:grid-cols-[minmax(0,1.15fr)_minmax(420px,0.85fr)]">
        <div className={PANEL_CLASS}>
          <div
            className={cn(
              PANEL_HEADER_CLASS,
              "flex items-center justify-between gap-2",
            )}
          >
            <p className={PANEL_TITLE_CLASS}>Live Decision Feed</p>
            <span className="font-mono text-[10px] uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">
              Windowed {decisionFeed.length}
            </span>
          </div>
          <div
            className="max-h-[520px] overflow-y-auto"
            role="feed"
            aria-label="Reverse chronological decision stream"
          >
            {decisionFeed.length === 0 ? (
              <div className="px-3 py-8 text-sm text-slate-500 dark:text-slate-400">
                Waiting for decisions, skips, or executions.
              </div>
            ) : (
              decisionFeed.map((item) => (
                <button
                  key={item.id}
                  type="button"
                  onClick={() => props.setActiveTraceId(item.traceId)}
                  disabled={!item.traceId}
                  className={cn(
                    "grid w-full grid-cols-[72px_1fr] gap-3 border-b px-3 py-2 text-left transition disabled:cursor-default",
                    ROW_DIVIDER_CLASS,
                    "hover:bg-slate-100 disabled:hover:bg-transparent dark:hover:bg-slate-900/80",
                  )}
                >
                  <time className="font-mono text-[11px] tabular-nums text-slate-500 dark:text-slate-400">
                    {formatClock(item.timestamp)}
                  </time>
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <span
                        className={cn(
                          "rounded px-1.5 py-0.5 font-mono text-xs font-semibold ring-1",
                          actionClass(item.action),
                        )}
                      >
                        {item.action}
                      </span>
                      <span className="font-mono text-sm font-semibold text-slate-900 dark:text-white">
                        {item.symbol}
                      </span>
                      {item.confidence != null && (
                        <span className="font-mono text-xs text-slate-500 dark:text-slate-400">
                          Confidence: {formatPercent(item.confidence)}
                        </span>
                      )}
                      <span className="ml-auto font-mono text-[10px] uppercase tracking-wide text-slate-400 dark:text-slate-500">
                        {item.source}
                      </span>
                    </div>
                    <div className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                      <span className="text-slate-400 dark:text-slate-500">
                        Reason:
                      </span>
                      <ul className="mt-1 grid gap-0.5 sm:grid-cols-2">
                        {item.reason.map((reason) => (
                          <li key={reason} className="truncate">
                            - {reason}
                          </li>
                        ))}
                      </ul>
                    </div>
                  </div>
                </button>
              ))
            )}
          </div>
        </div>

        <div className={PANEL_CLASS}>
          <div className={PANEL_HEADER_CLASS}>
            <p className={PANEL_TITLE_CLASS}>Trace Explorer</p>
          </div>
          <div className="p-3">
            {selectedDecision ? (
              <div className="space-y-2">
                <div className="flex items-center justify-between gap-3 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 dark:border-slate-800 dark:bg-slate-900/60">
                  <div>
                    <p className="font-mono text-sm text-slate-900 dark:text-white">
                      {selectedDecision.action} {selectedDecision.symbol}
                    </p>
                    <p className="text-xs text-slate-500 dark:text-slate-400">
                      Trace {selectedDecision.traceId ?? "not attached"}
                    </p>
                  </div>
                  <span className="font-mono text-xs text-slate-500 dark:text-slate-400">
                    {formatTimestamp(selectedDecision.timestamp)}
                  </span>
                </div>
                <div className="space-y-1">
                  {TRACE_COLUMNS.map((label, index) => (
                    <details
                      key={label}
                      className="group rounded-lg border border-slate-200 bg-white open:bg-slate-50 dark:border-slate-800 dark:bg-slate-950 dark:open:bg-slate-900/60"
                      open={index < 3}
                    >
                      <summary className="flex cursor-pointer items-center gap-2 px-3 py-2 text-xs font-semibold text-slate-700 marker:hidden dark:text-slate-200">
                        <span className="flex h-5 w-5 items-center justify-center rounded-full border border-slate-300 font-mono text-[10px] text-slate-500 dark:border-slate-700 dark:text-slate-400">
                          {index + 1}
                        </span>
                        {label}
                        <span className="ml-auto text-slate-400 group-open:hidden dark:text-slate-500">
                          expand
                        </span>
                      </summary>
                      <div className="border-t border-slate-200 px-3 py-2 text-xs leading-5 text-slate-500 dark:border-slate-800 dark:text-slate-400">
                        {index === 0 && selectedDecision.reason[0]}
                        {index === 1 && selectedDecision.reason.join(" ")}
                        {index === 2 && riskState}
                        {index === 3 &&
                          `${activePositions} active positions / ${signedUSD(openExposure)} exposure`}
                        {index === 4 &&
                          `${selectedDecision.source} event at ${formatClock(selectedDecision.timestamp)}`}
                        {index === 5 &&
                          (selectedDecision.action === "SKIP"
                            ? "No order routed."
                            : "Awaiting grade/outcome attribution.")}
                      </div>
                    </details>
                  ))}
                </div>
              </div>
            ) : (
              <div className="rounded-lg border border-dashed border-slate-300 px-3 py-8 text-sm text-slate-500 dark:border-slate-800 dark:text-slate-400">
                No decision trace selected yet.
              </div>
            )}
          </div>
        </div>
      </section>

      <section className="grid grid-cols-1 gap-3 xl:grid-cols-3">
        <div className={PANEL_CLASS}>
          <div className={PANEL_HEADER_CLASS}>
            <p className={PANEL_TITLE_CLASS}>Cognitive Evolution</p>
          </div>
          <div className={cn("divide-y", "divide-slate-200 dark:divide-slate-800/70")}>
            <KpiStrip
              label="Current Strategy Version"
              value={`v${Math.max(1, approvedProposals.length + rejectedProposals.length + 1)}`}
            />
            <KpiStrip
              label="Last Approved Proposal"
              value={
                approvedProposals[0]
                  ? proposalLabel(approvedProposals[0])
                  : "None approved"
              }
            />
            <KpiStrip
              label="Proposal Success Rate"
              value={
                proposalSuccessRate == null
                  ? "--"
                  : formatPercent(proposalSuccessRate)
              }
            />
            <div className="px-3 py-2">
              <p className={LABEL_CLASS}>Config Change Timeline</p>
              <ol className="mt-2 space-y-2">
                {(props.proposals.length > 0
                  ? props.proposals.slice(0, 4)
                  : []
                ).map((proposal) => (
                  <li
                    key={proposal.id}
                    className="border-l border-slate-300 pl-3 text-xs text-slate-500 dark:border-slate-700 dark:text-slate-400"
                  >
                    <p className="font-medium text-slate-700 dark:text-slate-200">
                      {proposalLabel(proposal)}
                    </p>
                    <p>{proposal.status} after challenger review</p>
                  </li>
                ))}
                {props.proposals.length === 0 && (
                  <li className="text-xs text-slate-500 dark:text-slate-400">
                    No strategy mutations recorded.
                  </li>
                )}
              </ol>
            </div>
          </div>
        </div>

        <div className={PANEL_CLASS}>
          <div className={PANEL_HEADER_CLASS}>
            <p className={PANEL_TITLE_CLASS}>Agent Activity</p>
          </div>
          <div
            className={cn(
              "max-h-[520px] divide-y overflow-y-auto",
              "divide-slate-200 dark:divide-slate-800/70",
            )}
          >
            {agentActivity.map((agent) => {
              const tone = resolveHealthTone(agent.status?.status);
              const currentTask =
                agent.relatedLog?.event_type ??
                agent.status?.last_event ??
                agent.status?.status ??
                "Idle";
              const lastOutput =
                agent.relatedLog?.message ??
                agent.status?.last_event ??
                "No output yet";
              const latencyMs = toFiniteNumber(agent.relatedLog?.latency_ms);
              return (
                <div key={agent.key} className="px-3 py-2">
                  <div className="flex items-center justify-between gap-2">
                    <p className="text-sm font-semibold text-slate-800 dark:text-slate-100">
                      {agent.label}
                    </p>
                    <span
                      className={cn(
                        "h-2 w-2 rounded-full ring-4",
                        statusToneClass(tone),
                      )}
                    />
                  </div>
                  <dl className="mt-2 grid grid-cols-[90px_1fr] gap-x-2 gap-y-1 text-xs">
                    <dt className="text-slate-500 dark:text-slate-500">
                      Current task
                    </dt>
                    <dd className="truncate text-slate-600 dark:text-slate-300">
                      {currentTask}
                    </dd>
                    <dt className="text-slate-500 dark:text-slate-500">
                      Last output
                    </dt>
                    <dd className="truncate text-slate-500 dark:text-slate-400">
                      {lastOutput}
                    </dd>
                    <dt className="text-slate-500 dark:text-slate-500">
                      Last seen
                    </dt>
                    <dd className="font-mono text-slate-500 dark:text-slate-400">
                      {formatAge(agent.status?.seconds_ago)}
                      {latencyMs != null ? ` · ${latencyMs.toFixed(0)}ms` : ""}
                    </dd>
                  </dl>
                </div>
              );
            })}
          </div>
        </div>

        <div className={PANEL_CLASS}>
          <div className={PANEL_HEADER_CLASS}>
            <p className={PANEL_TITLE_CLASS}>System Health</p>
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-1">
            {systemHealth.map((indicator) => (
              <StatePill key={indicator.label} {...indicator} />
            ))}
          </div>
        </div>
      </section>
    </div>
  );
}
