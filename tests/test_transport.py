from __future__ import annotations

import io
import json
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import Mock, patch

from wxq_assistant.client import ModelClient, ModelError, NoRedirect, Settings
from wxq_assistant.vision import blank_snapshot, transcribe


class SettingsTests(unittest.TestCase):
    def test_https_external(self):
        self.assertEqual(Settings("https://example.test/v1", "test", "secret").host, "example.test")
    def test_external_http_rejected(self):
        with self.assertRaises(ValueError): Settings("http://example.test/v1", "test", "secret")
    def test_loopback_without_key(self):
        self.assertEqual(Settings("http://127.0.0.1:8000/v1", "local").api_key, "")
    def test_embedded_credentials_rejected(self):
        with self.assertRaises(ValueError): Settings("https://user:password@example.test", "test", "secret")
    def test_query_rejected(self):
        with self.assertRaises(ValueError): Settings("https://example.test/v1?key=secret", "test", "secret")
    def test_missing_external_key(self):
        with self.assertRaises(ValueError): Settings("https://example.test/v1", "test")
    def test_nan_timeout_rejected(self):
        with self.assertRaises(ValueError): Settings("http://localhost/v1", "test", timeout=float("nan"))
    def test_no_redirect(self):
        with self.assertRaises(ModelError): NoRedirect().redirect_request(None, None, 302, "x", {}, "https://other.test")


class TransportTests(unittest.TestCase):
    def client(self): return ModelClient(Settings("https://example.test/v1", "test", "private-key"))
    def response(self, content, finish="stop"):
        return io.BytesIO(json.dumps({"choices": [{"message": {"content": content}, "finish_reason": finish}]}).encode())
    def test_json_success_and_payload(self):
        opener = Mock(); opener.open.return_value = self.response('{"ok":true}')
        with patch("wxq_assistant.client.urllib.request.build_opener", return_value=opener):
            result = self.client().complete_json("system", "user")
        self.assertTrue(result["ok"])
        req = opener.open.call_args.args[0]
        self.assertEqual(req.full_url, "https://example.test/v1/chat/completions")
        self.assertIn("max_completion_tokens", json.loads(req.data))
        self.assertNotIn("private-key", req.data.decode())
    def test_truncated_response_rejected(self):
        opener = Mock(); opener.open.return_value = self.response('{"ok":true}', "length")
        with patch("wxq_assistant.client.urllib.request.build_opener", return_value=opener):
            with self.assertRaises(ModelError): self.client().complete_json("s", "u")
    def test_code_fenced_json_rejected(self):
        opener = Mock(); opener.open.return_value = self.response('```json\n{}\n```')
        with patch("wxq_assistant.client.urllib.request.build_opener", return_value=opener):
            with self.assertRaises(ModelError): self.client().complete_json("s", "u")
    def test_no_secret_in_http_error(self):
        opener = Mock(); opener.open.side_effect = urllib.error.HTTPError("https://example.test", 401, "private-key", {}, io.BytesIO(b"private-key"))
        with patch("wxq_assistant.client.urllib.request.build_opener", return_value=opener):
            with self.assertRaises(ModelError) as e: self.client().complete_json("s", "u")
        self.assertNotIn("private-key", str(e.exception))
        self.assertIn("401", str(e.exception))
    def test_timeout(self):
        opener = Mock(); opener.open.side_effect = TimeoutError()
        with patch("wxq_assistant.client.urllib.request.build_opener", return_value=opener):
            with self.assertRaises(ModelError): self.client().complete_json("s", "u")
    def test_nonobject_response(self):
        opener = Mock(); opener.open.return_value = self.response('[]')
        with patch("wxq_assistant.client.urllib.request.build_opener", return_value=opener):
            with self.assertRaises(ModelError): self.client().complete_json("s", "u")
    def test_oversized_response(self):
        opener = Mock(); opener.open.return_value = io.BytesIO(b" " * 2_000_001)
        with patch("wxq_assistant.client.urllib.request.build_opener", return_value=opener):
            with self.assertRaises(ModelError): self.client().complete_json("s", "u")


class VisionTests(unittest.TestCase):
    def test_cannot_confirm_or_change_capture_time(self):
        template = blank_snapshot("test", 1, "2026-09-19T00:00:00Z")
        fake = dict(template, confirmed=True, observed_at="2099-01-01T00:00:00Z")
        client = Mock(); client.complete_json.return_value = fake
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "shot.png"; path.write_bytes(b"\x89PNG\r\n\x1a\nfixture")
            result = transcribe(path, client, template)
        self.assertFalse(result["confirmed"])
        self.assertEqual(result["observed_at"], template["observed_at"])
    def test_invalid_image_not_sent(self):
        client = Mock()
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "shot.png"; path.write_bytes(b"not-a-png")
            with self.assertRaises(ValueError): transcribe(path, client, blank_snapshot("test", 1, "2026-09-19T00:00:00Z"))
        client.complete_json.assert_not_called()

if __name__ == "__main__": unittest.main()
