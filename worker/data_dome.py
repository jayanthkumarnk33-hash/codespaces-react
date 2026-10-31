"""Cache a candidate DataDome cookie from a short-lived headless browser.

Cookie presence is not proof that a CAPTCHA was solved or API access was granted.
Only an accepted Garena lookup establishes that. This module does not interact
with CAPTCHA widgets or send challenges to an external solving service.
"""

from dataclasses import dataclass
import logging
import os
import threading
import time
from urllib.parse import unquote, urlsplit

try:
    from patchright.sync_api import sync_playwright
except ImportError:
    from playwright.sync_api import sync_playwright

logger = logging.getLogger(__name__)
TOKEN_TTL_SEC = 240
CHALLENGE_URL = "https://shop.garena.sg/"


class BrowserTokenError(RuntimeError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


@dataclass
class _TokenState:
    cookie: str = ""
    obtained_at: float = 0

    @property
    def is_valid(self):
        return bool(self.cookie) and time.monotonic() - self.obtained_at < TOKEN_TTL_SEC


class DataDomeTokenProvider:
    def __init__(self, headless=True, user_agent=None):
        self._lock = threading.Lock()
        self._state = _TokenState()
        self._headless = headless
        self._user_agent = user_agent

    def get_token(self):
        with self._lock:
            if not self._state.is_valid:
                self._state = _TokenState()
                self._state.cookie = self._acquire()
                self._state.obtained_at = time.monotonic()
            return self._state.cookie

    def invalidate(self):
        with self._lock:
            self._state = _TokenState()

    def shutdown(self):
        # Each browser is closed in the same thread that created it.
        self.invalidate()

    def _acquire(self):
        # Flask requests run on different threads. Never share live sync
        # Playwright objects across them; share only the cached cookie string.
        browser = None
        try:
            with sync_playwright() as playwright:
                options = {"headless": self._headless, "args": ["--no-sandbox"]}
                executable = os.environ.get("FF_CHROMIUM_EXECUTABLE")
                if executable:
                    options["executable_path"] = executable
                proxy_url = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
                if proxy_url:
                    proxy = urlsplit(proxy_url)
                    options["proxy"] = {"server": f"{proxy.scheme}://{proxy.hostname}:{proxy.port or 80}"}
                    if proxy.username:
                        options["proxy"]["username"] = unquote(proxy.username)
                    if proxy.password:
                        options["proxy"]["password"] = unquote(proxy.password)
                browser = playwright.chromium.launch(**options)
                try:
                    context_options = {"viewport": {"width": 1920, "height": 1080}, "locale": "en-SG"}
                    if self._user_agent:
                        context_options["user_agent"] = self._user_agent
                    context = browser.new_context(**context_options)
                    page = context.new_page()
                    response = page.goto(CHALLENGE_URL, wait_until="domcontentloaded", timeout=30000)
                    if response and response.status >= 400:
                        raise BrowserTokenError("BROWSER_PAGE_RESTRICTED")
                    deadline = time.monotonic() + 15
                    while time.monotonic() < deadline:
                        cookie = next((item for item in context.cookies() if item["name"] == "datadome"), None)
                        if cookie:
                            logger.info("Candidate DataDome cookie acquired; lookup acceptance remains unverified")
                            return cookie["value"]
                        page.wait_for_timeout(500)
                    raise BrowserTokenError("BROWSER_TOKEN_UNAVAILABLE")
                finally:
                    browser.close()
        except BrowserTokenError:
            raise
        except Exception as error:
            # Full browser errors can contain proxy URLs or session details.
            logger.warning("Browser token acquisition failed (%s)", type(error).__name__)
            raise BrowserTokenError("BROWSER_UNAVAILABLE") from None
