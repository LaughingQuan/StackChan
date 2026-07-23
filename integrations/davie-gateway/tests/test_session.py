from __future__ import annotations

import asyncio
import struct
from dataclasses import dataclass

from stackchan_davie_gateway.audio import pcm_to_wav
from stackchan_davie_gateway.capabilities import DeviceAction
from stackchan_davie_gateway.clients import DavieReply
from stackchan_davie_gateway.config import Settings
from stackchan_davie_gateway.session import StackChanSession


class FakeTransport:
    def __init__(self):
        self.json: list[dict] = []
        self.binary: list[bytes] = []
        self.closed = False

    async def send_json(self, payload: dict) -> None:
        self.json.append(payload)

    async def send_bytes(self, payload: bytes) -> None:
        self.binary.append(payload)

    async def close(self, code: int = 1000, reason: str | None = None) -> None:
        assert code == 1000
        self.closed = True


class FakeCodec:
    def __init__(self, _input_rate: int, _output_rate: int, _frame_duration: int):
        self.closed = False

    def decode(self, packet: bytes) -> bytes:
        return packet

    def encode(self, pcm: bytes) -> bytes:
        return b"encoded:" + pcm[:8]

    def close(self) -> None:
        self.closed = True


class FakeMedia:
    async def transcribe(self, _wav: bytes, *, hotwords: list[str]) -> str:
        assert "Davie" in hotwords
        return "Hello Davie"

    async def synthesize(self, _text: str) -> bytes:
        return pcm_to_wav(struct.pack("<1440h", *([600] * 1440)), 24000)


class FakeDavie:
    async def chat(self, text: str, *, device_id: str, session_id: str | None) -> DavieReply:
        assert text == "Hello Davie"
        assert device_id == "device-1"
        return DavieReply("Hello Jason. How can I help?", session_id or "davie-session-1")


class NoDavie:
    async def chat(self, *_args, **_kwargs) -> DavieReply:
        raise AssertionError("local device actions must not call Davie")


class EmptyMedia(FakeMedia):
    async def transcribe(self, _wav: bytes, *, hotwords: list[str]) -> str:
        return ""


def _pcm_frame(amplitude: int) -> bytes:
    return struct.pack("<960h", *([amplitude] * 960))


async def test_session_runs_turn_and_sends_audio() -> None:
    transport = FakeTransport()
    settings = Settings(
        endpoint_silence_ms=180,
        endpoint_min_speech_ms=120,
        endpoint_min_rms=300,
    )
    session = StackChanSession(
        transport=transport,
        settings=settings,
        media=FakeMedia(),
        davie=FakeDavie(),
        device_id="device-1",
        client_id="client-1",
        codec_factory=FakeCodec,
    )
    await session.handle_text(
        '{"type":"hello","version":1,"transport":"websocket",'
        '"features":{"mcp":true},"audio_params":{"format":"opus",'
        '"sample_rate":16000,"channels":1,"frame_duration":60}}'
    )
    await session.handle_text('{"type":"listen","state":"start","mode":"realtime"}')
    for _ in range(4):
        await session.handle_binary(_pcm_frame(1800))
    for _ in range(5):
        await session.handle_binary(_pcm_frame(10))
    assert session.response_task is not None
    await asyncio.wait_for(session.response_task, timeout=2)
    assert any(item.get("type") == "stt" and item.get("text") == "Hello Davie" for item in transport.json)
    assert any(item.get("type") == "tts" and item.get("state") == "start" for item in transport.json)
    assert any(item.get("type") == "tts" and item.get("state") == "stop" for item in transport.json)
    assert session.status()["endpoint"]["completed_turns"] == 1
    assert transport.binary
    await session.close()


