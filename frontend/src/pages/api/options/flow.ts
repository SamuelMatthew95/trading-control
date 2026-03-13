import type { NextApiRequest, NextApiResponse } from 'next';
import { getOptionsFlow } from '@/lib/unusualWhales';

const BACKEND_URL = process.env.BACKEND_API_URL;

export default async function handler(_req: NextApiRequest, res: NextApiResponse) {
  try {
    if (BACKEND_URL) {
      const response = await fetch(`${BACKEND_URL}/api/options/flow`);
      if (response.ok) {
        const data = await response.json();
        return res.status(200).json(data);
      }
    }

    const items = await getOptionsFlow();
    return res.status(200).json({ items });
  } catch (error: any) {
    return res.status(500).json({ error: error.message || 'Failed to load flow' });
  }
}
