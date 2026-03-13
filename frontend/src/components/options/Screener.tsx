import { useMemo, useState } from 'react';
import { ScreenerRow, TickerDetails } from '@/lib/unusualWhales';

interface Props {
  data: ScreenerRow[];
  details: TickerDetails | null;
  onSelect: (ticker: string) => void;
}

export default function Screener({ data, details, onSelect }: Props) {
  const [sortBy, setSortBy] = useState<keyof ScreenerRow>('ivRank');
  const [ivMin, setIvMin] = useState('0');
  const [ivMax, setIvMax] = useState('100');
  const [pcMax, setPcMax] = useState('10');
  const [minVol, setMinVol] = useState('0');

  const rows = useMemo(() => data
    .filter((d) => d.ivRank >= Number(ivMin) && d.ivRank <= Number(ivMax) && d.putCallRatio <= Number(pcMax) && d.volume >= Number(minVol))
    .sort((a, b) => (b[sortBy] as number) - (a[sortBy] as number)), [data, sortBy, ivMin, ivMax, pcMax, minVol]);

  return (
    <section className="bg-[#F5F5F5] rounded-lg border border-gray-200 p-4 shadow-sm">
      <h2 className="text-lg font-semibold mb-3">Options Screener</h2>
      <div className="grid grid-cols-2 md:grid-cols-5 gap-2 mb-3 text-sm">
        <select className="border rounded px-2 py-1" value={sortBy} onChange={(e) => setSortBy(e.target.value as keyof ScreenerRow)}>{['ticker','ivRank','putCallRatio','volume','openInterest','impliedMove','sentimentScore'].map((k)=><option key={k} value={k}>{k}</option>)}</select>
        <input className="border rounded px-2 py-1" value={ivMin} onChange={(e) => setIvMin(e.target.value)} placeholder="IV min" type="number" />
        <input className="border rounded px-2 py-1" value={ivMax} onChange={(e) => setIvMax(e.target.value)} placeholder="IV max" type="number" />
        <input className="border rounded px-2 py-1" value={pcMax} onChange={(e) => setPcMax(e.target.value)} placeholder="P/C max" type="number" />
        <input className="border rounded px-2 py-1" value={minVol} onChange={(e) => setMinVol(e.target.value)} placeholder="Min vol" type="number" />
      </div>
      <div className="overflow-auto">
        <table className="min-w-full text-sm">
          <thead className="bg-white text-xs uppercase text-gray-500 sticky top-0"><tr>{['Ticker','IV Rank','P/C Ratio','Volume','OI','Implied Move','Sentiment'].map((h)=><th key={h} className="py-2 pr-3 text-left">{h}</th>)}</tr></thead>
          <tbody>
            {rows.map((r, idx) => <tr key={r.ticker} onClick={() => onSelect(r.ticker)} className={`${idx % 2 ? 'bg-white' : 'bg-gray-50'} hover:bg-blue-50 cursor-pointer`}><td className="py-2 font-mono-data">{r.ticker}</td><td>{r.ivRank}</td><td>{r.putCallRatio}</td><td>{r.volume.toLocaleString()}</td><td>{r.openInterest.toLocaleString()}</td><td>{r.impliedMove}%</td><td>{r.sentimentScore}</td></tr>)}
          </tbody>
        </table>
      </div>
      {details && (
        <aside className="mt-4 bg-white border rounded-lg p-3">
          <h3 className="font-semibold mb-2">{details.ticker} Details</h3>
          <p className="text-sm mb-2">Max Pain: <span className="font-mono-data">{details.maxPain}</span></p>
          <p className="text-sm mb-2">Greeks Δ {details.greeks.delta} Γ {details.greeks.gamma} Θ {details.greeks.theta} ν {details.greeks.vega}</p>
          <div className="text-xs space-y-1">{details.chainSnapshot.map((c)=><div key={c.strike}>Strike {c.strike}: Calls {c.callOi} / Puts {c.putOi}</div>)}</div>
        </aside>
      )}
    </section>
  );
}