async def test_realtime_empty_transcript_keeps_listening_without_failure_alert() -> None:
    transport = FakeTransport()
    session = StackChanSession(
        transport=transport,
        settings=Settings(endpoint_silence_ms=180, endpoint_min_speech_ms=120, endpoint_min_rms=300),
        media=EmptyMedia(),
        davie=NoDavie(),
        device_id="device-1",
        client_id="client-1",
        codec_factory=FakeCodec,
    )
    await session.handle_text(
        '{"type":"hello","version":1,"transport":"websocket",'
        '"features":{"mcp":false},"audio_params":{"format":"opus",'
        '"sample_rate":16000,"channels":1,"frame_duration":60}}'
    )
    await session.handle_text('{"type":"listen","state":"start","mode":"realtime"}')
    for _ in range(4):
        await session.handle_binary(_pcm_frame(1800))
    for _ in range(5):
        await session.handle_binary(_pcm_frame(10))
    assert session.response_task is not None
    await asyncio.wait_for(session.response_task, timeout=2)
    assert session.listening is True
    assert session.empty_transcript_count == 1
    assert session.last_error == "asr_empty_transcript"
    assert not any(item.get("type") == "alert" for item in transport.json)
    await session.close()


async def test_official_mcp_is_initialized_by_gateway_and_tools_are_discovered() -> None:
    transport = FakeTransport()
    session = StackChanSession(
        transport=transport,
        settings=Settings(),
        media=FakeMedia(),
        davie=FakeDavie(),
        device_id="device-1",
        client_id="client-1",
        codec_factory=FakeCodec,
    )
    await session.handle_text(
        '{"type":"hello","version":1,"transport":"websocket",'
        '"features":{"mcp":true},"audio_params":{"format":"opus",'
        '"sample_rate":16000,"channels":1,"frame_duration":60}}'
    )
    initialize = transport.json[-1]["payload"]
    assert initialize["method"] == "initialize"
    assert initialize["params"]["capabilities"]["vision"]["url"].endswith(
        "/v1/vision/explain"
    )
    await session.handle_text(
        '{"type":"mcp","payload":{"jsonrpc":"2.0","id":1,'
        '"result":{"protocolVersion":"2024-11-05","capabilities":{"tools":{}}}}}'
    )
    tool_list_request = transport.json[-1]["payload"]
    assert tool_list_request["method"] == "tools/list"
    await session.handle_text(
        '{"type":"mcp","payload":{"jsonrpc":"2.0","id":2,'
        '"result":{"tools":[{"name":"self.get_device_status",'
        '"description":"status","inputSchema":{"type":"object"}}]}}}'
    )
    assert session.mcp_initialized is True
    assert "self.get_device_status" in session.mcp_tools
    await session.close()


async def test_device_tool_call_round_trip() -> None:
    transport = FakeTransport()
    session = StackChanSession(
        transport=transport,
        settings=Settings(),
        media=FakeMedia(),
        davie=FakeDavie(),
        device_id="device-1",
        client_id="client-1",
        codec_factory=FakeCodec,
    )
    await session.handle_text(
        '{"type":"hello","version":1,"transport":"websocket",'
        '"features":{"mcp":false},"audio_params":{"format":"opus",'
        '"sample_rate":16000,"channels":1,"frame_duration":60}}'
    )
    session.mcp_tools["self.audio_speaker.set_volume"] = {
        "name": "self.audio_speaker.set_volume"
    }
    task = asyncio.create_task(
        session.call_tool("self.audio_speaker.set_volume", {"volume": 45})
    )
    await asyncio.sleep(0)
    request = transport.json[-1]["payload"]
    assert request["method"] == "tools/call"
    assert request["params"]["arguments"] == {"volume": 45}
    await session.handle_text(
        '{"type":"mcp","payload":{"jsonrpc":"2.0","id":1,'
        '"result":{"content":[{"type":"text","text":"true"}]}}}'
    )
    result = await task
    assert result["content"][0]["text"] == "true"
    await session.close()


def test_camera_tool_result_extracts_local_vision_answer() -> None:
    result = {
        "content": [
            {
                "type": "text",
                "text": '{"success":true,"result":"I can see a blue cup."}',
            }
        ]
    }
    assert StackChanSession._extract_tool_text(result) == "I can see a blue cup."


