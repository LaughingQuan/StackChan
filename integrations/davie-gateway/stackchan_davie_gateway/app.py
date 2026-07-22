from __future__ import annotations

import asyncio
import hmac
import re
import time
from contextlib import asynccontextmanager
from typing import Annotated, Any, Callable

from fastapi import FastAPI, File, Form, Header, HTTPException, Request, UploadFile, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from .audio import OpusCodec
from .clients import DavieClient, MediaClient
from .config import Settings
from .protocol import ProtocolError
from .session import StackChanSession


class SayRequest(BaseModel):
    text: str = Field(min_length=1, max_length=1000)


class ToolCallRequest(BaseModel):
    arguments: dict[str, Any] = Field(default_factory=dict)


DEVICE_ID_PATTERN = re.compile(r"^[A-Za-z0-9:._-]{1,128}$")


def create_app(
    settings: Settings | None = None,
    *,
    media_client: MediaClient | None = None,
    davie_client: DavieClient | None = None,
    codec_factory: Callable[[int, int, int], OpusCodec] = OpusCodec,
) -> FastAPI:
    config = settings or Settings.from_env()
    media = media_client or MediaClient(config.media_base_url)
    davie = davie_client or DavieClient(config.davie_base_url, config.davie_api_key)
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

    app = FastAPI(title="StackChan Davie Gateway", version="0.1.0", lifespan=lifespan)

    @app.get("/health")
    async def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "service": "stackchan-davie-gateway",
            "version": "0.1.0",
            "connected_devices": len(sessions),
            "device_auth_configured": bool(config.device_token),
            "davie_auth_configured": bool(config.davie_api_key),
            "admin_auth_configured": bool(config.admin_token),
            "media_base_url": config.media_base_url,
            "davie_base_url": config.davie_base_url,
        }

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

    @app.post("/v1/devices/{device_id}/say")
    async def say(device_id: str, body: SayRequest, authorization: str | None = Header(default=None)):
        require_admin(authorization)
        session = sessions.get(device_id)
        if not session:
            raise HTTPException(status_code=404, detail="device is not connected")
        await session.say(body.text)
        return {"status": "accepted", "device_id": device_id}

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
