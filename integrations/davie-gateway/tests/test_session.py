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
        self.close_reason: str | None = None

    async def send_json(self, payload: dict) -> None:
        self.json.append(payload)

    async def send_bytes(self, payload: bytes) -> None:
        self.binary.append(payload)

    async def close(self, code: int = 1000, reason: str | None = None) -> None:
        assert code == 1000
        self.closed = True
        self.close_reason = reason


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


class SequenceMedia(FakeMedia):
    def __init__(self, transcripts: list[str]):
        self.transcripts = transcripts

    async def transcribe(self, _wav: bytes, *, hotwords: list[str]) -> str:
        assert self.transcripts
        return self.transcripts.pop(0)


class SleepMedia(FakeMedia):
    async def transcribe(self, _wav: bytes, *, hotwords: list[str]) -> str:
        return "Goodbye Davie"


class NameOnlyMedia(FakeMedia):
    async def transcribe(self, _wav: bytes, *, hotwords: list[str]) -> str:
        assert hotwords == ["Davie", "StackChan"]
        return "Jason, Jason, Jason, Jason."


class HallucinatingMedia(FakeMedia):
    async def transcribe(self, _wav: bytes, *, hotwords: list[str]) -> str:
        return " ".join(["imagined"] * 40)


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
    timing = session.status()["last_turn_timing"]
    assert timing["outcome"] == "completed"
    assert timing["input_audio_ms"] > 0
    assert timing["asr_ms"] >= 0
    assert timing["llm_ms"] >= 0
    assert timing["response_ready_ms"] >= timing["asr_ms"]
    assert timing["tts_synthesis_ms"] >= 0
    assert timing["first_audio_ms"] >= timing["response_ready_ms"]
    assert timing["streamed_audio_ms"] > 0
    assert timing["total_ms"] >= timing["first_audio_ms"]
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
    assert session.consecutive_empty_transcript_count == 1
    assert session.last_error == "asr_empty_transcript"
    assert session.state == "listening"
    assert not any(item.get("type") == "alert" for item in transport.json)
    timing = session.status()["last_turn_timing"]
    assert timing["outcome"] == "empty_transcript"
    assert timing["asr_ms"] >= 0
    assert timing["llm_ms"] is None
    assert timing["first_audio_ms"] is None
    assert timing["total_ms"] >= timing["asr_ms"]
    await session.close()