async def test_abort_invalidates_generation() -> None:
    transport = FakeTransport()
    session = StackChanSession(
        transport=transport,
        settings=Settings(),
        media=FakeMedia(),
        davie=FakeDavie(),
        device_id="device-1",
        client_id="client-1",
        codec_factory=FakeCodec,
    )
    session.speaking = True
    generation = session.generation_id
    await session.cancel_response(reason="barge_in")
    assert session.generation_id == generation + 1
    assert session.interrupt_count == 1
    assert transport.json[-1]["state"] == "stop"
    await session.close()


async def test_speech_start_cancels_inflight_response_before_tts() -> None:
    transport = FakeTransport()
    session = StackChanSession(
        transport=transport,
        settings=Settings(endpoint_min_rms=300),
        media=FakeMedia(),
        davie=FakeDavie(),
        device_id="device-1",
        client_id="client-1",
        codec_factory=FakeCodec,
    )
    await session.handle_text(
        '{"type":"hello","version":1,"transport":"websocket",'
        '"features":{"mcp":true},"audio_params":{"format":"opus",'
        '"sample_rate":16000,"channels":1,"frame_duration":60}}'
    )

    response_started = asyncio.Event()
    response_cancelled = asyncio.Event()

    async def slow_response() -> None:
        response_started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            response_cancelled.set()
            raise

    session.response_task = asyncio.create_task(slow_response())
    await response_started.wait()
    generation = session.generation_id

    await session.handle_binary(_pcm_frame(1800))
    await session.handle_binary(_pcm_frame(1800))

    assert response_cancelled.is_set()
    assert session.response_task is None
    assert session.generation_id == generation + 1
    assert session.interrupt_count == 1
    assert transport.json[-1]["state"] == "stop"
    assert transport.json[-1]["reason"] == "barge_in"
    await session.close()


async def test_manual_listen_stop_commits_captured_turn() -> None:
    transport = FakeTransport()
    session = StackChanSession(
        transport=transport,
        settings=Settings(endpoint_min_speech_ms=120, endpoint_min_rms=300),
        media=FakeMedia(),
        davie=FakeDavie(),
        device_id="device-1",
        client_id="client-1",
        codec_factory=FakeCodec,
    )
    await session.handle_text(
        '{"type":"hello","version":1,"transport":"websocket",'
        '"features":{"mcp":false},"audio_params":{"format":"opus",'
        '"sample_rate":16000,"channels":1,"frame_duration":60}}'
    )
    await session.handle_text('{"type":"listen","state":"start","mode":"manual"}')
    for _ in range(4):
        await session.handle_binary(_pcm_frame(1800))
    await session.handle_text('{"type":"listen","state":"stop"}')
    assert session.response_task is not None
    await asyncio.wait_for(session.response_task, timeout=2)
    assert session.last_transcript == "Hello Davie"
    await session.close()


async def test_concurrent_say_keeps_only_latest_generation() -> None:
    class SlowMedia(FakeMedia):
        async def synthesize(self, _text: str) -> bytes:
            await asyncio.sleep(0.05)
            return await super().synthesize(_text)

    transport = FakeTransport()
    session = StackChanSession(
        transport=transport,
        settings=Settings(),
        media=SlowMedia(),
        davie=FakeDavie(),
        device_id="device-1",
        client_id="client-1",
        codec_factory=FakeCodec,
    )
    await session.handle_text(
        '{"type":"hello","version":1,"transport":"websocket",'
        '"features":{"mcp":false},"audio_params":{"format":"opus",'
        '"sample_rate":16000,"channels":1,"frame_duration":60}}'
    )
    await asyncio.gather(session.say("first"), session.say("second"))
    assert session.response_task is not None
    await asyncio.wait_for(session.response_task, timeout=2)
    sentence_starts = [
        item.get("text")
        for item in transport.json
        if item.get("type") == "tts" and item.get("state") == "sentence_start"
    ]
    assert sentence_starts[-1] in {"first", "second"}
    assert session.interrupt_count == 1
    await session.close(close_transport=True)
    assert transport.closed is True


