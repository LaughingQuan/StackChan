from __future__ import annotations

import asyncio
import ctypes
import ctypes.util
import io
import math
import os
import subprocess
import wave
from collections import deque
from dataclasses import dataclass
from pathlib import Path


class OpusError(RuntimeError):
    pass


def _find_opus_library() -> str | None:
    candidates = [
        os.environ.get("STACKCHAN_LIBOPUS", ""),
        ctypes.util.find_library("opus") or "",
        "/opt/homebrew/lib/libopus.dylib",
        "/usr/local/lib/libopus.dylib",
        "/usr/lib/aarch64-linux-gnu/libopus.so.0",
        "/usr/lib/x86_64-linux-gnu/libopus.so.0",
        "/usr/lib/libopus.so.0",
    ]
    for candidate in candidates:
        if not candidate:
            continue
        if "/" not in candidate or Path(candidate).is_file():
            return candidate
    return None


class OpusCodec:
    """Small libopus wrapper for raw Xiaozhi Opus packets."""

    def __init__(self, input_rate: int, output_rate: int, frame_duration_ms: int = 60):
        library = _find_opus_library()
        if not library:
            raise OpusError("libopus is not installed")
        self._lib = ctypes.CDLL(library)
        self._configure_ffi()
        self.input_rate = input_rate
        self.output_rate = output_rate
        self.frame_duration_ms = frame_duration_ms
        error = ctypes.c_int()
        self._decoder = self._lib.opus_decoder_create(input_rate, 1, ctypes.byref(error))
        if not self._decoder or error.value != 0:
            raise OpusError(f"failed to create Opus decoder: {error.value}")
        self._encoder = self._lib.opus_encoder_create(output_rate, 1, 2049, ctypes.byref(error))
        if not self._encoder or error.value != 0:
            self._lib.opus_decoder_destroy(self._decoder)
            self._decoder = None
            raise OpusError(f"failed to create Opus encoder: {error.value}")

    def _configure_ffi(self) -> None:
        self._lib.opus_decoder_create.argtypes = [ctypes.c_int32, ctypes.c_int, ctypes.POINTER(ctypes.c_int)]
        self._lib.opus_decoder_create.restype = ctypes.c_void_p
        self._lib.opus_decode.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_ubyte),
            ctypes.c_int32,
            ctypes.POINTER(ctypes.c_int16),
            ctypes.c_int,
            ctypes.c_int,
        ]
        self._lib.opus_decode.restype = ctypes.c_int
        self._lib.opus_decoder_destroy.argtypes = [ctypes.c_void_p]
        self._lib.opus_encoder_create.argtypes = [
            ctypes.c_int32,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.POINTER(ctypes.c_int),
        ]
        self._lib.opus_encoder_create.restype = ctypes.c_void_p
        self._lib.opus_encode.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_int16),
            ctypes.c_int,
            ctypes.POINTER(ctypes.c_ubyte),
            ctypes.c_int32,
        ]
        self._lib.opus_encode.restype = ctypes.c_int
        self._lib.opus_encoder_destroy.argtypes = [ctypes.c_void_p]

    def decode(self, packet: bytes) -> bytes:
        packet_buffer = (ctypes.c_ubyte * len(packet)).from_buffer_copy(packet)
        max_samples = self.input_rate * self.frame_duration_ms // 1000
        pcm = (ctypes.c_int16 * max_samples)()
        decoded = self._lib.opus_decode(self._decoder, packet_buffer, len(packet), pcm, max_samples, 0)
        if decoded < 0:
            raise OpusError(f"Opus decode failed: {decoded}")
        return bytes(memoryview(pcm).cast("B")[: decoded * 2])

    def encode(self, pcm_s16le: bytes) -> bytes:
        frame_samples = self.output_rate * self.frame_duration_ms // 1000
        if len(pcm_s16le) != frame_samples * 2:
            raise OpusError("PCM frame has the wrong duration")
        pcm = (ctypes.c_int16 * frame_samples).from_buffer_copy(pcm_s16le)
        output = (ctypes.c_ubyte * 4096)()
        encoded = self._lib.opus_encode(self._encoder, pcm, frame_samples, output, len(output))
        if encoded < 0:
            raise OpusError(f"Opus encode failed: {encoded}")
        return bytes(output[:encoded])

    def close(self) -> None:
        if getattr(self, "_decoder", None):
            self._lib.opus_decoder_destroy(self._decoder)
            self._decoder = None
        if getattr(self, "_encoder", None):
            self._lib.opus_encoder_destroy(self._encoder)
            self._encoder = None


