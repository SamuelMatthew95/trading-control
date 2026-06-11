/**
 * Pure derivation layer for the System dashboard — wire shapes in, render
 * models out. No JSX in here; everything is unit-testable in isolation.
 */
import { parseTimestampMs, signedUSD, toFiniteNum as toFiniteNumber } from "@/lib/formatters";
import {
  ALL_AGENT_NAMES,
  agentDisplayName,
  canonicalAgentKey,
} from "@/constants/agents";
import type {
  AgentLog,
  AgentHeartbeat,
  Notification,
  Order,
  Proposal,
} from "@/stores/useDashboardStore";
import type { StatusTone } from "./types";

export type DecisionAction = "BUY" | "SELL" | "SKIP" | "HOLD";

export type DecisionFeedItem = {
  id: string;
  timestamp: string | null;
  action: DecisionAction;
  symbol: string;
  confidence: number | null;
  reason: string[];
  traceId: string | null;
  source: "decision" | "order" | "notification";
};

export type AgentActivityRow = {
  key: string;
  label: string;
  status?: AgentHeartbeat;
  relatedLog?: AgentLog;
};

export const SURFACED_DECISION_LIMIT = 48;
export const TRACE_COLUMNS = [
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
/** Canonical timestamp parsing (formatters.parseTimestampMs) as a Date. */
export function parseTimestampDate(value: unknown): Date | null {
  const ms = parseTimestampMs(value)
  return ms == null ? null : new Date(ms)
}

export function timestampMs(value: unknown): number {
  return parseTimestampMs(value) ?? 0
}

// Start of the current UTC trading day. Used to scope the Daily PnL headline to
// today's orders instead of summing the whole recent-orders window.
export function startOfUtcDayMs(now: number): number {
  const date = new Date(now);
  return Date.UTC(date.getUTCFullYear(), date.getUTCMonth(), date.getUTCDate());
}

export function formatClock(value: string | null): string {
  const date = parseTimestampDate(value);
  if (!date) return "--:--:--";
  return new Intl.DateTimeFormat("en-US", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  }).format(date);
}

export function formatAge(secondsAgo: number | null | undefined): string {
  const seconds = toFiniteNumber(secondsAgo);
  if (seconds == null || seconds < 0) return "--";
  if (seconds < 60) return `${Math.round(seconds)}s ago`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  return `${Math.floor(minutes / 60)}h ago`;
}

export function normalizeAction(value: unknown): DecisionAction {
  const raw = String(value ?? "").toUpperCase();
  if (raw === "BUY" || raw === "LONG") return "BUY";
  if (raw === "SELL" || raw === "SHORT" || raw === "EXIT") return "SELL";
  if (raw === "SKIP" || raw === "REJECT") return "SKIP";
  return "HOLD";
}

export function compactReason(value: unknown, fallback: string): string[] {
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

export function resolveHealthTone(status: string | null | undefined): StatusTone {
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

export function deriveDecisionFeed({
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
export function deriveAgentActivity({
  agentStatuses,
  agentLogs,
}: {
  agentStatuses: AgentHeartbeat[];
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

export function proposalLabel(proposal: Proposal): string {
  return (
    proposal.content ||
    proposal.strategy_name ||
    proposal.proposal_type.replace(/_/g, " ")
  );
}

