from __future__ import annotations

import asyncio
import json
import os
import time
from typing import Any

import httpx
import websockets


TOOLS = [
    "self.camera.take_photo",
    "self.audio_speaker.set_volume",
    "self.robot.set_head_angles",
    "self.robot.set_led_color",
    "self.robot.create_reminder",
]


class SimulatedDevice:
    def __init__(self, websocket: Any):
        self.websocket = websocket
        self.events: list[dict[str, Any]] = []
        self.binary_packets = 0
        self.tool_calls: list[dict[str, Any]] = []

    async def receive_once(self, *, timeout: float = 0.25) -> bool:
        try:
            incoming = await asyncio.wait_for(self.websocket.recv(), timeout=timeout)
        except TimeoutError:
            return False
        if isinstance(incoming, bytes):
            self.binary_packets += 1
            return True
        event = json.loads(incoming)
        self.events.append(event)
        if event.get("type") != "mcp":
            return True
        request = event.get("payload") or {}
        method = request.get("method")
        if method == "initialize":
            result = {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "stackchan-capability-smoke", "version": "1"},
            }
        elif method == "tools/list":
            result = {
                "tools": [
                    {
                        "name": name,
                        "description": "Production contract smoke fixture",
                        "inputSchema": {"type": "object"},
                    }
                    for name in TOOLS
                ]
            }
        elif method == "tools/call":
            params = request.get("params") or {}
            self.tool_calls.append(params)
            if params.get("name") == "self.camera.take_photo":
                value = json.dumps(
                    {"success": True, "result": "I can see a blue test cup."}
                )
            else:
                value = "true"
            result = {"content": [{"type": "text", "text": value}]}
        else:
            result = {}
        await self.websocket.send(
            json.dumps(
                {
                    "type": "mcp",
                    "payload": {
                        "jsonrpc": "2.0",
                        "id": request["id"],
                        "result": result,
                    },
                }
            )
        )
        return True

    async def pump_until(self, task: asyncio.Task, *, timeout: float = 30.0) -> Any:
        deadline = time.monotonic() + timeout
        while not task.done():
            if time.monotonic() >= deadline:
                task.cancel()
                raise TimeoutError("timed out while waiting for gateway operation")
            await self.receive_once()
        return await task

    async def wait_for_event(self, predicate: Any, *, timeout: float = 60.0) -> dict[str, Any]:
        deadline = time.monotonic() + timeout
        for event in self.events:
            if predicate(event):
                return event
        while time.monotonic() < deadline:
            await self.receive_once(timeout=1.0)
            event = self.events[-1] if self.events else {}
            if predicate(event):
                return event
        raise TimeoutError("expected gateway event was not received")


async def checked_json(response: httpx.Response) -> dict[str, Any]:
    response.raise_for_status()
    value = response.json()
    if not isinstance(value, dict):
        raise RuntimeError("gateway returned a non-object response")
    return value


