import { SuggestedPlay } from './PlayCard';

export interface ActivePlay extends SuggestedPlay {
  status: 'OPEN' | 'UP' | 'DOWN' | 'EXPIRED' | 'CLOSED';
  currentPrice: number;
}

interface Props {
  plays: ActivePlay[];
  onClose: (play: ActivePlay) => void;
}

export default function ActivePlays({ plays, onClose }: Props) {
  return (
    <section className="bg-[#F5F5F5] rounded-lg border border-gray-200 p-4 shadow-sm">
      <h2 className="text-lg font-semibold mb-3">Active Plays</h2>
      <div className="space-y-2">
        {plays.map((play) => {
          const pnl = play.currentPrice - play.entry_price_estimate;
          return (
            <div key={`${play.ticker}-${play.expiry}-${play.strike}`} className="bg-white rounded border p-3 flex flex-wrap gap-3 items-center justify-between">
              <div>
                <div className="font-mono-data">{play.ticker} {play.action} {play.strike} {play.expiry}</div>
                <div className={`text-sm ${pnl >= 0 ? 'text-green-700' : 'text-red-700'}`}>P&L Est: {pnl >= 0 ? '+' : ''}${pnl.toFixed(2)}</div>
              </div>
              <span className="text-xs px-2 py-1 rounded bg-gray-100">{play.status}</span>
              <button onClick={() => onClose(play)} className="text-sm px-2 py-1 border rounded">Close</button>
            </div>
          );
        })}
        {plays.length === 0 && <p className="text-sm text-gray-500">No active plays yet.</p>}
      </div>
    </section>
  );
}
