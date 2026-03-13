interface Props {
  winRate: number;
  bestSignal: string;
  summary: string;
}

export default function LearningSummary({ winRate, bestSignal, summary }: Props) {
  return (
    <section className="bg-[#F5F5F5] rounded-lg border border-gray-200 p-4 shadow-sm">
      <h2 className="text-lg font-semibold mb-2">Learning Summary</h2>
      <div className="grid grid-cols-1 md:grid-cols-3 gap-3 mb-3">
        <div className="bg-white rounded border p-3"><p className="text-xs text-gray-500">Win Rate</p><p className="text-xl font-semibold">{winRate.toFixed(1)}%</p></div>
        <div className="bg-white rounded border p-3"><p className="text-xs text-gray-500">Most Accurate Signal</p><p className="text-xl font-semibold">{bestSignal}</p></div>
        <div className="bg-white rounded border p-3"><p className="text-xs text-gray-500">Feedback Loop</p><p className="text-sm">Updates from last 10 closed plays.</p></div>
      </div>
      <p className="text-sm bg-white rounded border p-3">{summary || 'Close more plays to build a stronger feedback loop.'}</p>
    </section>
  );
}
