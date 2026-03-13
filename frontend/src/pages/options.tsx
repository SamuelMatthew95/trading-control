import { useEffect, useState } from 'react';
import TopNav from '@/components/layout/TopNav';
import FlowFeed from '@/components/options/FlowFeed';
import Screener from '@/components/options/Screener';
import PlayCard, { SuggestedPlay } from '@/components/options/PlayCard';
import ActivePlays, { ActivePlay } from '@/components/options/ActivePlays';
import LearningSummary from '@/components/options/LearningSummary';
import { appendClosedPlay, readPlayHistory } from '@/lib/playStore';
import { FlowAlert, ScreenerRow, TickerDetails } from '@/lib/unusualWhales';

export default function OptionsPage() {
  const [flow, setFlow] = useState<FlowAlert[]>([]);
  const [screener, setScreener] = useState<ScreenerRow[]>([]);
  const [details, setDetails] = useState<TickerDetails | null>(null);
  const [loadingFlow, setLoadingFlow] = useState(false);
  const [plays, setPlays] = useState<SuggestedPlay[]>([]);
  const [active, setActive] = useState<ActivePlay[]>([]);
  const [learningText, setLearningText] = useState('');
  const [generating, setGenerating] = useState(false);
  const [agentTrace, setAgentTrace] = useState<Array<{ agent: string; summary: string }>>([]);
  const [guardrailState, setGuardrailState] = useState<{ kill_switch: boolean; rejected_count: number; requires_human_review?: boolean } | null>(null);
  const [taskPlan, setTaskPlan] = useState<string[]>([]);

  const loadFlow = async () => {
    setLoadingFlow(true);
    const res = await fetch('/api/options/flow');
    const data = await res.json();
    setFlow(data.items || []);
    setLoadingFlow(false);
  };

  const loadScreener = async () => {
    const res = await fetch('/api/options/screener');
    const data = await res.json();
    setScreener(data.items || []);
  };

  useEffect(() => {
    loadFlow();
    loadScreener();
    const minutePoll = setInterval(loadFlow, 60000);
    return () => clearInterval(minutePoll);
  }, []);

  useEffect(() => {
    const interval = setInterval(async () => {
      const updated = await Promise.all(active.map(async (play) => {
        const res = await fetch(`/api/options/ticker/${play.ticker}`);
        const data = await res.json();
        const currentPrice = data.item?.optionMid || play.currentPrice;
        const status = currentPrice >= play.entry_price_estimate ? 'UP' : 'DOWN';
        return { ...play, currentPrice, status } as ActivePlay;
      }));
      if (updated.length) setActive(updated);
    }, 300000);
    return () => clearInterval(interval);
  }, [active]);

  const generatePlays = async () => {
    setGenerating(true);
    const learningContext = readPlayHistory().slice(0, 10);
    const res = await fetch('/api/options/generate-plays', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ flow, screener, learningContext }),
    });
    const data = await res.json();
    setPlays(data.items || []);
    setAgentTrace(data.agent_trace || []);
    setGuardrailState(data.guardrail || null);
    setTaskPlan(data.task_plan || []);
    setGenerating(false);
  };

  const closePlay = async (play: ActivePlay) => {
    const pnl = play.currentPrice - play.entry_price_estimate;
    const evalRes = await fetch('/api/options/evaluate-play', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ play, pnl, recentFlow: flow.filter((f) => f.ticker === play.ticker) }),
    });
    const data = await evalRes.json();
    appendClosedPlay({ ticker: play.ticker, action: play.action, pnl, status: 'CLOSED', closedAt: new Date().toISOString(), evaluation: data.evaluation, signalTag: flow.find((f) => f.ticker === play.ticker)?.tag });
    setActive((prev) => prev.filter((p) => p !== play));
  };

  useEffect(() => {
    const history = readPlayHistory();
    const winRate = history.length ? (history.filter((h) => h.pnl > 0).length / history.length) * 100 : 0;
    const bestSignal = history.reduce<Record<string, number>>((acc, item) => {
      const k = item.signalTag || 'Unknown';
      acc[k] = (acc[k] || 0) + (item.pnl > 0 ? 1 : 0);
      return acc;
    }, {});
    const best = Object.entries(bestSignal).sort((a, b) => b[1] - a[1])[0]?.[0] || 'N/A';
    fetch('/api/options/learning-summary', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ history: history.slice(0, 10), winRate, bestSignal: best }) })
      .then((r) => r.json())
      .then((d) => setLearningText(d.summary || ''));
  }, [active.length, plays.length]);

  const history = readPlayHistory();
  const metrics = {
    winRate: history.length ? (history.filter((h) => h.pnl > 0).length / history.length) * 100 : 0,
    best: history.find((h) => h.pnl > 0)?.signalTag || 'N/A',
  };

  return (
    <div className="min-h-screen bg-gray-50 p-6">
      <div className="max-w-7xl mx-auto space-y-6">
        <header className="bg-white rounded-lg shadow-sm p-6">
          <h1 className="text-3xl font-bold">Options Intelligence</h1>
          <p className="text-gray-600 mt-1">Flow, screener insights, confirmed plays, and feedback-driven learning.</p>
        </header>
        <TopNav />

        <FlowFeed data={flow} loading={loadingFlow} onRefresh={loadFlow} />
        <Screener data={screener} details={details} onSelect={async (ticker) => {
          const res = await fetch(`/api/options/ticker/${ticker}`);
          const data = await res.json();
          setDetails(data.item || null);
        }} />

        <section className="bg-[#F5F5F5] rounded-lg border border-gray-200 p-4 shadow-sm">
          <div className="flex items-center justify-between mb-3">
            <h2 className="text-lg font-semibold">Confirmed Plays</h2>
            <button onClick={generatePlays} className="px-3 py-1 rounded bg-blue-600 text-white" disabled={generating}>{generating ? 'Generating...' : 'Generate Plays'}</button>
          </div>
          {guardrailState && (
            <div className={`mb-3 text-sm p-2 rounded border ${guardrailState.kill_switch ? 'bg-red-50 border-red-200 text-red-700' : 'bg-green-50 border-green-200 text-green-700'}`}>
              Guardrail: {guardrailState.kill_switch ? 'KILL SWITCH ACTIVE (no plays approved)' : `active (${guardrailState.rejected_count} rejected plays filtered)`}{guardrailState.requires_human_review ? ' · HUMAN REVIEW REQUIRED' : ''}
            </div>
          )}
          {taskPlan.length > 0 && (
            <div className="mb-3 bg-white border rounded p-3 text-sm">
              <h3 className="font-semibold mb-2">Orchestrator Task Plan</h3>
              <ol className="list-decimal ml-5">{taskPlan.map((step) => <li key={step}>{step}</li>)}</ol>
            </div>
          )}
          {agentTrace.length > 0 && (
            <div className="mb-3 bg-white border rounded p-3 text-sm">
              <h3 className="font-semibold mb-2">Options Agent Trace</h3>
              <div className="space-y-1">{agentTrace.map((trace) => <div key={trace.agent}><span className="font-mono-data">{trace.agent}</span>: {trace.summary}</div>)}</div>
            </div>
          )}
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
            {plays.map((play) => <PlayCard key={`${play.ticker}-${play.expiry}-${play.strike}`} play={play} onAccept={() => {
              setActive((prev) => [...prev, { ...play, status: 'OPEN', currentPrice: play.entry_price_estimate }]);
              setPlays((prev) => prev.filter((p) => p !== play));
            }} />)}
            {!plays.length && <p className="text-sm text-gray-500">Generate plays from current flow and screener context.</p>}
          </div>
        </section>

        <ActivePlays plays={active} onClose={closePlay} />
        <LearningSummary winRate={metrics.winRate} bestSignal={metrics.best} summary={learningText} />
      </div>
    </div>
  );
}
