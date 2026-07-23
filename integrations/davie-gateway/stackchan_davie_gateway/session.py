from __future__ import annotations

import asyncio
import json
import logging
import re
import time
import uuid
from typing import Any, Callable, Protocol

from .audio import OpusCodec, PcmEndpointDetector, iter_pcm_frames, pcm_to_wav, wav_to_pcm_async
from .capabilities import DeviceAction, capability_reply, parse_device_action
from .clients import DavieClient, DavieReply, MediaClient, sentence_segments, spoken_text
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
        self.empty_transcript_count = 0
        self.mcp_tools: dict[str, dict[str, Any]] = {}
        self.mcp_initialized = False
        self._mcp_request_id = 0
        self._mcp_pending: dict[int, str] = {}
        self._mcp_waiters: dict[int, asyncio.Future[dict[str, Any]]] = {}
        self.connected_at = time.time()

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
                    "clientInfo": {"name": "stackchan-davie-gateway", "version": "0.2.0"},
                },
                purpose="initialize",
            )

    async def _handle_listen(self, payload: dict[str, Any]) -> None:
        state = str(payload.get("state") or "")
        if state in {"start", "detect"}:
            self.listen_mode = str(payload.get("mode") or self.listen_mode)
            self.listening = True
            self.endpoint.reset()
        elif state == "stop":
            self.listening = False
            captured = self.endpoint.flush()
            if captured:
                await self._schedule_turn(captured)

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
        if result.speech_started and self._response_in_flight():
            if self.reader.state == "playing":
                self.reader.pause()
            await self.cancel_response(reason="barge_in")
            self.listening = True
        if result.complete_pcm:
            await self._schedule_turn(result.complete_pcm)

    async def _schedule_turn(self, pcm: bytes) -> None:
        async with self.response_lock:
            if self.closed or self._response_in_flight():
                return
            self.response_task = asyncio.create_task(self._process_turn(pcm))

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

    async def _process_turn(self, pcm: bytes) -> None:
        self.turn_count += 1
        self.generation_id += 1
        generation = self.generation_id
        try:
            transcript = await self.media.transcribe(
                pcm_to_wav(pcm, self.hello.sample_rate if self.hello else self.settings.input_sample_rate),
                hotwords=["Davie", "Jason", "Ingie", "StackChan"],
            )
            if generation != self.generation_id:
                return
            if not transcript:
                self.empty_transcript_count += 1
                self.last_error = "asr_empty_transcript"
                # Realtime audio can contain a wake chime tail or a short burst
                # of ambient noise. Keep listening instead of replacing the UI
                # with a misleading failure message.
                if self.listen_mode != "realtime":
                    await self.transport.send_json(
                        {
                            "session_id": self.session_id,
                            "type": "alert",
                            "status": "Listening",
                            "message": "I did not catch that. Please try again.",
                            "emotion": "neutral",
                        }
                    )
                return
            self.last_transcript = transcript
            await self.transport.send_json(
                {"session_id": self.session_id, "type": "stt", "text": transcript}
            )
            action = parse_device_action(transcript)
            if action and await self._handle_device_action(action, generation):
                return
            visual_reply = await self._visual_reply(transcript)
            if visual_reply:
                reply = visual_reply
            else:
                reply = await self.davie.chat(
                    transcript,
                    device_id=self.device_id,
                    session_id=self.davie_session_id,
                )
            if generation != self.generation_id:
                return
            self.davie_session_id = reply.session_id or self.davie_session_id
            response_text = spoken_text(
                reply.text,
                max_chars=self.settings.max_spoken_chars,
                max_sentences=self.settings.max_spoken_sentences,
            )
            self.last_response = response_text
            await self._speak(response_text, generation)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            LOGGER.exception("StackChan turn failed")
            self.last_error = type(exc).__name__
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

    async def _handle_device_action(self, action: DeviceAction, generation: int) -> bool:
        if action.kind == "help":
            await self._speak(capability_reply(chinese=action.chinese), generation)
            return True
        if action.kind == "reader_pause":
            changed = self.reader.pause()
            text = "朗读已暂停。" if action.chinese else "Reading is paused."
            if not changed and not self.reader.segments:
                text = "还没有加载阅读内容。" if action.chinese else "No reading is loaded yet."
            await self._speak(text, generation)
            return True
        if action.kind == "reader_resume":
            if not self.reader.resume():
                text = "没有可以继续的阅读内容。" if action.chinese else "There is no reading to continue."
                await self._speak(text, generation)
                return True
            await self._run_reader(generation)
            return True
        if action.kind == "reader_stop":
            changed = self.reader.stop()
            text = "朗读已停止，下次会从开头开始。" if action.chinese else "Reading stopped. It will restart from the beginning."
            if not changed:
                text = "还没有加载阅读内容。" if action.chinese else "No reading is loaded yet."
            await self._speak(text, generation)
            return True
        if action.kind == "reader_status":
            status = self.reader.status()
            if not status["segment_count"]:
                text = "还没有加载阅读内容。" if action.chinese else "No reading is loaded yet."
            elif action.chinese:
                text = f"正在读《{status['title']}》，进度约百分之 {status['progress_percent']}。"
            else:
                text = f"We are reading {status['title']}, at about {status['progress_percent']} percent."
            await self._speak(text, generation)
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
        await self._speak(text, generation)
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
        if generation == self.generation_id and self.reader.state == "completed":
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

    async def _speak(self, text: str, generation: int) -> None:
        if not text:
            return
        self.last_response = text
        self.speaking = True
        await self.transport.send_json({"session_id": self.session_id, "type": "llm", "emotion": "happy"})
        await self.transport.send_json({"session_id": self.session_id, "type": "tts", "state": "start"})
        try:
            for sentence in sentence_segments(text):
                if generation != self.generation_id:
                    return
                await self.transport.send_json(
                    {
                        "session_id": self.session_id,
                        "type": "tts",
                        "state": "sentence_start",
                        "text": sentence,
                    }
                )
                wav_bytes = await self.media.synthesize(sentence)
                pcm = await wav_to_pcm_async(wav_bytes, self.settings.output_sample_rate)
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
                        pack_audio_frame(encoded, self.hello.version if self.hello else 1, timestamp_ms=timestamp)
                    )
                    self.audio_frames_sent += 1
                    await asyncio.sleep(self.settings.frame_duration_ms / 1000)
        finally:
            if generation == self.generation_id:
                self.speaking = False
                await self.transport.send_json(
                    {"session_id": self.session_id, "type": "tts", "state": "stop"}
                )

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

    async def close(self, *, close_transport: bool = False) -> None:
        async with self.response_lock:
            if self.closed:
                return
            self.closed = True
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
        if close_transport:
            await self.transport.close(code=1000, reason="replaced by a newer device connection")

    def status(self) -> dict[str, Any]:
        return {
            "device_id": self.device_id,
            "client_id": self.client_id,
            "session_id": self.session_id,
            "connected_at": self.connected_at,
            "handshake_complete": self.hello is not None,
            "listening": self.listening,
            "speaking": self.speaking,
            "listen_mode": self.listen_mode,
            "generation_id": self.generation_id,
            "turn_count": self.turn_count,
            "empty_transcript_count": self.empty_transcript_count,
            "interrupt_count": self.interrupt_count,
            "audio_frames_received": self.audio_frames_received,
            "audio_frames_sent": self.audio_frames_sent,
            "last_transcript": self.last_transcript,
            "last_response": self.last_response,
            "last_error": self.last_error,
            "closed": self.closed,
            "mcp_initialized": self.mcp_initialized,
            "mcp_tool_count": len(self.mcp_tools),
            "mcp_tools": sorted(self.mcp_tools),
            "endpoint": self.endpoint.snapshot(),
            "reader": self.reader.status(),
        }
