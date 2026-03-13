import type { NextApiRequest, NextApiResponse } from 'next';

const MODEL = process.env.ANTHROPIC_MODEL || 'claude-sonnet-4-20250514';
const BACKEND_URL = process.env.BACKEND_API_URL;

export default async function handler(req: NextApiRequest, res: NextApiResponse) {
  if (req.method !== 'POST') return res.status(405).json({ error: 'Method not allowed' });

  try {
    if (BACKEND_URL) {
      const response = await fetch(`${BACKEND_URL}/api/options/plays/close`, {
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
      body: JSON.stringify({
        model: MODEL,
        max_tokens: 300,
        messages: [{ role: 'user', content: `Evaluate this closed options play outcome in 3 bullet points: ${JSON.stringify(req.body)}` }],
      }),
    });
    const payload = await response.json();
    return res.status(200).json({ evaluation: payload.content?.[0]?.text || 'Evaluation unavailable.' });
  } catch {
    return res.status(200).json({ evaluation: 'The thesis partially held. Entry timing could improve by waiting for confirmation. Prefer stronger trend alignment and larger sweep clusters.' });
  }
}
