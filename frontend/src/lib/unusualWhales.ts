export interface FlowAlert {
  id: string;
  ticker: string;
  strike: number;
  expiry: string;
  optionType: 'CALL' | 'PUT';
  premium: number;
  size: number;
  sentiment: 'Bullish' | 'Bearish';
  time: string;
  tag: 'Sweep' | 'Block' | 'Unusual';
}

export interface ScreenerRow {
  ticker: string;
  ivRank: number;
  putCallRatio: number;
  volume: number;
  openInterest: number;
  impliedMove: number;
  sentimentScore: number;
}

export interface TickerDetails {
  ticker: string;
  maxPain: number;
  chainSnapshot: Array<{ strike: number; callOi: number; putOi: number }>;
  greeks: { delta: number; gamma: number; theta: number; vega: number };
  optionMid: number;
}

const MCP_URL = process.env.UNUSUAL_WHALES_MCP_URL || 'https://api.unusualwhales.com/api/mcp';

async function callMcpTool<T>(tool: string, args: Record<string, unknown> = {}): Promise<T> {
  if (!process.env.UW_API_KEY) {
    throw new Error('UW_API_KEY is missing');
  }

  const response = await fetch(MCP_URL, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${process.env.UW_API_KEY}`,
    },
    body: JSON.stringify({
      jsonrpc: '2.0',
      id: `${tool}-${Date.now()}`,
      method: 'tools/call',
      params: { name: tool, arguments: args },
    }),
  });

  if (!response.ok) {
    throw new Error(`MCP request failed with ${response.status}`);
  }

  const payload = await response.json();
  if (payload.error) {
    throw new Error(payload.error.message || 'MCP tool call failed');
  }

  return payload.result?.content ?? payload.result;
}

export async function getOptionsFlow(): Promise<FlowAlert[]> {
  try {
    const data = await callMcpTool<FlowAlert[]>('options_flow_alerts');
    return data?.length ? data : buildMockFlow();
  } catch {
    return buildMockFlow();
  }
}

export async function getOptionsScreener(): Promise<ScreenerRow[]> {
  try {
    const data = await callMcpTool<ScreenerRow[]>('options_screener');
    return data?.length ? data : buildMockScreener();
  } catch {
    return buildMockScreener();
  }
}

export async function getTickerDetails(ticker: string): Promise<TickerDetails> {
  try {
    return await callMcpTool<TickerDetails>('options_ticker_snapshot', { ticker });
  } catch {
    return {
      ticker,
      maxPain: 450,
      optionMid: 4.12,
      chainSnapshot: [
        { strike: 430, callOi: 11240, putOi: 7300 },
        { strike: 440, callOi: 15880, putOi: 10220 },
        { strike: 450, callOi: 18800, putOi: 12005 },
      ],
      greeks: { delta: 0.42, gamma: 0.03, theta: -0.08, vega: 0.22 },
    };
  }
}

function buildMockFlow(): FlowAlert[] {
  return [
    { id: '1', ticker: 'NVDA', strike: 980, expiry: '2026-03-21', optionType: 'CALL', premium: 520000, size: 2200, sentiment: 'Bullish', time: new Date().toISOString(), tag: 'Sweep' },
    { id: '2', ticker: 'TSLA', strike: 240, expiry: '2026-01-17', optionType: 'PUT', premium: 340000, size: 1800, sentiment: 'Bearish', time: new Date().toISOString(), tag: 'Block' },
    { id: '3', ticker: 'SPY', strike: 600, expiry: '2025-12-19', optionType: 'CALL', premium: 290000, size: 6000, sentiment: 'Bullish', time: new Date().toISOString(), tag: 'Unusual' },
  ];
}

function buildMockScreener(): ScreenerRow[] {
  return [
    { ticker: 'NVDA', ivRank: 78, putCallRatio: 0.72, volume: 120340, openInterest: 560000, impliedMove: 6.3, sentimentScore: 84 },
    { ticker: 'AAPL', ivRank: 55, putCallRatio: 1.15, volume: 87500, openInterest: 420000, impliedMove: 4.1, sentimentScore: 62 },
    { ticker: 'TSLA', ivRank: 81, putCallRatio: 1.34, volume: 140090, openInterest: 610200, impliedMove: 8.2, sentimentScore: 41 },
  ];
}
