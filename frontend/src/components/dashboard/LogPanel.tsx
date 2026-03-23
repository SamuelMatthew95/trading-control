export function LogPanel({ events, isDark }: { events: Array<Record<string, unknown>>; isDark: boolean }) {
  const card = isDark ? 'border-slate-700 bg-slate-900/80 text-slate-100' : 'border-slate-300 bg-white text-slate-900';
  const row = isDark ? 'border-slate-700 bg-slate-950 text-slate-300' : 'border-slate-300 bg-slate-50 text-slate-700';

  return (
    <div className={`rounded-xl border p-4 ${card}`}>
      <h3 className="mb-3 text-lg font-semibold">Execution Logs</h3>
      <div className="max-h-80 space-y-2 overflow-auto font-mono text-xs">
        {events.map((event, idx) => (
          <details key={idx} className={`rounded border p-2 ${row}`}>
            <summary className="cursor-pointer text-cyan-500">{String(event.event_type || 'event')} • {String(event.timestamp || '')}</summary>
            <pre className="mt-2 whitespace-pre-wrap">{JSON.stringify(event, null, 2)}</pre>
          </details>
        ))}
      </div>
    </div>
  );
}
