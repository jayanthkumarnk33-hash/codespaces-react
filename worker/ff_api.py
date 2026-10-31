# ff_api.py
import threading
import time
import logging
import atexit
from dataclasses import dataclass, field
from datetime import datetime, timezone
from curl_cffi import requests as cr
from flask import Flask, jsonify
from data_dome import DataDomeTokenProvider, BrowserTokenError

# ─────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────
GARENA_PAGE  = "https://shop.garena.sg/?app=100067"
GARENA_API   = "https://shop.garena.sg/api/auth/player_id_login"
APP_ID       = 100067
REFRESH_SEC  = 8 * 60          # refresh ordinary HTTP session cookies
POOL_SIZE    = 3               # 3 independent sessions (if one dies, 2 back up)
RETRY_LIMIT  = 2               # two total attempts for a challenge response

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

CHROME_HEADERS = {
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Sec-Ch-Ua": '"Chromium";v="124", "Google Chrome";v="124"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"Windows"',
}

API_HEADERS = {
    "User-Agent": UA,
    "Content-Type": "application/json",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Origin": "https://shop.garena.sg",
    "Referer": GARENA_PAGE,
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
}

log = logging.getLogger("ff_api")
log.setLevel(logging.INFO)
logging.basicConfig(format="%(asctime)s %(levelname)s %(message)s")


# ─────────────────────────────────────────────
# Session (one Chrome-fingerprinted connection)
# ─────────────────────────────────────────────
@dataclass
class FFSession:
    index: int
    cr_session: cr.Session = field(init=False)
    cookies: dict = field(default_factory=dict)
    last_refresh: float = field(default_factory=time.time)
    dd_provider: DataDomeTokenProvider | None = field(default=None, repr=False)

    def __post_init__(self):
        # Supported Chrome profile; Garena may still require verification.
        self.cr_session = cr.Session(impersonate="chrome124")
        self.refresh()

    def refresh(self):
        """Refresh ordinary session cookies; this does not prove clearance."""
        try:
            r = self.cr_session.get(GARENA_PAGE, headers=CHROME_HEADERS, timeout=15)
            self.last_refresh = time.time()
            # cookies are stored inside cr_session automatically
            log.info(f"[S{self.index}] refreshed  status={r.status_code}  "
                     f"cf_clearance={'✓' if 'cf_clearance' in self.cr_session.cookies else '✗'}")
        except Exception as e:
            log.warning(f"[S{self.index}] refresh failed: {e}")

    def lookup(self, uid: str) -> dict:
        """POST the UID lookup using this session's cookies."""
        if self.dd_provider is not None:
            dd_token = self.dd_provider.get_token()
            # Preserve the other session cookies, replacing only DataDome.
            self.cr_session.cookies.delete("datadome")
            self.cr_session.cookies.set("datadome", dd_token, domain="shop.garena.sg", path="/")
        r = self.cr_session.post(
            GARENA_API,
            json={"app_id": APP_ID, "login_id": uid},
            headers=API_HEADERS,
            timeout=15,
        )
        try:
            body = r.json()
        except ValueError:
            body = None
        return {
            "status": r.status_code,
            "json": body,
        }


# ─────────────────────────────────────────────
# Pool – holds N sessions, picks a healthy one
# ─────────────────────────────────────────────
class SessionPool:
    def __init__(self, size: int = POOL_SIZE):
        self._lock = threading.Lock()
        self.dd_provider = DataDomeTokenProvider(headless=True, user_agent=UA)
        self.sessions: list[FFSession] = [FFSession(i, dd_provider=self.dd_provider) for i in range(size)]
        self._cursor = 0

    def _pick(self) -> FFSession:
        """Round-robin pick the least-recently-used session."""
        with self._lock:
            # find session with oldest last_refresh
            s = min(self.sessions, key=lambda s: s.last_refresh)
            return s

    def get(self) -> FFSession:
        return self._pick()

    def refresh_all(self):
        """Called by background thread every REFRESH_SEC."""
        for s in self.sessions:
            s.refresh()
        log.info(f"[POOL] all {len(self.sessions)} sessions refreshed at "
                 f"{datetime.now(timezone.utc).isoformat()}")


# ─────────────────────────────────────────────
# Background Refresher – runs forever
# ─────────────────────────────────────────────
class BackgroundRefresher(threading.Thread):
    def __init__(self, pool: SessionPool):
        super().__init__(daemon=True, name="CFRefresher")
        self.pool = pool

    def run(self):
        log.info(f"[REFRESHER] started – interval={REFRESH_SEC}s")
        while True:
            try:
                self.pool.refresh_all()
            except Exception as e:
                log.warning(f"[REFRESHER] tick error: {e}")
            time.sleep(REFRESH_SEC)


