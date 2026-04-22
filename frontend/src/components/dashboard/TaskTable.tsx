import { TradeRow } from "@/types/dashboard";

export function TaskTable({
  rows,
  isDark,
}: {
  rows: TradeRow[];
  isDark: boolean;
}) {
  const wrap = isDark ? "border-slate-700" : "border-slate-300";
  const head = isDark
    ? "bg-slate-800 text-slate-300"
    : "bg-slate-100 text-slate-700";
  const body = isDark
    ? "divide-slate-700 bg-slate-900/80 text-slate-200"
    : "divide-slate-200 bg-white text-slate-900";

  return (
    <div className={`overflow-x-auto rounded-xl border ${wrap}`}>
      <table className="min-w-full text-sm">
        <thead className={head}>
          <tr>
            {[
              "Date",
              "Asset",
              "Direction",
              "Entry",
              "Stop",
              "Target",
              "R:R",
              "PnL",
              "Outcome",
            ].map((headLabel) => (
              <th key={headLabel} className="px-4 py-3 text-left font-medium">
                {headLabel}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className={`divide-y ${body}`}>
          {rows.map((row) => (
            <tr key={row.id}>
              <td className="px-4 py-3">{row.date}</td>
              <td className="px-4 py-3">{row.asset}</td>
              <td className="px-4 py-3">{row.direction}</td>
              <td className="px-4 py-3">{row.entry}</td>
              <td className="px-4 py-3">{row.stop}</td>
              <td className="px-4 py-3">{row.target}</td>
              <td className="px-4 py-3">{row.rr_ratio}</td>
              <td className="px-4 py-3">
                {typeof row.pnl === "number" ? row.pnl.toFixed(2) : "-"}
              </td>
              <td className="px-4 py-3">{row.outcome}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
