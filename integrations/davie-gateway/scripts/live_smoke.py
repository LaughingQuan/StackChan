from __future__ import annotations

import asyncio
import json
import os
import time

import httpx
import websockets

from stackchan_davie_gateway.audio import OpusCodec, iter_pcm_frames, wav_to_pcm_async
from stackchan_davie_gateway.clients import MediaClient


async def run() -> None:
    gateway_http = os.environ.get(
        "STACKCHAN_SMOKE_GATEWAY_HTTP", "http://127.0.0.1:8793"
    )
    gateway_ws = gateway_http.replace("http://", "ws://", 1) + "/xiaozhi/v1/"
    media_url = os.environ.get(
        "STACKCHAN_SMOKE_MEDIA_URL", "http://media-gateway.local:8790"
    )
    prompt = os.environ.get(
        "STACKCHAN_SMOKE_PROMPT",
        "Hello Davie. Please answer with one short sentence.",
    )
    device_id = f"stackchan-smoke-{os.getpid()}"
    started = time.monotonic()

    async with httpx.AsyncClient(timeout=30) as client:
        bootstrap = (await client.post(f"{gateway_http}/xiaozhi/ota/", json={})).json()
    token = str(bootstrap["websocket"]["token"])

    media = MediaClient(media_url)
    input_codec = OpusCodec(16000, 16000, 60)
    output_codec = OpusCodec(24000, 24000, 60)
    try:
        source_wav = await media.synthesize(prompt)
        source_pcm = await wav_to_pcm_async(source_wav, 16000)
        source_pcm += b"\0" * (16000 * 2 * 2)

        events: list[str] = []
        output_pcm_bytes = 0
        async with websockets.connect(
            gateway_ws,
            additional_headers={
                "Authorization": f"Bearer {token}",
                "Device-Id": device_id,
                "Client-Id": f"{device_id}-client",
            },
            max_size=128 * 1024,
        ) as websocket:
            await websocket.send(
                json.dumps(
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
            )

            handshake_ready = False
            while not handshake_ready:
                message = json.loads(await asyncio.wait_for(websocket.recv(), timeout=10))
                if message.get("type") == "hello":
                    events.append("hello")
                elif message.get("type") == "mcp":
                    request = message.get("payload") or {}
                    method = request.get("method")
                    if method == "initialize":
                        await websocket.send(
                            json.dumps(
                                {
                                    "type": "mcp",
                                    "payload": {
                                        "jsonrpc": "2.0",
                                        "id": request["id"],
                                        "result": {
                                            "protocolVersion": "2024-11-05",
                                            "capabilities": {"tools": {}},
                                            "serverInfo": {"name": "smoke", "version": "1"},
                                        },
                                    },
                                }
                            )
                        )
                    elif method == "tools/list":
                        await websocket.send(
                            json.dumps(
                                {
                                    "type": "mcp",
                                    "payload": {
                                        "jsonrpc": "2.0",
                                        "id": request["id"],
                                        "result": {"tools": []},
                                    },
                                }
                            )
                        )
                        handshake_ready = True

            await websocket.send(
                json.dumps({"type": "listen", "state": "start", "mode": "realtime"})
            )
            for frame in iter_pcm_frames(source_pcm, sample_rate=16000, frame_duration_ms=60):
                await websocket.send(input_codec.encode(frame))

            deadline = time.monotonic() + 120
            while time.monotonic() < deadline:
                incoming = await asyncio.wait_for(websocket.recv(), timeout=30)
                if isinstance(incoming, bytes):
                    output_pcm_bytes += len(output_codec.decode(incoming))
                    continue
                event = json.loads(incoming)
                event_type = str(event.get("type") or "")
                if event_type:
                    events.append(event_type)
                if event_type == "alert":
                    raise RuntimeError("gateway returned an alert during live smoke")
                if event_type == "tts" and event.get("state") == "stop":
                    break
            else:
                raise TimeoutError("live smoke did not finish")

        required = {"hello", "stt", "llm", "tts"}
        if not required.issubset(events) or output_pcm_bytes <= 0:
            raise RuntimeError("live smoke did not cover the complete voice lifecycle")
        print(
            json.dumps(
                {
                    "status": "passed",
                    "device_id": device_id,
                    "event_types": sorted(set(events)),
                    "output_pcm_bytes": output_pcm_bytes,
                    "elapsed_seconds": round(time.monotonic() - started, 3),
                }
            )
        )
    finally:
        input_codec.close()
        output_codec.close()
        await media.close()


if __name__ == "__main__":
    asyncio.run(run())
