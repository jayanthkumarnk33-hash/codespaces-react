import test from 'node:test';
import assert from 'node:assert/strict';
import { createForward } from '../lib/forward.js';

test('invalid UID and absent backend do not make requests', async () => {
  const call = createForward({ env: {}, fetcher: () => { throw new Error('must not call'); } });
  assert.equal((await call('abc')).status, 400);
  assert.equal((await call('11111119')).body.code, 'WORKER_NOT_CONFIGURED');
});
test('gateway delegates UID to Python and forwards only player fields', async () => {
  const call = createForward({ env: { FF_WORKER_URL: 'https://worker.example', WORKER_API_KEY: 'test-only' },
    fetcher: async (url, options) => {
      assert.equal(url.href, 'https://worker.example/api/ff/11111119');
      assert.equal(options.headers.Authorization, 'Bearer test-only');
      return Response.json({ success: true, uid: '11111119', nickname: 'Sample', region: 'US', session_key: 'private' });
    },
  });
  const result = await call('11111119');
  assert.equal(result.body.nickname, 'Sample');
  assert.ok(!JSON.stringify(result).includes('private'));
});
test('Python challenge remains a challenge and is not replaced with a name', async () => {
  const call = createForward({ env: { FF_WORKER_URL: 'https://worker.example' }, fetcher: async () => Response.json({ success: false, uid: '11111119', code: 'LOOKUP_CHALLENGE', error: 'HTTP 403: Garena requires verification.' }, { status: 503 }) });
  const result = await call('11111119');
  assert.equal(result.status, 503);
  assert.equal(result.body.code, 'LOOKUP_CHALLENGE');
});
test('wrong UID, HTTP errors and non-JSON responses never produce success', async () => {
  for (const response of [Response.json({ success: true, uid: '22222222', nickname: 'Other' }), new Response('<html/>', { status: 502 }), Response.json({ success: true, uid: '11111119', nickname: 'Sample' }, { status: 500 })]) {
    const call = createForward({ env: { FF_WORKER_URL: 'https://worker.example' }, fetcher: async () => response });
    assert.equal((await call('11111119')).body.success, false);
  }
});
test('backend timeout is reported without leaking the target URL or key', async () => {
  const call = createForward({ env: { FF_WORKER_URL: 'https://worker.example' }, fetcher: async () => { throw new DOMException('private', 'TimeoutError'); } });
  const result = await call('11111119');
  assert.equal(result.body.code, 'WORKER_TIMEOUT');
  assert.ok(!JSON.stringify(result).includes('private'));
});
