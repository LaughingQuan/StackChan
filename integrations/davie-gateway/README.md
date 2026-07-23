# StackChan Davie Gateway

This service implements the official Xiaozhi WebSocket contract used by the
upstream StackChan firmware. It keeps device firmware independent from Davie's
model, ASR, TTS, memory, and tool implementations.

## Runtime flow

1. StackChan requests `/xiaozhi/ota/` and receives the local WebSocket URL.
2. StackChan streams raw Opus frames after the official hello/listen handshake.
3. The gateway decodes frames and performs adaptive endpointing.
4. Completed speech is sent to the NVIDIA media gateway's Fun-ASR service.
5. Text is sent to the authenticated Hermes API server with a stable per-device
   session key, preserving Davie memory and tools.
6. Davie's short spoken response is synthesized by CosyVoice3, encoded as raw
   Opus, and streamed back through the official TTS lifecycle.
7. Acoustic input first enters a `possible speech` state. Confirmed speech or a
   completed user turn invalidates the current generation and stops old audio;
   short noise bursts are discarded without cancelling Davie.
8. A voice command, authenticated API request, or configurable inactivity
   timeout closes the session so the device returns to wake-word mode.

Secrets are read from root-owned files on the deployed host. Wi-Fi credentials,
device tokens, and the Hermes API key must never be placed in Git.

## Supported capabilities

- Continuous official Opus input/output over WebSocket.
- Local Fun-ASR transcription and CosyVoice3 speech synthesis.
- Stable Davie session continuity and long-term memory scoping per device.
- Generation-safe abort and acoustic barge-in. Old audio is rejected after a
  generation is cancelled.
- ASR quality gating for wake/name-only tails, filler-only input, impossible
  transcript rates, and too-short noise bursts before they can call Davie.
- Explicit session lifecycle diagnostics plus `Goodbye Davie`/`休息吧`, admin
  sleep, and automatic idle sleep.
- Official MCP discovery and calls for camera, head motion, LEDs, reminders,
  volume, brightness, theme, device status, and other upstream tools.
- Camera JPEG analysis through Davie's multimodal API, bound back to the active
  spoken session so follow-up questions retain visual context.
- A voice-first capability router for help, reminders, volume, head movement,
  onboard LED control, and reading commands. Direct device actions do not spend
  a model call and only report success after the matching MCP tool succeeds.
- Persistent read-aloud state with sentence-level checkpoints. Barge-in pauses
  immediately; resume repeats the interrupted sentence instead of skipping it.
- High-level authenticated APIs for Davie to speak, see, control hardware, and
  load/play/pause/stop reading without knowing device-specific MCP details.
- Separate device and administrator authentication.

## Requirements

- Python 3.11 or newer.
- `libopus` available to the process.
- `ffmpeg` for sample-rate conversion.
- Reachable ASR/TTS media service and Davie API service.

The gateway is not tied to Rock5B. It can run on any Linux host that can reach
the media and Davie services.

## Development

```bash
uv sync --dev
uv run pytest -q
uv run python -m compileall -q stackchan_davie_gateway scripts tests
uv build
```

Live local voice and camera smokes:

```bash
uv run python scripts/live_smoke.py
uv run python scripts/vision_smoke.py --prompt "Describe this image." /path/to/image.jpg
```

Neither smoke prints or stores the device token obtained during bootstrap.

## Linux deployment

1. Create a dedicated unprivileged `stackchan-davie` service account.
2. Install the wheel into `/opt/stackchan-davie-gateway/.venv`.
3. Copy `deploy/runtime.env.example` to `/etc/stackchan-davie/runtime.env` and
   set only non-secret service addresses and endpointing values.
4. Store the Davie API key, device token, and admin token in separate root-owned
   files under `/etc/stackchan-davie/`.
5. Install `deploy/stackchan-davie-gateway.service`, then enable and start it.

The unit uses systemd `LoadCredential`, filesystem protection, a private `/tmp`,
and automatic restart. Do not replace credential files with environment values
inside source-controlled configuration.

## Firmware pairing

The OTA bootstrap endpoint is:

```text
http://GATEWAY_HOST:8793/xiaozhi/ota/
```

The upstream firmware obtains the authenticated WebSocket endpoint and camera
bridge from that bootstrap/initialize sequence. No Davie-specific model or
business logic is compiled into the ESP32 firmware.

## Operations

Health:

```bash
curl http://GATEWAY_HOST:8793/health
```

Administrator routes require the distinct admin token:

```text
GET  /v1/devices
GET  /v1/capabilities
GET  /v1/devices/{device_id}/capabilities
POST /v1/devices/{device_id}/say
POST /v1/devices/{device_id}/sleep
POST /v1/devices/{device_id}/vision
POST /v1/devices/{device_id}/reader/load
GET  /v1/devices/{device_id}/reader
POST /v1/devices/{device_id}/reader/play
POST /v1/devices/{device_id}/reader/pause
POST /v1/devices/{device_id}/reader/stop
DELETE /v1/devices/{device_id}/reader
POST /v1/devices/{device_id}/tools/{tool_name}
```

`/v1/capabilities` is public metadata and never contains credentials. All
device-specific routes require the administrator token. A book can be loaded
while the device is offline; autoplay requires an active audio session.
The official 1.4.3 firmware opens that session on wake, so immediate remote
speech, vision, and hardware actions require the device to be awake and
connected. Offline reader loading and persisted checkpoints do not.

`GET /v1/devices` exposes lifecycle, endpoint, transcription-quality, and
barge-in evidence. Network reachability, a connected WebSocket, or synthetic
audio is not accepted as proof of human wake-word or audible playback quality.

The camera endpoint follows the official StackChan multipart contract:

```text
POST /v1/vision/explain
Headers: Authorization, Device-Id, Client-Id
Fields:  question, file (JPEG)
```
