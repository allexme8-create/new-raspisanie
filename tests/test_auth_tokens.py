from __future__ import annotations

import hashlib
import hmac
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

import app as backend  # noqa: E402


class AdminTokenTests(unittest.TestCase):
    def test_issued_token_is_valid_without_session_state(self) -> None:
        token = backend._create_token()
        self.assertNotIn(token, backend._revoked_tokens)
        self.assertTrue(backend._check_token(token))

    def test_tampered_token_is_rejected(self) -> None:
        token = backend._create_token()
        replacement = "0" if token[-1] != "0" else "1"
        self.assertFalse(backend._check_token(token[:-1] + replacement))

    def test_staff_admin_requires_valid_header_and_disables_caching(self) -> None:
        from fastapi.testclient import TestClient
        token = backend._create_token()
        with TestClient(backend.app) as client:
            client.cookies.set("schedule_admin_token", token)
            self.assertEqual(client.get("/api/admin/users").status_code, 401)
            self.assertEqual(client.get("/api/admin/users", headers={"X-Admin-Token": "invalid"}).status_code, 401)
            response = client.get("/api/admin/users", headers={"X-Admin-Token": token})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.headers["cache-control"], "no-store")

    def test_expired_signed_token_is_rejected(self) -> None:
        payload = f"{int(time.time()) - 1}.test-nonce"
        signature = hmac.new(
            backend.ADMIN_TOKEN_SECRET,
            payload.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        self.assertFalse(backend._check_token(f"{payload}.{signature}"))


if __name__ == "__main__":
    unittest.main()