# ─────────────────────────────────────────────
# Lookup with auto-retry
# ─────────────────────────────────────────────
def lookup_uid(pool: SessionPool, uid: str) -> dict:
    last_err = None
    last_code = "LOOKUP_RESTRICTED"
    for attempt in range(1, RETRY_LIMIT + 1):
        s = pool.get()
        try:
            result = s.lookup(uid)
        except BrowserTokenError as error:
            return {"success": False, "code": error.code,
                    "error": "Browser could not provide a candidate DataDome cookie."}
        except Exception as error:
            log.warning("Lookup request failed (%s)", type(error).__name__)
            return {"success": False, "code": "LOOKUP_UNAVAILABLE",
                    "error": "The lookup request failed before a usable response was received."}
        body = result["json"]

        if (result["status"] == 200 and isinstance(body, dict) and body.get("open_id")
                and isinstance(body.get("nickname"), str) and body["nickname"].strip()):
            return {"success": True, "data": body}

        last_err = f"HTTP {result['status']}"
        challenge = (isinstance(body, dict) and isinstance(body.get("url"), str)
                     and any(marker in body["url"].lower() for marker in ("captcha", "challenge")))
        if challenge:
            last_code = "LOOKUP_CHALLENGE"
            last_err = f"HTTP {result['status']}: Garena requires verification."
            log.warning("[LOOKUP] %s attempt %s: upstream challenge", uid, attempt)
            pool.dd_provider.invalidate()
            if attempt < RETRY_LIMIT:
                time.sleep(0.5 * attempt)
                continue
        elif result["status"] == 429:
            last_code = "LOOKUP_RATE_LIMIT"
        elif result["status"] == 200:
            last_code = "LOOKUP_INVALID_RESPONSE"
            last_err = "Garena did not return confirmed player information."
        break

    return {"success": False, "code": last_code, "error": last_err or "lookup failed"}


# ─────────────────────────────────────────────
# Flask routes
# ─────────────────────────────────────────────
app = Flask(__name__)
pool  = SessionPool(POOL_SIZE)
atexit.register(pool.dd_provider.shutdown)
thread = BackgroundRefresher(pool)
thread.start()


@app.get("/api/ff/<uid>")
def api_ff(uid: str):
    if not uid.isdigit() or not (6 <= len(uid) <= 20):
        return jsonify({"success": False, "error": "UID must be 6-20 digits"}), 400

    t0 = time.time()
    res = lookup_uid(pool, uid)
    elapsed = round(time.time() - t0, 3)

    if res["success"]:
        d = res["data"]
        return jsonify({
            "success": True,
            "uid": uid,
            "open_id":  d.get("open_id"),
            "region":   d.get("region"),
            "nickname": d.get("nickname"),
            "img_url":  d.get("img_url"),
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "latency_ms": elapsed * 1000,
        })

    return jsonify({
        "success": False,
        "uid": uid,
        "code": res.get("code", "LOOKUP_RESTRICTED"),
        "error": res["error"],
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }), 503


@app.get("/health")
def health():
    """Ops endpoint – shows pool state."""
    return jsonify({
        "status": "ok",
        "pool_size": len(pool.sessions),
        "sessions": [
            {
                "index": s.index,
                "cf_clearance": "✓" if "cf_clearance" in s.cr_session.cookies else "✗",
                "last_refresh": datetime.fromtimestamp(s.last_refresh, tz=timezone.utc).isoformat(),
                "age_sec": round(time.time() - s.last_refresh),
            }
            for s in pool.sessions
        ],
        "refresher_alive": thread.is_alive(),
    })


# ─────────────────────────────────────────────
# Start
# ─────────────────────────────────────────────
if __name__ == "__main__":
    print(f"""
    ╔══════════════════════════════════════════╗
    ║  🔥 Free Fire UID API                   ║
    ║  Pool: {POOL_SIZE} sessions              ║
    ║  Auto-refresh: every {REFRESH_SEC // 60} min          ║
    ║  Listen: http://0.0.0.0:3000            ║
    ║                                        ║
    ║  GET  /api/ff/<uid>                    ║
    ║  GET  /health                          ║
    ╚══════════════════════════════════════════╝
    """)
    app.run(host="0.0.0.0", port=3000)
