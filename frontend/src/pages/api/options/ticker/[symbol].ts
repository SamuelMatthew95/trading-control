import type { NextApiRequest, NextApiResponse } from 'next';
import { getTickerDetails } from '@/lib/unusualWhales';

const BACKEND_URL = process.env.BACKEND_API_URL;

export default async function handler(req: NextApiRequest, res: NextApiResponse) {
  try {
    const symbol = String(req.query.symbol || '').toUpperCase();

    if (BACKEND_URL) {
      const response = await fetch(`${BACKEND_URL}/api/options/ticker/${symbol}`);
      if (response.ok) {
        const data = await response.json();
        return res.status(200).json(data);
      }
    }

    const item = await getTickerDetails(symbol);
    return res.status(200).json({ item });
  } catch (error: any) {
    return res.status(500).json({ error: error.message || 'Failed to load ticker details' });
  }
}
