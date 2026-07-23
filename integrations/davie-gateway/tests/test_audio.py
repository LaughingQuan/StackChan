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
    completed_result = None
    for _ in range(6):
        result = detector.feed(_frame(20))
        if result.complete_pcm:
            completed = result.complete_pcm
            completed_result = result
    assert completed is not None
    assert completed_result is not None
    assert completed_result.captured_ms > completed_result.voiced_ms >= 300
    assert completed_result.peak_rms == 1800
    assert completed_result.mean_rms > 0
    assert len(completed) > 5 * 960 * 2
    status = detector.snapshot()
    assert status["rms"] == 20
    assert status["threshold"] >= 400
    assert status["speaking"] is False
    assert status["completed_turns"] == 1
    assert status["last_completed_ms"] == completed_result.captured_ms
    assert status["last_completed_peak_rms"] == 1800


def test_endpoint_abandons_short_noise_burst_without_waiting_for_max_turn() -> None:
    detector = PcmEndpointDetector(
        frame_duration_ms=60,
        silence_ms=300,
        min_speech_ms=240,
        max_turn_ms=5000,
        min_rms=400,
    )
    detector.feed(_frame(1000))
    started = detector.feed(_frame(1000))
    assert started.speech_started is True
    result = None
    for _ in range(5):
        result = detector.feed(_frame(20))
    assert result is not None
    assert result.speech_abandoned is True
    assert result.complete_pcm is None
    assert detector.snapshot()["speaking"] is False
    assert detector.snapshot()["discarded_flushes"] == 1


def test_endpoint_snapshot_exposes_live_noise_and_candidate_state() -> None:
    detector = PcmEndpointDetector(
        frame_duration_ms=60,
        silence_ms=300,
        min_speech_ms=180,
        max_turn_ms=5000,
        min_rms=400,
    )
    detector.feed(_frame(100))
    detector.feed(_frame(900))
    status = detector.snapshot()
    assert status["rms"] == 900
    assert status["threshold"] >= 400
    assert status["noise_floor"] > 0
    assert status["candidate_ms"] == 60
    assert status["speaking"] is False


def test_pcm_wav_round_trip() -> None:
    pcm = _frame(900) * 3
    assert wav_to_pcm(pcm_to_wav(pcm, 16000), 16000) == pcm
