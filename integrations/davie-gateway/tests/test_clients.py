from __future__ import annotations

import json

import httpx

from stackchan_davie_gateway.clients import (
    DavieClient,
    MediaClient,
    SpokenSentenceBuffer,
    spoken_language_directive,
)


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


async def test_davie_stream_chat_forwards_ordered_deltas_and_session() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert payload["stream"] is True
        assert "Reply in the language used in the current user turn" in payload["messages"][0]["content"]
        assert "Reply only in English" in payload["messages"][1]["content"]
        assert request.headers["x-hermes-session-key"] == "stackchan:device-1"
        assert request.headers["x-hermes-session-id"] == "prior-session"
        body = "\n\n".join(
            [
                'data: {"object":"chat.completion.chunk","choices":[{"delta":{"role":"assistant"}}]}',
                'data: {"object":"hermes.tool.progress","tool":"memory"}',
                'data: {"object":"chat.completion.chunk","choices":[{"delta":{"content":"First sentence."}}]}',
                'data: {"object":"chat.completion.chunk","choices":[{"delta":{"content":" Second sentence."}}]}',
                'data: {"object":"chat.completion.chunk","choices":[{"delta":{},"finish_reason":"stop"}]}',
                "data: [DONE]",
            ]
        )
        return httpx.Response(
            200,
            headers={
                "Content-Type": "text/event-stream",
                "X-Hermes-Session-Id": "next-session",
            },
            content=(body + "\n\n").encode(),
        )

    client = DavieClient("http://davie.test", "secret")
    await client.client.aclose()
    client.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    deltas: list[str] = []

    async def on_delta(delta: str) -> None:
        deltas.append(delta)

    reply = await client.stream_chat(
        "Hello",
        device_id="device-1",
        session_id="prior-session",
        on_delta=on_delta,
    )

    assert deltas == ["First sentence.", " Second sentence."]
    assert reply.text == "First sentence. Second sentence."
    assert reply.session_id == "next-session"
    await client.close()


async def test_davie_stream_chat_rejects_truncated_sse() -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"Content-Type": "text/event-stream"},
            content=(
                'data: {"object":"chat.completion.chunk","choices":'
                '[{"delta":{"content":"Partial answer"}}]}\n\n'
            ).encode(),
        )

    client = DavieClient("http://davie.test", "")
    await client.client.aclose()
    client.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    try:
        await client.stream_chat(
            "Hello",
            device_id="device-1",
            session_id=None,
            on_delta=lambda _delta: _completed_awaitable(),
        )
    except RuntimeError as exc:
        assert "ended before completion" in str(exc)
    else:
        raise AssertionError("truncated SSE must fail closed")
    await client.close()


async def test_davie_stream_chat_falls_back_when_clean_stream_is_empty() -> None:
    requests: list[dict] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        requests.append(payload)
        if payload["stream"]:
            body = "\n\n".join(
                [
                    'data: {"choices":[{"delta":{"role":"assistant"}}]}',
                    'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}',
                    "data: [DONE]",
                ]
            )
            return httpx.Response(
                200,
                headers={"X-Hermes-Session-Id": "empty-stream-session"},
                content=(body + "\n\n").encode(),
            )
        assert request.headers["x-hermes-session-id"] == "empty-stream-session"
        return httpx.Response(
            200,
            headers={"X-Hermes-Session-Id": "fallback-session"},
            json={
                "choices": [
                    {"message": {"role": "assistant", "content": "我是 Davie。"}}
                ]
            },
        )

    client = DavieClient("http://davie.test", "")
    await client.client.aclose()
    client.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    deltas: list[str] = []

    async def on_delta(delta: str) -> None:
        deltas.append(delta)

    reply = await client.stream_chat(
        "请介绍你自己。",
        device_id="device-1",
        session_id=None,
        on_delta=on_delta,
    )

    assert [request["stream"] for request in requests] == [True, False]
    assert deltas == ["我是 Davie。"]
    assert reply.text == "我是 Davie。"
    assert reply.session_id == "fallback-session"
    await client.close()


async def test_davie_stream_chat_does_not_retry_after_progress_events() -> None:
    request_count = 0

    async def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal request_count
        request_count += 1
        body = "\n\n".join(
            [
                'data: {"object":"hermes.tool.progress","tool":"memory"}',
                'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}',
                "data: [DONE]",
            ]
        )
        return httpx.Response(200, content=(body + "\n\n").encode())

    client = DavieClient("http://davie.test", "")
    await client.client.aclose()
    client.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    try:
        await client.stream_chat(
            "Remember this.",
            device_id="device-1",
            session_id=None,
            on_delta=lambda _delta: _completed_awaitable(),
        )
    except RuntimeError as exc:
        assert "after progress events" in str(exc)
    else:
        raise AssertionError("a side-effectful empty stream must not be retried")
    assert request_count == 1
    await client.close()


async def _completed_awaitable() -> None:
    return None


def test_spoken_sentence_buffer_bounds_streamed_output() -> None:
    buffer = SpokenSentenceBuffer(max_chars=60, max_sentences=2)

    assert buffer.feed("Hello Jason.") == ["Hello Jason."]
    assert buffer.feed(" Visit https://example.com for details!") == [
        "Visit for details!"
    ]
    assert buffer.feed(" This third sentence must not be spoken.") == []
    assert buffer.finish() == []
    assert buffer.text == "Hello Jason. Visit for details!"

    bullet_buffer = SpokenSentenceBuffer(max_chars=60, max_sentences=1)
    assert bullet_buffer.feed("- **我是 Davie。**") == ["我是 Davie。"]


def test_spoken_language_directive_routes_current_turn_without_rewriting_it() -> None:
    assert "Reply only in English" in spoken_language_directive(
        "Explain why the sky looks blue."
    )
    assert "Reply only in Chinese" in spoken_language_directive("今天天气怎么样？")
    assert "Reply in English" in spoken_language_directive(
        "How do I say 加班 in English?"
    )
    assert "Reply in Chinese" in spoken_language_directive(
        "请解释一下 endpoint 这个词。"
    )
