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
    devices = [{"device_id": "stackchan-main", "state": "listening"}]
    requests = []
    reader = {"state": "idle", "title": "", "index": 0, "total": 0}

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
            self._json({"status": "ok", "service": "stackchan-davie-gateway", "version": "0.3.0"})
            return
        if self.path == "/v1/capabilities":
            self._json(
                {
                    "wake_word": "Davie",
                    "voice_session": {
                        "wake": {
                            "method": "device_local_voice",
                            "phrase": "Davie",
                            "instruction": (
                                "Say 'Davie' near the device, then wait for the screen to show Listening."
                            ),
                        },
                        "end": {
                            "voice_phrases": ["Goodbye Davie", "Go to sleep", "休息吧"],
                            "tool": {
                                "name": "stackchan_control",
                                "arguments": {"action": "sleep"},
                            },
                        },
                        "idle_timeout_seconds": 120,
                        "remote_wake_supported": False,
                    },
                    "capabilities": [{"id": "vision", "label": "Look and explain"}],
                }
            )
            return
        if self.path == "/v1/devices":
            if self.headers.get("Authorization") != f"Bearer {self.token}":
                self._json({"detail": "invalid admin token"}, 401)
                return
            self._json({"devices": self.devices})
            return
        if self.path == "/v1/devices/stackchan-main/reader":
            if self.headers.get("Authorization") != f"Bearer {self.token}":
                self._json({"detail": "invalid admin token"}, 401)
                return
            self._json({"device_id": "stackchan-main", "connected": bool(self.devices), "reader": self.reader})
            return
        if self.path == "/v1/devices/stackchan-main/capabilities":
            if self.headers.get("Authorization") != f"Bearer {self.token}":
                self._json({"detail": "invalid admin token"}, 401)
                return
            self._json(
                {
                    "connected": bool(self.devices),
                    "mcp_tools": [
                        "self.audio_speaker.set_volume",
                        "self.robot.set_head_angles",
                        "self.robot.set_led_color",
                    ],
                }
            )
            return
        self._json({"detail": "not found"}, 404)

    def do_POST(self):
        if self.headers.get("Authorization") != f"Bearer {self.token}":
            self._json({"detail": "invalid admin token"}, 401)
            return
        length = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(length) or b"{}")
        type(self).requests.append((self.path, body))
        if self.path == "/v1/devices/stackchan-main/say":
            self._json({"status": "accepted", "device_id": "stackchan-main"})
            return
        if self.path == "/v1/devices/stackchan-main/sleep":
            self._json(
                {
                    "status": "ok",
                    "device_id": "stackchan-main",
                    "session_state": "closed",
                    "close_reason": "admin_sleep",
                }
            )
            return
        if self.path == "/v1/devices/stackchan-main/vision":
            self._json(
                {
                    "status": "ok",
                    "device_id": "stackchan-main",
                    "result": "I can see a red book.",
                    "spoken": bool(body.get("speak")),
                }
            )
            return
        if self.path == "/v1/devices/stackchan-main/reader/load":
            type(self).reader = {"state": "playing" if body.get("autoplay") else "ready", "title": body["title"], "index": 0, "total": 2}
            self._json({"status": "accepted", "device_id": "stackchan-main", "connected": bool(type(self).devices), "reader": type(self).reader})
            return
        if self.path in {
            "/v1/devices/stackchan-main/reader/play",
            "/v1/devices/stackchan-main/reader/pause",
            "/v1/devices/stackchan-main/reader/stop",
        }:
            action = self.path.rsplit("/", 1)[-1]
            type(self).reader["state"] = {"play": "playing", "pause": "paused", "stop": "stopped"}[action]
            self._json({"status": "ok", "device_id": "stackchan-main", "connected": bool(type(self).devices), "reader": type(self).reader})
            return
        if self.path.startswith("/v1/devices/stackchan-main/tools/"):
            tool = self.path.rsplit("/", 1)[-1]
            if tool == "self.robot.create_reminder":
                result = {"content": [{"type": "text", "text": "7"}]}
            elif tool == "self.robot.get_reminders":
                result = {"content": [{"type": "text", "text": '[{"id":7,"message":"Stretch"}]'}]}
            elif tool == "self.robot.stop_reminder":
                result = {"content": [{"type": "text", "text": "true"}]}
            else:
                result = True
            self._json(
                {
                    "status": "ok",
                    "device_id": "stackchan-main",
                    "tool": tool,
                    "result": result,
                }
            )
            return
        self._json({"detail": "not found"}, 404)

    def do_DELETE(self):
        if self.headers.get("Authorization") != f"Bearer {self.token}":
            self._json({"detail": "invalid admin token"}, 401)
            return
        type(self).requests.append((self.path, None))
        if self.path == "/v1/devices/stackchan-main/reader":
            type(self).reader = {"state": "idle", "title": "", "index": 0, "total": 0}
            self._json({"status": "ok", "device_id": "stackchan-main", "connected": bool(type(self).devices), "removed": True, "reader": type(self).reader})
            return
        self._json({"detail": "not found"}, 404)


