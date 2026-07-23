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
from html.parser import HTMLParser
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
    reader_allowed_roots: tuple[Path, ...]

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
        roots = raw.get("reader_allowed_roots")
        if roots is None:
            roots = [Path.home() / "Documents", Path.home() / "Downloads", Path.home() / "NAS"]
        if not isinstance(roots, list) or not all(isinstance(item, str | Path) for item in roots):
            raise StackChanError(
                "configuration_invalid", "reader_allowed_roots must be a list of paths"
            )
        return cls(
            enabled=bool(raw.get("enabled", True)),
            base_url=base_url,
            admin_token_file=token_file,
            default_device_id=device_id,
            timeout_seconds=timeout,
            reader_allowed_roots=tuple(Path(item).expanduser().resolve() for item in roots),
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

    def target_device_id(self, *, require_connected: bool) -> str:
        if require_connected:
            return self.resolve_device_id()
        if self.config.default_device_id:
            return self.config.default_device_id
        connected_ids = [
            str(item.get("device_id") or "").strip()
            for item in self.devices()
            if DEVICE_ID_PATTERN.fullmatch(str(item.get("device_id") or "").strip())
        ]
        if len(connected_ids) == 1:
            return connected_ids[0]
        raise StackChanError(
            "default_device_required",
            "A default StackChan must be configured before content can be prepared while offline",
            next_step="Configure the primary StackChan device identity, then retry.",
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

    def _reader_source_text(self, source_path: str) -> str:
        candidate = Path(source_path).expanduser().resolve()
        if not candidate.is_file():
            raise StackChanError("reader_source_missing", "Reader source file does not exist")
        if not any(candidate.is_relative_to(root) for root in self.config.reader_allowed_roots):
            raise StackChanError(
                "reader_source_not_allowed",
                "Reader source is outside the configured document roots",
            )
        if candidate.stat().st_size > 2_000_000:
            raise StackChanError(
                "reader_source_too_large",
                "Reader source is over 2 MB; use Davie Document Intake to extract a smaller section",
            )
        if candidate.suffix.lower() not in {".txt", ".md", ".html", ".htm"}:
            raise StackChanError(
                "reader_source_format_unsupported",
                "Direct reader sources must be TXT, Markdown, or HTML; extract other files with Document Intake first",
            )
        try:
            raw = candidate.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise StackChanError(
                "reader_source_unreadable", "Reader source could not be decoded as UTF-8"
            ) from exc
        if candidate.suffix.lower() in {".html", ".htm"}:
            parser = _ReadableHTMLText()
            parser.feed(raw)
            raw = parser.text()
        return raw

    def reader(
        self,
        action: str,
        *,
        title: str = "",
        text: str = "",
        source_path: str = "",
        autoplay: bool = False,
    ) -> dict[str, Any]:
        normalized = action.strip().lower()
        if normalized == "resume":
            normalized = "play"
        if normalized not in {"load", "status", "play", "pause", "stop", "clear"}:
            raise StackChanError("reader_action_invalid", "Unsupported StackChan reader action")

        require_connected = normalized in {"play", "pause"} or (
            normalized == "load" and bool(autoplay)
        )
        device_id = self.target_device_id(require_connected=require_connected)
        if normalized == "load":
            content = text.strip()
            if source_path.strip():
                if content:
                    raise StackChanError(
                        "reader_source_ambiguous", "Provide either text or source_path, not both"
                    )
                content = self._reader_source_text(source_path.strip()).strip()
            if not content:
                raise StackChanError("reader_text_required", "Reader content is required")
            if len(content) > 500_000:
                raise StackChanError(
                    "reader_text_too_large", "Reader content is limited to 500,000 characters"
                )
            reader_title = title.strip() or (
                Path(source_path).stem if source_path.strip() else "Davie reading"
            )
            if len(reader_title) > 300:
                raise StackChanError(
                    "reader_title_too_long", "Reader title is limited to 300 characters"
                )
            payload = self._request(
                "POST",
                self._device_path(device_id, "reader/load"),
                body={"title": reader_title, "text": content, "autoplay": bool(autoplay)},
                authenticated=True,
            )
        elif normalized == "status":
            payload = self._request(
                "GET", self._device_path(device_id, "reader"), authenticated=True
            )
        elif normalized == "clear":
            payload = self._request(
                "DELETE", self._device_path(device_id, "reader"), authenticated=True
            )
        else:
            payload = self._request(
                "POST",
                self._device_path(device_id, f"reader/{normalized}"),
                authenticated=True,
            )
        return {
            "ok": payload.get("status") in {None, "ok", "accepted"},
            "status": payload.get("status") or "ok",
            "device": "configured_or_only_connected",
            "connected": bool(payload.get("connected")),
            "reader": payload.get("reader") if isinstance(payload.get("reader"), dict) else {},
            **({"removed": bool(payload.get("removed"))} if normalized == "clear" else {}),
        }

    @staticmethod
    def _integer(value: Any, *, name: str, minimum: int, maximum: int) -> int:
        if isinstance(value, bool) or not isinstance(value, int):
            raise StackChanError("control_argument_invalid", f"{name} must be an integer")
        if value < minimum or value > maximum:
            raise StackChanError(
                "control_argument_out_of_range",
                f"{name} must be between {minimum} and {maximum}",
            )
        return value

    @staticmethod
    def _mcp_value(result: Any) -> Any:
        if not isinstance(result, dict):
            return result
        content = result.get("content")
        if not isinstance(content, list):
            return result
        texts = [
            str(item.get("text"))
            for item in content
            if isinstance(item, dict) and item.get("type") == "text" and item.get("text") is not None
        ]
        if not texts:
            return result
        joined = "\n".join(texts)
        try:
            return json.loads(joined)
        except json.JSONDecodeError:
            return joined

    def _call_tool(self, device_id: str, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        return self._request(
            "POST",
            self._device_path(
                device_id, f"tools/{urllib.parse.quote(tool_name, safe='')}"
            ),
            body={"arguments": arguments},
            authenticated=True,
        )

    def control(
        self,
        action: str,
        *,
        volume: Any = None,
        yaw: Any = None,
        pitch: Any = None,
        speed: Any = 150,
        red: Any = None,
        green: Any = None,
        blue: Any = None,
    ) -> dict[str, Any]:
        normalized = action.strip().lower()
        if normalized == "sleep":
            device_id = self.resolve_device_id()
            payload = self._request(
                "POST",
                self._device_path(device_id, "sleep"),
                authenticated=True,
            )
            return {
                "ok": payload.get("status") == "ok",
                "status": payload.get("status"),
                "device": "configured_or_only_connected",
                "action": normalized,
                "session_state": payload.get("session_state"),
                "close_reason": payload.get("close_reason"),
            }
        if normalized == "volume":
            tool_name = "self.audio_speaker.set_volume"
            arguments = {
                "volume": self._integer(volume, name="volume", minimum=0, maximum=100)
            }
        elif normalized == "head":
            if yaw is None and pitch is None:
                raise StackChanError(
                    "control_argument_missing", "head control needs yaw, pitch, or both"
                )
            arguments = {"speed": self._integer(speed, name="speed", minimum=100, maximum=1000)}
            if yaw is not None:
                arguments["yaw"] = self._integer(yaw, name="yaw", minimum=-128, maximum=128)
            if pitch is not None:
                arguments["pitch"] = self._integer(
                    pitch, name="pitch", minimum=0, maximum=90
                )
            tool_name = "self.robot.set_head_angles"
        elif normalized == "led":
            tool_name = "self.robot.set_led_color"
            arguments = {
                "red": self._integer(red, name="red", minimum=0, maximum=168),
                "green": self._integer(green, name="green", minimum=0, maximum=168),
                "blue": self._integer(blue, name="blue", minimum=0, maximum=168),
            }
        else:
            raise StackChanError(
                "control_action_invalid",
                "StackChan control supports volume, head, led, or sleep",
            )
        device_id = self.resolve_device_id()
        payload = self._call_tool(device_id, tool_name, arguments)
        return {
            "ok": payload.get("status") == "ok",
            "status": payload.get("status"),
            "device": "configured_or_only_connected",
            "action": normalized,
            "result": self._mcp_value(payload.get("result")),
        }

    def reminder(
        self,
        action: str,
        *,
        duration_seconds: Any = None,
        message: str = "",
        repeat: Any = False,
        reminder_id: Any = None,
    ) -> dict[str, Any]:
        normalized = action.strip().lower()
        if normalized == "create":
            duration = self._integer(
                duration_seconds,
                name="duration_seconds",
                minimum=1,
                maximum=86_400,
            )
            reminder_message = message.strip() or "Time's up!"
            if len(reminder_message) > 300:
                raise StackChanError(
                    "reminder_message_too_long", "Reminder message is limited to 300 characters"
                )
            if not isinstance(repeat, bool):
                raise StackChanError("reminder_argument_invalid", "repeat must be a boolean")
            tool_name = "self.robot.create_reminder"
            arguments = {
                "duration_seconds": duration,
                "message": reminder_message,
                "repeat": repeat,
            }
        elif normalized == "list":
            tool_name = "self.robot.get_reminders"
            arguments = {}
        elif normalized == "stop":
            tool_name = "self.robot.stop_reminder"
            arguments = {
                "id": self._integer(reminder_id, name="reminder_id", minimum=0, maximum=2_147_483_647)
            }
        else:
            raise StackChanError(
                "reminder_action_invalid", "StackChan reminder supports create, list, or stop"
            )
        device_id = self.resolve_device_id()
        payload = self._call_tool(device_id, tool_name, arguments)
        return {
            "ok": payload.get("status") == "ok",
            "status": payload.get("status"),
            "device": "configured_or_only_connected",
            "action": normalized,
            "result": self._mcp_value(payload.get("result")),
            "lifecycle": "device_local_while_powered",
        }

    def storage(
        self,
        action: str,
        *,
        text: str = "",
        limit: Any = 3,
    ) -> dict[str, Any]:
        normalized = action.strip().lower()
        if normalized == "status":
            tool_name = "self.storage.get_status"
            arguments: dict[str, Any] = {}
        elif normalized == "self_test":
            tool_name = "self.storage.self_test"
            arguments = {}
        elif normalized == "save_note":
            note = text.strip()
            if not note:
                raise StackChanError("storage_note_required", "A short note is required")
            if len(note.encode("utf-8")) > 480:
                raise StackChanError(
                    "storage_note_too_long",
                    "TF edge notes are limited to 480 UTF-8 bytes",
                )
            tool_name = "self.storage.notes.save"
            arguments = {"text": note}
        elif normalized == "recent_notes":
            tool_name = "self.storage.notes.recent"
            arguments = {
                "limit": self._integer(limit, name="limit", minimum=1, maximum=10)
            }
        elif normalized == "reader_checkpoint":
            tool_name = "self.storage.reader.get_checkpoint"
            arguments = {}
        elif normalized == "diagnostics":
            tool_name = "self.storage.diagnostics.recent"
            arguments = {
                "limit": self._integer(limit, name="limit", minimum=1, maximum=10)
            }
        else:
            raise StackChanError(
                "storage_action_invalid",
                "StackChan storage supports status, self_test, save_note, recent_notes, "
                "reader_checkpoint, or diagnostics",
            )

        device_id = self.resolve_device_id()
        payload = self._call_tool(device_id, tool_name, arguments)
        result = self._mcp_value(payload.get("result"))
        return {
            "ok": payload.get("status") == "ok"
            and (not isinstance(result, dict) or result.get("ok") is not False),
            "status": payload.get("status"),
            "device": "configured_or_only_connected",
            "action": normalized,
            "result": result,
        }

    def status(self, *, include_capabilities: bool = True) -> dict[str, Any]:
        health = self.health()
        gateway_reachable = health.get("status") == "ok"
        result: dict[str, Any] = {
            "ok": gateway_reachable,
            "gateway_reachable": gateway_reachable,
            "gateway": {
                "status": health.get("status"),
                "service": health.get("service"),
                "version": health.get("version"),
            },
            "admin_credentials_configured": bool(self.config.read_admin_token()),
        }
        device_query_succeeded = True
        try:
            devices = self.devices()
        except StackChanError as exc:
            result["device_query"] = exc.as_dict()
            devices = []
            device_query_succeeded = False
        configured_connected = bool(
            self.config.default_device_id
            and any(item.get("device_id") == self.config.default_device_id for item in devices)
        )
        physical_device_session_active = configured_connected or (
            not self.config.default_device_id and len(devices) == 1
        )
        if not device_query_succeeded:
            physical_status = "unknown"
            safe_current_status = (
                "StackChan Gateway is reachable, but the physical device-session state is unknown "
                "because the authenticated device query failed."
            )
        elif physical_device_session_active:
            physical_status = "active_session"
            safe_current_status = (
                "StackChan Gateway is reachable and an active physical device session is connected."
            )
        else:
            physical_status = "no_active_session"
            safe_current_status = (
                "StackChan Gateway is reachable, but no active physical device session is connected. "
                "Do not report the robot as ready or online."
            )
        result["live_state"] = {
            "evidence": "authenticated_device_query" if device_query_succeeded else "unavailable",
            "physical_status": physical_status,
            "physical_device_session_active": (
                physical_device_session_active if device_query_succeeded else None
            ),
            "safe_current_status": safe_current_status,
        }
        result["claim_policy"] = (
            "This result is the live-state authority. Capability documents and Gateway reachability "
            "must not be used to claim that the physical robot is connected, ready, or audible."
        )
        result["device"] = {
            "connected_count": len(devices),
            "configured": bool(self.config.default_device_id),
            "configured_device_connected": configured_connected,
            "ready_for_immediate_output": (
                physical_device_session_active if device_query_succeeded else False
            ),
        }
        manifest = self.capabilities() if include_capabilities else {}
        voice_session = manifest.get("voice_session")
        if isinstance(voice_session, dict):
            result["human_operations"] = voice_session
        else:
            result["human_operations"] = {
                "wake": {
                    "method": "device_local_voice",
                    "phrase": str(manifest.get("wake_word") or "Davie"),
                    "instruction": (
                        "Say 'Davie' near the device, then wait for the screen to show Listening. "
                        "If speech is missed, tap Davie's face once."
                    ),
                    "fallback": {
                        "method": "screen_tap",
                        "target": "avatar_face",
                        "instruction": (
                            "Tap Davie's face once to start or end a voice session if the wake "
                            "phrase is missed."
                        ),
                        "implementation_state": "loaded_in_firmware",
                        "physical_acceptance": "pending_human",
                        "claim_policy": (
                            "Do not call screen-tap human-verified until a person confirms it on "
                            "the physical device."
                        ),
                    },
                },
                "end": {
                    "voice_phrases": ["Goodbye Davie", "Go to sleep", "休息吧"],
                    "tool": {"name": "stackchan_control", "arguments": {"action": "sleep"}},
                },
                "idle_timeout_seconds": 120,
                "remote_wake_supported": False,
                "display_sleep_note": (
                    "A dark display may be normal display sleep and does not by itself prove that "
                    "the device or Wi-Fi is offline."
                ),
            }
        if include_capabilities:
            capabilities = manifest.get("capabilities")
            result["capabilities"] = [
                {"id": item.get("id"), "label": item.get("label")}
                for item in capabilities
                if isinstance(item, dict)
            ] if isinstance(capabilities, list) else []
        return result


class _ReadableHTMLText(HTMLParser):
    _BLOCKED = {"script", "style", "noscript", "svg"}
    _BREAKS = {"p", "div", "article", "section", "li", "br", "h1", "h2", "h3", "h4", "h5", "h6"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._blocked_depth = 0
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, _attrs: list[tuple[str, str | None]]) -> None:
        lowered = tag.lower()
        if lowered in self._BLOCKED:
            self._blocked_depth += 1
        elif lowered in self._BREAKS and self._parts:
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        lowered = tag.lower()
        if lowered in self._BLOCKED and self._blocked_depth:
            self._blocked_depth -= 1
        elif lowered in self._BREAKS and self._parts:
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._blocked_depth and data.strip():
            self._parts.append(data.strip())

    def text(self) -> str:
        lines = [" ".join(line.split()) for line in " ".join(self._parts).splitlines()]
        return "\n".join(line for line in lines if line)

def json_result(callable_, *args, **kwargs) -> str:
    try:
        return json.dumps(callable_(*args, **kwargs), ensure_ascii=False)
    except StackChanError as exc:
        return json.dumps(exc.as_dict(), ensure_ascii=False)
