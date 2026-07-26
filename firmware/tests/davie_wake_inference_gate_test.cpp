#include "audio/davie_wake_inference_gate.h"

#include <cassert>

using davie::audio::DavieWakeInferenceGate;
using davie::audio::kWakeInferenceEndSilenceFrames;
using davie::audio::kWakeInferenceMaxSpeechFrames;
using davie::audio::kWakeInferenceMinimumRms;
using davie::audio::kWakeInferenceRearmQuietFrames;

int main()
{
    DavieWakeInferenceGate gate;

    auto decision = gate.OnFrame(20);
    assert(!decision.process_frame);
    assert(!decision.starts_segment);
    assert(decision.threshold_rms == kWakeInferenceMinimumRms);

    for (int frame = 0; frame < 100; ++frame) {
        decision = gate.OnFrame(25);
        assert(!decision.starts_segment);
        assert(!decision.process_frame);
    }
    assert(gate.NoiseFloorRms() > 24.0f);

    // A single impulse is not enough to create a wake candidate.
    decision = gate.OnFrame(1200);
    assert(!decision.starts_segment);
    decision = gate.OnFrame(25);
    assert(!decision.starts_segment);

    // Two consecutive voiced frames open one candidate and flush pre-roll.
    decision = gate.OnFrame(1200);
    assert(!decision.starts_segment);
    decision = gate.OnFrame(1200);
    assert(decision.starts_segment);
    assert(decision.flush_pre_roll);
    assert(!decision.process_frame);
    assert(!decision.ends_segment);
    assert(gate.IsSpeechActive());

    decision = gate.OnFrame(1200);
    assert(!decision.starts_segment);
    assert(!decision.flush_pre_roll);
    assert(decision.process_frame);

    for (std::size_t frame = 1;
         frame < kWakeInferenceEndSilenceFrames;
         ++frame) {
        decision = gate.OnFrame(20);
        assert(decision.process_frame);
        assert(!decision.ends_segment);
    }
    decision = gate.OnFrame(20);
    assert(decision.process_frame);
    assert(decision.ends_segment);
    assert(!gate.IsSpeechActive());

    decision = gate.OnFrame(20);
    assert(!decision.process_frame);

    gate.Reset();
    decision = gate.OnFrame(1000);
    assert(!decision.starts_segment);
    decision = gate.OnFrame(1000);
    assert(decision.starts_segment);
    for (std::size_t frame = 2;
         frame < kWakeInferenceMaxSpeechFrames;
         ++frame) {
        decision = gate.OnFrame(1000);
        assert(decision.process_frame);
        assert(decision.ends_segment ==
               (frame + 1 == kWakeInferenceMaxSpeechFrames));
    }
    assert(!gate.IsSpeechActive());
    assert(gate.IsSuppressed());

    // Sustained loud ambient audio must produce only one bounded candidate.
    for (std::size_t frame = 0;
         frame < kWakeInferenceMaxSpeechFrames * 2;
         ++frame) {
        decision = gate.OnFrame(1000);
        assert(!decision.starts_segment);
        assert(!decision.process_frame);
        assert(!decision.ends_segment);
    }
    for (std::size_t frame = 1;
         frame < kWakeInferenceRearmQuietFrames;
         ++frame) {
        decision = gate.OnFrame(20);
        assert(gate.IsSuppressed());
    }
    decision = gate.OnFrame(20);
    assert(!gate.IsSuppressed());
    decision = gate.OnFrame(1000);
    assert(!decision.starts_segment);
    decision = gate.OnFrame(1000);
    assert(decision.starts_segment);

    gate.Reset();
    assert(!gate.IsSpeechActive());
    assert(!gate.IsSuppressed());
    assert(gate.SpeechFrames() == 0);
    assert(gate.DetectionThresholdRms() == kWakeInferenceMinimumRms);

    return 0;
}
