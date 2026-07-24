from __future__ import annotations

import json

from stackchan_davie_gateway.diagnostics import DiagnosticStore


def _status(
    *,
    session_id: str,
    state: str = "ready",
    closed: bool = False,
) -> dict:
    return {
        "device_id": "stackchan-1",
        "client_id": "client-1",
        "session_id": session_id,
        "connected_at": 100.0,
        "session_state": state,
        "close_reason": "connection_closed" if closed else "",
        "handshake_complete": True,
        "identity_verified": True,
        "intended_firmware_verified": True,
        "firmware_expectation_state": "matched",
        "attestation_state": "ready",
        "device_attestation": {
            "schema_version": 1,
            "status": "ready",
            "firmware": {
                "project": "stack-chan",
                "version": "1.4.3-davie",
                "elf_sha256": "a" * 64,
            },
            "audio": {"device_aec": True},
        },
        "audio_frames_received": 10,
        "last_audio_received_at": 101.0,
        "audio_flowing": not closed,
        "audio_input_state": "closed" if closed else "flowing",
        "last_transcript": "private user speech",
        "last_response": "private assistant response",
        "diagnostic_timeline": [
            {
                "sequence": 1,
                "stage": "connected",
                "at": 100.0,
                "details": {},
            }
        ],
        "closed": closed,
    }


def test_diagnostics_survive_restart_and_count_reconnects(tmp_path) -> None:
    path = tmp_path / "diagnostics.json"
    first = DiagnosticStore(path, recent_limit=5)
    first.record("connected", _status(session_id="session-1"))
    first.record(
        "closed",
        _status(session_id="session-1", state="closed", closed=True),
    )

    restarted = DiagnosticStore(path, recent_limit=5)
    restarted.record("connected", _status(session_id="session-2"))
    snapshot = restarted.snapshot()

    device = snapshot["devices"]["stackchan-1"]
    assert device["connection_count"] == 2
    assert device["reconnect_count"] == 1
    assert device["last_session_id"] == "session-2"
    assert snapshot["recent_sessions"][0]["session_id"] == "session-1"
    assert snapshot["persistent"] is True
    assert snapshot["load_error"] == ""
    assert snapshot["write_error"] == ""


def test_diagnostics_never_persist_user_content_or_credentials(tmp_path) -> None:
    path = tmp_path / "diagnostics.json"
    store = DiagnosticStore(path)
    status = _status(session_id="session-private", state="closed", closed=True)
    status["device_attestation"]["ssid"] = "private-network"
    status["device_attestation"]["api_token"] = "private-token"
    store.record("connected", status)
    store.record("closed", status)

    serialized = path.read_text(encoding="utf-8")
    payload = json.loads(serialized)
    assert "private user speech" not in serialized
    assert "private assistant response" not in serialized
    assert "private-network" not in serialized
    assert "private-token" not in serialized
    assert payload["recent_sessions"][0]["device_id"] == "stackchan-1"


def test_corrupt_diagnostics_file_fails_open_without_losing_runtime(tmp_path) -> None:
    path = tmp_path / "diagnostics.json"
    path.write_text("{broken", encoding="utf-8")

    store = DiagnosticStore(path)
    store.record("connected", _status(session_id="session-recovered"))
    snapshot = store.snapshot()

    assert snapshot["load_error"] == "JSONDecodeError"
    assert snapshot["devices"]["stackchan-1"]["connection_count"] == 1
    assert json.loads(path.read_text(encoding="utf-8"))["schema_version"] == 1


def test_late_close_from_replaced_session_does_not_overwrite_current_device(tmp_path) -> None:
    store = DiagnosticStore(tmp_path / "diagnostics.json")
    store.record("connected", _status(session_id="session-old"))
    store.record("connected", _status(session_id="session-current"))
    store.record(
        "closed",
        _status(session_id="session-old", state="closed", closed=True),
    )

    device = store.snapshot()["devices"]["stackchan-1"]
    assert device["last_session_id"] == "session-current"
    assert device["last_state"] == "ready"
    assert device["audio_flowing"] is True
