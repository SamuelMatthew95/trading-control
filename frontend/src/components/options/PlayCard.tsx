export interface SuggestedPlay {
  ticker: string;
  action: string;
  strike: number;
  expiry: string;
  reasoning: string;
  confidence: number;
  entry_price_estimate: number;
  target: number;
  stop_loss: number;
}

interface Props {
  play: SuggestedPlay;
  onAccept: () => void;
}

export default function PlayCard({ play, onAccept }: Props) {
  return (
    <article className="bg-white border rounded-lg p-4 shadow-sm animate-[fadeIn_.3s_ease-in]">
      <div className="flex items-center justify-between mb-2">
        <span className="font-mono-data text-lg">{play.ticker}</span>
        <span className="px-2 py-1 text-xs rounded bg-blue-100 text-blue-700">{play.action}</span>
      </div>
      <p className="text-sm text-gray-600 mb-2">{play.strike} • {play.expiry}</p>
      <p className="text-sm mb-3">{play.reasoning}</p>
      <div className="h-1 bg-gray-200 rounded mb-2"><div className="h-1 bg-blue-600 rounded" style={{ width: `${play.confidence * 100}%` }} /></div>
      <p className="text-xs mb-3">Entry ${play.entry_price_estimate} · Target ${play.target} · Stop ${play.stop_loss}</p>
      <button onClick={onAccept} className="px-3 py-1 text-sm bg-green-600 text-white rounded">Accept</button>
    </article>
  );
}
