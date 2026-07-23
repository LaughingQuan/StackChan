from __future__ import annotations

import base64
import re
from dataclasses import dataclass

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
        "the current scene unless a camera image was captured for this turn. Keep the immediate spoken reply to "
        "one to three short sentences, use plain text without Markdown, and never read URLs or tool logs aloud. "
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
            [{"role": "system", "content": self.SPOKEN_SYSTEM}, {"role": "user", "content": text}],
            device_id=device_id,
            session_id=session_id,
        )

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
            [{"role": "system", "content": self.SPOKEN_SYSTEM}, {"role": "user", "content": content}],
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
        headers = {"X-Hermes-Session-Key": f"stackchan:{device_id}"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        if session_id:
            headers["X-Hermes-Session-Id"] = session_id
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


def spoken_text(value: str, *, max_chars: int, max_sentences: int) -> str:
    value = re.sub(r"```.*?```", "", value, flags=re.DOTALL)
    value = re.sub(r"https?://\S+", "", value)
    value = re.sub(r"[*_#>`~]+", "", value)
    value = re.sub(r"\s+", " ", value).strip()
    parts = [part.strip() for part in re.split(r"(?<=[.!?。！？])\s+", value) if part.strip()]
    value = " ".join(parts[:max_sentences]) if parts else value
    if len(value) > max_chars:
        value = value[:max_chars].rsplit(" ", 1)[0].rstrip(" ,;:") + "."
    return value


def sentence_segments(value: str) -> list[str]:
    segments = [part.strip() for part in re.split(r"(?<=[.!?。！？])\s+", value) if part.strip()]
    return segments or ([value.strip()] if value.strip() else [])


def _optional_float(value) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None
