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
from .capabilities import capability_manifest
from .clients import DavieClient, MediaClient
from .config import Settings
from .protocol import ProtocolError
from .reader import ReaderLibrary
from .session import StackChanSession


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
) -> FastAPI:
    config = settings or Settings.from_env()
    media = media_client or MediaClient(config.media_base_url)
    davie = davie_client or DavieClient(config.davie_base_url, config.davie_api_key)
    readers = reader_library or ReaderLibrary(config.reader_state_path)
    sessions: dict[str, StackChanSession] = {}
    sessions_lock = asyncio.Lock()

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
        if media_client is None:
            await media.close()
        if davie_client is None:
            await davie.close()

    app = FastAPI(title="StackChan Davie Gateway", version="0.3.0", lifespan=lifespan)

    @app.get("/health")
    async def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "service": "stackchan-davie-gateway",
            "version": "0.3.0",
            "connected_devices": len(sessions),
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
        websocket: dict[str, Any] = {"url": config.websocket_url, "version": 1}
        if config.device_token:
            websocket["token"] = config.device_token
        return {
            "websocket": websocket,
            "server_time": {
                "timestamp": int(time.time() * 1000),
                "timezone_offset": 480,
            },
        }

    @app.get("/v1/devices")
    async def devices(authorization: str | None = Header(default=None)) -> dict[str, Any]:
        require_admin(authorization)
        return {"devices": [session.status() for session in sessions.values()]}

    @app.get("/v1/devices/{device_id}/capabilities")
    async def device_capabilities(
        device_id: str,
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        require_admin(authorization)
        session = sessions.get(device_id)
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
        normalized_device_id = device_id or "stackchan-camera"
        if not DEVICE_ID_PATTERN.fullmatch(normalized_device_id):
            raise HTTPException(status_code=400, detail="invalid device identity")
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
        session = sessions.get(device_id)
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
        session = sessions.get(device_id)
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
        session = sessions.get(device_id)
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
        session = sessions.get(device_id)
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
        session = sessions.get(device_id)
        reader = session.reader if session else readers.for_device(device_id)
        return {"device_id": device_id, "connected": session is not None, "reader": reader.status()}

    @app.post("/v1/devices/{device_id}/reader/play")
    async def reader_play(
        device_id: str,
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        require_admin(authorization)
        session = sessions.get(device_id)
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
        session = sessions.get(device_id)
        if not session:
            raise HTTPException(status_code=404, detail="device is not connected")
        return {"status": "ok", "device_id": device_id, "reader": await session.reader_pause()}

    @app.post("/v1/devices/{device_id}/reader/stop")
    async def reader_stop(
        device_id: str,
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        require_admin(authorization)
        session = sessions.get(device_id)
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
        session = sessions.get(device_id)
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
        session = sessions.get(device_id)
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
        device_id = websocket.headers.get("device-id", "")
        client_id = websocket.headers.get("client-id", "")
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
