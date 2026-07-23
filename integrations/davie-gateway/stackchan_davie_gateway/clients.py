from __future__ import annotations

import base64
import json
import re
from dataclasses import dataclass
from typing import Awaitable, Callable

import httpx


@dataclass(frozen=True)
class DavieReply:
    text: str
    session_id: str | None


@dataclass(frozen=True)
class TranscriptionResult:
    transcript: str
    ctc_text: str = ""
    language: str = ""
    model: str = ""
    elapsed_seconds: float | None = None
    inference_seconds: float | None = None


class MediaClient:
    def __init__(self, base_url: str, *, timeout: float = 180.0):
        self.base_url = base_url.rstrip("/")
        self.client = httpx.AsyncClient(timeout=timeout)

    async def close(self) -> None:
        await self.client.aclose()

    async def transcribe(
        self, wav_bytes: bytes, *, hotwords: list[str]
    ) -> TranscriptionResult:
        response = await self.client.post(
            f"{self.base_url}/v1/audio/transcribe",
            json={
                "audio_base64": base64.b64encode(wav_bytes).decode("ascii"),
                "filename": "stackchan-turn.wav",
                "language": "auto",
                "hotwords": hotwords,
            },
        )
        response.raise_for_status()
        payload = response.json()
        return TranscriptionResult(
            transcript=str(payload.get("transcript") or "").strip(),
            ctc_text=str(payload.get("ctc_text") or "").strip(),
            language=str(payload.get("language") or "").strip(),
            model=str(payload.get("model") or "").strip(),
            elapsed_seconds=_optional_float(payload.get("elapsed_seconds")),
            inference_seconds=_optional_float(payload.get("inference_seconds")),
        )

    async def synthesize(self, text: str) -> bytes:
        response = await self.client.post(
            f"{self.base_url}/v1/speech/synthesize",
            json={"text": text},
        )
        response.raise_for_status()
        artifact_url = str(response.json().get("artifact_url") or "")
        if not artifact_url.startswith(("http://", "https://")):
            raise RuntimeError("speech service returned no artifact URL")
        audio = await self.client.get(artifact_url)
        audio.raise_for_status()
        return audio.content


