/**
 * Production-grade API client layer
 * 
 * This provides a single source of truth for all API calls
 * and prevents double-prefix issues and contract mismatches.
 */

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "/api";

/**
 * Runtime guard to detect double /api prefixes
 */
const guardDoublePrefix = (url: string): void => {
  if (url.includes("/api/api/")) {
    console.warn("🚨 Double /api detected:", url);
    // In development, throw an error to catch this immediately
    if (process.env.NODE_ENV === "development") {
      throw new Error(`Double API prefix detected: ${url}`);
    }
  }
};

/**
 * Build API URLs with consistent prefix handling
 * 
 * @param path - API path (should start with /)
 * @returns Full API URL
 */
export const api = (path: string): string => {
  if (!path.startsWith("/")) {
    console.warn("🚨 API path should start with /:", path);
    path = `/${path}`;
  }
  
  const url = `${API_BASE}${path}`;
  guardDoublePrefix(url);
  return url;
};

/**
 * Typed fetch wrapper for API calls
 */
export const apiFetch = async <T = unknown>(
  path: string,
  options?: RequestInit
): Promise<T> => {
  const url = api(path);
  
  const response = await fetch(url, {
    headers: {
      "Content-Type": "application/json",
      ...options?.headers,
    },
    ...options,
  });

  if (!response.ok) {
    throw new Error(`API request failed: ${response.status} ${response.statusText}`);
  }

  return response.json();
};

/**
 * Common API endpoints - centralized for consistency
 */
export const API_ENDPOINTS = {
  // Dashboard
  DASHBOARD_SNAPSHOT: "/dashboard/snapshot",
  DASHBOARD_PRICES: "/dashboard/prices",
  DASHBOARD_TRADE_FEED: "/dashboard/trade-feed",
  DASHBOARD_AGENT_INSTANCES: "/dashboard/agent-instances",
  DASHBOARD_PERFORMANCE_TRENDS: "/dashboard/performance-trends",
  DASHBOARD_KILL_SWITCH: "/dashboard/kill-switch",
  
  // Learning
  LEARNING_PROPOSALS: "/dashboard/learning/proposals",
  LEARNING_GRADES: "/dashboard/learning/grades",
  LEARNING_IC_WEIGHTS: "/dashboard/learning/ic-weights",
  LEARNING_REFLECTIONS: "/dashboard/learning/reflections",
  
  // System
  SYSTEM_HEALTH: "/dashboard/system-health",
  SYSTEM_METRICS: "/dashboard/system-metrics",
  
  // Agents
  AGENTS_STATUS: "/dashboard/agents/status",
  
  // Events
  EVENTS_RECENT: "/dashboard/events/recent",
  EVENTS_HISTORY: "/dashboard/history/events",
} as const;

/**
 * Export the base URL for legacy compatibility
 */
export { API_BASE };
