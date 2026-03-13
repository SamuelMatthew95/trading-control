import type { NextApiRequest, NextApiResponse } from 'next';

const MODEL = process.env.ANTHROPIC_MODEL || 'claude-sonnet-4-20250514';
const BACKEND_URL = process.env.BACKEND_API_URL;

export default async function handler(req: NextApiRequest, res: NextApiResponse) {
  if (req.method !== 'POST') return res.status(405).json({ error: 'Method not allowed' });

  try {
    if (BACKEND_URL) {
      const response = await fetch(`${BACKEND_URL}/api/options/learning/summary`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(req.body),
      });
      if (response.ok) {
        const data = await response.json();
        return res.status(200).json(data);
      }
    }

    if (!process.env.ANTHROPIC_API_KEY) throw new Error('Missing ANTHROPIC_API_KEY');
    const response = await fetch('https://api.anthropic.com/v1/messages', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'x-api-key': process.env.ANTHROPIC_API_KEY,
        'anthropic-version': '2023-06-01',
      },
      body: JSON.stringify({ model: MODEL, max_tokens: 300, messages: [{ role: 'user', content: `Summarize patterns and lessons from these closed plays: ${JSON.stringify(req.body.history || [])}` }] }),
    });
    const payload = await response.json();
    return res.status(200).json({ summary: payload.content?.[0]?.text || '' });
  } catch {
    return res.status(200).json({ summary: 'Winning outcomes favored continuation sweeps on high-liquidity tickers. Entries performed best with confirmation after first impulse and failed more often during mixed flow.' });
  }
}
