"use client";

import { useMemo } from "react";

import { cn } from "@/lib/utils";
import {
  formatTimestamp,
  signedUSD,
  toFiniteNum as toFiniteNumber,
} from "@/lib/formatters";
import type {
  AgentLog,
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

const SURFACED_DECISION_LIMIT = 48;
const TRACE_COLUMNS = [
  "Signal",
  "Reasoning",
  "Risk Evaluation",
  "Position Sizing",
  "Execution",
  "Outcome",
] as const;
const OPERATOR_AGENTS = [
  { key: "news", label: "News Agent" },
  { key: "macro", label: "Macro Agent" },
  { key: "proposal", label: "Proposal Agent" },
  { key: "risk", label: "Risk Agent" },
] as const;

const PANEL_CLASS =
  "rounded-xl border border-slate-800/80 bg-slate-950/80 shadow-sm shadow-black/20";
const PANEL_HEADER_CLASS = "border-b border-slate-800/80 px-3 py-2";
const PANEL_TITLE_CLASS =
  "text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-400";
const LABEL_CLASS =
  "text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-500";
const VALUE_CLASS = "font-mono text-sm tabular-nums text-slate-100";

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
    .split(/\n|;|\u2022|\. /)
    .map((part) => part.replace(/^-\s*/, "").trim())
    .filter(Boolean)
    .slice(0, 4);
}

function statusToneClass(tone: StatusTone): string {
  switch (tone) {
    case "ok":
      return "bg-emerald-400 text-emerald-300 ring-emerald-400/30";
    case "warn":
      return "bg-amber-400 text-amber-300 ring-amber-400/30";
    case "err":
      return "bg-rose-400 text-rose-300 ring-rose-400/30";
    default:
      return "bg-slate-500 text-slate-300 ring-slate-500/30";
  }
}

