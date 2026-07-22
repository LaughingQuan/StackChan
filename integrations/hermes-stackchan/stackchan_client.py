"""Small authenticated client for the local StackChan Davie gateway.

The client deliberately depends only on Python's standard library so the
Hermes plugin does not add another runtime environment or dependency solver.
Credentials are read from a local file and are never included in results or
exceptions.
"""

from __future__ import annotations

import json
import os
import re
import socket
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_CONFIG_PATH = Path.home() / ".hermes" / "stackchan.json"
DEVICE_ID_PATTERN = re.compile(r"^[A-Za-z0-9:._-]{1,128}$")


@dataclass(frozen=True)
class StackChanConfig:
    enabled: bool
    base_url: str
    admin_token_file: Path
    default_device_id: str
    timeout_seconds: float

    @classmethod
    def load(cls, path: Path | None = None) -> "StackChanConfig":
        config_path = path or Path(
            os.environ.get("STACKCHAN_PLUGIN_CONFIG", str(DEFAULT_CONFIG_PATH))
        ).expanduser()
        try:
            raw = json.loads(config_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            raw = {}
        except (OSError, json.JSONDecodeError) as exc:
            raise StackChanError(
                "configuration_invalid",
                f"StackChan plugin configuration could not be read: {type(exc).__name__}",
            ) from exc
        if not isinstance(raw, dict):
            raise StackChanError(
                "configuration_invalid", "StackChan plugin configuration must be an object"
            )

        base_url = str(raw.get("base_url") or "http://127.0.0.1:8793").rstrip("/")
        parsed = urllib.parse.urlparse(base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise StackChanError(
                "configuration_invalid", "StackChan gateway base_url must be HTTP(S)"
            )

        device_id = str(raw.get("default_device_id") or "").strip()
        if device_id and not DEVICE_ID_PATTERN.fullmatch(device_id):
            raise StackChanError(
                "configuration_invalid", "Configured StackChan device identity is invalid"
            )

        token_file = Path(
            str(
                raw.get("admin_token_file")
                or (Path.home() / ".hermes" / "secrets" / "stackchan-admin-token")
            )
        ).expanduser()
        try:
            timeout = min(15.0, max(0.5, float(raw.get("timeout_seconds", 4.0))))
        except (TypeError, ValueError) as exc:
            raise StackChanError(
                "configuration_invalid", "StackChan timeout_seconds must be numeric"
            ) from exc
        return cls(
            enabled=bool(raw.get("enabled", True)),
            base_url=base_url,
            admin_token_file=token_file,
            default_device_id=device_id,
            timeout_seconds=timeout,
        )

    def read_admin_token(self) -> str:
        try:
            return self.admin_token_file.read_text(encoding="utf-8").strip()
        except OSError:
            return ""


class StackChanError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        http_status: int | None = None,
        retryable: bool = False,
        next_step: str = "",
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status
        self.retryable = retryable
        self.next_step = next_step

    def as_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "ok": False,
            "error": self.code,
            "message": self.message,
            "retryable": self.retryable,
        }
        if self.http_status is not None:
            result["http_status"] = self.http_status
        if self.next_step:
            result["next_step"] = self.next_step
        return result


class StackChanClient:
    def __init__(self, config: StackChanConfig) -> None:
        self.config = config

    def _request(
        self,
        method: str,
        path: str,
        *,
        body: dict[str, Any] | None = None,
        authenticated: bool = False,
    ) -> dict[str, Any]:
        headers = {"Accept": "application/json"}
        data = None
        if body is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        if authenticated:
            token = self.config.read_admin_token()
            if not token:
                raise StackChanError(
                    "admin_credentials_missing",
                    "StackChan admin credentials are not configured for Davie",
                    next_step="Configure the local StackChan admin token file, then retry.",
                )
            headers["Authorization"] = f"Bearer {token}"

        request = urllib.request.Request(
            f"{self.config.base_url}{path}", data=data, headers=headers, method=method
        )
        try:
            with urllib.request.urlopen(request, timeout=self.config.timeout_seconds) as response:
                raw = response.read()
        except urllib.error.HTTPError as exc:
            detail = ""
            try:
                payload = json.loads(exc.read().decode("utf-8", errors="replace"))
                detail = str(payload.get("detail") or "") if isinstance(payload, dict) else ""
            except (json.JSONDecodeError, OSError, UnicodeError):
                detail = ""
            if exc.code == 401:
                raise StackChanError(
                    "admin_credentials_rejected",
                    "StackChan gateway rejected Davie's local credentials",
                    http_status=401,
                    next_step="Refresh the local StackChan admin token, then retry.",
                ) from exc
            if exc.code == 404 and detail == "device is not connected":
                raise StackChanError(
                    "device_not_connected",
                    "StackChan is online but not in an active Davie voice session",
                    http_status=404,
                    retryable=True,
                    next_step="Say 'Davie' near StackChan to wake it, then retry the action.",
                ) from exc
            raise StackChanError(
                "gateway_request_failed",
                detail or f"StackChan gateway returned HTTP {exc.code}",
                http_status=exc.code,
                retryable=exc.code >= 500,
            ) from exc
        except (urllib.error.URLError, TimeoutError, socket.timeout) as exc:
            raise StackChanError(
                "gateway_unreachable",
                "The local StackChan gateway did not respond in time",
                retryable=True,
                next_step="Check the Rock5B StackChan gateway and local network, then retry.",
            ) from exc

        try:
            payload = json.loads(raw.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeError) as exc:
            raise StackChanError(
                "gateway_response_invalid", "StackChan gateway returned invalid JSON"
            ) from exc
        if not isinstance(payload, dict):
            raise StackChanError(
                "gateway_response_invalid", "StackChan gateway returned a non-object response"
            )
        return payload

    def health(self) -> dict[str, Any]:
        return self._request("GET", "/health")

    def capabilities(self) -> dict[str, Any]:
        return self._request("GET", "/v1/capabilities")

    def devices(self) -> list[dict[str, Any]]:
        payload = self._request("GET", "/v1/devices", authenticated=True)
        devices = payload.get("devices")
        return [item for item in devices if isinstance(item, dict)] if isinstance(devices, list) else []

    def resolve_device_id(self, explicit_device_id: str = "") -> str:
        requested = explicit_device_id.strip()
        if requested and not DEVICE_ID_PATTERN.fullmatch(requested):
            raise StackChanError("invalid_device_id", "StackChan device identity is invalid")
        connected_ids = [
            str(item.get("device_id") or "").strip()
            for item in self.devices()
            if DEVICE_ID_PATTERN.fullmatch(str(item.get("device_id") or "").strip())
        ]
        preferred = requested or self.config.default_device_id
        if preferred:
            if preferred in connected_ids:
                return preferred
            raise StackChanError(
                "device_not_connected",
                "StackChan is online but not in an active Davie voice session",
                retryable=True,
                next_step="Say 'Davie' near StackChan to wake it, then retry the action.",
            )
        if len(connected_ids) == 1:
            return connected_ids[0]
        if len(connected_ids) > 1:
            raise StackChanError(
                "device_selection_required",
                "More than one StackChan is connected and no default device is configured",
                next_step="Configure a default StackChan device before retrying.",
            )
        raise StackChanError(
            "device_not_connected",
            "No StackChan is currently in an active Davie voice session",
            retryable=True,
            next_step="Say 'Davie' near StackChan to wake it, then retry the action.",
        )

    def _device_path(self, device_id: str, suffix: str) -> str:
        return f"/v1/devices/{urllib.parse.quote(device_id, safe='')}/{suffix.lstrip('/')}"

    def say(self, text: str) -> dict[str, Any]:
        spoken_text = text.strip()
        if not spoken_text:
            raise StackChanError("text_required", "StackChan speech text is required")
        if len(spoken_text) > 1000:
            raise StackChanError(
                "text_too_long", "StackChan immediate speech is limited to 1000 characters"
            )
        device_id = self.resolve_device_id()
        payload = self._request(
            "POST",
            self._device_path(device_id, "say"),
            body={"text": spoken_text},
            authenticated=True,
        )
        return {
            "ok": payload.get("status") == "accepted",
            "status": payload.get("status"),
            "device": "configured_or_only_connected",
            "characters": len(spoken_text),
        }

    def vision(self, question: str, *, speak: bool = True) -> dict[str, Any]:
        prompt = question.strip()
        if not prompt:
            raise StackChanError("question_required", "A camera question is required")
        if len(prompt) > 500:
            raise StackChanError(
                "question_too_long", "StackChan camera questions are limited to 500 characters"
            )
        device_id = self.resolve_device_id()
        payload = self._request(
            "POST",
            self._device_path(device_id, "vision"),
            body={"question": prompt, "speak": bool(speak)},
            authenticated=True,
        )
        return {
            "ok": payload.get("status") == "ok",
            "status": payload.get("status"),
            "device": "configured_or_only_connected",
            "result": str(payload.get("result") or ""),
            "spoken": bool(payload.get("spoken")),
        }

    def status(self, *, include_capabilities: bool = True) -> dict[str, Any]:
        health = self.health()
        result: dict[str, Any] = {
            "ok": health.get("status") == "ok",
            "gateway": {
                "status": health.get("status"),
                "service": health.get("service"),
                "version": health.get("version"),
            },
            "admin_credentials_configured": bool(self.config.read_admin_token()),
        }
        try:
            devices = self.devices()
        except StackChanError as exc:
            result["device_query"] = exc.as_dict()
            devices = []
        configured_connected = bool(
            self.config.default_device_id
            and any(item.get("device_id") == self.config.default_device_id for item in devices)
        )
        result["device"] = {
            "connected_count": len(devices),
            "configured": bool(self.config.default_device_id),
            "configured_device_connected": configured_connected,
            "ready_for_immediate_output": configured_connected or (
                not self.config.default_device_id and len(devices) == 1
            ),
        }
        if include_capabilities:
            manifest = self.capabilities()
            capabilities = manifest.get("capabilities")
            result["capabilities"] = [
                {"id": item.get("id"), "label": item.get("label")}
                for item in capabilities
                if isinstance(item, dict)
            ] if isinstance(capabilities, list) else []
        return result


def json_result(callable_, *args, **kwargs) -> str:
    try:
        return json.dumps(callable_(*args, **kwargs), ensure_ascii=False)
    except StackChanError as exc:
        return json.dumps(exc.as_dict(), ensure_ascii=False)
