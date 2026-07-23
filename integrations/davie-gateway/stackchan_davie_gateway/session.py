from __future__ import annotations

import asyncio
import json
import logging
import re
import time
import uuid
from typing import Any, Callable, Protocol

from .audio import (
    EndpointResult,
    OpusCodec,
    PcmEndpointDetector,
    iter_pcm_frames,
    pcm_to_wav,
    wav_to_pcm_async,
)
from .capabilities import DeviceAction, capability_reply, parse_device_action
from .clients import (
    DavieClient,
    DavieReply,
    MediaClient,
    SpokenSentenceBuffer,
    TranscriptionResult,
    sentence_segments,
    spoken_text,
)
from .config import Settings
from .protocol import (
    ClientHello,
    ProtocolError,
    pack_audio_frame,
    parse_client_hello,
    parse_json_message,
    server_hello,
    unpack_audio_frame,
)
from .reader import ReaderState
from .version import __version__


LOGGER = logging.getLogger(__name__)

VISUAL_REQUEST_PATTERN = re.compile(
    r"(?:what (?:do|can) you see|look at (?:this|that)|can you see|what is this|read this|"
    r"take (?:a )?(?:photo|picture)|camera|\u4f60\u770b\u5230|\u5e2e\u6211\u770b|\u770b\u770b|\u8fd9\u662f\u4ec0\u4e48|\u8bfb\u4e00\u4e0b|\u6444\u50cf\u5934)",
    re.IGNORECASE,
)

HEAD_POSITIONS = {
    "left": {"yaw": -35, "pitch": 0, "speed": 180},
    "right": {"yaw": 35, "pitch": 0, "speed": 180},
    "up": {"yaw": 0, "pitch": 25, "speed": 180},
    "center": {"yaw": 0, "pitch": 0, "speed": 180},
}
LED_COLORS = {
    "red": {"red": 168, "green": 0, "blue": 0},
    "green": {"red": 0, "green": 168, "blue": 0},
    "blue": {"red": 0, "green": 0, "blue": 168},
    "white": {"red": 100, "green": 100, "blue": 100},
    "off": {"red": 0, "green": 0, "blue": 0},
}


class SessionTransport(Protocol):
    async def send_json(self, payload: dict[str, Any]) -> None: ...

    async def send_bytes(self, payload: bytes) -> None: ...

    async def close(self, code: int = 1000, reason: str | None = None) -> None: ...


