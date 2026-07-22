from __future__ import annotations

import html
import json
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable


_HTML_TAG = re.compile(r"<[^>]+>")
_SENTENCE = re.compile(r"(?<=[.!?。！？])(?:[\"'”’)]*)\s+")


def reader_segments(value: str, *, max_chars: int = 360) -> list[str]:
    text = html.unescape(_HTML_TAG.sub(" ", value.replace("\r\n", "\n")))
    paragraphs = [" ".join(part.split()) for part in re.split(r"\n\s*\n|\n", text) if part.strip()]
    units: list[str] = []
    for paragraph in paragraphs:
        units.extend(part.strip() for part in _SENTENCE.split(paragraph) if part.strip())

    segments: list[str] = []
    for unit in units:
        while len(unit) > max_chars:
            split_at = unit.rfind(" ", 0, max_chars + 1)
            if split_at < max_chars // 2:
                split_at = max_chars
            prefix, unit = unit[:split_at].strip(), unit[split_at:].strip()
            if prefix:
                segments.append(prefix)
        if unit:
            segments.append(unit)
    return segments


@dataclass
class ReaderState:
    device_id: str
    title: str = ""
    segments: list[str] = field(default_factory=list)
    index: int = 0
    state: str = "idle"
    loaded_at: float | None = None
    updated_at: float = field(default_factory=time.time)
    _on_change: Callable[[], None] | None = field(default=None, repr=False, compare=False)

    def load(self, title: str, text: str) -> None:
        segments = reader_segments(text)
        if not segments:
            raise ValueError("reader content is empty")
        self.title = title.strip() or "Untitled reading"
        self.segments = segments
        self.index = 0
        self.state = "ready"
        self.loaded_at = time.time()
        self._changed()

    def resume(self) -> bool:
        if not self.segments or self.state == "completed":
            return False
        self.state = "playing"
        self._changed()
        return True

    def pause(self) -> bool:
        if not self.segments or self.state not in {"playing", "ready"}:
            return False
        self.state = "paused"
        self._changed()
        return True

    def stop(self) -> bool:
        if not self.segments:
            return False
        self.index = 0
        self.state = "stopped"
        self._changed()
        return True

    def clear(self) -> bool:
        if not self.segments:
            return False
        self.title = ""
        self.segments = []
        self.index = 0
        self.state = "idle"
        self.loaded_at = None
        self._changed()
        return True

    def current(self) -> str | None:
        if 0 <= self.index < len(self.segments):
            return self.segments[self.index]
        return None

    def advance(self) -> None:
        self.index += 1
        if self.index >= len(self.segments):
            self.index = len(self.segments)
            self.state = "completed"
        self._changed()

    def status(self) -> dict[str, object]:
        total = len(self.segments)
        return {
            "title": self.title,
            "state": self.state,
            "segment_index": self.index,
            "segment_number": min(self.index + 1, total) if total else 0,
            "segment_count": total,
            "progress_percent": round((self.index / total) * 100, 1) if total else 0.0,
            "loaded_at": self.loaded_at,
            "updated_at": self.updated_at,
            "resume_repeats_interrupted_segment": True,
        }

    def to_record(self) -> dict[str, object]:
        return {
            "device_id": self.device_id,
            "title": self.title,
            "segments": self.segments,
            "index": self.index,
            "state": "paused" if self.state == "playing" else self.state,
            "loaded_at": self.loaded_at,
            "updated_at": self.updated_at,
        }

    def _changed(self) -> None:
        self.updated_at = time.time()
        if self._on_change:
            self._on_change()


class ReaderLibrary:
    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path else None
        self._readers: dict[str, ReaderState] = {}
        self._load()

    def for_device(self, device_id: str) -> ReaderState:
        reader = self._readers.get(device_id)
        if reader is None:
            reader = ReaderState(device_id=device_id, _on_change=self.save)
            self._readers[device_id] = reader
        else:
            reader._on_change = self.save
        return reader

    def save(self) -> None:
        if self.path is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": 1,
            "devices": {device_id: state.to_record() for device_id, state in self._readers.items()},
        }
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        os.replace(temporary, self.path)

    def remove(self, device_id: str) -> bool:
        reader = self._readers.pop(device_id, None)
        if reader is None:
            return False
        reader._on_change = None
        self.save()
        return True

    def _load(self) -> None:
        if self.path is None or not self.path.exists():
            return
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            records = payload.get("devices", {}) if isinstance(payload, dict) else {}
            if not isinstance(records, dict):
                return
            for device_id, record in records.items():
                if not isinstance(device_id, str) or not isinstance(record, dict):
                    continue
                segments = record.get("segments")
                if not isinstance(segments, list) or not all(isinstance(item, str) for item in segments):
                    continue
                index = min(max(int(record.get("index", 0)), 0), len(segments))
                state = str(record.get("state") or "paused")
                if state not in {"idle", "ready", "paused", "stopped", "completed"}:
                    state = "paused"
                self._readers[device_id] = ReaderState(
                    device_id=device_id,
                    title=str(record.get("title") or ""),
                    segments=segments,
                    index=index,
                    state=state,
                    loaded_at=record.get("loaded_at") if isinstance(record.get("loaded_at"), (int, float)) else None,
                    updated_at=float(record.get("updated_at") or time.time()),
                    _on_change=self.save,
                )
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            self._readers = {}