function actionClass(action: DecisionAction): string {
  switch (action) {
    case "BUY":
      return "text-emerald-300 bg-emerald-400/10 ring-emerald-400/30";
    case "SELL":
      return "text-rose-300 bg-rose-400/10 ring-rose-400/30";
    case "SKIP":
      return "text-amber-300 bg-amber-400/10 ring-amber-400/30";
    default:
      return "text-slate-300 bg-slate-400/10 ring-slate-400/30";
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

function proposalLabel(proposal: Proposal): string {
  return (
    proposal.content ||
    proposal.strategy_name ||
    proposal.proposal_type.replace(/_/g, " ")
  );
}

function formatPercent(value: unknown): string {
  const number = toFiniteNumber(value);
  if (number == null) return "--";
  const scaled = Math.abs(number) <= 1 ? number * 100 : number;
  return `${scaled.toFixed(1)}%`;
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
    <div className="border-b border-slate-800/70 px-3 py-2 last:border-b-0">
      <p className={LABEL_CLASS}>{label}</p>
      <p
        className={cn(
          VALUE_CLASS,
          tone === "ok" && "text-emerald-300",
          tone === "warn" && "text-amber-300",
          tone === "err" && "text-rose-300",
        )}
      >
        {value}
      </p>
    </div>
  );
}

function StatePill({ label, tone, value }: HealthIndicator) {
  return (
    <div className="flex items-center justify-between gap-3 border-b border-slate-800/70 px-3 py-2 last:border-b-0">
      <div className="flex items-center gap-2">
        <span
          className={cn("h-2 w-2 rounded-full ring-4", statusToneClass(tone))}
          aria-hidden="true"
        />
        <span className="text-xs font-medium text-slate-200">{label}</span>
      </div>
      <span className="font-mono text-[11px] uppercase tracking-wide text-slate-400">
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

  const selectedDecision = decisionFeed[0] ?? null;
  const netPnl =
    props.resolvedPerformanceSummary?.total_pnl ??
    props.orders.reduce(
      (sum, order) => sum + (toFiniteNumber(order.pnl) ?? 0),
      0,
    );
  const dailyPnl = props.orders.reduce(
    (sum, order) => sum + (toFiniteNumber(order.pnl) ?? 0),
    0,
  );
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

  const latestProposal = props.proposals[0];
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
    <div className="space-y-3 text-slate-100">
      <section
        className="grid grid-cols-1 gap-3 xl:grid-cols-[minmax(0,1fr)_360px]"
        aria-label="Command Center overview"
      >
        <div className={PANEL_CLASS}>
          <div className={PANEL_HEADER_CLASS}>
            <div className="flex items-center justify-between gap-3">
              <div>
                <p className={PANEL_TITLE_CLASS}>Command Center</p>
                <h1 className="mt-1 text-xl font-semibold tracking-tight text-white">
                  Decisions, risk, execution
                </h1>
              </div>
              <span className="rounded-full border border-slate-700 px-2 py-1 font-mono text-[10px] uppercase tracking-[0.18em] text-slate-400">
                {props.isInMemoryMode ? "Paper / memory" : "Live capable"}
              </span>
            </div>
          </div>
          <div className="grid grid-cols-2 divide-x divide-y divide-slate-800/70 md:grid-cols-3 xl:grid-cols-6 xl:divide-y-0">
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
            <span className="font-mono text-[10px] uppercase tracking-[0.16em] text-slate-500">
              Windowed {decisionFeed.length}
            </span>
          </div>
          <div
            className="max-h-[520px] overflow-y-auto"
            role="feed"
            aria-label="Reverse chronological decision stream"
          >
            {decisionFeed.length === 0 ? (
              <div className="px-3 py-8 text-sm text-slate-500">
                Waiting for decisions, skips, or executions.
              </div>
            ) : (
              decisionFeed.map((item) => (
                <button
                  key={item.id}
                  type="button"
                  onClick={() => props.setActiveTraceId(item.traceId)}
                  disabled={!item.traceId}
                  className="grid w-full grid-cols-[72px_1fr] gap-3 border-b border-slate-800/70 px-3 py-2 text-left transition hover:bg-slate-900/80 disabled:cursor-default disabled:hover:bg-transparent"
                >
                  <time className="font-mono text-[11px] tabular-nums text-slate-500">
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
                      <span className="font-mono text-sm font-semibold text-white">
                        {item.symbol}
                      </span>
                      {item.confidence != null && (
                        <span className="font-mono text-xs text-slate-400">
                          Confidence: {formatPercent(item.confidence)}
                        </span>
                      )}
                      <span className="ml-auto font-mono text-[10px] uppercase tracking-wide text-slate-600">
                        {item.source}
                      </span>
                    </div>
                    <div className="mt-1 text-xs text-slate-400">
                      <span className="text-slate-500">Reason:</span>
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
                <div className="flex items-center justify-between gap-3 rounded-lg border border-slate-800 bg-slate-900/60 px-3 py-2">
                  <div>
                    <p className="font-mono text-sm text-white">
                      {selectedDecision.action} {selectedDecision.symbol}
                    </p>
                    <p className="text-xs text-slate-500">
                      Trace {selectedDecision.traceId ?? "not attached"}
                    </p>
                  </div>
                  <span className="font-mono text-xs text-slate-400">
                    {formatTimestamp(selectedDecision.timestamp)}
                  </span>
                </div>
                <div className="space-y-1">
                  {TRACE_COLUMNS.map((label, index) => (
                    <details
                      key={label}
                      className="group rounded-lg border border-slate-800 bg-slate-950 open:bg-slate-900/60"
                      open={index < 3}
                    >
                      <summary className="flex cursor-pointer items-center gap-2 px-3 py-2 text-xs font-semibold text-slate-200 marker:hidden">
                        <span className="flex h-5 w-5 items-center justify-center rounded-full border border-slate-700 font-mono text-[10px] text-slate-400">
                          {index + 1}
                        </span>
                        {label}
                        <span className="ml-auto text-slate-600 group-open:hidden">
                          expand
                        </span>
                      </summary>
                      <div className="border-t border-slate-800 px-3 py-2 text-xs leading-5 text-slate-400">
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
              <div className="rounded-lg border border-dashed border-slate-800 px-3 py-8 text-sm text-slate-500">
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
          <div className="divide-y divide-slate-800/70">
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
                    className="border-l border-slate-700 pl-3 text-xs text-slate-400"
                  >
                    <p className="font-medium text-slate-200">
                      {proposalLabel(proposal)}
                    </p>
                    <p>{proposal.status} after challenger review</p>
                  </li>
                ))}
                {props.proposals.length === 0 && (
                  <li className="text-xs text-slate-500">
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
          <div className="divide-y divide-slate-800/70">
            {OPERATOR_AGENTS.map((agent) => {
              const status = props.agentStatuses.find((candidate) =>
                candidate.name.toLowerCase().includes(agent.key),
              );
              const relatedLog = props.agentLogs.find((log) =>
                String(log.agent_name ?? log.agent ?? "")
                  .toLowerCase()
                  .includes(agent.key),
              );
              const tone = resolveHealthTone(status?.status);
              return (
                <div key={agent.key} className="px-3 py-2">
                  <div className="flex items-center justify-between gap-2">
                    <p className="text-sm font-semibold text-slate-100">
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
                    <dt className="text-slate-500">Current task</dt>
                    <dd className="truncate text-slate-300">
                      {relatedLog?.event_type ?? status?.status ?? "Waiting"}
                    </dd>
                    <dt className="text-slate-500">Last output</dt>
                    <dd className="truncate text-slate-400">
                      {relatedLog?.message ??
                        status?.last_event ??
                        "No output yet"}
                    </dd>
                    <dt className="text-slate-500">Latency</dt>
                    <dd className="font-mono text-slate-400">
                      {relatedLog?.latency_ms ?? status?.seconds_ago ?? "--"} ms
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

      <section className={PANEL_CLASS}>
        <div
          className={cn(
            PANEL_HEADER_CLASS,
            "flex items-center justify-between gap-2",
          )}
        >
          <p className={PANEL_TITLE_CLASS}>Proposal Center</p>
          <span className="font-mono text-[10px] uppercase tracking-[0.16em] text-slate-500">
            {props.proposals.length} candidates
          </span>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[760px] text-left text-xs">
            <thead className="bg-slate-900/70 text-[10px] uppercase tracking-[0.16em] text-slate-500">
              <tr>
                <th className="px-3 py-2 font-semibold">Candidate Change</th>
                <th className="px-3 py-2 font-semibold">
                  Expected Improvement
                </th>
                <th className="px-3 py-2 font-semibold">Backtest Delta</th>
                <th className="px-3 py-2 font-semibold">Challenger Verdict</th>
                <th className="px-3 py-2 font-semibold">Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/70">
              {(props.proposals.length > 0
                ? props.proposals.slice(0, 8)
                : latestProposal
                  ? [latestProposal]
                  : []
              ).map((proposal) => (
                <tr key={proposal.id} className="text-slate-300">
                  <td className="px-3 py-2 font-medium text-slate-100">
                    {proposalLabel(proposal)}
                  </td>
                  <td className="px-3 py-2 font-mono">
                    {formatPercent(proposal.confidence)}
                  </td>
                  <td className="px-3 py-2 font-mono">
                    {proposal.grade_score != null
                      ? formatPercent(proposal.grade_score)
                      : "--"}
                  </td>
                  <td className="px-3 py-2">
                    {proposal.status === "approved"
                      ? "Approved"
                      : proposal.status === "rejected"
                        ? "Rejected"
                        : "Pending review"}
                  </td>
                  <td className="px-3 py-2">
                    <span
                      className={cn(
                        "rounded px-2 py-1 font-mono text-[10px] uppercase ring-1",
                        proposal.status === "approved" &&
                          "bg-emerald-400/10 text-emerald-300 ring-emerald-400/30",
                        proposal.status === "rejected" &&
                          "bg-rose-400/10 text-rose-300 ring-rose-400/30",
                        proposal.status === "pending" &&
                          "bg-amber-400/10 text-amber-300 ring-amber-400/30",
                      )}
                    >
                      {proposal.status}
                    </span>
                  </td>
                </tr>
              ))}
              {props.proposals.length === 0 && (
                <tr>
                  <td
                    colSpan={5}
                    className="px-3 py-8 text-center text-sm text-slate-500"
                  >
                    No challenger proposals are awaiting operator review.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