class StackChanSession:
    def __init__(
        self,
        *,
        transport: SessionTransport,
        settings: Settings,
        media: MediaClient,
        davie: DavieClient,
        device_id: str,
        client_id: str,
        codec_factory: Callable[[int, int, int], OpusCodec] = OpusCodec,
        reader: ReaderState | None = None,
    ):
        self.transport = transport
        self.settings = settings
        self.media = media
        self.davie = davie
        self.device_id = device_id or "unknown-device"
        self.client_id = client_id or "unknown-client"
        self.reader = reader or ReaderState(device_id=self.device_id)
        self.session_id = f"stackchan-{uuid.uuid4().hex}"
        self.davie_session_id: str | None = None
        self.hello: ClientHello | None = None
        self.codec: OpusCodec | None = None
        self.codec_factory = codec_factory
        self.endpoint = self._new_endpoint()
        self.listening = False
        self.listen_mode = "auto"
        self.speaking = False
        self.generation_id = 0
        self.response_task: asyncio.Task | None = None
        self.response_lock = asyncio.Lock()
        self.closed = False
        self.last_transcript = ""
        self.last_response = ""
        self.last_error = ""
        self.audio_frames_received = 0
        self.audio_frames_sent = 0
        self.interrupt_count = 0
        self.turn_count = 0
        self.accepted_turn_count = 0
        self.empty_transcript_count = 0
        self.consecutive_empty_transcript_count = 0
        self.rejected_transcript_count = 0
        self.dropped_turn_count = 0
        self.last_rejected_transcript = ""
        self.last_transcription_quality: dict[str, Any] = {}
        self.last_turn_timing: dict[str, Any] = {}
        self.barge_in_candidate = False
        self.barge_in_candidate_count = 0
        self.barge_in_confirmed_count = 0
        self.barge_in_suppressed_count = 0
        self.last_barge_in_decision = ""
        self.last_barge_in_at: float | None = None
        self.mcp_tools: dict[str, dict[str, Any]] = {}
        self.mcp_initialized = False
        self._mcp_request_id = 0
        self._mcp_pending: dict[int, str] = {}
        self._mcp_waiters: dict[int, asyncio.Future[dict[str, Any]]] = {}
        self._reader_checkpoint_task: asyncio.Task | None = None
        self._pending_reader_checkpoint: dict[str, Any] | None = None
        self.reader_checkpoint_mirror_count = 0
        self.reader_checkpoint_failure_count = 0
        self.last_reader_checkpoint_error = ""
        self.connected_at = time.time()
        self.state = "connecting"
        self.state_changed_at = self.connected_at
        self.last_activity_at = self.connected_at
        self.last_activity_reason = "connected"
        self.close_reason = ""
        self.idle_timeout_count = 0
        self.state_transition_count = 0
        self._last_activity_monotonic = time.monotonic()
        self._inactivity_task: asyncio.Task | None = None

    def _new_endpoint(self) -> PcmEndpointDetector:
        return PcmEndpointDetector(
            frame_duration_ms=self.settings.frame_duration_ms,
            silence_ms=self.settings.endpoint_silence_ms,
            min_speech_ms=self.settings.endpoint_min_speech_ms,
            max_turn_ms=self.settings.endpoint_max_turn_ms,
            min_rms=self.settings.endpoint_min_rms,
        )

    async def handle_text(self, raw: str) -> None:
        self._ensure_open()
        payload = parse_json_message(raw)
        message_type = payload["type"]
        if message_type == "hello":
            await self._handle_hello(payload)
            return
        if self.hello is None:
            raise ProtocolError("hello must be completed first")
        if message_type == "listen":
            await self._handle_listen(payload)
        elif message_type == "abort":
            await self.cancel_response(reason=str(payload.get("reason") or "device_abort"))
        elif message_type == "mcp":
            await self._handle_mcp(payload)

    async def _handle_hello(self, payload: dict[str, Any]) -> None:
        if self.hello is not None:
            raise ProtocolError("duplicate hello")
        self.hello = parse_client_hello(payload)
        self.codec = self.codec_factory(
            self.hello.sample_rate,
            self.settings.output_sample_rate,
            self.hello.frame_duration_ms,
        )
        self.endpoint = self._new_endpoint()
        await self.transport.send_json(
            server_hello(
                self.session_id,
                sample_rate=self.settings.output_sample_rate,
                frame_duration_ms=self.settings.frame_duration_ms,
            )
        )
        self._mark_activity("hello")
        self._set_state("ready")
        self._start_inactivity_watchdog()
        if self.hello.supports_mcp:
            await self._send_mcp_request(
                "initialize",
                {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {
                        "vision": {
                            "url": self.settings.vision_explain_url,
                            "token": self.settings.device_token,
                        }
                    },
                    "clientInfo": {"name": "stackchan-davie-gateway", "version": __version__},
                },
                purpose="initialize",
            )

    async def _handle_listen(self, payload: dict[str, Any]) -> None:
        state = str(payload.get("state") or "")
        if state in {"start", "detect"}:
            self.listen_mode = str(payload.get("mode") or self.listen_mode)
            self.listening = True
            self.endpoint.reset()
            self._clear_barge_in_candidate()
            self._mark_activity("listen_started")
            self._set_state("listening")
        elif state == "stop":
            self.listening = False
            result = self.endpoint.flush_result()
            if result.complete_pcm:
                if self._response_in_flight():
                    await self._confirm_barge_in("completed_manual_turn")
                await self._schedule_turn(result.complete_pcm, result)
            elif not self.closed:
                self._set_state("ready")

    async def _handle_mcp(self, payload: dict[str, Any]) -> None:
        message = payload.get("payload")
        if not isinstance(message, dict):
            return
        response_id = message.get("id")
        if not isinstance(response_id, int):
            return
        purpose = self._mcp_pending.pop(response_id, "")
        waiter = self._mcp_waiters.pop(response_id, None)
        if waiter and not waiter.done():
            waiter.set_result(message)
            return
        if "error" in message:
            self.last_error = f"mcp_{purpose or 'request'}_failed"
            return
        result = message.get("result")
        if not isinstance(result, dict):
            return
        if purpose == "initialize":
            self.mcp_initialized = True
            await self._request_mcp_tools("")
        elif purpose == "tools/list":
            tools = result.get("tools")
            if isinstance(tools, list):
                for tool in tools:
                    if isinstance(tool, dict) and isinstance(tool.get("name"), str):
                        self.mcp_tools[tool["name"]] = tool
            next_cursor = result.get("nextCursor")
            if isinstance(next_cursor, str) and next_cursor:
                await self._request_mcp_tools(next_cursor)

    async def _send_mcp_request(
        self,
        method: str,
        params: dict[str, Any],
        *,
        purpose: str,
        waiter: asyncio.Future[dict[str, Any]] | None = None,
    ) -> int:
        self._mcp_request_id += 1
        request_id = self._mcp_request_id
        self._mcp_pending[request_id] = purpose
        if waiter is not None:
            self._mcp_waiters[request_id] = waiter
        await self.transport.send_json(
            {
                "session_id": self.session_id,
                "type": "mcp",
                "payload": {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "method": method,
                    "params": params,
                },
            }
        )
        return request_id

    async def _request_mcp_tools(self, cursor: str) -> None:
        await self._send_mcp_request(
            "tools/list",
            {"cursor": cursor, "withUserTools": False},
            purpose="tools/list",
        )

    async def call_tool(
        self,
        name: str,
        arguments: dict[str, Any] | None = None,
        *,
        timeout: float = 15.0,
    ) -> dict[str, Any]:
        self._ensure_open()
        if name not in self.mcp_tools:
            raise ProtocolError(f"device tool is unavailable: {name}")
        loop = asyncio.get_running_loop()
        waiter: asyncio.Future[dict[str, Any]] = loop.create_future()
        request_id = await self._send_mcp_request(
            "tools/call",
            {"name": name, "arguments": arguments or {}},
            purpose="tools/call",
            waiter=waiter,
        )
        try:
            response = await asyncio.wait_for(waiter, timeout=timeout)
        except (asyncio.CancelledError, TimeoutError):
            self._mcp_pending.pop(request_id, None)
            self._mcp_waiters.pop(request_id, None)
            if not waiter.done():
                waiter.cancel()
            raise
        if "error" in response:
            raise ProtocolError("device tool call failed")
        result = response.get("result")
        return result if isinstance(result, dict) else {"value": result}

    async def handle_binary(self, raw: bytes) -> None:
        self._ensure_open()
        if self.hello is None or self.codec is None:
            raise ProtocolError("audio received before hello")
        packet, _timestamp = unpack_audio_frame(raw, self.hello.version)
        pcm = self.codec.decode(packet)
        self.audio_frames_received += 1
        result = self.endpoint.feed(pcm)
        if result.speech_started:
            self._mark_activity("speech_started")
            self._set_state("listening")
            if self._response_in_flight():
                self.barge_in_candidate = True
                self.barge_in_candidate_count += 1
                self.last_barge_in_decision = "possible_speech"
        if self.barge_in_candidate:
            if not self._response_in_flight():
                self._clear_barge_in_candidate("response_finished_before_confirmation")
            elif (
                self.endpoint.snapshot()["voiced_ms"]
                >= self.settings.barge_in_confirmation_ms
            ):
                await self._confirm_barge_in("confirmed_speech")
        if result.speech_abandoned:
            self._clear_barge_in_candidate("insufficient_speech")
            if not self.closed:
                if self.speaking:
                    self._set_state("speaking")
                elif self._response_in_flight():
                    self._set_state("thinking")
                else:
                    self._set_state("listening")
        if result.complete_pcm:
            if self._response_in_flight():
                await self._confirm_barge_in("completed_user_turn")
            self._clear_barge_in_candidate()
            await self._schedule_turn(result.complete_pcm, result)

    async def _schedule_turn(
        self, pcm: bytes, evidence: EndpointResult | None = None
    ) -> None:
        async with self.response_lock:
            if self.closed or self._response_in_flight():
                self.dropped_turn_count += 1
                self.last_error = "turn_dropped_response_in_flight"
                return
            self.response_task = asyncio.create_task(self._process_turn(pcm, evidence))

    def _response_in_flight(self) -> bool:
        return bool(self.response_task and not self.response_task.done())

    def _ensure_open(self) -> None:
        if self.closed:
            raise ProtocolError("session is closed")

    async def _cancel_response_task_locked(self) -> None:
        task = self.response_task
        if not task or task.done() or task is asyncio.current_task():
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        finally:
            if self.response_task is task:
                self.response_task = None

    async def _process_turn(
        self, pcm: bytes, evidence: EndpointResult | None = None
    ) -> None:
        self.turn_count += 1
        self.generation_id += 1
        generation = self.generation_id
        turn_started_monotonic = time.monotonic()
        timing = {
            "generation_id": generation,
            "started_at": time.time(),
            "outcome": "in_progress",
            "input_audio_ms": (
                evidence.captured_ms
                if evidence and evidence.captured_ms
                else self._pcm_duration_ms(pcm)
            ),
            "voiced_audio_ms": evidence.voiced_ms if evidence else None,
            "asr_ms": None,
            "asr_provider_ms": None,
            "first_text_ms": None,
            "llm_ms": None,
            "response_ready_ms": None,
            "tts_synthesis_ms": 0.0,
            "tts_sentence_count": 0,
            "tts_first_sentence_ms": None,
            "tts_max_sentence_ms": 0.0,
            "first_audio_ms": None,
            "streamed_audio_ms": 0,
            "first_text_to_first_audio_ms": None,
            "post_first_audio_gap_ms": None,
            "total_ms": None,
        }
        self.last_turn_timing = timing
        self._set_state("transcribing")
        try:
            asr_started = time.monotonic()
            try:
                transcription = await self.media.transcribe(
                    pcm_to_wav(pcm, self.hello.sample_rate if self.hello else self.settings.input_sample_rate),
                    hotwords=["Davie", "StackChan"],
                )
            finally:
                self._update_turn_timing(
                    timing,
                    asr_ms=self._elapsed_ms(asr_started),
                )
            if generation != self.generation_id:
                self._finish_turn_timing(
                    timing,
                    turn_started_monotonic,
                    outcome="superseded",
                )
                return
            if isinstance(transcription, str):
                transcription = TranscriptionResult(transcript=transcription)
            self._update_turn_timing(
                timing,
                asr_provider_ms=(
                    round(transcription.elapsed_seconds * 1000, 3)
                    if transcription.elapsed_seconds is not None
                    else None
                ),
            )
            transcript = transcription.transcript.strip()
            quality = self._assess_transcription(transcript, pcm, evidence)
            self.last_transcription_quality = {
                **quality,
                "model": transcription.model,
                "language": transcription.language,
                "ctc_available": bool(transcription.ctc_text),
                "elapsed_seconds": transcription.elapsed_seconds,
                "inference_seconds": transcription.inference_seconds,
            }
            if not transcript:
                self.empty_transcript_count += 1
                self.consecutive_empty_transcript_count += 1
                self.rejected_transcript_count += 1
                self.last_error = "asr_empty_transcript"
                self._set_state("listening")
                # Realtime audio can contain a wake chime tail or a short burst
                # of ambient noise. The first empty turn after wake is not a
                # user error: keep Listening so the person can start naturally.
                # Repeated empty turns in non-realtime mode still get feedback.
                if (
                    self.listen_mode != "realtime"
                    and self.consecutive_empty_transcript_count > 1
                ):
                    await self.transport.send_json(
                        {
                            "session_id": self.session_id,
                            "type": "alert",
                            "status": "Listening",
                            "message": "I did not catch that. Please try again.",
                            "emotion": "neutral",
                        }
                    )
                self._finish_turn_timing(
                    timing,
                    turn_started_monotonic,
                    outcome="empty_transcript",
                )
                return
            self.consecutive_empty_transcript_count = 0
            if not quality["accepted"]:
                self.rejected_transcript_count += 1
                self.last_rejected_transcript = transcript[:240]
                self.last_error = f"asr_rejected_{quality['reason']}"
                self._set_state("listening")
                self._finish_turn_timing(
                    timing,
                    turn_started_monotonic,
                    outcome="rejected_transcript",
                )
                return
            self.last_transcript = transcript
            self.accepted_turn_count += 1
            self.last_error = ""
            self._mark_activity("accepted_transcript")
            await self.transport.send_json(
                {"session_id": self.session_id, "type": "stt", "text": transcript}
            )
            action = parse_device_action(transcript)
            if action and await self._handle_device_action(
                action,
                generation,
                timing=timing,
                turn_started_monotonic=turn_started_monotonic,
            ):
                self._finish_turn_timing(
                    timing,
                    turn_started_monotonic,
                    outcome="device_action",
                )
                return
            self._set_state("thinking")
            llm_started = time.monotonic()
            visual_reply = await self._visual_reply(transcript)
            if visual_reply:
                try:
                    reply = visual_reply
                finally:
                    self._update_turn_timing(
                        timing,
                        llm_ms=self._elapsed_ms(llm_started),
                    )
                if generation != self.generation_id:
                    self._finish_turn_timing(
                        timing,
                        turn_started_monotonic,
                        outcome="superseded",
                    )
                    return
                response_text = spoken_text(
                    reply.text,
                    max_chars=self.settings.max_spoken_chars,
                    max_sentences=self.settings.max_spoken_sentences,
                )
                self._update_turn_timing(
                    timing,
                    first_text_ms=self._elapsed_ms(turn_started_monotonic),
                    response_ready_ms=self._elapsed_ms(turn_started_monotonic),
                )
                self.last_response = response_text
                await self._speak(
                    response_text,
                    generation,
                    timing=timing,
                    turn_started_monotonic=turn_started_monotonic,
                )
            elif callable(getattr(self.davie, "stream_chat", None)):
                response_text, reply = await self._stream_davie_and_speak(
                    transcript,
                    generation,
                    timing=timing,
                    turn_started_monotonic=turn_started_monotonic,
                    llm_started_monotonic=llm_started,
                )
            else:
                try:
                    reply = await self.davie.chat(
                        transcript,
                        device_id=self.device_id,
                        session_id=self.davie_session_id,
                    )
                finally:
                    self._update_turn_timing(
                        timing,
                        llm_ms=self._elapsed_ms(llm_started),
                    )
                if generation != self.generation_id:
                    self._finish_turn_timing(
                        timing,
                        turn_started_monotonic,
                        outcome="superseded",
                    )
                    return
                response_text = spoken_text(
                    reply.text,
                    max_chars=self.settings.max_spoken_chars,
                    max_sentences=self.settings.max_spoken_sentences,
                )
                self._update_turn_timing(
                    timing,
                    first_text_ms=self._elapsed_ms(turn_started_monotonic),
                    response_ready_ms=self._elapsed_ms(turn_started_monotonic),
                )
                self.last_response = response_text
                await self._speak(
                    response_text,
                    generation,
                    timing=timing,
                    turn_started_monotonic=turn_started_monotonic,
                )
            if generation != self.generation_id:
                self._finish_turn_timing(
                    timing,
                    turn_started_monotonic,
                    outcome="superseded",
                )
                return
            self.davie_session_id = reply.session_id or self.davie_session_id
            self.last_response = response_text
            if generation == self.generation_id:
                self._finish_turn_timing(
                    timing,
                    turn_started_monotonic,
                    outcome="completed",
                )
            else:
                self._finish_turn_timing(
                    timing,
                    turn_started_monotonic,
                    outcome="superseded",
                )
        except asyncio.CancelledError:
            self._finish_turn_timing(
                timing,
                turn_started_monotonic,
                outcome="cancelled",
            )
            raise
        except Exception as exc:
            LOGGER.exception("StackChan turn failed")
            self.last_error = type(exc).__name__
            self._finish_turn_timing(
                timing,
                turn_started_monotonic,
                outcome="error",
                error_type=type(exc).__name__,
            )
            if generation == self.generation_id:
                self.speaking = False
                await self.transport.send_json(
                    {
                        "session_id": self.session_id,
                        "type": "alert",
                        "status": "Davie is unavailable",
                        "message": "Please try again in a moment.",
                        "emotion": "sad",
                    }
                )
        finally:
            if timing.get("outcome") == "in_progress":
                self._finish_turn_timing(
                    timing,
                    turn_started_monotonic,
                    outcome=(
                        "superseded"
                        if generation != self.generation_id
                        else "error"
                    ),
                )
            if generation == self.generation_id and not self.closed and not self.speaking:
                self._set_state("listening" if self.listening else "ready")

    async def _stream_davie_and_speak(
        self,
        transcript: str,
        generation: int,
        *,
        timing: dict[str, Any],
        turn_started_monotonic: float,
        llm_started_monotonic: float,
    ) -> tuple[str, DavieReply]:
        sentence_buffer = SpokenSentenceBuffer(
            max_chars=self.settings.max_spoken_chars,
            max_sentences=self.settings.max_spoken_sentences,
        )
        sentence_queue: asyncio.Queue[str | None] = asyncio.Queue()
        speaking_task = asyncio.create_task(
            self._speak_queue(
                sentence_queue,
                generation,
                timing=timing,
                turn_started_monotonic=turn_started_monotonic,
            )
        )
        queue_closed = False

        async def on_delta(delta: str) -> None:
            if generation != self.generation_id:
                raise asyncio.CancelledError
            if delta.strip() and timing.get("first_text_ms") is None:
                self._update_turn_timing(
                    timing,
                    first_text_ms=self._elapsed_ms(turn_started_monotonic),
                )
            for sentence in sentence_buffer.feed(delta):
                self.last_response = sentence_buffer.text
                await sentence_queue.put(sentence)

        try:
            reply = await self.davie.stream_chat(
                transcript,
                device_id=self.device_id,
                session_id=self.davie_session_id,
                on_delta=on_delta,
            )
            for sentence in sentence_buffer.finish():
                if timing.get("first_text_ms") is None:
                    self._update_turn_timing(
                        timing,
                        first_text_ms=self._elapsed_ms(turn_started_monotonic),
                    )
                self.last_response = sentence_buffer.text
                await sentence_queue.put(sentence)
            self._update_turn_timing(
                timing,
                llm_ms=self._elapsed_ms(llm_started_monotonic),
                response_ready_ms=self._elapsed_ms(turn_started_monotonic),
            )
            await sentence_queue.put(None)
            queue_closed = True
            await speaking_task
            response_text = sentence_buffer.text
            if not response_text:
                raise RuntimeError("Davie returned no speakable streamed response")
            return response_text, reply
        finally:
            if not queue_closed:
                await sentence_queue.put(None)
            if not speaking_task.done():
                speaking_task.cancel()
            try:
                await speaking_task
            except asyncio.CancelledError:
                pass

    async def _speak_queue(
        self,
        sentence_queue: asyncio.Queue[str | None],
        generation: int,
        *,
        timing: dict[str, Any],
        turn_started_monotonic: float,
    ) -> None:
        first_sentence = await sentence_queue.get()
        if first_sentence is None or generation != self.generation_id:
            return
        self.speaking = True
        self._set_state("speaking")
        await self.transport.send_json(
            {"session_id": self.session_id, "type": "llm", "emotion": "happy"}
        )
        await self.transport.send_json(
            {"session_id": self.session_id, "type": "tts", "state": "start"}
        )
        metrics = {
            "tts_synthesis_ms": 0.0,
            "tts_sentence_count": 0,
            "tts_first_sentence_ms": None,
            "tts_max_sentence_ms": 0.0,
            "streamed_audio_ms": 0,
        }
        audio_queue: asyncio.Queue[Any] = asyncio.Queue(maxsize=1)

        async def synthesize_ahead() -> None:
            sentence: str | None = first_sentence
            try:
                while sentence is not None:
                    if generation != self.generation_id:
                        break
                    pcm = await self._synthesize_sentence(
                        sentence,
                        timing=timing,
                        metrics=metrics,
                    )
                    if generation != self.generation_id:
                        break
                    await audio_queue.put((sentence, pcm))
                    sentence = await sentence_queue.get()
                await audio_queue.put(None)
            except Exception as exc:
                await audio_queue.put(exc)

        synthesis_task = asyncio.create_task(synthesize_ahead())
        try:
            while True:
                prepared = await audio_queue.get()
                if prepared is None:
                    break
                if isinstance(prepared, Exception):
                    raise prepared
                sentence, pcm = prepared
                await self._send_prepared_sentence(
                    sentence,
                    pcm,
                    generation,
                    timing=timing,
                    turn_started_monotonic=turn_started_monotonic,
                    metrics=metrics,
                )
        finally:
            if not synthesis_task.done():
                synthesis_task.cancel()
            try:
                await synthesis_task
            except asyncio.CancelledError:
                pass
            self._update_turn_timing(timing, **metrics)
            if generation == self.generation_id:
                self.speaking = False
                await self.transport.send_json(
                    {"session_id": self.session_id, "type": "tts", "state": "stop"}
                )
                self._mark_activity("response_completed")
                if not self.closed:
                    self._set_state("listening" if self.listening else "ready")

    def _pcm_duration_ms(self, pcm: bytes) -> int:
        sample_rate = (
            self.hello.sample_rate
            if self.hello
            else self.settings.input_sample_rate
        )
        return round((len(pcm) / 2 / max(sample_rate, 1)) * 1000)

    @staticmethod
    def _elapsed_ms(started_monotonic: float) -> float:
        return round((time.monotonic() - started_monotonic) * 1000, 3)

    def _update_turn_timing(
        self,
        timing: dict[str, Any],
        **values: Any,
    ) -> None:
        if self.last_turn_timing is timing:
            timing.update(values)

    def _finish_turn_timing(
        self,
        timing: dict[str, Any],
        turn_started_monotonic: float,
        *,
        outcome: str,
        **values: Any,
    ) -> None:
        if self.last_turn_timing is not timing:
            return
        timing.update(
            {
                "outcome": outcome,
                "completed_at": time.time(),
                "total_ms": self._elapsed_ms(turn_started_monotonic),
                **values,
            }
        )
        first_text_ms = timing.get("first_text_ms")
        first_audio_ms = timing.get("first_audio_ms")
        streamed_audio_ms = timing.get("streamed_audio_ms")
        total_ms = timing.get("total_ms")
        if first_text_ms is not None and first_audio_ms is not None:
            timing["first_text_to_first_audio_ms"] = round(
                max(0.0, float(first_audio_ms) - float(first_text_ms)),
                3,
            )
        if (
            first_audio_ms is not None
            and streamed_audio_ms is not None
            and total_ms is not None
        ):
            timing["post_first_audio_gap_ms"] = round(
                max(
                    0.0,
                    float(total_ms)
                    - float(first_audio_ms)
                    - float(streamed_audio_ms),
                ),
                3,
            )

    def _assess_transcription(
        self,
        transcript: str,
        pcm: bytes,
        evidence: EndpointResult | None,
    ) -> dict[str, Any]:
        sample_rate = (
            self.hello.sample_rate
            if self.hello
            else self.settings.input_sample_rate
        )
        duration_ms = (
            evidence.captured_ms
            if evidence and evidence.captured_ms
            else int((len(pcm) / 2 / max(sample_rate, 1)) * 1000)
        )
        normalized = transcript.lower().strip()
        tokens = re.findall(
            r"[a-z]+(?:'[a-z]+)?|\d+|[\u3400-\u9fff]+",
            normalized,
        )
        wake_or_name_tokens = {
            "davie",
            "davy",
            "davey",
            "jason",
            "ingie",
            "angie",
            "stackchan",
            "stack",
            "chan",
        }
        filler_tokens = {"ah", "er", "erm", "hm", "hmm", "uh", "um"}
        accepted = True
        reason = "accepted"
        if not transcript.strip():
            accepted = False
            reason = "empty"
        elif tokens and all(token in wake_or_name_tokens for token in tokens):
            accepted = False
            reason = "wake_or_name_only"
        elif tokens and all(token in filler_tokens for token in tokens):
            accepted = False
            reason = "filler_only"
        else:
            duration_seconds = max(duration_ms / 1000, 0.1)
            allowed_words = max(
                12,
                int(
                    duration_seconds
                    * self.settings.max_transcript_words_per_second
                ),
            )
            if len(tokens) > allowed_words:
                accepted = False
                reason = "implausible_transcript_rate"
        return {
            "accepted": accepted,
            "reason": reason,
            "duration_ms": duration_ms,
            "token_count": len(tokens),
            "words_per_second": round(
                len(tokens) / max(duration_ms / 1000, 0.1), 2
            ),
            "voiced_ms": evidence.voiced_ms if evidence else None,
            "peak_rms": evidence.peak_rms if evidence else None,
            "mean_rms": evidence.mean_rms if evidence else None,
        }

    def _clear_barge_in_candidate(self, suppressed_reason: str = "") -> None:
        if self.barge_in_candidate and suppressed_reason:
            self.barge_in_suppressed_count += 1
            self.last_barge_in_decision = suppressed_reason
        self.barge_in_candidate = False

    async def _confirm_barge_in(self, reason: str) -> None:
        if not self._response_in_flight():
            self._clear_barge_in_candidate("response_finished_before_confirmation")
            return
        if self.reader.state == "playing":
            self.reader.pause()
        self.barge_in_confirmed_count += 1
        self.last_barge_in_decision = reason
        self.last_barge_in_at = time.time()
        self.barge_in_candidate = False
        await self.cancel_response(reason="barge_in")
        self.listening = True

    async def _visual_reply(self, transcript: str):
        if "self.camera.take_photo" not in self.mcp_tools or not VISUAL_REQUEST_PATTERN.search(transcript):
            return None
        try:
            text = await self.see(transcript, speak=False)
            if not text:
                return None
            return DavieReply(text=text, session_id=self.davie_session_id)
        except (ProtocolError, TimeoutError):
            LOGGER.warning("StackChan camera tool did not return a usable result", exc_info=True)
            return None

    async def _handle_device_action(
        self,
        action: DeviceAction,
        generation: int,
        *,
        timing: dict[str, Any] | None = None,
        turn_started_monotonic: float | None = None,
    ) -> bool:
        if action.kind == "session_sleep":
            text = "晚安，需要我时再叫 Davie。" if action.chinese else "Goodbye. Say Davie when you need me again."
            await self._speak(
                text,
                generation,
                timing=timing,
                turn_started_monotonic=turn_started_monotonic,
            )
            await self.sleep(reason="voice_sleep", announce=False)
            return True
        if action.kind == "help":
            await self._speak(
                capability_reply(chinese=action.chinese),
                generation,
                timing=timing,
                turn_started_monotonic=turn_started_monotonic,
            )
            return True
        if action.kind == "reader_pause":
            changed = self.reader.pause()
            self._schedule_reader_checkpoint()
            text = "朗读已暂停。" if action.chinese else "Reading is paused."
            if not changed and not self.reader.segments:
                text = "还没有加载阅读内容。" if action.chinese else "No reading is loaded yet."
            await self._speak(
                text,
                generation,
                timing=timing,
                turn_started_monotonic=turn_started_monotonic,
            )
            return True
        if action.kind == "reader_resume":
            if not self.reader.resume():
                text = "没有可以继续的阅读内容。" if action.chinese else "There is no reading to continue."
                await self._speak(
                    text,
                    generation,
                    timing=timing,
                    turn_started_monotonic=turn_started_monotonic,
                )
                return True
            self._schedule_reader_checkpoint()
            await self._run_reader(generation)
            return True
        if action.kind == "reader_stop":
            changed = self.reader.stop()
            self._schedule_reader_checkpoint()
            text = "朗读已停止，下次会从开头开始。" if action.chinese else "Reading stopped. It will restart from the beginning."
            if not changed:
                text = "还没有加载阅读内容。" if action.chinese else "No reading is loaded yet."
            await self._speak(
                text,
                generation,
                timing=timing,
                turn_started_monotonic=turn_started_monotonic,
            )
            return True
        if action.kind == "reader_status":
            status = self.reader.status()
            if not status["segment_count"]:
                text = "还没有加载阅读内容。" if action.chinese else "No reading is loaded yet."
            elif action.chinese:
                text = f"正在读《{status['title']}》，进度约百分之 {status['progress_percent']}。"
            else:
                text = f"We are reading {status['title']}, at about {status['progress_percent']} percent."
            await self._speak(
                text,
                generation,
                timing=timing,
                turn_started_monotonic=turn_started_monotonic,
            )
            return True
        if action.kind == "storage_note_save":
            text = str(action.arguments.get("text") or "").strip()
            if len(text.encode("utf-8")) > 480:
                reply = (
                    "这条笔记太长了，请缩短到大约两三句话。"
                    if action.chinese
                    else "That note is too long. Please keep it to two or three short sentences."
                )
                await self._speak(
                    reply,
                    generation,
                    timing=timing,
                    turn_started_monotonic=turn_started_monotonic,
                )
                return True
            payload = await self._call_storage_json(
                "self.storage.notes.save",
                {"text": text},
            )
            if payload.get("ok") is True:
                reply = "已经记在 TF 卡里了。" if action.chinese else "I saved that on the TF card."
            else:
                reply = (
                    "TF 卡笔记现在不可用，但我们的对话仍可继续。"
                    if action.chinese
                    else "TF card notes are unavailable, but our conversation can continue."
                )
            await self._speak(
                reply,
                generation,
                timing=timing,
                turn_started_monotonic=turn_started_monotonic,
            )
            return True
        if action.kind == "storage_notes_recent":
            payload = await self._call_storage_json(
                "self.storage.notes.recent",
                {"limit": int(action.arguments.get("limit") or 3)},
            )
            notes = payload.get("notes")
            note_texts = [
                str(item.get("text") or "").strip()[:160]
                for item in notes
                if isinstance(item, dict) and str(item.get("text") or "").strip()
            ] if isinstance(notes, list) else []
            if not note_texts:
                reply = "TF 卡里还没有笔记。" if action.chinese else "There are no notes on the TF card yet."
            elif action.chinese:
                reply = "最近的笔记是：" + "；".join(note_texts) + "。"
            else:
                reply = "Your latest notes are: " + "; ".join(note_texts) + "."
            await self._speak(
                reply,
                generation,
                timing=timing,
                turn_started_monotonic=turn_started_monotonic,
            )
            return True
        if action.kind == "storage_status":
            payload = await self._call_storage_json("self.storage.get_status", {})
            if payload.get("mounted") is True and payload.get("writable") is True:
                free_gib = round(float(payload.get("free_bytes") or 0) / (1024**3), 1)
                count = int(payload.get("note_count") or 0)
                reply = (
                    f"TF 卡工作正常，剩余约 {free_gib} GB，保存了 {count} 条笔记。"
                    if action.chinese
                    else f"The TF card is ready, with about {free_gib} gigabytes free and {count} saved notes."
                )
            else:
                reply = (
                    "TF 卡目前不可用，但对话、视觉和朗读服务仍可继续。"
                    if action.chinese
                    else "The TF card is unavailable, but conversation, vision, and reading still work."
                )
            await self._speak(
                reply,
                generation,
                timing=timing,
                turn_started_monotonic=turn_started_monotonic,
            )
            return True

        tool_name = ""
        arguments: dict[str, Any] = {}
        success_en = "Done."
        success_zh = "好了。"
        if action.kind == "reminder":
            tool_name = "self.robot.create_reminder"
            arguments = action.arguments
            success_en, success_zh = "Reminder set.", "提醒已设置。"
        elif action.kind == "volume":
            tool_name = "self.audio_speaker.set_volume"
            arguments = action.arguments
            success_en = f"Volume is set to {arguments['volume']}."
            success_zh = f"音量已调到 {arguments['volume']}。"
        elif action.kind == "head":
            tool_name = "self.robot.set_head_angles"
            arguments = HEAD_POSITIONS[action.arguments["direction"]]
            success_en, success_zh = "I moved my head.", "我已经转动头部。"
        elif action.kind == "led":
            tool_name = "self.robot.set_led_color"
            arguments = LED_COLORS[action.arguments["color"]]
            success_en, success_zh = "The onboard light is set.", "机身灯已经设置。"
        else:
            return False

        try:
            await self.call_tool(tool_name, arguments)
            text = success_zh if action.chinese else success_en
        except (ProtocolError, TimeoutError):
            LOGGER.warning("StackChan local action failed: %s", action.kind, exc_info=True)
            text = "这个设备功能目前不可用。" if action.chinese else "That device control is unavailable right now."
        await self._speak(
            text,
            generation,
            timing=timing,
            turn_started_monotonic=turn_started_monotonic,
        )
        return True

    async def _run_reader(self, generation: int) -> None:
        while generation == self.generation_id and self.reader.state == "playing":
            segment = self.reader.current()
            if segment is None:
                break
            status = self.reader.status()
            await self.transport.send_json(
                {
                    "session_id": self.session_id,
                    "type": "alert",
                    "status": "Reading",
                    "message": f"{status['title']} · {status['segment_number']}/{status['segment_count']}",
                    "emotion": "happy",
                }
            )
            self.last_response = segment
            await self._speak(segment, generation)
            if generation != self.generation_id or self.reader.state != "playing":
                return
            self.reader.advance()
            self._schedule_reader_checkpoint()
        if generation == self.generation_id and self.reader.state == "completed":
            self._schedule_reader_checkpoint()
            await self.transport.send_json(
                {
                    "session_id": self.session_id,
                    "type": "alert",
                    "status": "Reading complete",
                    "message": self.reader.title,
                    "emotion": "happy",
                }
            )

    async def see(self, question: str, *, speak: bool = True) -> str:
        if "self.camera.take_photo" not in self.mcp_tools:
            raise ProtocolError("device camera tool is unavailable")
        await self.transport.send_json(
            {
                "session_id": self.session_id,
                "type": "alert",
                "status": "Looking",
                "message": "Using the camera",
                "emotion": "neutral",
            }
        )
        result = await self.call_tool(
            "self.camera.take_photo",
            {"question": question},
            timeout=120.0,
        )
        text = self._extract_tool_text(result)
        if not text:
            raise ProtocolError("camera returned no explanation")
        self.last_response = text
        if speak:
            await self.say(text)
        return text

    async def _call_storage_json(
        self,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        if tool_name not in self.mcp_tools:
            return {"ok": False, "error": "storage_tool_unavailable"}
        try:
            result = await self.call_tool(tool_name, arguments, timeout=4.0)
        except (ProtocolError, TimeoutError):
            LOGGER.warning("StackChan storage tool failed: %s", tool_name, exc_info=True)
            return {"ok": False, "error": "storage_tool_failed"}
        return self._extract_tool_json(result)

    @staticmethod
    def _extract_tool_json(result: dict[str, Any]) -> dict[str, Any]:
        content = result.get("content")
        if not isinstance(content, list):
            return {}
        for item in content:
            if not isinstance(item, dict) or item.get("type") != "text":
                continue
            value = str(item.get("text") or "").strip()
            if not value:
                continue
            try:
                payload = json.loads(value)
            except json.JSONDecodeError:
                return {}
            return payload if isinstance(payload, dict) else {}
        return {}

    def _schedule_reader_checkpoint(self) -> None:
        if (
            self.closed
            or not self.reader.segments
            or "self.storage.reader.set_checkpoint" not in self.mcp_tools
        ):
            return
        status = self.reader.status()
        self._pending_reader_checkpoint = {
            "title": str(status["title"])[:192],
            "index": int(status["segment_index"]),
            "total": int(status["segment_count"]),
            "state": str(status["state"])[:32],
        }
        if self._reader_checkpoint_task is None or self._reader_checkpoint_task.done():
            self._reader_checkpoint_task = asyncio.create_task(self._flush_reader_checkpoint())

    async def _flush_reader_checkpoint(self) -> None:
        await asyncio.sleep(0.05)
        while self._pending_reader_checkpoint is not None and not self.closed:
            checkpoint = self._pending_reader_checkpoint
            self._pending_reader_checkpoint = None
            payload = await self._call_storage_json(
                "self.storage.reader.set_checkpoint",
                checkpoint,
            )
            if payload.get("ok") is True:
                self.reader_checkpoint_mirror_count += 1
                self.last_reader_checkpoint_error = ""
            else:
                self.reader_checkpoint_failure_count += 1
                self.last_reader_checkpoint_error = str(
                    payload.get("error") or "checkpoint_write_failed"
                )

    @staticmethod
    def _extract_tool_text(result: dict[str, Any]) -> str:
        content = result.get("content")
        if not isinstance(content, list):
            return ""
        for item in content:
            if not isinstance(item, dict) or item.get("type") != "text":
                continue
            value = str(item.get("text") or "").strip()
            if not value:
                continue
            try:
                payload = json.loads(value)
            except json.JSONDecodeError:
                return value
            if isinstance(payload, dict) and payload.get("success") is True:
                return str(payload.get("result") or "").strip()
        return ""

    async def _speak(
        self,
        text: str,
        generation: int,
        *,
        timing: dict[str, Any] | None = None,
        turn_started_monotonic: float | None = None,
    ) -> None:
        if not text:
            return
        self.last_response = text
        sentence_queue: asyncio.Queue[str | None] = asyncio.Queue()
        for sentence in sentence_segments(text):
            sentence_queue.put_nowait(sentence)
        sentence_queue.put_nowait(None)
        synthetic_timing = timing if timing is not None else {}
        await self._speak_queue(
            sentence_queue,
            generation,
            timing=synthetic_timing,
            turn_started_monotonic=(
                turn_started_monotonic
                if turn_started_monotonic is not None
                else time.monotonic()
            ),
        )

    async def _synthesize_sentence(
        self,
        sentence: str,
        *,
        timing: dict[str, Any] | None,
        metrics: dict[str, Any],
    ) -> bytes:
        synthesis_started = time.monotonic()
        try:
            wav_bytes = await self.media.synthesize(sentence)
            return await wav_to_pcm_async(
                wav_bytes,
                self.settings.output_sample_rate,
            )
        finally:
            sentence_ms = self._elapsed_ms(synthesis_started)
            metrics["tts_synthesis_ms"] = round(
                float(metrics["tts_synthesis_ms"])
                + sentence_ms,
                3,
            )
            metrics["tts_sentence_count"] = int(metrics["tts_sentence_count"]) + 1
            if metrics["tts_first_sentence_ms"] is None:
                metrics["tts_first_sentence_ms"] = sentence_ms
            metrics["tts_max_sentence_ms"] = max(
                float(metrics["tts_max_sentence_ms"]),
                sentence_ms,
            )
            if timing is not None:
                self._update_turn_timing(timing, **metrics)

    async def _send_prepared_sentence(
        self,
        sentence: str,
        pcm: bytes,
        generation: int,
        *,
        timing: dict[str, Any] | None,
        turn_started_monotonic: float | None,
        metrics: dict[str, Any],
    ) -> None:
        await self.transport.send_json(
            {
                "session_id": self.session_id,
                "type": "tts",
                "state": "sentence_start",
                "text": sentence,
            }
        )
        for frame in iter_pcm_frames(
            pcm,
            sample_rate=self.settings.output_sample_rate,
            frame_duration_ms=self.settings.frame_duration_ms,
        ):
            if generation != self.generation_id or self.codec is None:
                return
            encoded = self.codec.encode(frame)
            timestamp = self.audio_frames_sent * self.settings.frame_duration_ms
            await self.transport.send_bytes(
                pack_audio_frame(
                    encoded,
                    self.hello.version if self.hello else 1,
                    timestamp_ms=timestamp,
                )
            )
            self.audio_frames_sent += 1
            metrics["streamed_audio_ms"] = (
                int(metrics["streamed_audio_ms"])
                + self.settings.frame_duration_ms
            )
            if (
                timing is not None
                and turn_started_monotonic is not None
                and timing.get("first_audio_ms") is None
            ):
                self._update_turn_timing(
                    timing,
                    first_audio_ms=self._elapsed_ms(turn_started_monotonic),
                )
            await asyncio.sleep(self.settings.frame_duration_ms / 1000)

    async def say(self, text: str) -> None:
        async with self.response_lock:
            self._ensure_open()
            had_response = self.speaking or self._response_in_flight()
            if had_response:
                if self.reader.state == "playing":
                    self.reader.pause()
                self.generation_id += 1
                self.speaking = False
                await self._cancel_response_task_locked()
                self.interrupt_count += 1
                await self.transport.send_json(
                    {
                        "session_id": self.session_id,
                        "type": "tts",
                        "state": "stop",
                        "reason": "server_say_override",
                    }
                )
            self.generation_id += 1
            generation = self.generation_id
            self.response_task = asyncio.create_task(self._speak(text, generation))

    async def load_reader(self, *, title: str, text: str, autoplay: bool = False) -> dict[str, Any]:
        async with self.response_lock:
            self._ensure_open()
            if self.speaking or self._response_in_flight():
                if self.reader.state == "playing":
                    self.reader.pause()
                self.generation_id += 1
                self.speaking = False
                await self._cancel_response_task_locked()
                await self.transport.send_json(
                    {"session_id": self.session_id, "type": "tts", "state": "stop", "reason": "reader_load"}
                )
            self.reader.load(title, text)
            self._schedule_reader_checkpoint()
            if autoplay:
                self._start_reader_locked()
            return self.reader.status()

    async def reader_play(self) -> dict[str, Any]:
        async with self.response_lock:
            self._ensure_open()
            if self.hello is None or self.codec is None:
                raise ProtocolError("device audio session is not ready")
            if self.speaking or self._response_in_flight():
                if self.reader.state == "playing":
                    return self.reader.status()
                self.generation_id += 1
                self.speaking = False
                await self._cancel_response_task_locked()
                await self.transport.send_json(
                    {"session_id": self.session_id, "type": "tts", "state": "stop", "reason": "reader_play"}
                )
            if not self.reader.resume():
                raise ProtocolError("no resumable reading is loaded")
            self._schedule_reader_checkpoint()
            self._start_reader_locked(already_resumed=True)
            return self.reader.status()

    def _start_reader_locked(self, *, already_resumed: bool = False) -> None:
        if self.hello is None or self.codec is None:
            raise ProtocolError("device audio session is not ready")
        if not already_resumed and not self.reader.resume():
            raise ProtocolError("no resumable reading is loaded")
        self.generation_id += 1
        generation = self.generation_id
        self.response_task = asyncio.create_task(self._run_reader(generation))

    async def reader_pause(self) -> dict[str, Any]:
        async with self.response_lock:
            self._ensure_open()
            was_playing = self.reader.state == "playing"
            self.reader.pause()
            self._schedule_reader_checkpoint()
            if was_playing:
                self.generation_id += 1
                self.speaking = False
                await self._cancel_response_task_locked()
                self.interrupt_count += 1
                await self.transport.send_json(
                    {"session_id": self.session_id, "type": "tts", "state": "stop", "reason": "reader_pause"}
                )
            return self.reader.status()

    async def reader_stop(self) -> dict[str, Any]:
        async with self.response_lock:
            self._ensure_open()
            had_response = self.speaking or self._response_in_flight()
            self.reader.stop()
            self._schedule_reader_checkpoint()
            if had_response:
                self.generation_id += 1
                self.speaking = False
                await self._cancel_response_task_locked()
                self.interrupt_count += 1
                await self.transport.send_json(
                    {"session_id": self.session_id, "type": "tts", "state": "stop", "reason": "reader_stop"}
                )
            return self.reader.status()

    async def cancel_response(self, *, reason: str) -> None:
        async with self.response_lock:
            if self.closed:
                return
            self._clear_barge_in_candidate()
            had_response = self.speaking or self._response_in_flight()
            if self.reader.state == "playing":
                self.reader.pause()
            self.generation_id += 1
            self.speaking = False
            await self._cancel_response_task_locked()
            if had_response:
                self.interrupt_count += 1
                await self.transport.send_json(
                    {
                        "session_id": self.session_id,
                        "type": "tts",
                        "state": "stop",
                        "reason": reason,
                    }
                )

    def _set_state(self, state: str) -> None:
        if self.state == state:
            return
        self.state = state
        self.state_changed_at = time.time()
        self.state_transition_count += 1

    def _mark_activity(self, reason: str) -> None:
        self.last_activity_at = time.time()
        self._last_activity_monotonic = time.monotonic()
        self.last_activity_reason = reason

    def _start_inactivity_watchdog(self) -> None:
        if self.settings.session_idle_timeout_seconds <= 0 or self._inactivity_task:
            return
        self._inactivity_task = asyncio.create_task(self._inactivity_watchdog())

    async def _inactivity_watchdog(self) -> None:
        interval = max(
            0.05,
            min(
                self.settings.session_watchdog_interval_seconds,
                self.settings.session_idle_timeout_seconds / 4,
            ),
        )
        try:
            while not self.closed:
                await asyncio.sleep(interval)
                if self.speaking or self._response_in_flight() or self.reader.state == "playing":
                    continue
                idle_seconds = time.monotonic() - self._last_activity_monotonic
                if idle_seconds < self.settings.session_idle_timeout_seconds:
                    continue
                self.idle_timeout_count += 1
                await self.sleep(reason="inactivity_timeout")
                return
        except asyncio.CancelledError:
            raise

    async def sleep(self, *, reason: str, announce: bool = True) -> None:
        if self.closed:
            return
        self._set_state("sleeping")
        if announce:
            await self.transport.send_json(
                {
                    "session_id": self.session_id,
                    "type": "alert",
                    "status": "Sleeping",
                    "message": "Say Davie when you need me again.",
                    "emotion": "neutral",
                }
            )
        await self.close(close_transport=True, reason=reason)

    async def close(self, *, close_transport: bool = False, reason: str = "connection_closed") -> None:
        inactivity_task: asyncio.Task | None = None
        checkpoint_task: asyncio.Task | None = None
        async with self.response_lock:
            if self.closed:
                return
            self.closed = True
            self.close_reason = reason
            self._set_state("closed")
            self._clear_barge_in_candidate()
            if self.reader.state == "playing":
                self.reader.pause()
            self.generation_id += 1
            self.speaking = False
            await self._cancel_response_task_locked()
            if self.codec:
                self.codec.close()
                self.codec = None
            for waiter in self._mcp_waiters.values():
                if not waiter.done():
                    waiter.cancel()
            self._mcp_waiters.clear()
            self._mcp_pending.clear()
            inactivity_task = self._inactivity_task
            self._inactivity_task = None
            if inactivity_task and inactivity_task is not asyncio.current_task():
                inactivity_task.cancel()
            checkpoint_task = self._reader_checkpoint_task
            self._reader_checkpoint_task = None
            if checkpoint_task and checkpoint_task is not asyncio.current_task():
                checkpoint_task.cancel()
        if inactivity_task and inactivity_task is not asyncio.current_task():
            try:
                await inactivity_task
            except asyncio.CancelledError:
                pass
        if checkpoint_task and checkpoint_task is not asyncio.current_task():
            try:
                await checkpoint_task
            except asyncio.CancelledError:
                pass
        if close_transport:
            await self.transport.close(code=1000, reason=reason)

    def status(self) -> dict[str, Any]:
        return {
            "device_id": self.device_id,
            "client_id": self.client_id,
            "session_id": self.session_id,
            "connected_at": self.connected_at,
            "session_state": self.state,
            "state_changed_at": self.state_changed_at,
            "state_transition_count": self.state_transition_count,
            "last_activity_at": self.last_activity_at,
            "last_activity_reason": self.last_activity_reason,
            "inactivity_deadline_at": (
                self.last_activity_at + self.settings.session_idle_timeout_seconds
                if self.settings.session_idle_timeout_seconds > 0
                else None
            ),
            "idle_timeout_count": self.idle_timeout_count,
            "close_reason": self.close_reason,
            "handshake_complete": self.hello is not None,
            "listening": self.listening,
            "speaking": self.speaking,
            "listen_mode": self.listen_mode,
            "generation_id": self.generation_id,
            "turn_count": self.turn_count,
            "accepted_turn_count": self.accepted_turn_count,
            "empty_transcript_count": self.empty_transcript_count,
            "consecutive_empty_transcript_count": self.consecutive_empty_transcript_count,
            "rejected_transcript_count": self.rejected_transcript_count,
            "dropped_turn_count": self.dropped_turn_count,
            "interrupt_count": self.interrupt_count,
            "barge_in_candidate": self.barge_in_candidate,
            "barge_in_candidate_count": self.barge_in_candidate_count,
            "barge_in_confirmed_count": self.barge_in_confirmed_count,
            "barge_in_suppressed_count": self.barge_in_suppressed_count,
            "last_barge_in_decision": self.last_barge_in_decision,
            "last_barge_in_at": self.last_barge_in_at,
            "audio_frames_received": self.audio_frames_received,
            "audio_frames_sent": self.audio_frames_sent,
            "last_transcript": self.last_transcript,
            "last_rejected_transcript": self.last_rejected_transcript,
            "last_transcription_quality": self.last_transcription_quality,
            "last_turn_timing": dict(self.last_turn_timing),
            "last_response": self.last_response,
            "last_error": self.last_error,
            "closed": self.closed,
            "mcp_initialized": self.mcp_initialized,
            "mcp_tool_count": len(self.mcp_tools),
            "mcp_tools": sorted(self.mcp_tools),
            "endpoint": self.endpoint.snapshot(),
            "reader": self.reader.status(),
            "reader_checkpoint": {
                "mirror_count": self.reader_checkpoint_mirror_count,
                "failure_count": self.reader_checkpoint_failure_count,
                "last_error": self.last_reader_checkpoint_error,
                "pending": self._pending_reader_checkpoint is not None,
            },
        }
