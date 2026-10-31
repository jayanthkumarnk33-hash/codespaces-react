import http from 'node:http';
import lookup from './api/ff/[uid].js';
import health from './api/health.js';
import { send } from './lib/send.js';

const server = http.createServer((req, res) => {
  const path = new URL(req.url, 'http://localhost').pathname;
  const match = /^\/api\/ff\/([^/]+)\/?$/.exec(path);
  if (match) {
    try { req.query = { uid: decodeURIComponent(match[1]) }; }
    catch { return send(res, 400, { success: false, code: 'INVALID_UID' }); }
    return lookup(req, res);
  }
  if (['/', '/health', '/api/health'].includes(path)) return health(req, res);
  send(res, 404, { success: false, code: 'NOT_FOUND' });
});
const port = Number(process.env.PORT || 3000);
server.listen(port, '127.0.0.1', () => console.log(`Gateway ready at http://127.0.0.1:${port}`));
server.on('error', error => { console.error(`Gateway startup failed: ${error.code || 'UNKNOWN'}`); process.exitCode = 1; });
