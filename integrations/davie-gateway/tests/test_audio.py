from __future__ import annotations

import struct

from stackchan_davie_gateway.audio import PcmEndpointDetector, pcm_to_wav, wav_to_pcm


def _frame(amplitude: int, samples: int = 960) -> bytes:
    return struct.pack(f"<{samples}h", *([amplitude] * samples))


def test_endpoint_ignores_noise_then_commits_speech() -> None:
    detector = PcmEndpointDetector(
        frame_duration_ms=60,
        silence_ms=300,
        min_speech_ms=180,
        max_turn_ms=5000,
        min_rms=400,
    )
    for _ in range(8):
        assert detector.feed(_frame(80)).complete_pcm is None
    started = False
    for _ in range(5):
        started = detector.feed(_frame(1800)).speech_started or started
    assert started
    completed = None
    for _ in range(6):
        completed = detector.feed(_frame(20)).complete_pcm or completed
    assert completed is not None
    assert len(completed) > 5 * 960 * 2


def test_pcm_wav_round_trip() -> None:
    pcm = _frame(900) * 3
    assert wav_to_pcm(pcm_to_wav(pcm, 16000), 16000) == pcm
