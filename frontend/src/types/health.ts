export interface HealthResponse {
  success: boolean;
  data: HealthData;
  error: string | null;
}

export interface HealthData {
  status: "healthy" | "unhealthy";
  database_connected: boolean;
  feedback_jobs_pending: number;
  feedback_jobs_failed: number;
  scoring_pending: number;
  scoring_failed: number;
  oldest_pending_score_age_seconds: number | null;
  telemetry: TelemetryData;
  timestamp: string;
}

export interface TelemetryData {
  error_rate: number;
  avg_latency_ms: number;
  total_requests: number;
}

export interface BotControlResponse {
  success: boolean;
  data: {
    status: "started" | "stopped";
    message: string;
  };
  error: string | null;
}
