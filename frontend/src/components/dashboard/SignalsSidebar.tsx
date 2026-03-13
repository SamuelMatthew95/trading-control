import { useEffect, useState } from 'react';
import axios from 'axios';

type Signal = {
  id: string;
  priority: 'urgent' | 'review' | 'info';
  message: string;
  action_label: string;
  action_type: 'flag' | 'reinforce' | 'view_run' | 'dismiss';
};

export function SignalsSidebar() {
  const [open, setOpen] = useState(true);
  const [items, setItems] = useState<Signal[]>([]);

  const load = async () => {
    const res = await axios.get('/signals');
    setItems(res.data.items || []);
  };

  useEffect(() => {
    load().catch(() => undefined);
    const t = setInterval(() => load().catch(() => undefined), 60000);
    return () => clearInterval(t);
  }, []);

  const dismiss = async (id: string) => {
    const prev = items;
    setItems((curr) => curr.filter((x) => x.id !== id));
    try {
      await axios.post(`/signals/${id}/dismiss`);
    } catch {
      setItems(prev);
    }
  };

  if (!open) return <button className="fixed right-2 top-1/2 rounded bg-slate-800 px-2 py-1 text-white" onClick={() => setOpen(true)}>Signals</button>;

  return (
    <aside className="fixed right-0 top-0 h-full w-72 overflow-y-auto border-l border-slate-700 bg-slate-900 p-3 text-slate-100">
      <div className="mb-3 flex items-center justify-between"><h3 className="font-semibold">Signals</h3><button onClick={() => setOpen(false)}>×</button></div>
      {(['urgent', 'review', 'info'] as const).map((priority) => (
        <section key={priority} className="mb-4">
          <h4 className="mb-2 text-sm font-bold capitalize">{priority}</h4>
          {items.filter((x) => x.priority === priority).map((s) => (
            <div key={s.id} className="mb-2 rounded border border-slate-700 p-2 text-xs">
              <p>{s.message}</p>
              <button className="mt-1 rounded bg-slate-700 px-2 py-1" onClick={() => dismiss(s.id)}>{s.action_label}</button>
            </div>
          ))}
        </section>
      ))}
    </aside>
  );
}
