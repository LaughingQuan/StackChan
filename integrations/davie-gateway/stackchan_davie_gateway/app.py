from __future__ import annotations

import asyncio
import hmac
import os
import re
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Any, Callable

from fastapi import FastAPI, File, Form, Header, HTTPException, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from .audio import OpusCodec
from .audio_diagnostics import AudioDiagnosticStore
from .capabilities import capability_manifest
from .clients import DavieClient, MediaClient
from .config import Settings
from .diagnostics import DiagnosticStore
from .protocol import ProtocolError
from .reader import ReaderLibrary
from .session import StackChanSession
from .version import __version__


class SayRequest(BaseModel):
    text: str = Field(min_length=1, max_length=1000)


class ToolCallRequest(BaseModel):
    arguments: dict[str, Any] = Field(default_factory=dict)


class VisionRequest(BaseModel):
    question: str = Field(min_length=1, max_length=500)
    speak: bool = True


class ReaderLoadRequest(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    text: str = Field(min_length=1, max_length=1_000_000)
    autoplay: bool = False


class AudioDiagnosticRequest(BaseModel):
    duration_seconds: int = Field(default=10, ge=1, le=10)


DEVICE_ID_PATTERN = re.compile(r"^[A-Za-z0-9:._-]{1,128}$")


def _camera_snapshot_path(directory: str, device_id: str) -> Path:
    safe_device_id = re.sub(r"[^A-Za-z0-9._-]", "_", device_id)
    return Path(directory) / f"{safe_device_id}.jpg"


def _write_camera_snapshot(path: Path, image_bytes: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_suffix(".jpg.tmp")
    temporary_path.write_bytes(image_bytes)
    os.replace(temporary_path, path)


def create_app(
    settings: Settings | None = None,
    *,
    media_client: MediaClient | None = None,
    davie_client: DavieClient | None = None,
    codec_factory: Callable[[int, int, int], OpusCodec] = OpusCodec,
    reader_library: ReaderLibrary | None = None,
    diagnostic_store: DiagnosticStore | None = None,
    audio_diagnostic_store: AudioDiagnosticStore | None = None,
) -> FastAPI:
    config = settings or Settings.from_env()
    media = media_client or MediaClient(config.media_base_url)
    davie = davie_client or DavieClient(config.davie_base_url, config.davie_api_key)
    readers = reader_library or ReaderLibrary(config.reader_state_path)
    diagnostics = diagnostic_store or DiagnosticStore(
        config.diagnostic_state_path,
        recent_limit=config.recent_session_limit,
    )
    audio_diagnostics = audio_diagnostic_store or AudioDiagnosticStore(
        config.audio_diagnostic_root or None,
        nas_root=config.audio_diagnostic_nas_root or None,
        recent_limit=config.audio_diagnostic_recent_limit,
    )
    owns_audio_diagnostics = audio_diagnostic_store is None
    sessions: dict[str, StackChanSession] = {}
    sessions_lock = asyncio.Lock()

    def session_for(device_id: str) -> StackChanSession | None:
        """按设备标识取会话。键一律小写——MAC 大小写不是身份的一部分，
        握手处已归一化，这里保证管理端点传大写也能命中同一台设备。"""
        return sessions.get(device_id.lower())

    def require_admin(authorization: str | None) -> None:
        if config.allow_insecure and not config.admin_token:
            return
        expected = f"Bearer {config.admin_token}"
        if not authorization or not hmac.compare_digest(authorization, expected):
            raise HTTPException(status_code=401, detail="invalid admin token")

    def require_device(authorization: str | None) -> None:
        if config.allow_insecure and not config.device_token:
            return
        expected = f"Bearer {config.device_token}"
        if not authorization or not hmac.compare_digest(authorization, expected):
            raise HTTPException(status_code=401, detail="invalid device token")

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        config.validate_runtime()
        yield
        async with sessions_lock:
            active_sessions = list(sessions.values())
            sessions.clear()
        for session in active_sessions:
            await session.close(close_transport=True)
        if owns_audio_diagnostics:
            await asyncio.to_thread(audio_diagnostics.close)
        if media_client is None:
            await media.close()
        if davie_client is None:
            await davie.close()

    app = FastAPI(title="StackChan Davie Gateway", version=__version__, lifespan=lifespan)

    @app.get("/health")
    async def health() -> dict[str, Any]:
        active_statuses = [session.diagnostic_status() for session in sessions.values()]
        heartbeat_snapshot = diagnostics.heartbeat_snapshot(
            stale_seconds=config.heartbeat_stale_seconds
        )
        fresh_heartbeats = heartbeat_snapshot["fresh"]
        active_device_ids = {
            str(status.get("device_id") or "").lower()
            for status in active_statuses
            if status.get("device_id")
        }
        heartbeat_only = [
            heartbeat
            for heartbeat in fresh_heartbeats
            if heartbeat["device_id"] not in active_device_ids
        ]
        flowing_count = sum(
            1 for status in active_statuses if status["audio_flowing"]
        )
        handshake_count = sum(
            1 for status in active_statuses if status["handshake_complete"]
        )
        identified_count = sum(
            1 for status in active_statuses if status["identity_verified"]
        )
        intended_firmware_count = sum(
            1
            for status in active_statuses
            if status["intended_firmware_verified"]
        )
        last_seen_at = max(
            [
                float(status["last_activity_at"])
                for status in active_statuses
                if status.get("last_activity_at") is not None
            ]
            + [
                float(heartbeat["last_heartbeat_at"])
                for heartbeat in fresh_heartbeats
            ],
            default=None,
        )
        if not active_statuses:
            device_runtime_status = (
                "idle_ready" if fresh_heartbeats else "no_device"
            )
        elif flowing_count:
            device_runtime_status = "audio_flowing"
        else:
            device_runtime_status = "connected_no_audio"
        # 固件不匹配此前只体现为 intended_firmware_devices 少了一个数，status 恒为 ok。
        # 结果是「设备被官方 OTA 换掉」与「一切正常」在 HTTP 探测上完全同形——
        # 2026-07-24 设备漂移到官方 1.4.4 两天无人发现，就是这么来的。
        # 注意：只降 status，不动 gateway_healthy/service_healthy——网关本身是好的，
        # 把它标不健康会让看门狗去重启一个没有故障的服务。
        firmware_states = sorted(
            {
                str(status.get("firmware_expectation_state") or "unknown")
                for status in active_statuses
                if not status["intended_firmware_verified"]
            }
        )
        degraded_reasons: list[str] = []
        if active_statuses and intended_firmware_count < len(active_statuses):
            degraded_reasons.append(
                "firmware_expectation:" + ",".join(firmware_states or ["unknown"])
            )
        heartbeat_firmware_states = sorted(
            {
                heartbeat["firmware_expectation_state"]
                for heartbeat in heartbeat_only
                if not heartbeat["intended_firmware_verified"]
            }
        )
        if heartbeat_firmware_states:
            degraded_reasons.append(
                "heartbeat_firmware_expectation:"
                + ",".join(heartbeat_firmware_states)
            )
        diagnostic_snapshot = diagnostics.snapshot()
        audio_diagnostic_snapshot = audio_diagnostics.snapshot()
        return {
            "status": "degraded" if degraded_reasons else "ok",
            "degraded_reasons": degraded_reasons,
            "service_healthy": True,
            "gateway_healthy": True,
            "service": "stackchan-davie-gateway",
            "version": __version__,
            "device_runtime_status": device_runtime_status,
            "device_connected": bool(active_statuses),
            "device_reachable": bool(active_statuses or fresh_heartbeats),
            "active_voice_sessions": len(active_statuses),
            "heartbeat_ready_devices": len(fresh_heartbeats),
            "connected_devices": len(active_statuses),
            "handshake_complete_devices": handshake_count,
            "identified_devices": identified_count,
            "intended_firmware_devices": intended_firmware_count
            + sum(
                1
                for heartbeat in heartbeat_only
                if heartbeat["intended_firmware_verified"]
            ),
            "audio_flowing_devices": flowing_count,
            "last_seen_at": last_seen_at,
            "recent_sessions": len(diagnostic_snapshot["recent_sessions"]),
            "heartbeat": {
                "interval_seconds": config.heartbeat_interval_seconds,
                "stale_seconds": config.heartbeat_stale_seconds,
                "fresh_count": heartbeat_snapshot["fresh_count"],
                "stale_count": heartbeat_snapshot["stale_count"],
                "last_heartbeat_at": heartbeat_snapshot["last_heartbeat_at"],
            },
            "diagnostic_persistence": {
                "enabled": diagnostics.persistent,
                "load_error": diagnostics.load_error,
                "write_error": diagnostics.write_error,
            },
            "audio_diagnostics": {
                "enabled": audio_diagnostic_snapshot["enabled"],
                "default_state": audio_diagnostic_snapshot["default_state"],
                "active_count": len(audio_diagnostic_snapshot["active"]),
                "nas_sync_enabled": audio_diagnostic_snapshot[
                    "nas_sync_enabled"
                ],
            },
            "device_auth_configured": bool(config.device_token),
            "davie_auth_configured": bool(config.davie_api_key),
            "admin_auth_configured": bool(config.admin_token),
            "media_base_url": config.media_base_url,
            "davie_base_url": config.davie_base_url,
        }

    @app.get("/v1/capabilities")
    async def capabilities() -> dict[str, Any]:
        return capability_manifest()

    @app.api_route("/xiaozhi/ota/", methods=["GET", "POST"])
    async def ota_bootstrap(_request: Request) -> dict[str, Any]:
        websocket: dict[str, Any] = {
            "url": config.websocket_url,
            "version": 1,
            "heartbeat_url": config.heartbeat_url,
            # ESP-IDF NVS keys are limited to 15 characters.
            "heartbeat_sec": config.heartbeat_interval_seconds,
        }
        if config.device_token:
            websocket["token"] = config.device_token
        return {
            "websocket": websocket,
            "server_time": {
                "timestamp": int(time.time() * 1000),
                "timezone_offset": 480,
            },
        }

    @app.post("/v1/device-heartbeat")
    async def device_heartbeat(
        attestation: dict[str, Any],
        authorization: str | None = Header(default=None),
        device_id: str | None = Header(default=None, alias="Device-Id"),
        client_id: str | None = Header(default=None, alias="Client-Id"),
    ) -> dict[str, Any]:
        require_device(authorization)
        normalized_device_id = str(device_id or "").lower()
        normalized_client_id = str(client_id or "").lower()
        if not DEVICE_ID_PATTERN.fullmatch(
            normalized_device_id
        ) or not DEVICE_ID_PATTERN.fullmatch(normalized_client_id):
            raise HTTPException(status_code=422, detail="invalid device identity")
        try:
            StackChanSession._validate_device_attestation(attestation)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        firmware_state = StackChanSession.evaluate_firmware_expectation(
            config,
            attestation,
            identity_verified=True,
        )
        device = diagnostics.record_heartbeat(
            device_id=normalized_device_id,
            client_id=normalized_client_id,
            attestation=attestation,
            firmware_expectation_state=firmware_state,
            intended_firmware_verified=firmware_state == "matched",
        )
        return {
            "status": "ok",
            "device_id": normalized_device_id,
            "heartbeat_count": device["heartbeat_count"],
            "received_at": device["last_heartbeat_at"],
            "firmware_expectation_state": firmware_state,
            "intended_firmware_verified": firmware_state == "matched",
        }

    @app.get("/v1/devices")
    async def devices(authorization: str | None = Header(default=None)) -> dict[str, Any]:
        require_admin(authorization)
        return {"devices": [session.status() for session in sessions.values()]}

    @app.get("/v1/sessions/recent")
    async def session_history(
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        require_admin(authorization)
        return {"sessions": diagnostics.snapshot()["recent_sessions"]}

    @app.get("/v1/diagnostics")
    async def diagnostic_history(
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        require_admin(authorization)
        return diagnostics.snapshot(
            active_sessions=[
                session.diagnostic_status()
                for session in sessions.values()
            ]
        )

    @app.get("/v1/devices/{device_id}/diagnostics")
    async def device_diagnostics(
        device_id: str,
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        require_admin(authorization)
        if not DEVICE_ID_PATTERN.fullmatch(device_id):
            raise HTTPException(status_code=400, detail="invalid device identity")
        session = session_for(device_id)
        return diagnostics.device_snapshot(
            device_id,
            active_status=session.diagnostic_status() if session else None,
        )

    @app.get("/v1/devices/{device_id}/diagnostics/audio")
    async def audio_diagnostic_status(
        device_id: str,
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        require_admin(authorization)
        if not DEVICE_ID_PATTERN.fullmatch(device_id):
            raise HTTPException(status_code=400, detail="invalid device identity")
        return audio_diagnostics.snapshot(device_id)

    @app.post("/v1/devices/{device_id}/diagnostics/audio")
    async def start_audio_diagnostic(
        device_id: str,
        request: AudioDiagnosticRequest,
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        require_admin(authorization)
        if not DEVICE_ID_PATTERN.fullmatch(device_id):
            raise HTTPException(status_code=400, detail="invalid device identity")
        session = session_for(device_id)
        if session is None or session.hello is None:
            raise HTTPException(
                status_code=409,
                detail="device audio session is not ready",
            )
        try:
            capture = audio_diagnostics.arm(
                device_id=device_id,
                session_id=session.session_id,
                duration_seconds=request.duration_seconds,
            )
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        session.record_diagnostic_event(
            "audio_diagnostic_armed",
            persist=True,
            capture_id=capture["capture_id"],
            duration_seconds=request.duration_seconds,
        )
        capture["tf_timeline_marker"] = (
            await session.append_device_diagnostic_marker(
                "audio_capture_armed",
                (
                    f"id={capture['capture_id']};"
                    f"duration_seconds={request.duration_seconds};"
                    "source=gateway_received_afe_output"
                ),
            )
        )
        return capture

    @app.delete("/v1/devices/{device_id}/diagnostics/audio")
    async def cancel_audio_diagnostic(
        device_id: str,
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        require_admin(authorization)
        if not DEVICE_ID_PATTERN.fullmatch(device_id):
            raise HTTPException(status_code=400, detail="invalid device identity")
        capture = audio_diagnostics.cancel(device_id)
        if capture is None:
            raise HTTPException(
                status_code=404,
                detail="no active diagnostic capture",
            )
        session = session_for(device_id)
        if session is not None:
            session.record_diagnostic_event(
                "audio_diagnostic_cancelled",
                persist=True,
                capture_id=capture["capture_id"],
            )
            capture["tf_timeline_marker"] = (
                await session.append_device_diagnostic_marker(
                    "audio_capture_cancelled",
                    f"id={capture['capture_id']}",
                )
            )
        else:
            capture["tf_timeline_marker"] = "unavailable"
        return capture

    @app.get("/v1/devices/{device_id}/capabilities")
    async def device_capabilities(
        device_id: str,
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        require_admin(authorization)
        session = session_for(device_id)
        manifest = capability_manifest()
        return {
            **manifest,
            "device_id": device_id,
            "connected": session is not None,
            "mcp_tools": sorted(session.mcp_tools) if session else [],
            "reader": (session.reader if session else readers.for_device(device_id)).status(),
        }

    @app.post("/v1/vision/explain")
    async def vision_explain(
        question: Annotated[str, Form(min_length=1, max_length=500)],
        file: Annotated[UploadFile, File()],
        authorization: str | None = Header(default=None),
        device_id: str | None = Header(default=None, alias="Device-Id"),
        client_id: str | None = Header(default=None, alias="Client-Id"),
    ) -> dict[str, Any]:
        require_device(authorization)
        normalized_device_id = (device_id or "stackchan-camera").lower()
        if not DEVICE_ID_PATTERN.fullmatch(normalized_device_id):
            raise HTTPException(status_code=400, detail="invalid device identity")
        client_id = client_id.lower() if client_id else client_id
        if client_id and not DEVICE_ID_PATTERN.fullmatch(client_id):
            raise HTTPException(status_code=400, detail="invalid client identity")
        if file.content_type not in {"image/jpeg", "image/jpg"}:
            raise HTTPException(status_code=415, detail="camera image must be JPEG")
        image_bytes = await file.read(config.max_camera_image_bytes + 1)
        await file.close()
        if not image_bytes:
            raise HTTPException(status_code=400, detail="camera image is empty")
        if len(image_bytes) > config.max_camera_image_bytes:
            raise HTTPException(status_code=413, detail="camera image is too large")
        snapshot_path = _camera_snapshot_path(config.camera_snapshot_dir, normalized_device_id)
        await asyncio.to_thread(_write_camera_snapshot, snapshot_path, image_bytes)
        async with sessions_lock:
            active_session = sessions.get(normalized_device_id)
        if active_session and client_id and active_session.client_id != client_id:
            raise HTTPException(status_code=409, detail="camera client does not match active device session")

        reply = await davie.analyze_image(
            question,
            image_bytes,
            mime_type="image/jpeg",
            device_id=normalized_device_id,
            session_id=active_session.davie_session_id if active_session else None,
        )
        if active_session and reply.session_id:
            async with sessions_lock:
                if sessions.get(normalized_device_id) is active_session:
                    active_session.davie_session_id = reply.session_id
        return {"success": True, "result": reply.text}

    @app.get("/v1/devices/{device_id}/camera/latest")
    async def latest_camera_snapshot(
        device_id: str,
        authorization: str | None = Header(default=None),
    ) -> FileResponse:
        require_admin(authorization)
        if not DEVICE_ID_PATTERN.fullmatch(device_id):
            raise HTTPException(status_code=400, detail="invalid device identity")
        snapshot_path = _camera_snapshot_path(config.camera_snapshot_dir, device_id)
        if not snapshot_path.is_file():
            raise HTTPException(status_code=404, detail="camera snapshot is not available")
        captured_at = str(snapshot_path.stat().st_mtime)
        return FileResponse(
            snapshot_path,
            media_type="image/jpeg",
            filename=f"stackchan-{snapshot_path.name}",
            headers={
                "Cache-Control": "no-store",
                "X-StackChan-Captured-At": captured_at,
            },
        )

    @app.post("/v1/devices/{device_id}/say")
    async def say(device_id: str, body: SayRequest, authorization: str | None = Header(default=None)):
        require_admin(authorization)
        session = session_for(device_id)
        if not session:
            raise HTTPException(status_code=404, detail="device is not connected")
        await session.say(body.text)
        return {"status": "accepted", "device_id": device_id}

    @app.post("/v1/devices/{device_id}/sleep")
    async def sleep_device(
        device_id: str,
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        require_admin(authorization)
        session = session_for(device_id)
        if not session:
            raise HTTPException(status_code=404, detail="device is not connected")
        await session.sleep(reason="admin_sleep")
        return {
            "status": "ok",
            "device_id": device_id,
            "session_state": session.state,
            "close_reason": session.close_reason,
        }

    @app.post("/v1/devices/{device_id}/vision")
    async def device_vision(
        device_id: str,
        body: VisionRequest,
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        require_admin(authorization)
        session = session_for(device_id)
        if not session:
            raise HTTPException(status_code=404, detail="device is not connected")
        try:
            result = await session.see(body.question, speak=body.speak)
        except (ProtocolError, TimeoutError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {"status": "ok", "device_id": device_id, "result": result, "spoken": body.speak}

    @app.post("/v1/devices/{device_id}/reader/load")
    async def reader_load(
        device_id: str,
        body: ReaderLoadRequest,
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        require_admin(authorization)
        if len(body.text) > config.max_reader_chars:
            raise HTTPException(status_code=413, detail="reader content is too large")
        session = session_for(device_id)
        try:
            if session:
                reader_status = await session.load_reader(
                    title=body.title,
                    text=body.text,
                    autoplay=body.autoplay,
                )
            else:
                if body.autoplay:
                    raise HTTPException(status_code=409, detail="device is not connected for autoplay")
                reader = readers.for_device(device_id)
                reader.load(body.title, body.text)
                reader_status = reader.status()
        except (ProtocolError, ValueError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {"status": "accepted", "device_id": device_id, "connected": session is not None, "reader": reader_status}

    @app.get("/v1/devices/{device_id}/reader")
    async def reader_status(
        device_id: str,
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        require_admin(authorization)
        session = session_for(device_id)
        reader = session.reader if session else readers.for_device(device_id)
        return {"device_id": device_id, "connected": session is not None, "reader": reader.status()}

    @app.post("/v1/devices/{device_id}/reader/play")
    async def reader_play(
        device_id: str,
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        require_admin(authorization)
        session = session_for(device_id)
        if not session:
            raise HTTPException(status_code=404, detail="device is not connected")
        try:
            status = await session.reader_play()
        except ProtocolError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {"status": "accepted", "device_id": device_id, "reader": status}

    @app.post("/v1/devices/{device_id}/reader/pause")
    async def reader_pause(
        device_id: str,
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        require_admin(authorization)
        session = session_for(device_id)
        if not session:
            raise HTTPException(status_code=404, detail="device is not connected")
        return {"status": "ok", "device_id": device_id, "reader": await session.reader_pause()}

    @app.post("/v1/devices/{device_id}/reader/stop")
    async def reader_stop(
        device_id: str,
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        require_admin(authorization)
        session = session_for(device_id)
        if not session:
            reader = readers.for_device(device_id)
            reader.stop()
            return {"status": "ok", "device_id": device_id, "connected": False, "reader": reader.status()}
        return {"status": "ok", "device_id": device_id, "connected": True, "reader": await session.reader_stop()}

    @app.delete("/v1/devices/{device_id}/reader")
    async def reader_clear(
        device_id: str,
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        require_admin(authorization)
        session = session_for(device_id)
        if session:
            await session.reader_stop()
            session.reader.clear()
            return {
                "status": "ok",
                "device_id": device_id,
                "connected": True,
                "removed": True,
                "reader": session.reader.status(),
            }
        reader = readers.for_device(device_id)
        removed = reader.clear()
        status = reader.status()
        readers.remove(device_id)
        return {
            "status": "ok",
            "device_id": device_id,
            "connected": False,
            "removed": removed,
            "reader": status,
        }

    @app.post("/v1/devices/{device_id}/tools/{tool_name}")
    async def call_tool(
        device_id: str,
        tool_name: str,
        body: ToolCallRequest,
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        require_admin(authorization)
        session = session_for(device_id)
        if not session:
            raise HTTPException(status_code=404, detail="device is not connected")
        try:
            result = await session.call_tool(tool_name, body.arguments)
        except ProtocolError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {"status": "ok", "device_id": device_id, "tool": tool_name, "result": result}

    @app.websocket("/xiaozhi/v1/")
    async def xiaozhi_websocket(websocket: WebSocket):
        authorization = websocket.headers.get("authorization", "")
        expected_device_auth = f"Bearer {config.device_token}"
        if not config.allow_insecure and not hmac.compare_digest(authorization, expected_device_auth):
            await websocket.close(code=1008, reason="invalid device token")
            return
        # MAC 大小写不是身份的一部分。固件上报小写、人写的配置常是大写，
        # 不在这里归一化，同一台设备就会按大小写产生两份会话与两份诊断状态。
        device_id = websocket.headers.get("device-id", "").lower()
        client_id = websocket.headers.get("client-id", "").lower()
        if not DEVICE_ID_PATTERN.fullmatch(device_id) or not DEVICE_ID_PATTERN.fullmatch(client_id):
            await websocket.close(code=1008, reason="invalid device identity")
            return
        await websocket.accept()
        session = StackChanSession(
            transport=websocket,
            settings=config,
            media=media,
            davie=davie,
            device_id=device_id,
            client_id=client_id,
            codec_factory=codec_factory,
            reader=readers.for_device(device_id),
            diagnostic_sink=diagnostics.record,
            diagnostic_audio_sink=audio_diagnostics.feed,
        )
        async with sessions_lock:
            previous = sessions.get(device_id)
            sessions[device_id] = session
        if previous:
            await previous.close(close_transport=True)
        try:
            while True:
                message = await websocket.receive()
                if message.get("type") == "websocket.disconnect":
                    break
                if message.get("text") is not None:
                    await session.handle_text(message["text"])
                elif message.get("bytes") is not None:
                    await session.handle_binary(message["bytes"])
        except WebSocketDisconnect:
            pass
        except ProtocolError as exc:
            await websocket.close(code=1003, reason=str(exc)[:120])
        finally:
            async with sessions_lock:
                if sessions.get(device_id) is session:
                    sessions.pop(device_id, None)
            await session.close()

    return app


app = create_app()
