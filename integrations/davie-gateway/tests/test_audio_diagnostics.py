from __future__ import annotations

import json
import time
import wave

import pytest
from fastapi.testclient import TestClient

from stackchan_davie_gateway.app import create_app
from stackchan_davie_gateway.audio_diagnostics import AudioDiagnosticStore
from stackchan_davie_gateway.config import Settings


class NullClient:
    async def close(self) -> None:
        return None


class CaptureCodec:
    def __init__(self, _input_rate: int, _output_rate: int, _frame_duration: int):
        self.closed = False

    def decode(self, _packet: bytes) -> bytes:
        return b"\x00\x00" * 960

    def close(self) -> None:
        self.closed = True


def test_audio_diagnostics_are_off_until_explicitly_armed(tmp_path) -> None:
    store = AudioDiagnosticStore(
        tmp_path / "local",
        nas_root=tmp_path / "nas",
    )
    try:
        assert store.snapshot()["default_state"] == "off"
        assert store.feed("device", "session", b"\x01\x00" * 960, 16000) is None
        assert not (tmp_path / "local").exists()
        with pytest.raises(ValueError, match="diagnostic_duration_out_of_range"):
            store.arm(
                device_id="device",
                session_id="session",
                duration_seconds=11,
            )
    finally:
        store.close()


def test_audio_diagnostic_is_bounded_persisted_and_synced(tmp_path) -> None:
    local = tmp_path / "local"
    nas = tmp_path / "nas"
    store = AudioDiagnosticStore(local, nas_root=nas)
    try:
        armed = store.arm(
            device_id="stackchan-test",
            session_id="session-1",
            duration_seconds=1,
        )
        with pytest.raises(ValueError, match="diagnostic_capture_already_active"):
            store.arm(
                device_id="stackchan-test",
                session_id="session-1",
                duration_seconds=1,
            )

        terminal = store.feed(
            "stackchan-test",
            "session-1",
            b"\x01\x00" * 16000,
            16000,
        )
        assert terminal is not None
        assert terminal["status"] == "persisting"
        assert store.wait_for_idle(timeout=5)

        recent = store.snapshot("stackchan-test")["recent"]
        assert len(recent) == 1
        receipt = recent[0]
        assert receipt["capture_id"] == armed["capture_id"]
        assert receipt["status"] == "ready"
        assert receipt["captured_ms"] == 1000
        assert receipt["nas_sync_status"] == "synced"
        assert len(receipt["sha256"]) == 64

        local_wav = local / armed["capture_id"] / "capture.wav"
        nas_wav = nas / armed["capture_id"] / "capture.wav"
        assert local_wav.read_bytes() == nas_wav.read_bytes()
        with wave.open(str(local_wav), "rb") as captured:
            assert captured.getnchannels() == 1
            assert captured.getsampwidth() == 2
            assert captured.getframerate() == 16000
            assert captured.getnframes() == 16000

        manifest = json.loads(
            (local / armed["capture_id"] / "manifest.json").read_text(
                encoding="utf-8"
            )
        )
        serialized = json.dumps(manifest)
        assert manifest["source"] == "gateway_received_afe_output"
        assert manifest["nas_sync_status"] == "synced"
        assert "transcript" not in serialized
        assert "pcm" not in serialized
    finally:
        store.close()

    reloaded = AudioDiagnosticStore(local, nas_root=nas)
    try:
        assert reloaded.snapshot("stackchan-test")["recent"][0]["status"] == "ready"
    finally:
        reloaded.close()


def test_audio_diagnostic_fails_closed_when_session_changes(tmp_path) -> None:
    store = AudioDiagnosticStore(tmp_path / "local")
    try:
        store.arm(
            device_id="stackchan-test",
            session_id="session-1",
            duration_seconds=1,
        )
        terminal = store.feed(
            "stackchan-test",
            "session-2",
            b"\x01\x00" * 960,
            16000,
        )
        assert terminal is not None
        assert terminal["status"] == "failed"
        assert terminal["error"] == "diagnostic_session_changed"
        assert store.snapshot("stackchan-test")["active"] == []
    finally:
        store.close()


