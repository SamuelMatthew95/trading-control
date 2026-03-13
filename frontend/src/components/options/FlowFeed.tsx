import { useMemo, useState } from 'react';
import { FlowAlert } from '@/lib/unusualWhales';

interface Props {
  data: FlowAlert[];
  loading: boolean;
  onRefresh: () => void;
}

export default function FlowFeed({ data, loading, onRefresh }: Props) {
  const [ticker, setTicker] = useState('');
  const [side, setSide] = useState<'ALL' | 'CALL' | 'PUT'>('ALL');
  const [sweepsOnly, setSweepsOnly] = useState(false);
  const [minPremium, setMinPremium] = useState('0');

  const filtered = useMemo(() => data.filter((row) => {
    if (ticker && !row.ticker.toLowerCase().includes(ticker.toLowerCase())) return false;
    if (side !== 'ALL' && row.optionType !== side) return false;
    if (sweepsOnly && row.tag !== 'Sweep') return false;
    if (row.premium < Number(minPremium || 0)) return false;
    return true;
  }), [data, ticker, side, sweepsOnly, minPremium]);

  return (
    <section className="bg-[#F5F5F5] rounded-lg border border-gray-200 p-4 shadow-sm">
      <div className="flex items-center justify-between mb-3">
        <h2 className="text-lg font-semibold">Options Flow Feed</h2>
        <button onClick={onRefresh} className="text-sm px-3 py-1 bg-blue-600 text-white rounded">Refresh</button>
      </div>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-2 mb-3 text-sm">
        <input className="border rounded px-2 py-1" placeholder="Ticker" value={ticker} onChange={(e) => setTicker(e.target.value)} />
        <select className="border rounded px-2 py-1" value={side} onChange={(e) => setSide(e.target.value as any)}><option value="ALL">Calls + Puts</option><option value="CALL">Calls only</option><option value="PUT">Puts only</option></select>
        <input className="border rounded px-2 py-1" placeholder="Min Premium" type="number" value={minPremium} onChange={(e) => setMinPremium(e.target.value)} />
        <label className="flex items-center gap-2"><input type="checkbox" checked={sweepsOnly} onChange={(e) => setSweepsOnly(e.target.checked)} /> Sweeps only</label>
      </div>
      <div className="overflow-auto max-h-80">
        <table className="min-w-full text-sm">
          <thead className="sticky top-0 bg-white">
            <tr className="text-left text-xs uppercase text-gray-500">
              {['Ticker','Strike','Expiry','Type','Premium','Size','Sentiment','Time','Tag'].map((h)=><th key={h} className="py-2 pr-3">{h}</th>)}
            </tr>
          </thead>
          <tbody>
            {loading ? <tr><td className="py-4" colSpan={9}>Loading flow...</td></tr> : filtered.map((row, idx) => (
              <tr key={row.id} className={`${idx % 2 ? 'bg-white' : 'bg-gray-50'} ${row.sentiment === 'Bullish' ? 'bg-green-50/60' : 'bg-red-50/60'} transition-all`}>
                <td className="py-2 font-mono-data">{row.ticker}</td><td>{row.strike}</td><td>{row.expiry}</td><td>{row.optionType}</td><td>${row.premium.toLocaleString()}</td><td>{row.size.toLocaleString()}</td><td className={row.sentiment === 'Bullish' ? 'text-green-700' : 'text-red-700'}>{row.sentiment}</td><td>{new Date(row.time).toLocaleTimeString()}</td><td>{row.tag}</td>
              </tr>
            ))}
            {!loading && filtered.length === 0 && <tr><td className="py-4" colSpan={9}>No matching flow alerts.</td></tr>}
          </tbody>
        </table>
      </div>
    </section>
  );
}