async def run() -> None:
    gateway_http = os.environ.get(
        "STACKCHAN_SMOKE_GATEWAY_HTTP", "http://127.0.0.1:8793"
    ).rstrip("/")
    admin_token = os.environ.get("STACKCHAN_SMOKE_ADMIN_TOKEN", "")
    if not admin_token:
        raise RuntimeError("STACKCHAN_SMOKE_ADMIN_TOKEN is required")
    device_id = "stackchan-capability-smoke"
    client_id = f"{device_id}-client"
    gateway_ws = gateway_http.replace("http://", "ws://", 1) + "/xiaozhi/v1/"
    admin_headers = {"Authorization": f"Bearer {admin_token}"}
    started = time.monotonic()

    async with httpx.AsyncClient(timeout=30) as client:
        bootstrap = await checked_json(
            await client.post(f"{gateway_http}/xiaozhi/ota/", json={})
        )
        device_token = str((bootstrap.get("websocket") or {}).get("token") or "")
        if not device_token:
            raise RuntimeError("bootstrap did not return a device token")

        async with websockets.connect(
            gateway_ws,
            additional_headers={
                "Authorization": f"Bearer {device_token}",
                "Device-Id": device_id,
                "Client-Id": client_id,
            },
            max_size=128 * 1024,
        ) as websocket:
            device = SimulatedDevice(websocket)
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

            capabilities: dict[str, Any] = {}
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                await device.receive_once(timeout=0.5)
                response = await client.get(
                    f"{gateway_http}/v1/devices/{device_id}/capabilities",
                    headers=admin_headers,
                )
                capabilities = await checked_json(response)
                if set(capabilities.get("mcp_tools") or []) == set(TOOLS):
                    break
            else:
                raise TimeoutError("MCP tool discovery did not complete")

            tool_task = asyncio.create_task(
                client.post(
                    f"{gateway_http}/v1/devices/{device_id}/tools/self.audio_speaker.set_volume",
                    headers=admin_headers,
                    json={"arguments": {"volume": 35}},
                )
            )
            await checked_json(await device.pump_until(tool_task))

            vision_task = asyncio.create_task(
                client.post(
                    f"{gateway_http}/v1/devices/{device_id}/vision",
                    headers=admin_headers,
                    json={"question": "What do you see?", "speak": False},
                )
            )
            vision = await checked_json(await device.pump_until(vision_task))
            if vision.get("result") != "I can see a blue test cup.":
                raise RuntimeError("high-level vision did not return the MCP camera result")

            loaded = await checked_json(
                await client.post(
                    f"{gateway_http}/v1/devices/{device_id}/reader/load",
                    headers=admin_headers,
                    json={
                        "title": "Capability smoke reader",
                        "text": (
                            "This is the first sentence for reading. "
                            "This is the second sentence after resume."
                        ),
                        "autoplay": False,
                    },
                )
            )
            if loaded["reader"]["segment_count"] != 2:
                raise RuntimeError("reader did not preserve sentence-level progress")

            await checked_json(
                await client.post(
                    f"{gateway_http}/v1/devices/{device_id}/reader/play",
                    headers=admin_headers,
                )
            )
            binary_before_pause = device.binary_packets
            deadline = time.monotonic() + 30
            while device.binary_packets == binary_before_pause:
                if time.monotonic() >= deadline:
                    raise TimeoutError("reader did not emit device audio")
                await device.receive_once(timeout=1.0)
            paused = await checked_json(
                await client.post(
                    f"{gateway_http}/v1/devices/{device_id}/reader/pause",
                    headers=admin_headers,
                )
            )
            if (
                paused["reader"]["state"] != "paused"
                or paused["reader"]["segment_index"] != 0
                or paused["reader"]["segment_number"] != 1
            ):
                raise RuntimeError("reader pause skipped the interrupted sentence")

            await checked_json(
                await client.post(
                    f"{gateway_http}/v1/devices/{device_id}/reader/play",
                    headers=admin_headers,
                )
            )
            await device.wait_for_event(
                lambda event: event.get("type") == "alert"
                and event.get("status") == "Reading complete",
                timeout=90,
            )
            final_status = await checked_json(
                await client.get(
                    f"{gateway_http}/v1/devices/{device_id}/reader",
                    headers=admin_headers,
                )
            )
            if final_status["reader"]["state"] != "completed":
                raise RuntimeError("reader did not persist its completed state")

        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            capabilities_after_close = await checked_json(
                await client.get(
                    f"{gateway_http}/v1/devices/{device_id}/capabilities",
                    headers=admin_headers,
                )
            )
            if capabilities_after_close.get("connected") is False:
                break
            await asyncio.sleep(0.1)
        cleanup = await checked_json(
            await client.delete(
                f"{gateway_http}/v1/devices/{device_id}/reader",
                headers=admin_headers,
            )
        )
        if cleanup["reader"]["segment_count"] != 0:
            raise RuntimeError("capability smoke did not clean up its reader fixture")

    volume_calls = [
        call for call in device.tool_calls
        if call.get("name") == "self.audio_speaker.set_volume"
    ]
    if not volume_calls or volume_calls[-1].get("arguments") != {"volume": 35}:
        raise RuntimeError("remote volume control did not reach the device MCP tool")
    print(
        json.dumps(
            {
                "status": "passed",
                "mcp_tool_count": len(capabilities.get("mcp_tools") or []),
                "vision_result": vision["result"],
                "reader_state": final_status["reader"]["state"],
                "reader_segments": final_status["reader"]["segment_count"],
                "binary_audio_packets": device.binary_packets,
                "tool_calls": len(device.tool_calls),
                "elapsed_seconds": round(time.monotonic() - started, 3),
            }
        )
    )


if __name__ == "__main__":
    asyncio.run(run())
