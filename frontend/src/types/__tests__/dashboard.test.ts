import type {
  AgentView,
  MonitoringOverview,
  TradeRow,
  TradingStats,
} from "@/types/dashboard";

describe("dashboard types compile usage", () => {
  it("allows expected typed object shapes", () => {
    const agent: AgentView = { name: "SIGNAL_AGENT", status: "idle" };
    const overview: MonitoringOverview = {
      uptime_seconds: 10,
      total_requests: 100,
      total_errors: 1,
      error_rate: 1,
      avg_latency_ms: 120,
      p95_latency_ms: 240,
      recent_events: [],
      agent_status: [agent],
    };

    expect(overview.agent_status[0].name).toBe("SIGNAL_AGENT");
  });

  it("supports strongly-typed stats and trade rows", () => {
    const stats: TradingStats = {
      total_trades: 10,
      wins: 7,
      losses: 3,
      win_rate: 70,
      total_pnl: 1250.5,
    };
    const row: TradeRow = {
      id: 1,
      date: "2026-03-13",
      asset: "AAPL",
      direction: "LONG",
      entry: 150,
      stop: 145,
      target: 160,
      rr_ratio: 2,
      pnl: 55.2,
      outcome: "WIN",
    };

    expect(stats.win_rate).toBe(70);
    expect(row.asset).toBe("AAPL");
  });
});
