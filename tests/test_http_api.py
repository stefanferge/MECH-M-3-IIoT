import json
import os
import re
import socket
import unittest
import urllib.error
import urllib.request


BASE_URL = os.environ.get("IOT_BASE_URL", "http://192.168.137.146").rstrip("/")
TIMEOUT_SECONDS = float(os.environ.get("IOT_HTTP_TIMEOUT", "3.0"))


def _request(method, path, payload=None, timeout=TIMEOUT_SECONDS):
    url = f"{BASE_URL}{path}"
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8")
            return resp.status, body
    except (urllib.error.URLError, socket.timeout) as exc:
        raise ConnectionError(f"HTTP request failed: {exc}") from exc


def _get_json(method, path, payload=None):
    status, body = _request(method, path, payload=payload)
    try:
        data = json.loads(body) if body else {}
    except json.JSONDecodeError as exc:
        raise AssertionError(f"Invalid JSON response for {path}: {body!r}") from exc
    return status, data


class HttpApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            _get_json("GET", "/status")
        except ConnectionError as exc:
            raise unittest.SkipTest(
                f"Device not reachable at {BASE_URL}. Set IOT_BASE_URL if needed. {exc}"
            ) from exc

    def test_status_endpoint(self):
        status, data = _get_json("GET", "/status")
        self.assertEqual(status, 200)
        self.assertIn("device_id", data)
        self.assertIn("timestamp", data)
        self.assertIn("status", data)
        self.assertIn("ip", data)
        timestamp = data["timestamp"]
        self.assertIsInstance(timestamp, str)
        self.assertRegex(timestamp, r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")

    def test_config_get(self):
        status, data = _get_json("GET", "/config")
        self.assertEqual(status, 200)
        self.assertIn("interval", data)
        self.assertIsInstance(data["interval"], int)

    def test_config_post_updates_interval(self):
        _, data = _get_json("GET", "/config")
        original = int(data.get("interval", 1))
        new_interval = original + 1 if original < 60 else original - 1

        status, updated = _get_json("POST", "/config", payload={"interval": new_interval})
        self.assertEqual(status, 200)
        self.assertEqual(updated.get("interval"), new_interval)

        _, confirm = _get_json("GET", "/config")
        self.assertEqual(confirm.get("interval"), new_interval)

        _get_json("POST", "/config", payload={"interval": original})