async def test_first_auto_empty_transcript_stays_listening_then_repeated_empty_prompts() -> None:
    transport = FakeTransport()
    session = StackChanSession(
        transport=transport,
        settings=Settings(),
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
    await session.handle_text('{"type":"listen","state":"start","mode":"auto"}')

    await session._process_turn(_pcm_frame(1800))

    assert session.empty_transcript_count == 1
    assert session.consecutive_empty_transcript_count == 1
    assert session.state == "listening"
    assert not any(item.get("type") == "alert" for item in transport.json)

    await session._process_turn(_pcm_frame(1800))

    alerts = [item for item in transport.json if item.get("type") == "alert"]
    assert session.empty_transcript_count == 2
    assert session.consecutive_empty_transcript_count == 2
    assert session.state == "listening"
    assert alerts == [
        {
            "session_id": session.session_id,
            "type": "alert",
            "status": "Listening",
            "message": "I did not catch that. Please try again.",
            "emotion": "neutral",
        }
    ]
    await session.close()


async def test_valid_turn_resets_consecutive_empty_transcript_prompting() -> None:
    transport = FakeTransport()
    session = StackChanSession(
        transport=transport,
        settings=Settings(),
        media=SequenceMedia(["", "Hello Davie", ""]),
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
    await session.handle_text('{"type":"listen","state":"start","mode":"auto"}')

    await session._process_turn(_pcm_frame(1800))
    await session._process_turn(_pcm_frame(1800))
    await session._process_turn(_pcm_frame(1800))

    assert session.accepted_turn_count == 1
    assert session.empty_transcript_count == 2
    assert session.consecutive_empty_transcript_count == 1
    assert not any(item.get("type") == "alert" for item in transport.json)
    await session.close()


async def test_voice_sleep_command_closes_session_without_model_call() -> None:
    transport = FakeTransport()
    session = StackChanSession(
        transport=transport,
        settings=Settings(),
        media=SleepMedia(),
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

    assert session.closed is True
    assert session.state == "closed"
    assert session.close_reason == "voice_sleep"
    assert transport.closed is True
    assert transport.close_reason == "voice_sleep"
    assert session.last_response.startswith("Goodbye")


async def test_inactivity_watchdog_returns_device_to_sleep() -> None:
    transport = FakeTransport()
    session = StackChanSession(
        transport=transport,
        settings=Settings(
            session_idle_timeout_seconds=0.08,
            session_watchdog_interval_seconds=0.01,
        ),
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

    await asyncio.sleep(0.16)

    status = session.status()
    assert status["closed"] is True
    assert status["session_state"] == "closed"
    assert status["idle_timeout_count"] == 1
    assert status["close_reason"] == "inactivity_timeout"
    assert transport.closed is True
    assert any(item.get("status") == "Sleeping" for item in transport.json)


async def test_name_only_wake_tail_is_rejected_before_davie() -> None:
    transport = FakeTransport()
    session = StackChanSession(
        transport=transport,
        settings=Settings(),
        media=NameOnlyMedia(),
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

    await session._process_turn(_pcm_frame(1800) * 5)

    status = session.status()
    assert status["accepted_turn_count"] == 0
    assert status["rejected_transcript_count"] == 1
    assert status["last_transcription_quality"]["reason"] == "wake_or_name_only"
    assert status["last_error"] == "asr_rejected_wake_or_name_only"
    assert status["last_turn_timing"]["outcome"] == "rejected_transcript"
    assert status["last_turn_timing"]["first_audio_ms"] is None
    assert not any(item.get("type") == "stt" for item in transport.json)
    await session.close()


async def test_implausibly_fast_transcript_is_rejected_before_davie() -> None:
    transport = FakeTransport()
    session = StackChanSession(
        transport=transport,
        settings=Settings(max_transcript_words_per_second=6),
        media=HallucinatingMedia(),
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

    await session._process_turn(_pcm_frame(1800) * 10)

    assert session.rejected_transcript_count == 1
    assert session.last_transcription_quality["reason"] == "implausible_transcript_rate"
    assert session.last_transcript == ""
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


async def test_cancelled_turn_timing_does_not_overwrite_next_generation() -> None:
    class BlockingDavie(FakeDavie):
        def __init__(self):
            self.started = asyncio.Event()

        async def chat(
            self,
            text: str,
            *,
            device_id: str,
            session_id: str | None,
        ) -> DavieReply:
            self.started.set()
            await asyncio.Event().wait()
            raise AssertionError("unreachable")

    transport = FakeTransport()
    blocking_davie = BlockingDavie()
    session = StackChanSession(
        transport=transport,
        settings=Settings(),
        media=FakeMedia(),
        davie=blocking_davie,
        device_id="device-1",
        client_id="client-1",
        codec_factory=FakeCodec,
    )
    await session.handle_text(
        '{"type":"hello","version":1,"transport":"websocket",'
        '"features":{"mcp":false},"audio_params":{"format":"opus",'
        '"sample_rate":16000,"channels":1,"frame_duration":60}}'
    )
    first_task = asyncio.create_task(session._process_turn(_pcm_frame(1800)))
    session.response_task = first_task
    await blocking_davie.started.wait()

    await session.cancel_response(reason="test_cancel")

    cancelled_timing = session.status()["last_turn_timing"]
    assert cancelled_timing["outcome"] == "cancelled"
    assert cancelled_timing["llm_ms"] >= 0
    assert cancelled_timing["first_audio_ms"] is None
    assert cancelled_timing["total_ms"] >= cancelled_timing["asr_ms"]

    session.davie = FakeDavie()
    await session._process_turn(_pcm_frame(1800))
    completed_timing = session.status()["last_turn_timing"]
    assert completed_timing["generation_id"] > cancelled_timing["generation_id"]
    assert completed_timing["outcome"] == "completed"
    assert completed_timing["first_audio_ms"] is not None
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

    assert response_cancelled.is_set() is False
    assert session.barge_in_candidate is True
    assert session.barge_in_confirmed_count == 0

    for _ in range(4):
        await session.handle_binary(_pcm_frame(1800))

    assert response_cancelled.is_set()
    assert session.response_task is None
    assert session.generation_id == generation + 1
    assert session.interrupt_count == 1
    assert session.barge_in_candidate_count == 1
    assert session.barge_in_confirmed_count == 1
    assert session.last_barge_in_decision == "confirmed_speech"
    assert transport.json[-1]["state"] == "stop"
    assert transport.json[-1]["reason"] == "barge_in"
    await session.close()


async def test_short_noise_burst_does_not_cancel_inflight_response() -> None:
    transport = FakeTransport()
    session = StackChanSession(
        transport=transport,
        settings=Settings(
            endpoint_silence_ms=300,
            endpoint_min_speech_ms=240,
            endpoint_min_rms=300,
            barge_in_confirmation_ms=360,
        ),
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

    response_cancelled = asyncio.Event()

    async def slow_response() -> None:
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            response_cancelled.set()
            raise

    session.response_task = asyncio.create_task(slow_response())
    await asyncio.sleep(0)
    await session.handle_binary(_pcm_frame(1800))
    await session.handle_binary(_pcm_frame(1800))
    for _ in range(5):
        await session.handle_binary(_pcm_frame(10))

    assert response_cancelled.is_set() is False
    assert session.barge_in_candidate is False
    assert session.barge_in_confirmed_count == 0
    assert session.barge_in_suppressed_count == 1
    assert session.last_barge_in_decision == "insufficient_speech"
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

    for _ in range(6):
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
