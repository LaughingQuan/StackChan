from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _read_secret(env_name: str, file_env_name: str, default_file: str) -> str:
    direct = os.environ.get(env_name, "").strip()
    if direct:
        return direct
    secret_file = Path(os.environ.get(file_env_name, default_file))
    try:
        return secret_file.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


@dataclass(frozen=True)
class Settings:
    host: str = "0.0.0.0"
    port: int = 8793
    public_host: str = "stackchan-gateway.local"
    media_base_url: str = "http://media-gateway.local:8790"
    davie_base_url: str = "http://davie-gateway.local:8642"
    davie_api_key: str = ""
    device_token: str = ""
    admin_token: str = ""
    allow_insecure: bool = False
    input_sample_rate: int = 16000
    output_sample_rate: int = 24000
    frame_duration_ms: int = 60
    endpoint_silence_ms: int = 900
    endpoint_min_speech_ms: int = 240
    endpoint_max_turn_ms: int = 20000
    endpoint_min_rms: int = 420
    session_idle_timeout_seconds: float = 120.0
    session_watchdog_interval_seconds: float = 1.0
    max_spoken_sentences: int = 3
    max_spoken_chars: int = 520
    max_camera_image_bytes: int = 2_000_000
    camera_snapshot_dir: str = "/var/lib/stackchan-davie/camera"
    max_reader_chars: int = 500_000
    reader_state_path: str = "/var/lib/stackchan-davie/readers.json"

    @property
    def websocket_url(self) -> str:
        return f"ws://{self.public_host}:{self.port}/xiaozhi/v1/"

    @property
    def vision_explain_url(self) -> str:
        return f"http://{self.public_host}:{self.port}/v1/vision/explain"

    def validate_runtime(self) -> None:
        if self.allow_insecure:
            return
        missing = [
            name
            for name, value in (
                ("Davie API key", self.davie_api_key),
                ("device token", self.device_token),
                ("admin token", self.admin_token),
            )
            if not value
        ]
        if missing:
            raise RuntimeError(f"missing required StackChan credentials: {', '.join(missing)}")

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            host=os.environ.get("STACKCHAN_DAVIE_HOST", "0.0.0.0"),
            port=int(os.environ.get("STACKCHAN_DAVIE_PORT", "8793")),
            public_host=os.environ.get(
                "STACKCHAN_DAVIE_PUBLIC_HOST", "stackchan-gateway.local"
            ),
            media_base_url=os.environ.get(
                "STACKCHAN_MEDIA_BASE_URL", "http://media-gateway.local:8790"
            ).rstrip("/"),
            davie_base_url=os.environ.get(
                "STACKCHAN_DAVIE_BASE_URL", "http://davie-gateway.local:8642"
            ).rstrip("/"),
            davie_api_key=_read_secret(
                "STACKCHAN_DAVIE_API_KEY",
                "STACKCHAN_DAVIE_API_KEY_FILE",
                "/etc/stackchan-davie/davie-api-key",
            ),
            device_token=_read_secret(
                "STACKCHAN_DEVICE_TOKEN",
                "STACKCHAN_DEVICE_TOKEN_FILE",
                "/etc/stackchan-davie/device-token",
            ),
            admin_token=_read_secret(
                "STACKCHAN_ADMIN_TOKEN",
                "STACKCHAN_ADMIN_TOKEN_FILE",
                "/etc/stackchan-davie/admin-token",
            ),
            allow_insecure=os.environ.get("STACKCHAN_ALLOW_INSECURE", "0").strip().lower()
            in {"1", "true", "yes"},
            endpoint_silence_ms=int(os.environ.get("STACKCHAN_ENDPOINT_SILENCE_MS", "900")),
            endpoint_min_speech_ms=int(os.environ.get("STACKCHAN_ENDPOINT_MIN_SPEECH_MS", "240")),
            endpoint_max_turn_ms=int(os.environ.get("STACKCHAN_ENDPOINT_MAX_TURN_MS", "20000")),
            endpoint_min_rms=int(os.environ.get("STACKCHAN_ENDPOINT_MIN_RMS", "420")),
            session_idle_timeout_seconds=float(
                os.environ.get("STACKCHAN_SESSION_IDLE_TIMEOUT_SECONDS", "120")
            ),
            session_watchdog_interval_seconds=float(
                os.environ.get("STACKCHAN_SESSION_WATCHDOG_INTERVAL_SECONDS", "1")
            ),
            camera_snapshot_dir=os.environ.get(
                "STACKCHAN_CAMERA_SNAPSHOT_DIR", "/var/lib/stackchan-davie/camera"
            ),
            max_reader_chars=int(os.environ.get("STACKCHAN_MAX_READER_CHARS", "500000")),
            reader_state_path=os.environ.get(
                "STACKCHAN_READER_STATE_PATH", "/var/lib/stackchan-davie/readers.json"
            ),
        )
