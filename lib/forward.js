function fail(status, code, error) {
  return { status, body: { success: false, code, error } };
}

export function createForward({ fetcher = fetch, env = process.env } = {}) {
  return async uid => {
    if (typeof uid !== 'string' || !/^[0-9]{6,20}$/.test(uid)) {
      return fail(400, 'INVALID_UID', 'UID must contain 6-20 ASCII digits.');
    }
    if (!env.FF_WORKER_URL) return fail(503, 'WORKER_NOT_CONFIGURED', 'Configure FF_WORKER_URL for the original Python backend.');
    let url;
    try {
      const base = new URL(env.FF_WORKER_URL);
      if (!['http:', 'https:'].includes(base.protocol) || base.username || base.password || base.search || base.hash) throw new Error();
      url = new URL(`api/ff/${uid}`, `${base.href.replace(/\/$/, '')}/`);
    } catch {
      return fail(503, 'WORKER_CONFIGURATION_REQUIRED', 'FF_WORKER_URL must be a valid HTTP(S) backend URL.');
    }
    try {
      const headers = { Accept: 'application/json' };
      if (env.WORKER_API_KEY) headers.Authorization = `Bearer ${env.WORKER_API_KEY}`;
      const response = await fetcher(url, {
        method: 'GET', headers, redirect: 'manual', signal: AbortSignal.timeout(80000),
      });
      let data;
      try { data = await response.json(); }
      catch { return fail(502, 'WORKER_INVALID_RESPONSE', 'The Python backend returned a non-JSON response.'); }
      if (!data || typeof data !== 'object' || Array.isArray(data)) {
        return fail(502, 'WORKER_INVALID_RESPONSE', 'The Python backend returned an unexpected response.');
      }
      if (data.success === true) {
        if (!response.ok || String(data.uid) !== uid || typeof data.nickname !== 'string' || !data.nickname.trim()) {
          return fail(502, 'WORKER_INVALID_RESPONSE', 'No matching player nickname was confirmed by the backend.');
        }
        const body = {};
        for (const key of ['success', 'uid', 'nickname', 'region', 'open_id', 'img_url', 'checked_at', 'latency_ms']) {
          if (Object.hasOwn(data, key)) body[key] = data[key];
        }
        return { status: response.status, body };
      }
      const code = typeof data.code === 'string' && /^[A-Z0-9_]{1,64}$/.test(data.code) ? data.code : 'WORKER_LOOKUP_FAILED';
      const error = typeof data.error === 'string' ? data.error.replace(/https?:\/\/[^\s'"<>]+/g, '[URL]').slice(0, 240) : 'The Python backend could not confirm player information.';
      return { status: response.ok ? 502 : response.status >= 400 ? response.status : 502,
        body: { success: false, uid, code, error, ...(data.checked_at ? { checked_at: data.checked_at } : {}) } };
    } catch (error) {
      const timeout = error?.name === 'TimeoutError' || error?.name === 'AbortError';
      return fail(timeout ? 504 : 502, timeout ? 'WORKER_TIMEOUT' : 'WORKER_UNAVAILABLE',
        timeout ? 'The Python backend timed out.' : 'The Python backend could not be reached.');
    }
  };
}

export const forward = createForward();
