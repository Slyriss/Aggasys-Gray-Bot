import os
import sys
import unittest
from unittest.mock import patch


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
BOT_DIR = os.path.join(ROOT, "bot")
if BOT_DIR not in sys.path:
    sys.path.insert(0, BOT_DIR)

import url_ingester


class FakeResponse:
    def __init__(self, url, *, status_code=200, headers=None, text="", redirect=False):
        self.url = url
        self.status_code = status_code
        self.headers = headers or {}
        self.text = text
        self.content = text.encode("utf-8")
        self.is_redirect = redirect

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeAsyncClient:
    responses = []
    requested = []

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def get(self, url):
        self.requested.append(url)
        return self.responses.pop(0)


class UrlSafetyTests(unittest.IsolatedAsyncioTestCase):
    def test_blocks_localhost_and_private_ip_literals(self):
        self.assertFalse(url_ingester.is_safe_fetch_url("http://localhost:8080/secret"))
        self.assertFalse(url_ingester.is_safe_fetch_url("http://127.0.0.1/admin"))
        self.assertFalse(url_ingester.is_safe_fetch_url("http://10.0.0.5/admin"))
        self.assertFalse(url_ingester.is_safe_fetch_url("http://169.254.169.254/latest/meta-data"))
        self.assertFalse(url_ingester.is_safe_fetch_url("file:///etc/passwd"))

    def test_blocks_hostname_that_resolves_to_private_address(self):
        with patch.object(
            url_ingester.socket,
            "getaddrinfo",
            return_value=[(None, None, None, None, ("192.168.1.10", 80))],
        ):
            self.assertFalse(url_ingester.is_safe_fetch_url("https://internal.example.com/page"))

    def test_allows_hostname_that_resolves_to_public_address(self):
        with patch.object(
            url_ingester.socket,
            "getaddrinfo",
            return_value=[(None, None, None, None, ("93.184.216.34", 443))],
        ):
            self.assertTrue(url_ingester.is_safe_fetch_url("https://example.com/page"))

    async def test_fetch_url_text_blocks_private_redirect_target(self):
        FakeAsyncClient.responses = [
            FakeResponse(
                "https://example.com/start",
                status_code=302,
                headers={"location": "http://127.0.0.1/admin"},
                redirect=True,
            )
        ]
        FakeAsyncClient.requested = []

        with patch.object(url_ingester, "is_safe_fetch_url", side_effect=[True, False]), \
             patch.object(url_ingester.httpx, "AsyncClient", FakeAsyncClient):
            title, text = await url_ingester.fetch_url_text("https://example.com/start")

        self.assertIsNone(title)
        self.assertIsNone(text)
        self.assertEqual(FakeAsyncClient.requested, ["https://example.com/start"])

    async def test_fetch_url_text_reads_safe_html(self):
        html = "<html><title>Example</title><body><p>" + ("hello " * 30) + "</p></body></html>"
        FakeAsyncClient.responses = [
            FakeResponse(
                "https://example.com/page",
                headers={"content-type": "text/html"},
                text=html,
            )
        ]
        FakeAsyncClient.requested = []

        with patch.object(url_ingester, "is_safe_fetch_url", return_value=True), \
             patch.object(url_ingester.httpx, "AsyncClient", FakeAsyncClient):
            title, text = await url_ingester.fetch_url_text("https://example.com/page")

        self.assertEqual(title, "Example")
        self.assertIn("hello", text)


if __name__ == "__main__":
    unittest.main()
