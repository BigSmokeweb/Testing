"""
Test F10 / F11: SSRF via HTTP 302 redirect to loopback.
"""
import http.server
import threading
import unittest
from urllib.parse import urlparse
from app.public_checks import run_public_checks
from app.safety import validate_url

class RedirectHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        # Redirect to local loopback
        self.send_response(302)
        self.send_header("Location", "http://127.0.0.1:5432/evil")
        self.end_headers()

    def log_message(self, format, *args):
        pass

class TestRedirectSSRF(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = http.server.HTTPServer(("127.0.0.1", 0), RedirectHandler)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def test_redirect_to_loopback_detected(self):
        from app.safety import safe_http_fetch
        target_url = f"http://localhost:{self.port}/test"
        with self.assertRaises(ValueError) as ctx:
            safe_http_fetch(target_url, timeout=2)
        self.assertIn("Blocked URL at hop", str(ctx.exception), "safe_http_fetch blocked redirect to loopback")
