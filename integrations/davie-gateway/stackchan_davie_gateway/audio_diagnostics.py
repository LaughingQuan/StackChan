from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import threading
import time
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .audio import pcm_to_wav


MAX_CAPTURE_SECONDS = 10
LOGGER = logging.getLogger(__name__)


@dataclass
class _ActiveCapture:
    capture_id: str
    device_id: str
    session_id: str
    duration_seconds: int
    created_at: float
    pcm: bytearray = field(default_factory=bytearray)
    sample_rate: int | None = None


class AudioDiagnosticStore:
    """Explicit, bounded AFE-output capture with asynchronous NAS archival."""

    def __init__(
        self,
        root: str | Path | None,
        *,
        nas_root: str | Path | None = None,
        recent_limit: int = 20,
    ):
        self.root = Path(root) if root else None
        self.nas_root = Path(nas_root) if nas_root else None
        self.recent_limit = max(1, int(recent_limit))
        self._lock = threading.RLock()
        self._active: dict[str, _ActiveCapture] = {}
        self._recent: list[dict[str, Any]] = []
        self._futures: set[Future[None]] = set()
        self._closed = False
        self._executor = ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix="stackchan-audio-diagnostic",
        )
        self._load_existing()

    def _load_existing(self) -> None:
        if self.root is None or not self.root.is_dir():
            return
        loaded: list[dict[str, Any]] = []
        for manifest_path in self.root.glob("*/manifest.json"):
            try:
                payload = json.loads(manifest_path.read_text(encoding="utf-8"))
            except (OSError, ValueError, json.JSONDecodeError):
                continue
            if (
                isinstance(payload, dict)
                and payload.get("schema_version") == 1
                and isinstance(payload.get("capture_id"), str)
            ):
                loaded.append(self._public_record(payload))
        loaded.sort(
            key=lambda item: float(item.get("created_at") or 0),
            reverse=True,
        )
        self._recent = loaded[: self.recent_limit]

    @staticmethod
    def _public_record(record: dict[str, Any]) -> dict[str, Any]:
        allowed = {
            "schema_version",
            "capture_id",
            "device_id",
            "session_id",
            "status",
            "source",
            "duration_seconds",
            "captured_ms",
            "sample_rate",
            "created_at",
            "completed_at",
            "sha256",
            "bytes",
            "local_wav_path",
            "nas_sync_status",
            "nas_wav_path",
            "error",
        }
        return {
            key: deepcopy(record[key])
            for key in allowed
            if key in record
        }

    def arm(
        self,
        *,
        device_id: str,
        session_id: str,
        duration_seconds: int,
    ) -> dict[str, Any]:
        if self.root is None:
            raise ValueError("diagnostic_capture_disabled")
        if not 1 <= int(duration_seconds) <= MAX_CAPTURE_SECONDS:
            raise ValueError("diagnostic_duration_out_of_range")
        with self._lock:
            if self._closed:
                raise ValueError("diagnostic_store_closed")
            if device_id in self._active:
                raise ValueError("diagnostic_capture_already_active")
            capture_id = (
                f"audio-{int(time.time() * 1000)}-{uuid.uuid4().hex[:8]}"
            )
            capture = _ActiveCapture(
                capture_id=capture_id,
                device_id=device_id,
                session_id=session_id,
                duration_seconds=int(duration_seconds),
                created_at=time.time(),
            )
            self._active[device_id] = capture
            record = self._record_for(capture, status="armed")
            self._upsert_recent_locked(record)
            return self._public_record(record)

    def cancel(self, device_id: str) -> dict[str, Any] | None:
        with self._lock:
            capture = self._active.pop(device_id, None)
            if capture is None:
                return None
            record = self._record_for(capture, status="cancelled")
            record["completed_at"] = time.time()
            self._upsert_recent_locked(record)
            return self._public_record(record)

    def feed(
        self,
        device_id: str,
        session_id: str,
        pcm_s16le: bytes,
        sample_rate: int,
    ) -> dict[str, Any] | None:
        if not pcm_s16le:
            return None
        with self._lock:
            capture = self._active.get(device_id)
            if capture is None:
                return None
            if capture.session_id != session_id:
                self._active.pop(device_id, None)
                record = self._record_for(capture, status="failed")
                record.update(
                    {
                        "completed_at": time.time(),
                        "error": "diagnostic_session_changed",
                    }
                )
                self._upsert_recent_locked(record)
                return self._public_record(record)
            if capture.sample_rate is None:
                capture.sample_rate = int(sample_rate)
            elif capture.sample_rate != int(sample_rate):
                self._active.pop(device_id, None)
                record = self._record_for(capture, status="failed")
                record.update(
                    {
                        "completed_at": time.time(),
                        "error": "diagnostic_sample_rate_changed",
                    }
                )
                self._upsert_recent_locked(record)
                return self._public_record(record)

            target_bytes = capture.duration_seconds * capture.sample_rate * 2
            remaining = max(0, target_bytes - len(capture.pcm))
            capture.pcm.extend(pcm_s16le[:remaining])
            progress = self._record_for(capture, status="capturing")
            self._upsert_recent_locked(progress)
            if len(capture.pcm) < target_bytes:
                return None

            self._active.pop(device_id, None)
            record = self._record_for(capture, status="persisting")
            record["completed_at"] = time.time()
            self._upsert_recent_locked(record)
            future = self._executor.submit(
                self._persist,
                record,
                bytes(capture.pcm),
            )
            self._futures.add(future)
            future.add_done_callback(self._forget_future)
            return self._public_record(record)

    def _record_for(
        self,
        capture: _ActiveCapture,
        *,
        status: str,
    ) -> dict[str, Any]:
        sample_rate = capture.sample_rate
        captured_ms = (
            round(len(capture.pcm) / 2 / sample_rate * 1000)
            if sample_rate
            else 0
        )
        return {
            "schema_version": 1,
            "capture_id": capture.capture_id,
            "device_id": capture.device_id,
            "session_id": capture.session_id,
            "status": status,
            "source": "gateway_received_afe_output",
            "duration_seconds": capture.duration_seconds,
            "captured_ms": captured_ms,
            "sample_rate": sample_rate,
            "created_at": capture.created_at,
            "nas_sync_status": "disabled" if self.nas_root is None else "pending",
        }

    def _persist(self, record: dict[str, Any], pcm_s16le: bytes) -> None:
        capture_id = str(record["capture_id"])
        try:
            if self.root is None:
                raise OSError("diagnostic_capture_root_disabled")
            wav_bytes = pcm_to_wav(pcm_s16le, int(record["sample_rate"]))
            digest = hashlib.sha256(wav_bytes).hexdigest()
            destination = self.root / capture_id
            temporary = self.root / f".{capture_id}.tmp-{os.getpid()}"
            if temporary.exists():
                shutil.rmtree(temporary)
            temporary.mkdir(parents=True, exist_ok=False)
            wav_path = temporary / "capture.wav"
            wav_path.write_bytes(wav_bytes)

            final_record = {
                **record,
                "status": "ready",
                "sha256": digest,
                "bytes": len(wav_bytes),
                "local_wav_path": str(destination / "capture.wav"),
                "error": "",
            }
            self._write_manifest(temporary / "manifest.json", final_record)
            if destination.exists():
                shutil.rmtree(destination)
            os.replace(temporary, destination)

            if self.nas_root is not None:
                try:
                    nas_destination = self.nas_root / capture_id
                    nas_temporary = self.nas_root / f".{capture_id}.tmp-{os.getpid()}"
                    self.nas_root.mkdir(parents=True, exist_ok=True)
                    if nas_temporary.exists():
                        shutil.rmtree(nas_temporary)
                    shutil.copytree(destination, nas_temporary)
                    if nas_destination.exists():
                        shutil.rmtree(nas_destination)
                    os.replace(nas_temporary, nas_destination)
                    final_record["nas_sync_status"] = "synced"
                    final_record["nas_wav_path"] = str(
                        nas_destination / "capture.wav"
                    )
                    self._write_manifest(
                        nas_destination / "manifest.json",
                        final_record,
                    )
                except OSError as exc:
                    final_record["nas_sync_status"] = "failed"
                    final_record["error"] = f"nas_sync_{type(exc).__name__}"
            self._write_manifest(destination / "manifest.json", final_record)
            with self._lock:
                self._upsert_recent_locked(final_record)
            self._prune_local_captures()
        except Exception as exc:
            LOGGER.exception("Unable to persist diagnostic audio capture")
            failed = {
                **record,
                "status": "failed",
                "error": type(exc).__name__,
            }
            with self._lock:
                self._upsert_recent_locked(failed)

    def _prune_local_captures(self) -> None:
        if self.root is None or not self.root.is_dir():
            return
        manifests: list[tuple[float, Path]] = []
        for manifest_path in self.root.glob("*/manifest.json"):
            try:
                payload = json.loads(manifest_path.read_text(encoding="utf-8"))
                created_at = float(payload.get("created_at") or 0)
            except (OSError, TypeError, ValueError, json.JSONDecodeError):
                created_at = manifest_path.stat().st_mtime
            manifests.append((created_at, manifest_path.parent))
        manifests.sort(key=lambda item: item[0], reverse=True)
        for _created_at, capture_path in manifests[self.recent_limit :]:
            try:
                shutil.rmtree(capture_path)
            except OSError:
                LOGGER.warning(
                    "Unable to prune diagnostic audio capture %s",
                    capture_path,
                    exc_info=True,
                )

    @staticmethod
    def _write_manifest(path: Path, payload: dict[str, Any]) -> None:
        temporary = path.with_name(f".{path.name}.tmp-{threading.get_ident()}")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
            + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, path)

    def _upsert_recent_locked(self, record: dict[str, Any]) -> None:
        capture_id = record["capture_id"]
        self._recent = [
            item
            for item in self._recent
            if item.get("capture_id") != capture_id
        ]
        self._recent.insert(0, self._public_record(record))
        del self._recent[self.recent_limit :]

    def _forget_future(self, future: Future[None]) -> None:
        with self._lock:
            self._futures.discard(future)

    def snapshot(self, device_id: str | None = None) -> dict[str, Any]:
        with self._lock:
            active = [
                self._public_record(self._record_for(capture, status="capturing"))
                for capture in self._active.values()
                if device_id is None or capture.device_id == device_id
            ]
            recent = [
                deepcopy(item)
                for item in self._recent
                if device_id is None or item.get("device_id") == device_id
            ]
        return {
            "enabled": self.root is not None,
            "default_state": "off",
            "max_capture_seconds": MAX_CAPTURE_SECONDS,
            "source": "gateway_received_afe_output",
            "active": active,
            "recent": recent,
            "nas_sync_enabled": self.nas_root is not None,
        }

    def wait_for_idle(self, timeout: float = 5.0) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with self._lock:
                pending = list(self._futures)
            if not pending:
                return True
            for future in pending:
                try:
                    future.result(timeout=max(0.01, deadline - time.monotonic()))
                except TimeoutError:
                    return False
        return False

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            self._active.clear()
        self.wait_for_idle()
        self._executor.shutdown(wait=True, cancel_futures=False)
