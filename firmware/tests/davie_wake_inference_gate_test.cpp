#include "audio/davie_wake_inference_gate.h"

#include <cassert>

using davie::audio::DavieWakeInferenceGate;
using davie::audio::kWakeInferenceMaxSpeechFrames;

int main()
{
    DavieWakeInferenceGate gate;

    auto decision = gate.OnFrame(false, false);
    assert(!decision.process_frame);
    assert(!decision.reset_model);

    decision = gate.OnFrame(true, true);
    assert(decision.prepend_vad_cache);
    assert(decision.process_frame);
    assert(!decision.reset_model);
    assert(gate.IsSpeechActive());

    decision = gate.OnFrame(true, true);
    assert(!decision.prepend_vad_cache);
    assert(decision.process_frame);
    assert(!decision.reset_model);

    decision = gate.OnFrame(false, false);
    assert(decision.process_frame);
    assert(decision.reset_model);
    assert(!gate.IsSpeechActive());

    decision = gate.OnFrame(false, false);
    assert(!decision.process_frame);
    assert(!decision.reset_model);

    gate.Reset();
    for (std::size_t frame = 0; frame < kWakeInferenceMaxSpeechFrames; ++frame) {
        decision = gate.OnFrame(true, frame == 0);
        assert(decision.process_frame);
        assert(!decision.reset_model);
    }
    decision = gate.OnFrame(true, false);
    assert(!decision.process_frame);
    assert(decision.reset_model);
    assert(gate.IsSuppressed());

    decision = gate.OnFrame(true, false);
    assert(!decision.process_frame);
    assert(!decision.reset_model);

    decision = gate.OnFrame(false, false);
    assert(!decision.process_frame);
    assert(!decision.reset_model);
    assert(!gate.IsSuppressed());

    decision = gate.OnFrame(true, true);
    assert(decision.prepend_vad_cache);
    assert(decision.process_frame);

    gate.SuppressUntilSilence();
    assert(gate.IsSuppressed());
    decision = gate.OnFrame(true, false);
    assert(!decision.process_frame);
    decision = gate.OnFrame(false, false);
    assert(!gate.IsSuppressed());

    gate.Reset();
    assert(!gate.IsSpeechActive());
    assert(!gate.IsSuppressed());
    assert(gate.SpeechFrames() == 0);

    return 0;
}
