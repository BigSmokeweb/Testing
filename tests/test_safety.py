import ipaddress
import unittest
from unittest.mock import patch
from app.safety import validate_url, is_ip_blocked


class TestSafetySSRF(unittest.TestCase):
    def test_localhost_and_loopback_rejected(self):
        valid, reason = validate_url("http://localhost:8000")
        self.assertFalse(valid)
        self.assertTrue("Loopback" in reason or "resolve" in reason or "127.0.0.1" in reason)

        valid, reason = validate_url("http://127.0.0.1:8000")
        self.assertFalse(valid)
        self.assertIn("Loopback", reason)

        valid, reason = validate_url("http://[::1]:8000")
        self.assertFalse(valid)
        self.assertIn("Loopback", reason)

    def test_private_ips_rejected(self):
        valid, reason = validate_url("http://10.0.0.5/api")
        self.assertFalse(valid)
        self.assertIn("Private network", reason)

        valid, reason = validate_url("https://192.168.1.1/")
        self.assertFalse(valid)
        self.assertIn("Private network", reason)

        valid, reason = validate_url("http://172.16.0.10:3000")
        self.assertFalse(valid)
        self.assertIn("Private network", reason)

    def test_cloud_metadata_rejected(self):
        valid, reason = validate_url("http://169.254.169.254/latest/meta-data")
        self.assertFalse(valid)
        self.assertTrue("metadata" in reason.lower() or "link-local" in reason.lower())

    def test_hostname_resolving_to_private_ip_mocked(self):
        with patch("app.safety.resolve_hostname_ips", return_value=[ipaddress.ip_address("10.10.10.10")]):
            valid, reason = validate_url("http://internal-corp-service.com")
            self.assertFalse(valid)
            self.assertIn("resolves to forbidden IP", reason)

    def test_embedded_credentials_rejected(self):
        valid, reason = validate_url("https://admin:secret123@example.com")
        self.assertFalse(valid)
        self.assertIn("embedded credentials", reason)

    def test_non_http_schemes_rejected(self):
        valid, reason = validate_url("ftp://example.com/file")
        self.assertFalse(valid)
        self.assertIn("Scheme", reason)

        valid, reason = validate_url("file:///etc/passwd")
        self.assertFalse(valid)
        self.assertIn("Scheme", reason)

    def test_public_url_allowed(self):
        with patch("app.safety.resolve_hostname_ips", return_value=[ipaddress.ip_address("93.184.216.34")]):
            valid, reason = validate_url("https://example.com")
            self.assertTrue(valid)
            self.assertEqual(reason, "")


if __name__ == "__main__":
    unittest.main()
