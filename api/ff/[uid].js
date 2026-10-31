import { forward } from '../../lib/forward.js';
import { send } from '../../lib/send.js';

export default async function handler(req, res) {
  if (req.method !== 'GET') return send(res, 405, { success: false, code: 'METHOD_NOT_ALLOWED', error: 'Use GET.' }, { Allow: 'GET' });
  const result = await forward(req.query?.uid);
  send(res, result.status, result.body);
}
