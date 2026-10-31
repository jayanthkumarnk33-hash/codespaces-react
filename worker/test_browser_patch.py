import ast
from concurrent.futures import ThreadPoolExecutor
import logging
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from data_dome import BrowserTokenError, DataDomeTokenProvider


def load_lookup():
    # Read only this function: importing ff_api starts network/background work.
    module = ast.parse(Path(__file__).with_name("ff_api.py").read_text())
    node = next(item for item in module.body if isinstance(item, ast.FunctionDef) and item.name == "lookup_uid")
    namespace = {"RETRY_LIMIT": 2, "BrowserTokenError": BrowserTokenError, "SessionPool": object,
                 "log": logging.getLogger("test"), "time": SimpleNamespace(sleep=lambda _: None)}
    exec(compile(ast.Module(body=[node], type_ignores=[]), "<lookup>", "exec"), namespace)
    return namespace["lookup_uid"]


class IntegrationTests(unittest.TestCase):
    def test_concurrent_requests_share_only_one_acquisition(self):
        provider = DataDomeTokenProvider()
        provider._acquire = Mock(return_value="candidate-cookie")
        with ThreadPoolExecutor(max_workers=4) as executor:
            self.assertEqual(list(executor.map(lambda _: provider.get_token(), range(8))), ["candidate-cookie"] * 8)
        provider._acquire.assert_called_once()
        provider.invalidate()
        provider.get_token()
        self.assertEqual(provider._acquire.call_count, 2)

    def test_failed_acquisition_does_not_reuse_old_cookie(self):
        provider = DataDomeTokenProvider()
        provider._acquire = Mock(side_effect=["old", BrowserTokenError("BROWSER_UNAVAILABLE")])
        provider.get_token()
        provider.invalidate()
        with self.assertRaises(BrowserTokenError):
            provider.get_token()
        self.assertEqual(provider._state.cookie, "")

    def test_browser_exception_is_a_structured_failure(self):
        session = Mock()
        session.lookup.side_effect = BrowserTokenError("BROWSER_UNAVAILABLE")
        pool = SimpleNamespace(get=lambda: session)
        result = load_lookup()(pool, "11111119")
        self.assertFalse(result["success"])
        self.assertEqual(result["code"], "BROWSER_UNAVAILABLE")

    def test_challenge_is_retried_once_and_never_reported_as_success(self):
        session = Mock()
        session.lookup.return_value = {"status": 403, "json": {"url": "https://geo.captcha-delivery.com/captcha/?secret=x"}}
        pool = SimpleNamespace(get=lambda: session, dd_provider=Mock())
        result = load_lookup()(pool, "11111119")
        self.assertEqual(result["code"], "LOOKUP_CHALLENGE")
        self.assertEqual(session.lookup.call_count, 2)
        self.assertNotIn("secret", str(result))

    def test_open_id_alone_is_not_confirmed_player_info(self):
        session = Mock()
        session.lookup.return_value = {"status": 200, "json": {"open_id": "example"}}
        result = load_lookup()(SimpleNamespace(get=lambda: session), "11111119")
        self.assertFalse(result["success"])

    def test_player_response_is_accepted(self):
        session = Mock()
        session.lookup.return_value = {"status": 200, "json": {"open_id": "example", "nickname": "Test"}}
        result = load_lookup()(SimpleNamespace(get=lambda: session), "11111119")
        self.assertTrue(result["success"])


if __name__ == "__main__":
    unittest.main()
