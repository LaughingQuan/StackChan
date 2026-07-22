from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path

import httpx


async def run(image_path: Path, prompt: str) -> None:
    gateway_http = os.environ.get(
        "STACKCHAN_SMOKE_GATEWAY_HTTP", "http://127.0.0.1:8793"
    )
    started_image = image_path.read_bytes()

    async with httpx.AsyncClient(timeout=120) as client:
        bootstrap_response = await client.post(f"{gateway_http}/xiaozhi/ota/", json={})
        bootstrap_response.raise_for_status()
        bootstrap = bootstrap_response.json()
        token = str(bootstrap["websocket"]["token"])

        response = await client.post(
            f"{gateway_http}/v1/vision/explain",
            headers={
                "Authorization": f"Bearer {token}",
                "Device-Id": "stackchan-vision-smoke",
                "Client-Id": "stackchan-vision-smoke-client",
            },
            files={"file": (image_path.name, started_image, "image/jpeg")},
            data={"question": prompt},
        )
        response.raise_for_status()
        payload = response.json()

    description = str(payload.get("result") or "").strip()
    if not description:
        raise RuntimeError("vision bridge returned an empty description")
    print(
        json.dumps(
            {
                "status": "passed",
                "image_bytes": len(started_image),
                "description": description,
            },
            ensure_ascii=False,
        )
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a live StackChan vision bridge smoke")
    parser.add_argument("image", type=Path)
    parser.add_argument(
        "--prompt",
        default="Describe this image accurately in one short sentence.",
    )
    args = parser.parse_args()
    asyncio.run(run(args.image, args.prompt))


if __name__ == "__main__":
    main()
