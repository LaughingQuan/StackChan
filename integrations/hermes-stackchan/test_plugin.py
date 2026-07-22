from __future__ import annotations

import importlib.util
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest


HERE = Path(__file__).resolve().parent


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


client_module = _load_module("stackchan_client_test", HERE / "stackchan_client.py")
plugin_module = _load_module("jm_stackchan_test", HERE / "__init__.py")


class _GatewayHandler(BaseHTTPRequestHandler):
    token = "test-admin-token"

    def log_message(self, _format, *_args):
        return

    def _json(self, payload, status=200):
        raw = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        if self.path == "/health":
            self._json({"status": "ok", "service": "stackchan-davie-gateway", "version": "0.2.0"})
            return
        if self.path == "/v1/capabilities":
            self._json({"capabilities": [{"id": "vision", "label": "Look and explain"}]})
            return
        if self.path == "/v1/devices":
            if self.headers.get("Authorization") != f"Bearer {self.token}":
                self._json({"detail": "invalid admin token"}, 401)
                return
            self._json({"devices": [{"device_id": "stackchan-main", "state": "listening"}]})
            return
        self._json({"detail": "not found"}, 404)


@pytest.fixture
def gateway(tmp_path):
    server = ThreadingHTTPServer(("127.0.0.1", 0), _GatewayHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    token_path = tmp_path / "admin-token"
    token_path.write_text(_GatewayHandler.token)
    config_path = tmp_path / "stackchan.json"
    config_path.write_text(
        json.dumps(
            {
                "base_url": f"http://127.0.0.1:{server.server_port}",
                "admin_token_file": str(token_path),
                "default_device_id": "stackchan-main",
                "timeout_seconds": 1,
            }
        )
    )
    yield config_path
    server.shutdown()
    thread.join(timeout=2)


def test_status_reports_gateway_device_and_capability_without_identity(gateway):
    config = client_module.StackChanConfig.load(gateway)
    result = client_module.StackChanClient(config).status()

    assert result["ok"] is True
    assert result["gateway"]["version"] == "0.2.0"
    assert result["device"] == {
        "connected_count": 1,
        "configured": True,
        "configured_device_connected": True,
        "ready_for_immediate_output": True,
    }
    assert result["capabilities"] == [{"id": "vision", "label": "Look and explain"}]
    assert "stackchan-main" not in json.dumps(result)
    assert _GatewayHandler.token not in json.dumps(result)


def test_status_keeps_health_when_admin_token_is_missing(gateway):
    raw = json.loads(gateway.read_text())
    raw["admin_token_file"] = str(gateway.parent / "missing")
    gateway.write_text(json.dumps(raw))
    config = client_module.StackChanConfig.load(gateway)

    result = client_module.StackChanClient(config).status(include_capabilities=False)

    assert result["ok"] is True
    assert result["admin_credentials_configured"] is False
    assert result["device_query"]["error"] == "admin_credentials_missing"
    assert "capabilities" not in result


def test_http_credential_failure_never_leaks_token(gateway):
    raw = json.loads(gateway.read_text())
    token_path = Path(raw["admin_token_file"])
    token_path.write_text("wrong-secret-value")
    config = client_module.StackChanConfig.load(gateway)

    result = json.loads(client_module.json_result(client_module.StackChanClient(config).status))

    assert result["ok"] is True
    assert result["device_query"]["error"] == "admin_credentials_rejected"
    assert "wrong-secret-value" not in json.dumps(result)


def test_plugin_registers_only_read_only_status_tool():
    calls = []

    class Context:
        def register_tool(self, **kwargs):
            calls.append(("tool", kwargs))

        def register_command(self, *args, **kwargs):
            calls.append(("command", (args, kwargs)))

    plugin_module.register(Context())

    tool = next(item[1] for item in calls if item[0] == "tool")
    assert tool["name"] == "stackchan_status"
    assert tool["toolset"] == "stackchan"
    assert tool["handler"] is plugin_module._handle_status