@pytest.fixture
def gateway(tmp_path):
    _GatewayHandler.devices = [{"device_id": "stackchan-main", "state": "listening"}]
    _GatewayHandler.requests = []
    _GatewayHandler.reader = {"state": "idle", "title": "", "index": 0, "total": 0}
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
                "reader_allowed_roots": [str(tmp_path)],
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
    assert result["gateway_reachable"] is True
    assert result["gateway"]["version"] == "0.3.0"
    assert result["live_state"] == {
        "evidence": "authenticated_device_query",
        "physical_status": "active_session",
        "physical_device_session_active": True,
        "safe_current_status": (
            "StackChan Gateway is reachable and an active physical device session is connected."
        ),
    }
    assert "Gateway reachability" in result["claim_policy"]
    assert result["device"] == {
        "connected_count": 1,
        "configured": True,
        "configured_device_connected": True,
        "ready_for_immediate_output": True,
    }
    assert result["human_operations"]["wake"]["phrase"] == "Davie"
    assert result["human_operations"]["wake"]["method"] == "device_local_voice"
    assert result["human_operations"]["end"]["voice_phrases"] == [
        "Goodbye Davie",
        "Go to sleep",
        "休息吧",
    ]
    assert result["human_operations"]["remote_wake_supported"] is False
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
    assert result["live_state"]["physical_status"] == "unknown"
    assert result["live_state"]["physical_device_session_active"] is None
    assert result["device"]["ready_for_immediate_output"] is False
    assert "capabilities" not in result


def test_status_does_not_treat_gateway_health_as_robot_presence(gateway):
    _GatewayHandler.devices = []
    config = client_module.StackChanConfig.load(gateway)

    result = client_module.StackChanClient(config).status(include_capabilities=False)

    assert result["gateway_reachable"] is True
    assert result["live_state"]["physical_status"] == "no_active_session"
    assert result["live_state"]["physical_device_session_active"] is False
    assert result["device"]["connected_count"] == 0
    assert result["device"]["ready_for_immediate_output"] is False
    assert "Do not report the robot as ready or online" in result["live_state"]["safe_current_status"]


def test_http_credential_failure_never_leaks_token(gateway):
    raw = json.loads(gateway.read_text())
    token_path = Path(raw["admin_token_file"])
    token_path.write_text("wrong-secret-value")
    config = client_module.StackChanConfig.load(gateway)

    result = json.loads(client_module.json_result(client_module.StackChanClient(config).status))

    assert result["ok"] is True
    assert result["device_query"]["error"] == "admin_credentials_rejected"
    assert result["live_state"]["physical_status"] == "unknown"
    assert "wrong-secret-value" not in json.dumps(result)


def test_say_selects_configured_connected_device_and_posts_plain_text(gateway):
    client = client_module.StackChanClient(client_module.StackChanConfig.load(gateway))

    result = client.say("  Hello from Davie.  ")

    assert result == {
        "ok": True,
        "status": "accepted",
        "device": "configured_or_only_connected",
        "characters": 17,
    }
    assert _GatewayHandler.requests[-1] == (
        "/v1/devices/stackchan-main/say",
        {"text": "Hello from Davie."},
    )