def test_audio_diagnostic_local_retention_is_bounded_but_nas_archive_remains(
    tmp_path,
) -> None:
    local = tmp_path / "local"
    nas = tmp_path / "nas"
    store = AudioDiagnosticStore(local, nas_root=nas, recent_limit=1)
    capture_ids: list[str] = []
    try:
        for session_id in ("session-1", "session-2"):
            armed = store.arm(
                device_id="stackchan-test",
                session_id=session_id,
                duration_seconds=1,
            )
            capture_ids.append(armed["capture_id"])
            store.feed(
                "stackchan-test",
                session_id,
                b"\x01\x00" * 16000,
                16000,
            )
            assert store.wait_for_idle(timeout=5)

        assert not (local / capture_ids[0]).exists()
        assert (local / capture_ids[1] / "capture.wav").is_file()
        assert (nas / capture_ids[0] / "capture.wav").is_file()
        assert (nas / capture_ids[1] / "capture.wav").is_file()
        assert len(store.snapshot()["recent"]) == 1
    finally:
        store.close()
        store.close()

    with pytest.raises(ValueError, match="diagnostic_store_closed"):
        store.arm(
            device_id="stackchan-test",
            session_id="session-3",
            duration_seconds=1,
        )


def test_audio_diagnostic_admin_contract_captures_only_after_arm(tmp_path) -> None:
    store = AudioDiagnosticStore(
        tmp_path / "local",
        nas_root=tmp_path / "nas",
    )
    app = create_app(
        Settings(
            device_token="device-secret",
            davie_api_key="davie-secret",
            admin_token="admin-secret",
            diagnostic_state_path=str(tmp_path / "diagnostics.json"),
        ),
        media_client=NullClient(),
        davie_client=NullClient(),
        codec_factory=CaptureCodec,
        audio_diagnostic_store=store,
    )
    headers = {"Authorization": "Bearer admin-secret"}
    try:
        with TestClient(app) as client:
            assert (
                client.post(
                    "/v1/devices/offline/diagnostics/audio",
                    headers=headers,
                    json={"duration_seconds": 1},
                ).status_code
                == 409
            )
            assert (
                client.get(
                    "/v1/devices/stackchan-capture/diagnostics/audio"
                ).status_code
                == 401
            )

            with client.websocket_connect(
                "/xiaozhi/v1/",
                headers={
                    "Authorization": "Bearer device-secret",
                    "Device-Id": "stackchan-capture",
                    "Client-Id": "capture-client",
                },
            ) as websocket:
                websocket.send_text(
                    '{"type":"hello","version":1,"transport":"websocket",'
                    '"features":{"mcp":false},"audio_params":{"format":"opus",'
                    '"sample_rate":16000,"channels":1,"frame_duration":60}}'
                )
                assert websocket.receive_json()["type"] == "hello"
                armed = client.post(
                    "/v1/devices/stackchan-capture/diagnostics/audio",
                    headers=headers,
                    json={"duration_seconds": 1},
                )
                assert armed.status_code == 200
                assert armed.json()["tf_timeline_marker"] == "unavailable"

                for _ in range(17):
                    websocket.send_bytes(b"encoded")

                deadline = time.monotonic() + 5
                recent = []
                while time.monotonic() < deadline:
                    response = client.get(
                        "/v1/devices/stackchan-capture/diagnostics/audio",
                        headers=headers,
                    )
                    recent = response.json()["recent"]
                    if recent and recent[0]["status"] == "ready":
                        break
                    time.sleep(0.02)

                assert recent[0]["status"] == "ready"
                assert recent[0]["captured_ms"] == 1000
                assert client.get("/health").json()["audio_diagnostics"][
                    "active_count"
                ] == 0
    finally:
        store.close()