def pcm_rms(pcm_s16le: bytes) -> int:
    if len(pcm_s16le) < 2:
        return 0
    sample_count = len(pcm_s16le) // 2
    samples = memoryview(pcm_s16le[: sample_count * 2]).cast("h")
    energy = sum(int(sample) * int(sample) for sample in samples)
    return int(math.sqrt(energy / sample_count)) if sample_count else 0


@dataclass(frozen=True)
class EndpointResult:
    speech_started: bool = False
    speech_abandoned: bool = False
    complete_pcm: bytes | None = None
    rms: int = 0
    threshold: int = 0
    captured_ms: int = 0
    voiced_ms: int = 0
    peak_rms: int = 0
    mean_rms: int = 0


class PcmEndpointDetector:
    def __init__(
        self,
        *,
        frame_duration_ms: int,
        silence_ms: int,
        min_speech_ms: int,
        max_turn_ms: int,
        min_rms: int,
    ):
        self.frame_duration_ms = frame_duration_ms
        self.silence_frames = max(1, silence_ms // frame_duration_ms)
        self.min_speech_frames = max(1, min_speech_ms // frame_duration_ms)
        self.max_turn_frames = max(1, max_turn_ms // frame_duration_ms)
        self.min_rms = min_rms
        self.start_frames = max(2, 120 // frame_duration_ms)
        self.pre_roll_frames = max(2, 300 // frame_duration_ms)
        self._last_rms = 0
        self._last_threshold = min_rms
        self._completed_turns = 0
        self._discarded_flushes = 0
        self._last_completed_ms = 0
        self._last_completed_voiced_ms = 0
        self._last_completed_peak_rms = 0
        self._last_completed_mean_rms = 0
        self.reset()

    def reset(self) -> None:
        self._pre_roll: deque[bytes] = deque(maxlen=self.pre_roll_frames)
        self._pre_roll_rms: deque[int] = deque(maxlen=self.pre_roll_frames)
        self._frames: list[bytes] = []
        self._speaking = False
        self._candidate_frames = 0
        self._voiced_frames = 0
        self._silence_frames = 0
        self._noise_floor = 120.0
        self._turn_rms_total = 0
        self._turn_rms_count = 0
        self._turn_peak_rms = 0

    def _threshold(self) -> int:
        return max(self.min_rms, int(self._noise_floor * 2.8))

    def feed(self, pcm_s16le: bytes) -> EndpointResult:
        rms = pcm_rms(pcm_s16le)
        threshold = self._threshold()
        self._last_rms = rms
        self._last_threshold = threshold
        voiced = rms >= threshold
        speech_started = False

        if not self._speaking:
            self._pre_roll.append(pcm_s16le)
            self._pre_roll_rms.append(rms)
            if voiced:
                self._candidate_frames += 1
            else:
                self._candidate_frames = 0
                self._noise_floor = (self._noise_floor * 0.97) + (rms * 0.03)
            if self._candidate_frames >= self.start_frames:
                self._speaking = True
                speech_started = True
                self._frames = list(self._pre_roll)
                self._turn_rms_total = sum(self._pre_roll_rms)
                self._turn_rms_count = len(self._pre_roll_rms)
                self._turn_peak_rms = max(self._pre_roll_rms, default=0)
                self._voiced_frames = self._candidate_frames
                self._silence_frames = 0
            return EndpointResult(speech_started=speech_started, rms=rms, threshold=threshold)

        self._frames.append(pcm_s16le)
        self._turn_rms_total += rms
        self._turn_rms_count += 1
        self._turn_peak_rms = max(self._turn_peak_rms, rms)
        if voiced:
            self._voiced_frames += 1
            self._silence_frames = 0
        else:
            self._silence_frames += 1

        complete = False
        if self._silence_frames >= self.silence_frames:
            if self._voiced_frames >= self.min_speech_frames:
                complete = True
            else:
                self._discarded_flushes += 1
                self.reset()
                return EndpointResult(
                    speech_abandoned=True,
                    rms=rms,
                    threshold=threshold,
                )
        if len(self._frames) >= self.max_turn_frames:
            complete = True
        if not complete:
            return EndpointResult(rms=rms, threshold=threshold)

        return self._complete_result(rms=rms, threshold=threshold)

    def flush(self) -> bytes | None:
        return self.flush_result().complete_pcm

    def flush_result(self) -> EndpointResult:
        if not self._frames or self._voiced_frames < self.min_speech_frames:
            self._discarded_flushes += 1
            self.reset()
            return EndpointResult(rms=self._last_rms, threshold=self._last_threshold)
        return self._complete_result(rms=self._last_rms, threshold=self._last_threshold)

    def _complete_result(self, *, rms: int, threshold: int) -> EndpointResult:
        captured = b"".join(self._frames)
        captured_ms = len(self._frames) * self.frame_duration_ms
        voiced_ms = self._voiced_frames * self.frame_duration_ms
        mean_rms = (
            int(self._turn_rms_total / self._turn_rms_count)
            if self._turn_rms_count
            else 0
        )
        result = EndpointResult(
            complete_pcm=captured,
            rms=rms,
            threshold=threshold,
            captured_ms=captured_ms,
            voiced_ms=voiced_ms,
            peak_rms=self._turn_peak_rms,
            mean_rms=mean_rms,
        )
        self._completed_turns += 1
        self._last_completed_ms = captured_ms
        self._last_completed_voiced_ms = voiced_ms
        self._last_completed_peak_rms = self._turn_peak_rms
        self._last_completed_mean_rms = mean_rms
        self.reset()
        return result

    def snapshot(self) -> dict[str, int | float | bool]:
        return {
            "rms": self._last_rms,
            "threshold": self._last_threshold,
            "noise_floor": round(self._noise_floor, 1),
            "speaking": self._speaking,
            "candidate_ms": self._candidate_frames * self.frame_duration_ms,
            "voiced_ms": self._voiced_frames * self.frame_duration_ms,
            "silence_ms": self._silence_frames * self.frame_duration_ms,
            "captured_ms": len(self._frames) * self.frame_duration_ms,
            "completed_turns": self._completed_turns,
            "discarded_flushes": self._discarded_flushes,
            "last_completed_ms": self._last_completed_ms,
            "last_completed_voiced_ms": self._last_completed_voiced_ms,
            "last_completed_peak_rms": self._last_completed_peak_rms,
            "last_completed_mean_rms": self._last_completed_mean_rms,
        }


def pcm_to_wav(pcm_s16le: bytes, sample_rate: int) -> bytes:
    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(pcm_s16le)
    return output.getvalue()


def wav_to_pcm(wav_bytes: bytes, target_sample_rate: int) -> bytes:
    try:
        with wave.open(io.BytesIO(wav_bytes), "rb") as wav:
            if wav.getnchannels() == 1 and wav.getsampwidth() == 2 and wav.getframerate() == target_sample_rate:
                return wav.readframes(wav.getnframes())
    except wave.Error:
        pass
    result = subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            "pipe:0",
            "-f",
            "s16le",
            "-acodec",
            "pcm_s16le",
            "-ac",
            "1",
            "-ar",
            str(target_sample_rate),
            "pipe:1",
        ],
        input=wav_bytes,
        capture_output=True,
        check=False,
        timeout=30,
    )
    if result.returncode != 0 or not result.stdout:
        raise RuntimeError("ffmpeg could not normalize synthesized speech")
    return result.stdout


async def wav_to_pcm_async(wav_bytes: bytes, target_sample_rate: int) -> bytes:
    try:
        with wave.open(io.BytesIO(wav_bytes), "rb") as wav:
            if wav.getnchannels() == 1 and wav.getsampwidth() == 2 and wav.getframerate() == target_sample_rate:
                return wav.readframes(wav.getnframes())
    except wave.Error:
        pass

    process = await asyncio.create_subprocess_exec(
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        "pipe:0",
        "-f",
        "s16le",
        "-acodec",
        "pcm_s16le",
        "-ac",
        "1",
        "-ar",
        str(target_sample_rate),
        "pipe:1",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, _stderr = await asyncio.wait_for(process.communicate(wav_bytes), timeout=30)
    except (asyncio.CancelledError, TimeoutError):
        process.kill()
        await process.wait()
        raise
    if process.returncode != 0 or not stdout:
        raise RuntimeError("ffmpeg could not normalize synthesized speech")
    return stdout


def iter_pcm_frames(pcm_s16le: bytes, *, sample_rate: int, frame_duration_ms: int):
    frame_bytes = sample_rate * frame_duration_ms // 1000 * 2
    for offset in range(0, len(pcm_s16le), frame_bytes):
        frame = pcm_s16le[offset : offset + frame_bytes]
        if len(frame) < frame_bytes:
            frame = frame + (b"\0" * (frame_bytes - len(frame)))
        yield frame
