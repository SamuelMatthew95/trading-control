import { getHealthyAgentRatio, getTokenAndCostTotals } from "@/utils/dashboard";

describe("dashboard utils", () => {
  it("calculates token and cost totals", () => {
    const totals = getTokenAndCostTotals([
      { token_usage: 100, cost_usd: 0.01 },
      { token_usage: 50, cost_usd: 0.02 },
    ]);
    expect(totals).toEqual({ tokenUsage: 150, cost: 0.03 });
  });

  it("tolerates missing fields and string values in events", () => {
    const totals = getTokenAndCostTotals([
      { token_usage: "300", cost_usd: "0.005" },
      { event_type: "request_completed" },
      { token_usage: null, cost_usd: undefined },
    ] as Array<Record<string, unknown>>);

    expect(totals).toEqual({ tokenUsage: 300, cost: 0.005 });
  });

  it("builds healthy ratio string", () => {
    const ratio = getHealthyAgentRatio([
      { name: "a", status: "idle" },
      { name: "b", status: "running" },
      { name: "c", status: "failed" },
    ]);
    expect(ratio).toBe("2/3");
  });

  it("handles empty agent array", () => {
    expect(getHealthyAgentRatio([])).toBe("0/0");
  });
});