def test_vision_returns_answer_and_respects_visual_only_mode(gateway):
    client = client_module.StackChanClient(client_module.StackChanConfig.load(gateway))

    result = client.vision("What is in front of you?", speak=False)

    assert result["ok"] is True
    assert result["result"] == "I can see a red book."
    assert result["spoken"] is False
    assert _GatewayHandler.requests[-1][1]["speak"] is False


def test_immediate_output_fails_with_actionable_wake_instruction(gateway):
    _GatewayHandler.devices = []
    client = client_module.StackChanClient(client_module.StackChanConfig.load(gateway))

    result = json.loads(client_module.json_result(client.say, "Hello"))

    assert result["error"] == "device_not_connected"
    assert result["retryable"] is True
    assert "Say 'Davie'" in result["next_step"]
    assert not _GatewayHandler.requests


def test_reader_can_be_preloaded_while_device_is_offline(gateway):
    _GatewayHandler.devices = []
    client = client_module.StackChanClient(client_module.StackChanConfig.load(gateway))

    result = client.reader("load", title="Short story", text="First sentence. Second sentence.")

    assert result["ok"] is True
    assert result["connected"] is False
    assert result["reader"]["state"] == "ready"
    assert _GatewayHandler.requests[-1] == (
        "/v1/devices/stackchan-main/reader/load",
        {"title": "Short story", "text": "First sentence. Second sentence.", "autoplay": False},
    )


def test_reader_play_pause_resume_stop_and_clear(gateway):
    client = client_module.StackChanClient(client_module.StackChanConfig.load(gateway))
    client.reader("load", title="Story", text="One. Two.")

    assert client.reader("play")["reader"]["state"] == "playing"
    assert client.reader("pause")["reader"]["state"] == "paused"
    assert client.reader("resume")["reader"]["state"] == "playing"
    assert client.reader("stop")["reader"]["state"] == "stopped"
    assert client.reader("status")["reader"]["title"] == "Story"
    cleared = client.reader("clear")
    assert cleared["removed"] is True
    assert cleared["reader"]["state"] == "idle"


def test_reader_extracts_readable_html_without_script(gateway):
    source = gateway.parent / "lesson.html"
    source.write_text("<html><style>hidden</style><h1>Hello</h1><p>Read this sentence.</p><script>bad()</script></html>")
    client = client_module.StackChanClient(client_module.StackChanConfig.load(gateway))

    client.reader("load", source_path=str(source))

    request = _GatewayHandler.requests[-1][1]
    assert request["title"] == "lesson"
    assert "Hello" in request["text"]
    assert "Read this sentence." in request["text"]
    assert "hidden" not in request["text"]
    assert "bad()" not in request["text"]


def test_reader_rejects_source_outside_configured_roots(gateway, tmp_path):
    outside = tmp_path.parent / "outside-reader.txt"
    outside.write_text("Do not load me")
    client = client_module.StackChanClient(client_module.StackChanConfig.load(gateway))

    result = json.loads(client_module.json_result(client.reader, "load", source_path=str(outside)))

    assert result["error"] == "reader_source_not_allowed"


@pytest.mark.parametrize(
    ("kwargs", "path", "arguments"),
    [
        (
            {"action": "volume", "volume": 45},
            "/v1/devices/stackchan-main/tools/self.audio_speaker.set_volume",
            {"volume": 45},
        ),
        (
            {"action": "head", "yaw": -30, "pitch": 20, "speed": 150},
            "/v1/devices/stackchan-main/tools/self.robot.set_head_angles",
            {"yaw": -30, "pitch": 20, "speed": 150},
        ),
        (
            {"action": "led", "red": 0, "green": 0, "blue": 168},
            "/v1/devices/stackchan-main/tools/self.robot.set_led_color",
            {"red": 0, "green": 0, "blue": 168},
        ),
    ],
)
def test_control_maps_only_allowlisted_actions(gateway, kwargs, path, arguments):
    client = client_module.StackChanClient(client_module.StackChanConfig.load(gateway))

    result = client.control(**kwargs)

    assert result["ok"] is True
    assert _GatewayHandler.requests[-1] == (path, {"arguments": arguments})


