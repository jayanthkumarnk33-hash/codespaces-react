import { send } from '../lib/send.js';
export default function handler(_req, res) {
  send(res, 200, { success: true, status: 'ok', worker_configured: Boolean(process.env.FF_WORKER_URL), note: 'Gateway process health only.' });
}