class DavieClient:
    SPOKEN_SYSTEM = (
        "You are Davie speaking through StackChan, your local desktop body. StackChan gives you a microphone, "
        "speaker, camera, face, movable head, light, reminders, and a resumable reading mode. Respond naturally "
        "as Jason's capable assistant and use your normal memory and tools when needed. Never claim you can see "
        "the current scene unless a camera image was captured for this turn. Start with a direct, useful sentence "
        "of no more than twelve words so speech can begin promptly. Add at most two more short sentences only when "
        "they improve the answer. Reply in the language used in the current user turn unless the user explicitly "
        "asks for another language; for Chinese, keep the first sentence under eighteen Han characters. Use plain "
        "text without Markdown, and never read URLs or tool logs aloud. "
        "If a task needs longer work, briefly say what you are doing and complete it with your available tools. "
        "The local gateway handles direct device controls and reading commands before they reach you."
    )

    def __init__(self, base_url: str, api_key: str, *, timeout: float = 300.0):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.client = httpx.AsyncClient(timeout=timeout)

    async def close(self) -> None:
        await self.client.aclose()

    async def chat(self, text: str, *, device_id: str, session_id: str | None) -> DavieReply:
        return await self._completion(
            self._spoken_messages(text),
            device_id=device_id,
            session_id=session_id,
        )

    async def stream_chat(
        self,
        text: str,
        *,
        device_id: str,
        session_id: str | None,
        on_delta: Callable[[str], Awaitable[None]],
    ) -> DavieReply:
        headers = self._headers(device_id=device_id, session_id=session_id)
        messages = self._spoken_messages(text)
        chunks: list[str] = []
        saw_terminal_event = False
        saw_nonchoice_event = False
        async with self.client.stream(
            "POST",
            f"{self.base_url}/v1/chat/completions",
            headers=headers,
            json={
                "model": "davie",
                "stream": True,
                "messages": messages,
            },
        ) as response:
            response.raise_for_status()
            response_session_id = response.headers.get("X-Hermes-Session-Id")
            async for line in response.aiter_lines():
                line = line.strip()
                if not line or line.startswith(":") or not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    saw_terminal_event = True
                    break
                try:
                    payload = json.loads(data)
                except json.JSONDecodeError:
                    continue
                choices = payload.get("choices") or []
                if not choices:
                    saw_nonchoice_event = True
                    continue
                if choices[0].get("finish_reason") is not None:
                    saw_terminal_event = True
                delta = (choices[0].get("delta") or {}).get("content")
                if not isinstance(delta, str) or not delta:
                    continue
                chunks.append(delta)
                await on_delta(delta)
        if not saw_terminal_event:
            raise RuntimeError("Davie streamed response ended before completion")
        content = "".join(chunks).strip()
        if not content:
            if saw_nonchoice_event:
                raise RuntimeError(
                    "Davie returned an empty streamed response after progress events"
                )
            reply = await self._completion(
                messages,
                device_id=device_id,
                session_id=response_session_id or session_id,
            )
            await on_delta(reply.text)
            return reply
        return DavieReply(content, response_session_id)

    async def analyze_image(
        self,
        question: str,
        image_bytes: bytes,
        *,
        mime_type: str,
        device_id: str,
        session_id: str | None = None,
    ) -> DavieReply:
        image_data = base64.b64encode(image_bytes).decode("ascii")
        content = [
            {
                "type": "text",
                "text": (
                    "Analyze the camera image and answer the user's question directly. "
                    "Be concrete, do not claim details that are not visible, and keep the spoken answer concise. "
                    f"Question: {question}"
                ),
            },
            {
                "type": "image_url",
                "image_url": {"url": f"data:{mime_type};base64,{image_data}"},
            },
        ]
        return await self._completion(
            [
                *self._spoken_system_messages(question),
                {"role": "user", "content": content},
            ],
            device_id=device_id,
            session_id=session_id,
        )

    async def _completion(
        self,
        messages: list[dict],
        *,
        device_id: str,
        session_id: str | None,
    ) -> DavieReply:
        headers = self._headers(device_id=device_id, session_id=session_id)
        response = await self.client.post(
            f"{self.base_url}/v1/chat/completions",
            headers=headers,
            json={
                "model": "davie",
                "stream": False,
                "messages": messages,
            },
        )
        response.raise_for_status()
        payload = response.json()
        choices = payload.get("choices") or []
        if not choices:
            raise RuntimeError("Davie returned no response choice")
        content = str((choices[0].get("message") or {}).get("content") or "").strip()
        if not content:
            raise RuntimeError("Davie returned an empty response")
        return DavieReply(content, response.headers.get("X-Hermes-Session-Id"))

    def _headers(self, *, device_id: str, session_id: str | None) -> dict[str, str]:
        headers = {"X-Hermes-Session-Key": f"stackchan:{device_id}"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        if session_id:
            headers["X-Hermes-Session-Id"] = session_id
        return headers

    def _spoken_messages(self, text: str) -> list[dict[str, str]]:
        return [
            *self._spoken_system_messages(text),
            {"role": "user", "content": text},
        ]

    def _spoken_system_messages(self, text: str) -> list[dict[str, str]]:
        return [
            {"role": "system", "content": self.SPOKEN_SYSTEM},
            {"role": "system", "content": spoken_language_directive(text)},
        ]


class SpokenSentenceBuffer:
    """Turns streamed model deltas into the exact bounded text spoken aloud."""

    def __init__(self, *, max_chars: int, max_sentences: int):
        self.max_chars = max_chars
        self.max_sentences = max_sentences
        self.buffer = ""
        self.sentences: list[str] = []

    @property
    def text(self) -> str:
        return " ".join(self.sentences)

    def feed(self, delta: str) -> list[str]:
        if self.is_full or not delta:
            return []
        self.buffer += delta
        ready: list[str] = []
        while not self.is_full:
            match = re.search(r"[.!?。！？](?:[*_`~]*)(?:\s+|$)", self.buffer)
            if match is None:
                break
            candidate = self.buffer[: match.end()].strip()
            self.buffer = self.buffer[match.end() :]
            spoken = self._bounded_sentence(candidate)
            if spoken:
                self.sentences.append(spoken)
                ready.append(spoken)
        return ready

    def finish(self) -> list[str]:
        if self.is_full:
            self.buffer = ""
            return []
        candidate = self.buffer.strip()
        self.buffer = ""
        spoken = self._bounded_sentence(candidate)
        if not spoken:
            return []
        self.sentences.append(spoken)
        return [spoken]

    @property
    def is_full(self) -> bool:
        return (
            len(self.sentences) >= self.max_sentences
            or len(self.text) >= self.max_chars
        )

    def _bounded_sentence(self, candidate: str) -> str:
        if not candidate:
            return ""
        separator_chars = 1 if self.sentences else 0
        remaining = self.max_chars - len(self.text) - separator_chars
        if remaining <= 0:
            return ""
        return spoken_text(
            candidate,
            max_chars=remaining,
            max_sentences=1,
        )


def spoken_text(value: str, *, max_chars: int, max_sentences: int) -> str:
    value = re.sub(r"```.*?```", "", value, flags=re.DOTALL)
    value = re.sub(r"https?://\S+", "", value)
    value = re.sub(r"[*_#>`~]+", "", value)
    value = re.sub(r"\s+", " ", value).strip()
    value = re.sub(r"^(?:[-+•]|\d+[.)])\s+", "", value)
    parts = [part.strip() for part in re.split(r"(?<=[.!?。！？])\s+", value) if part.strip()]
    value = " ".join(parts[:max_sentences]) if parts else value
    if len(value) > max_chars:
        value = value[:max_chars].rsplit(" ", 1)[0].rstrip(" ,;:") + "."
    return value


def spoken_language_directive(value: str) -> str:
    """Pin the current spoken turn's language without changing user text or memory."""

    han_count = len(re.findall(r"[\u3400-\u4dbf\u4e00-\u9fff]", value))
    latin_count = len(re.findall(r"[A-Za-z]", value))
    if latin_count and not han_count:
        language_rule = "Reply only in English"
    elif han_count and not latin_count:
        language_rule = "Reply only in Chinese"
    elif latin_count > han_count * 2:
        language_rule = (
            "Reply in English, while preserving any Chinese terms that the user wants explained"
        )
    elif han_count:
        language_rule = (
            "Reply in Chinese, while preserving any English terms that the user wants explained"
        )
    else:
        language_rule = "Reply in the same language as the current user turn"
    return (
        "Per-turn spoken language contract: "
        f"{language_rule}. This instruction applies only to the current reply and overrides stored "
        "language preferences. Do not translate into another language unless the user explicitly asks."
    )


def sentence_segments(value: str) -> list[str]:
    segments = [part.strip() for part in re.split(r"(?<=[.!?。！？])\s+", value) if part.strip()]
    return segments or ([value.strip()] if value.strip() else [])


def _optional_float(value) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None
