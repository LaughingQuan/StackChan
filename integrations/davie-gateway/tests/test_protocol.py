from __future__ import annotations

import struct

import pytest

from stackchan_davie_gateway.protocol import (
    ProtocolError,
    pack_audio_frame,
    parse_client_hello,
    unpack_audio_frame,
)


def test_parse_official_client_hello() -> None:
    hello = parse_client_hello(
        {
            "type": "hello",
            "version": 1,
            "transport": "websocket",
            "features": {"mcp": True},
            "audio_params": {
                "format": "opus",
                "sample_rate": 16000,
                "channels": 1,
                "frame_duration": 60,
            },
        }
    )
    assert hello.version == 1
    assert hello.supports_mcp is True
    assert hello.sample_rate == 16000


@pytest.mark.parametrize("version", [1, 2, 3])
def test_audio_framing_round_trip(version: int) -> None:
    raw = b"opus-packet"
    packed = pack_audio_frame(raw, version, timestamp_ms=1234)
    unpacked, timestamp = unpack_audio_frame(packed, version)
    assert unpacked == raw
    assert timestamp == (1234 if version == 2 else 0)


def test_rejects_truncated_v2_audio() -> None:
    with pytest.raises(ProtocolError):
        unpack_audio_frame(struct.pack("!H", 2), 2)


def test_rejects_non_60ms_audio_contract() -> None:
    with pytest.raises(ProtocolError, match="60 ms"):
        parse_client_hello(
            {
                "type": "hello",
                "version": 1,
                "transport": "websocket",
                "audio_params": {
                    "format": "opus",
                    "sample_rate": 16000,
                    "channels": 1,
                    "frame_duration": 20,
                },
            }
        )


def test_rejects_oversized_audio_packet() -> None:
    with pytest.raises(ProtocolError, match="too large"):
        unpack_audio_frame(b"x" * 9000, 1)
