export interface ClosedPlayRecord {
  ticker: string;
  action: string;
  pnl: number;
  status: string;
  closedAt: string;
  evaluation?: string;
  signalTag?: string;
}

const STORAGE_KEY = 'uw_play_history';

export function readPlayHistory(): ClosedPlayRecord[] {
  if (typeof window === 'undefined') return [];
  const raw = localStorage.getItem(STORAGE_KEY);
  if (!raw) return [];

  try {
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

export function appendClosedPlay(play: ClosedPlayRecord) {
  if (typeof window === 'undefined') return;
  const current = readPlayHistory();
  current.unshift(play);
  localStorage.setItem(STORAGE_KEY, JSON.stringify(current));
}
