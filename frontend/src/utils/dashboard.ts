import { AgentView } from "@/types/dashboard";

export function getTokenAndCostTotals(events: Array<Record<string, unknown>>): {
  tokenUsage: number;
  cost: number;
} {
  return events.reduce<{ tokenUsage: number; cost: number }>(
    (acc, evt) => {
      acc.tokenUsage += Number(evt.token_usage || 0);
      acc.cost += Number(evt.cost_usd || 0);
      return acc;
    },
    { tokenUsage: 0, cost: 0 },
  );
}

export function getHealthyAgentRatio(agents: AgentView[]): string {
  const healthy = agents.filter((agent) => agent.status !== "failed").length;
  return `${healthy}/${agents.length}`;
}
