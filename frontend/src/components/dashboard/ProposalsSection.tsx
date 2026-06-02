"use client";

import { useMemo, useState } from "react";
import { Check, X } from "lucide-react";

import { api } from "@/lib/apiClient";
import {
  cardClass,
  mutedClass,
  sectionTitleClass,
} from "@/lib/dashboard-styles";
import { proposalRouting, type ProposalRouting } from "@/lib/proposal-routing";
import { cn } from "@/lib/utils";
import { useCodexStore, type Proposal } from "@/stores/useCodexStore";

function routingBadgeClass(kind: ProposalRouting["kind"]): string {
  if (kind === "config-pr")
    return "border-sky-400/30 bg-sky-400/10 text-sky-700 dark:text-sky-300";
  if (kind === "issue")
    return "border-violet-400/30 bg-violet-400/10 text-violet-700 dark:text-violet-300";
  if (kind === "unknown")
    return "border-slate-300/40 bg-slate-400/10 text-slate-600 dark:text-slate-400";
  // control-plane / prompt / tool / mixed are all system-applied state changes
  return "border-teal-400/30 bg-teal-400/10 text-teal-700 dark:text-teal-300";
}

function proposalLabel(proposal: Proposal): string {
  return (
    proposal.content ||
    proposal.strategy_name ||
    proposal.proposal_type.replace(/_/g, " ")
  );
}

function formatPercent(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return "--";
  const normalized = Math.abs(value) <= 1 ? value * 100 : value;
  return `${normalized.toFixed(1)}%`;
}

function statusClass(status: Proposal["status"]): string {
  if (status === "approved")
    return "border-emerald-400/30 bg-emerald-400/10 text-emerald-700 dark:text-emerald-300";
  if (status === "rejected")
    return "border-rose-400/30 bg-rose-400/10 text-rose-700 dark:text-rose-300";
  return "border-amber-400/30 bg-amber-400/10 text-amber-700 dark:text-amber-300";
}

function EmptyProposals() {
  return (
    <div className="rounded-lg border border-dashed border-slate-200 bg-white px-3 py-8 text-center dark:border-slate-800 dark:bg-slate-950/60">
      <p className="text-sm font-semibold text-slate-600 dark:text-slate-300">
        No proposals awaiting review.
      </p>
      <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
        The Proposal Agent will add candidate changes here after reflection and
        challenger review.
      </p>
    </div>
  );
}

