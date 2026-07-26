from __future__ import annotations

import json
import os
import threading
import time
from copy import deepcopy
from pathlib import Path
from typing import Any


SCHEMA_VERSION = 1
_DENIED_KEY_PARTS = {
    "api_key",
    "authorization",
    "credential",
    "password",
    "raw_audio",
    "secret",
    "ssid",
    "token",
    "transcript",
    "user_content",
}


def _bounded_scalar(value: Any) -> str | int | float | bool | None:
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return str(value)[:240]


def _safe_value(value: Any, *, depth: int = 0) -> Any:
    if depth > 6:
        return "[depth-limited]"
    if isinstance(value, dict):
        safe: dict[str, Any] = {}
        for raw_key, item in list(value.items())[:96]:
            key = str(raw_key)[:80]
            normalized = key.lower()
            if any(part in normalized for part in _DENIED_KEY_PARTS):
                continue
            safe[key] = _safe_value(item, depth=depth + 1)
        return safe
    if isinstance(value, list):
        return [_safe_value(item, depth=depth + 1) for item in value[:128]]
    return _bounded_scalar(value)


def _safe_session_snapshot(status: dict[str, Any]) -> dict[str, Any]:
    allowed = {
        "device_id",
        "client_id",
        "session_id",
        "connected_at",
        "session_state",
        "state_changed_at",
        "state_transition_count",
        "last_activity_at",
        "last_activity_reason",
        "idle_timeout_count",
        "close_reason",
        "handshake_complete",
        "identity_verified",
        "intended_firmware_verified",
        "firmware_expectation_state",
        "attestation_state",
        "attestation_received_at",
        "attestation_error",
        "device_attestation",
        "listening",
        "speaking",
        "generation_id",
        "turn_count",
        "accepted_turn_count",
        "empty_transcript_count",
        "rejected_transcript_count",
        "dropped_turn_count",
        "interrupt_count",
        "audio_frames_received",
        "audio_frames_sent",
        "last_audio_received_at",
        "last_audio_sent_at",
        "audio_flowing",
        "audio_input_state",
        "last_error",
        "closed",
        "mcp_initialized",
        "mcp_tool_count",
        "diagnostic_timeline",
    }
    return {
        key: _safe_value(status[key])
        for key in allowed
        if key in status
    }


class DiagnosticStore:
    """Atomically persists bounded device/session evidence without user content."""

    def __init__(self, path: str | Path | None, *, recent_limit: int = 20):
        self.path = Path(path) if path else None
        self.recent_limit = max(1, int(recent_limit))
        self._lock = threading.RLock()
        self._load_error = ""
        self._write_error = ""
        self._data: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "updated_at": None,
            "devices": {},
            "recent_sessions": [],
        }
        self._load()

    @property
    def persistent(self) -> bool:
        return self.path is not None

    @property
    def load_error(self) -> str:
        return self._load_error

    @property
    def write_error(self) -> str:
        return self._write_error

    def _load(self) -> None:
        if self.path is None or not self.path.is_file():
            return
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            if (
                not isinstance(payload, dict)
                or payload.get("schema_version") != SCHEMA_VERSION
                or not isinstance(payload.get("devices"), dict)
                or not isinstance(payload.get("recent_sessions"), list)
            ):
                raise ValueError("unsupported diagnostics schema")
            self._data = {
                "schema_version": SCHEMA_VERSION,
                "updated_at": payload.get("updated_at"),
                "devices": _safe_value(payload["devices"]),
                "recent_sessions": [
                    _safe_session_snapshot(item)
                    for item in payload["recent_sessions"][: self.recent_limit]
                    if isinstance(item, dict)
                ],
            }
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            self._load_error = type(exc).__name__

    def _write_locked(self) -> None:
        if self.path is None:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_name(
                f".{self.path.name}.tmp-{os.getpid()}-{threading.get_ident()}"
            )
            temporary.write_text(
                json.dumps(
                    self._data,
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
            os.replace(temporary, self.path)
            self._write_error = ""
        except OSError as exc:
            self._write_error = type(exc).__name__

    def record(self, event: str, status: dict[str, Any]) -> None:
        safe = _safe_session_snapshot(status)
        device_id = str(safe.get("device_id") or "")
        session_id = str(safe.get("session_id") or "")
        if not device_id or not session_id:
            return

        now = time.time()
        with self._lock:
            devices = self._data["devices"]
            device = devices.get(device_id)
            if not isinstance(device, dict):
                device = {
                    "device_id": device_id,
                    "connection_count": 0,
                    "reconnect_count": 0,
                }
                devices[device_id] = device

            if event == "connected" and device.get("last_session_id") != session_id:
                connection_count = int(device.get("connection_count") or 0) + 1
                device["connection_count"] = connection_count
                device["reconnect_count"] = max(0, connection_count - 1)
                device["last_connected_at"] = safe.get("connected_at") or now

            is_latest_session = (
                event == "connected"
                or not device.get("last_session_id")
                or device.get("last_session_id") == session_id
            )
            if is_latest_session:
                device.update(
                    {
                        "last_session_id": session_id,
                        "last_client_id": safe.get("client_id"),
                        "last_event": str(event)[:80],
                        "last_event_at": now,
                        "last_state": safe.get("session_state"),
                        "handshake_complete": bool(safe.get("handshake_complete")),
                        "identity_verified": bool(safe.get("identity_verified")),
                        "intended_firmware_verified": bool(
                            safe.get("intended_firmware_verified")
                        ),
                        "firmware_expectation_state": safe.get(
                            "firmware_expectation_state"
                        ),
                        "attestation_state": safe.get("attestation_state"),
                        "audio_input_state": safe.get("audio_input_state"),
                        "audio_flowing": bool(safe.get("audio_flowing")),
                        "last_audio_received_at": safe.get("last_audio_received_at"),
                    }
                )
                attestation = safe.get("device_attestation")
                if isinstance(attestation, dict) and attestation:
                    device["last_attestation"] = attestation
            if event == "closed":
                if is_latest_session:
                    device["last_disconnected_at"] = now
                    device["last_close_reason"] = safe.get("close_reason")
                recent = self._data["recent_sessions"]
                recent[:] = [
                    item
                    for item in recent
                    if item.get("session_id") != session_id
                ]
                recent.insert(0, safe)
                del recent[self.recent_limit :]

            self._data["updated_at"] = now
            self._write_locked()

    def snapshot(self, *, active_sessions: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        with self._lock:
            payload = deepcopy(self._data)
        active = [
            _safe_session_snapshot(item)
            for item in (active_sessions or [])
        ]
        payload.update(
            {
                "persistent": self.persistent,
                "load_error": self.load_error,
                "write_error": self.write_error,
                "known_device_count": len(payload["devices"]),
                "active_sessions": active,
            }
        )
        return payload

    def device_snapshot(
        self,
        device_id: str,
        *,
        active_status: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        # 设备标识大小写不敏感：会话按小写建键，但管理端点的路径参数可能是任意大小写。
        device_id = device_id.lower()
        with self._lock:
            known = deepcopy(self._data["devices"].get(device_id))
            recent = [
                deepcopy(item)
                for item in self._data["recent_sessions"]
                if str(item.get("device_id") or "").lower() == device_id
            ]
        return {
            "device_id": device_id,
            "known": known is not None,
            "history": known,
            "active_session": (
                _safe_session_snapshot(active_status)
                if active_status is not None
                else None
            ),
            "recent_sessions": recent,
            "persistent": self.persistent,
            "load_error": self.load_error,
            "write_error": self.write_error,
        }
