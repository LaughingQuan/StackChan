from __future__ import annotations

import json

import httpx

from stackchan_davie_gateway.clients import MediaClient


async def test_media_transcription_preserves_diagnostics() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert payload["language"] == "auto"
        assert payload["hotwords"] == ["Davie", "StackChan"]
        return httpx.Response(
            200,
            json={
                "transcript": "What can you do?",
                "ctc_text": "what can you do",
                "language": "auto",
                "model": "Fun-ASR-Nano-2512",
                "elapsed_seconds": 0.2,
                "inference_seconds": 0.15,
            },
        )

    media = MediaClient("http://media.test")
    await media.client.aclose()
    media.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    result = await media.transcribe(b"wav", hotwords=["Davie", "StackChan"])

    assert result.transcript == "What can you do?"
    assert result.ctc_text == "what can you do"
    assert result.model == "Fun-ASR-Nano-2512"
    assert result.elapsed_seconds == 0.2
    assert result.inference_seconds == 0.15
    await media.close()