export function ProposalsSection() {
  const proposals = useCodexStore((state) => state.proposals);
  const updateProposalStatus = useCodexStore(
    (state) => state.updateProposalStatus,
  );
  const [pendingAction, setPendingAction] = useState<string | null>(null);

  const summary = useMemo(
    () => ({
      pending: proposals.filter((proposal) => proposal.status === "pending")
        .length,
      approved: proposals.filter((proposal) => proposal.status === "approved")
        .length,
      rejected: proposals.filter((proposal) => proposal.status === "rejected")
        .length,
    }),
    [proposals],
  );

  const handleVote = async (id: string, vote: "approve" | "reject") => {
    setPendingAction(id);
    const status =
      vote === "approve" ? ("approved" as const) : ("rejected" as const);
    try {
      const response = await fetch(
        api(`/dashboard/learning/proposals/${encodeURIComponent(id)}`),
        {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ status }),
        },
      );
      if (response.ok) updateProposalStatus(id, status);
    } catch {
      // network failure — leave proposal in current state
    } finally {
      setPendingAction(null);
    }
  };

  return (
    <section className={cardClass}>
      <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className={sectionTitleClass}>Proposal Queue</p>
          <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
            Table-first review of candidate strategy changes, expected impact,
            and challenger verdicts.
          </p>
        </div>
        <div className="flex flex-wrap gap-2 font-mono text-[10px] uppercase tracking-[0.14em]">
          <span className="rounded border border-amber-400/30 bg-amber-400/10 px-2 py-1 text-amber-700 dark:text-amber-300">
            Pending {summary.pending}
          </span>
          <span className="rounded border border-emerald-400/30 bg-emerald-400/10 px-2 py-1 text-emerald-700 dark:text-emerald-300">
            Approved {summary.approved}
          </span>
          <span className="rounded border border-rose-400/30 bg-rose-400/10 px-2 py-1 text-rose-700 dark:text-rose-300">
            Rejected {summary.rejected}
          </span>
        </div>
      </div>

      {proposals.length === 0 ? (
        <EmptyProposals />
      ) : (
        <div className="overflow-x-auto rounded-lg border border-slate-200 dark:border-slate-800">
          <table className="w-full min-w-[860px] text-left text-xs">
            <thead className="bg-slate-100 text-[10px] uppercase tracking-[0.16em] text-slate-500 dark:bg-slate-900/80 dark:text-slate-400">
              <tr>
                <th className="px-3 py-2 font-semibold">Candidate Change</th>
                <th className="px-3 py-2 font-semibold">Type</th>
                <th className="px-3 py-2 font-semibold">On Approve</th>
                <th className="px-3 py-2 font-semibold">
                  Expected Improvement
                </th>
                <th className="px-3 py-2 font-semibold">Backtest Delta</th>
                <th className="px-3 py-2 font-semibold">Traceability</th>
                <th className="px-3 py-2 font-semibold">Status</th>
                <th className="px-3 py-2 text-right font-semibold">Decision</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-200 bg-white dark:divide-slate-800/80 dark:bg-slate-950/50">
              {proposals.map((proposal) => {
                const isPending = proposal.status === "pending";
                return (
                  <tr
                    key={proposal.id}
                    className="align-top text-slate-600 dark:text-slate-300"
                  >
                    <td className="max-w-[360px] px-3 py-2">
                      <p className="line-clamp-2 font-medium text-slate-900 dark:text-slate-100">
                        {proposalLabel(proposal)}
                      </p>
                      <p className={cn(mutedClass, "mt-1")}>ID {proposal.id}</p>
                    </td>
                    <td className="px-3 py-2 text-slate-500 dark:text-slate-400">
                      {proposal.proposal_type.replace(/_/g, " ")}
                    </td>
                    <td className="px-3 py-2">
                      {(() => {
                        const routing = proposalRouting(proposal.proposal_type);
                        return (
                          <span
                            title={routing.hint}
                            className={cn(
                              "inline-block rounded border px-2 py-1 font-mono text-[10px] uppercase tracking-wide",
                              routingBadgeClass(routing.kind),
                            )}
                          >
                            {routing.label}
                          </span>
                        );
                      })()}
                    </td>
                    <td className="px-3 py-2 font-mono text-slate-600 dark:text-slate-300">
                      {formatPercent(proposal.confidence)}
                    </td>
                    <td className="px-3 py-2 font-mono text-slate-600 dark:text-slate-300">
                      {proposal.grade_score != null
                        ? formatPercent(proposal.grade_score)
                        : "--"}
                    </td>
                    <td className="px-3 py-2 font-mono text-[11px] text-slate-500 dark:text-slate-400">
                      {proposal.reflection_trace_id || proposal.trace_id ? (
                        <span>
                          {String(
                            proposal.reflection_trace_id ?? proposal.trace_id,
                          ).slice(0, 18)}
                          …
                        </span>
                      ) : (
                        "--"
                      )}
                    </td>
                    <td className="px-3 py-2">
                      <span
                        className={cn(
                          "rounded border px-2 py-1 font-mono text-[10px] uppercase",
                          statusClass(proposal.status),
                        )}
                      >
                        {proposal.status}
                      </span>
                    </td>
                    <td className="px-3 py-2">
                      {isPending ? (
                        <div className="flex justify-end gap-2">
                          <button
                            type="button"
                            disabled={pendingAction === proposal.id}
                            onClick={() => handleVote(proposal.id, "approve")}
                            className="inline-flex items-center gap-1 rounded border border-emerald-400/30 bg-emerald-400/10 px-2 py-1 text-[11px] font-semibold text-emerald-700 hover:bg-emerald-400/20 disabled:opacity-50 dark:text-emerald-300"
                          >
                            <Check className="h-3 w-3" /> Approve
                          </button>
                          <button
                            type="button"
                            disabled={pendingAction === proposal.id}
                            onClick={() => handleVote(proposal.id, "reject")}
                            className="inline-flex items-center gap-1 rounded border border-rose-400/30 bg-rose-400/10 px-2 py-1 text-[11px] font-semibold text-rose-700 hover:bg-rose-400/20 disabled:opacity-50 dark:text-rose-300"
                          >
                            <X className="h-3 w-3" /> Reject
                          </button>
                        </div>
                      ) : (
                        <p className="text-right text-[11px] text-slate-500 dark:text-slate-400">
                          Reviewed
                        </p>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