def test_control_sleep_uses_gateway_lifecycle_contract(gateway):
    client = client_module.StackChanClient(client_module.StackChanConfig.load(gateway))

    result = client.control("sleep")

    assert result["ok"] is True
    assert result["session_state"] == "closed"
    assert result["close_reason"] == "admin_sleep"
    assert _GatewayHandler.requests[-1] == (
        "/v1/devices/stackchan-main/sleep",
        {},
    )


@pytest.mark.parametrize(
    "kwargs",
    [
        {"action": "volume", "volume": 101},
        {"action": "head"},
        {"action": "head", "yaw": -129},
        {"action": "led", "red": 169, "green": 0, "blue": 0},
        {"action": "arbitrary_tool", "volume": 10},
    ],
)
def test_control_rejects_invalid_or_unlisted_actions_before_network(gateway, kwargs):
    client = client_module.StackChanClient(client_module.StackChanConfig.load(gateway))
    before = list(_GatewayHandler.requests)

    result = json.loads(client_module.json_result(client.control, **kwargs))

    assert result["ok"] is False
    assert result["error"].startswith("control_")
    assert _GatewayHandler.requests == before


def test_reminder_create_list_and_stop_use_device_local_contract(gateway):
    client = client_module.StackChanClient(client_module.StackChanConfig.load(gateway))

    created = client.reminder(
        "create", duration_seconds=600, message="Stretch", repeat=False
    )
    listed = client.reminder("list")
    stopped = client.reminder("stop", reminder_id=7)

    assert created["result"] == 7
    assert listed["result"] == [{"id": 7, "message": "Stretch"}]
    assert stopped["result"] is True
    assert created["lifecycle"] == "device_local_while_powered"
    assert _GatewayHandler.requests[-3:] == [
        (
            "/v1/devices/stackchan-main/tools/self.robot.create_reminder",
            {"arguments": {"duration_seconds": 600, "message": "Stretch", "repeat": False}},
        ),
        ("/v1/devices/stackchan-main/tools/self.robot.get_reminders", {"arguments": {}}),
        ("/v1/devices/stackchan-main/tools/self.robot.stop_reminder", {"arguments": {"id": 7}}),
    ]


@pytest.mark.parametrize(
    "kwargs",
    [
        {"action": "create", "duration_seconds": 0},
        {"action": "create", "duration_seconds": 60, "repeat": "yes"},
        {"action": "create", "duration_seconds": 60, "message": "x" * 301},
        {"action": "stop", "reminder_id": -1},
        {"action": "delete_all"},
    ],
)
def test_reminder_rejects_invalid_input_before_network(gateway, kwargs):
    client = client_module.StackChanClient(client_module.StackChanConfig.load(gateway))
    before = list(_GatewayHandler.requests)

    result = json.loads(client_module.json_result(client.reminder, **kwargs))

    assert result["ok"] is False
    assert "reminder" in result["error"] or result["error"].startswith("control_")
    assert _GatewayHandler.requests == before


def test_plugin_registers_status_speech_and_vision_tools():
    calls = []

    class Context:
        def register_tool(self, **kwargs):
            calls.append(("tool", kwargs))

        def register_command(self, *args, **kwargs):
            calls.append(("command", (args, kwargs)))

    plugin_module.register(Context())

    tools = {item[1]["name"]: item[1] for item in calls if item[0] == "tool"}
    assert set(tools) == {"stackchan_status", "stackchan_say", "stackchan_vision", "stackchan_reader", "stackchan_control", "stackchan_reminder"}
    assert all(tool["toolset"] == "stackchan" for tool in tools.values())
    assert tools["stackchan_status"]["handler"] is plugin_module._handle_status
    assert "MANDATORY live-state check" in tools["stackchan_status"]["description"]
    assert tools["stackchan_say"]["handler"] is plugin_module._handle_say
    assert tools["stackchan_vision"]["handler"] is plugin_module._handle_vision
    assert tools["stackchan_reader"]["handler"] is plugin_module._handle_reader
    assert tools["stackchan_control"]["handler"] is plugin_module._handle_control
    assert tools["stackchan_reminder"]["handler"] is plugin_module._handle_reminder
