from __future__ import annotations

import json
import struct
from dataclasses import dataclass
from typing import Any


class ProtocolError(ValueError):
    pass


MAX_JSON_MESSAGE_BYTES = 64 * 1024
MAX_AUDIO_PACKET_BYTES = 8 * 1024


@dataclass(frozen=True)
class ClientHello:
    version: int
    sample_rate: int
    channels: int
    frame_duration_ms: int
    supports_mcp: bool
    supports_server_aec: bool


def parse_json_message(raw: str) -> dict[str, Any]:
    if len(raw.encode("utf-8")) > MAX_JSON_MESSAGE_BYTES:
        raise ProtocolError("JSON message is too large")
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ProtocolError("invalid JSON message") from exc
    if not isinstance(payload, dict):
        raise ProtocolError("message must be a JSON object")
    message_type = payload.get("type")
    if not isinstance(message_type, str) or not message_type:
        raise ProtocolError("message type is required")
    return payload


def parse_client_hello(payload: dict[str, Any]) -> ClientHello:
    if payload.get("type") != "hello" or payload.get("transport") != "websocket":
        raise ProtocolError("expected websocket hello")
    version = int(payload.get("version") or 1)
    if version not in {1, 2, 3}:
        raise ProtocolError(f"unsupported protocol version: {version}")
    audio = payload.get("audio_params") or {}
    if not isinstance(audio, dict) or audio.get("format") != "opus":
        raise ProtocolError("only Opus audio is supported")
    sample_rate = int(audio.get("sample_rate") or 16000)
    channels = int(audio.get("channels") or 1)
    frame_duration = int(audio.get("frame_duration") or 60)
    if sample_rate not in {8000, 12000, 16000, 24000, 48000}:
        raise ProtocolError("unsupported Opus sample rate")
    if channels != 1:
        raise ProtocolError("only mono device audio is supported")
    if frame_duration != 60:
        raise ProtocolError("this gateway requires 60 ms Opus frames")
    features = payload.get("features") or {}
    return ClientHello(
        version=version,
        sample_rate=sample_rate,
        channels=channels,
        frame_duration_ms=frame_duration,
        supports_mcp=bool(features.get("mcp")),
        supports_server_aec=bool(features.get("aec")),
    )


def server_hello(session_id: str, *, sample_rate: int, frame_duration_ms: int) -> dict[str, Any]:
    return {
        "type": "hello",
        "transport": "websocket",
        "session_id": session_id,
        "audio_params": {
            "format": "opus",
            "sample_rate": sample_rate,
            "channels": 1,
            "frame_duration": frame_duration_ms,
        },
    }


def unpack_audio_frame(payload: bytes, version: int) -> tuple[bytes, int]:
    if len(payload) > MAX_AUDIO_PACKET_BYTES:
        raise ProtocolError("audio frame is too large")
    if version == 1:
        if not payload:
            raise ProtocolError("empty audio frame")
        return payload, 0
    if version == 2:
        header = struct.Struct("!HHIII")
        if len(payload) < header.size:
            raise ProtocolError("truncated v2 audio frame")
        frame_version, frame_type, _reserved, timestamp, size = header.unpack_from(payload)
        if frame_version != 2 or frame_type != 0 or size != len(payload) - header.size:
            raise ProtocolError("invalid v2 audio frame")
        return payload[header.size:], timestamp
    if version == 3:
        header = struct.Struct("!BBH")
        if len(payload) < header.size:
            raise ProtocolError("truncated v3 audio frame")
        frame_type, _reserved, size = header.unpack_from(payload)
        if frame_type != 0 or size != len(payload) - header.size:
            raise ProtocolError("invalid v3 audio frame")
        return payload[header.size:], 0
    raise ProtocolError(f"unsupported protocol version: {version}")


def pack_audio_frame(payload: bytes, version: int, *, timestamp_ms: int = 0) -> bytes:
    if not payload:
        raise ProtocolError("empty audio frame")
    if len(payload) > MAX_AUDIO_PACKET_BYTES:
        raise ProtocolError("audio frame is too large")
    if version == 1:
        return payload
    if version == 2:
        return struct.pack("!HHIII", 2, 0, 0, timestamp_ms, len(payload)) + payload
    if version == 3:
        if len(payload) > 0xFFFF:
            raise ProtocolError("v3 audio payload is too large")
        return struct.pack("!BBH", 0, 0, len(payload)) + payload
    raise ProtocolError(f"unsupported protocol version: {version}")
