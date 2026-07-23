from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import httpx
import websockets
from websockets.exceptions import ConnectionClosed


async def run() -> None:
    gateway_http = os.environ.get(
        "STACKCHAN_SMOKE_GATEWAY_HTTP", "http://127.0.0.1:8793"
    ).rstrip("/")
    gateway_ws = gateway_http.replace("http://", "ws://", 1) + "/xiaozhi/v1/"
    token_file = Path(
        os.environ.get(
            "STACKCHAN_SMOKE_ADMIN_TOKEN_FILE",
            str(Path.home() / ".hermes/secrets/stackchan-admin-token"),
        )
    )
    admin_token = token_file.read_text(encoding="utf-8").strip()
    if not admin_token:
        raise RuntimeError("admin token file is empty")
    device_id = f"stackchan-lifecycle-smoke-{os.getpid()}"
    client_id = f"{device_id}-client"

    async with httpx.AsyncClient(timeout=10) as client:
        bootstrap_response = await client.post(f"{gateway_http}/xiaozhi/ota/", json={})
        bootstrap_response.raise_for_status()
        device_token = str(bootstrap_response.json()["websocket"]["token"])
        async with websockets.connect(
            gateway_ws,
            additional_headers={
                "Authorization": f"Bearer {device_token}",
                "Device-Id": device_id,
                "Client-Id": client_id,
            },
        ) as websocket:
            await websocket.send(
                json.dumps(
                    {
                        "type": "hello",
                        "version": 1,
                        "transport": "websocket",
                        "features": {"mcp": False},
                        "audio_params": {
                            "format": "opus",
                            "sample_rate": 16000,
                            "channels": 1,
                            "frame_duration": 60,
                        },
                    }
                )
            )
            hello = json.loads(await asyncio.wait_for(websocket.recv(), timeout=5))
            if hello.get("type") != "hello":
                raise RuntimeError("gateway did not complete the hello handshake")

            admin_headers = {"Authorization": f"Bearer {admin_token}"}
            devices_response = await client.get(
                f"{gateway_http}/v1/devices", headers=admin_headers
            )
            devices_response.raise_for_status()
            devices = devices_response.json().get("devices") or []
            status = next(
                (
                    item
                    for item in devices
                    if isinstance(item, dict) and item.get("device_id") == device_id
                ),
                None,
            )
            if not status or status.get("session_state") != "ready":
                raise RuntimeError("live session did not expose ready lifecycle evidence")

            sleep_response = await client.post(
                f"{gateway_http}/v1/devices/{device_id}/sleep",
                headers=admin_headers,
            )
            sleep_response.raise_for_status()
            receipt = sleep_response.json()
            if (
                receipt.get("session_state") != "closed"
                or receipt.get("close_reason") != "admin_sleep"
            ):
                raise RuntimeError("sleep endpoint returned an invalid lifecycle receipt")

            saw_sleeping_alert = False
            try:
                while True:
                    incoming = await asyncio.wait_for(websocket.recv(), timeout=5)
                    if isinstance(incoming, str):
                        event = json.loads(incoming)
                        saw_sleeping_alert = saw_sleeping_alert or (
                            event.get("type") == "alert"
                            and event.get("status") == "Sleeping"
                        )
            except ConnectionClosed:
                pass
            if not saw_sleeping_alert:
                raise RuntimeError("device did not receive the sleeping lifecycle event")

    print(
        json.dumps(
            {
                "status": "passed",
                "handshake": True,
                "ready_status": True,
                "sleep_receipt": True,
                "sleeping_alert": True,
                "transport_closed": True,
            }
        )
    )


if __name__ == "__main__":
    asyncio.run(run())