async def test_help_command_is_answered_locally_without_model_call() -> None:
    class HelpMedia(FakeMedia):
        async def transcribe(self, _wav: bytes, *, hotwords: list[str]) -> str:
            return "Davie, what can you do?"

    transport = FakeTransport()
    session = StackChanSession(
        transport=transport,
        settings=Settings(),
        media=HelpMedia(),
        davie=NoDavie(),
        device_id="device-1",
        client_id="client-1",
        codec_factory=FakeCodec,
    )
    await session.handle_text(
        '{"type":"hello","version":1,"transport":"websocket",'
        '"features":{"mcp":false},"audio_params":{"format":"opus",'
        '"sample_rate":16000,"channels":1,"frame_duration":60}}'
    )
    await session._process_turn(_pcm_frame(1800))
    assert "look and explain" in session.last_response.lower() or any(
        "look and explain" in str(item.get("text", "")).lower() for item in transport.json
    )
    assert transport.binary
    await session.close()


async def test_reader_barge_in_pauses_without_skipping_current_segment() -> None:
    class SlowReaderMedia(FakeMedia):
        async def synthesize(self, _text: str) -> bytes:
            await asyncio.sleep(1)
            return await super().synthesize(_text)

    transport = FakeTransport()
    session = StackChanSession(
        transport=transport,
        settings=Settings(endpoint_min_rms=300),
        media=SlowReaderMedia(),
        davie=FakeDavie(),
        device_id="device-1",
        client_id="client-1",
        codec_factory=FakeCodec,
    )
    await session.handle_text(
        '{"type":"hello","version":1,"transport":"websocket",'
        '"features":{"mcp":false},"audio_params":{"format":"opus",'
        '"sample_rate":16000,"channels":1,"frame_duration":60}}'
    )
    await session.load_reader(title="Test book", text="First sentence. Second sentence.")
    await session.reader_play()
    await asyncio.sleep(0.01)
    assert session.reader.state == "playing"
    assert session.reader.current() == "First sentence."

    await session.handle_binary(_pcm_frame(1800))
    await session.handle_binary(_pcm_frame(1800))

    assert session.reader.state == "paused"
    assert session.reader.index == 0
    assert session.reader.current() == "First sentence."
    assert transport.json[-1]["reason"] == "barge_in"
    await session.close()


async def test_reader_play_completes_and_reports_progress() -> None:
    transport = FakeTransport()
    session = StackChanSession(
        transport=transport,
        settings=Settings(),
        media=FakeMedia(),
        davie=FakeDavie(),
        device_id="device-1",
        client_id="client-1",
        codec_factory=FakeCodec,
    )
    await session.handle_text(
        '{"type":"hello","version":1,"transport":"websocket",'
        '"features":{"mcp":false},"audio_params":{"format":"opus",'
        '"sample_rate":16000,"channels":1,"frame_duration":60}}'
    )
    await session.load_reader(title="Test book", text="First sentence. Second sentence.")
    await session.reader_play()
    assert session.response_task is not None
    await asyncio.wait_for(session.response_task, timeout=3)
    assert session.reader.state == "completed"
    assert session.reader.status()["progress_percent"] == 100.0
    assert any(item.get("status") == "Reading complete" for item in transport.json)
    await session.close()


async def test_local_capability_reply_updates_session_diagnostics() -> None:
    transport = FakeTransport()
    session = StackChanSession(
        transport=transport,
        settings=Settings(),
        media=FakeMedia(),
        davie=FakeDavie(),
        device_id="device-1",
        client_id="client-1",
        codec_factory=FakeCodec,
    )
    await session.handle_text(
        '{"type":"hello","version":1,"transport":"websocket",'
        '"features":{"mcp":false},"audio_params":{"format":"opus",'
        '"sample_rate":16000,"channels":1,"frame_duration":60}}'
    )

    handled = await session._handle_device_action(
        DeviceAction("help", chinese=False), session.generation_id
    )

    assert handled is True
    assert session.last_response.startswith("I can talk with you")
    assert session.status()["last_response"] == session.last_response
    await session.close()
