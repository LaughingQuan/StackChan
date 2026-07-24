#pragma once

#include <cstddef>

namespace davie::audio {

constexpr std::size_t kWakeInferenceMaxSpeechFrames = 100;

struct WakeInferenceDecision {
    bool starts_segment = false;
    bool prepend_vad_cache = false;
    bool process_frame = false;
    bool ends_segment = false;
    bool reset_model = false;
};

class DavieWakeInferenceGate {
public:
    WakeInferenceDecision OnFrame(bool is_speech, bool has_vad_cache)
    {
        if (!is_speech) {
            if (suppress_until_silence_) {
                suppress_until_silence_ = false;
                speech_active_ = false;
                speech_frames_ = 0;
                return {};
            }
            if (!speech_active_) {
                return {};
            }

            // VAD already preserves a configured silence tail. Feed the first
            // silence frame so MultiNet can close the phrase, then reset.
            speech_active_ = false;
            speech_frames_ = 0;
            WakeInferenceDecision decision;
            decision.process_frame = true;
            decision.ends_segment = true;
            decision.reset_model = true;
            return decision;
        }

        if (suppress_until_silence_) {
            return {};
        }

        const bool starts_speech = !speech_active_;
        speech_active_ = true;
        ++speech_frames_;
        if (speech_frames_ > kWakeInferenceMaxSpeechFrames) {
            speech_active_ = false;
            speech_frames_ = 0;
            suppress_until_silence_ = true;
            WakeInferenceDecision decision;
            decision.ends_segment = true;
            decision.reset_model = true;
            return decision;
        }

        WakeInferenceDecision decision;
        decision.starts_segment = starts_speech;
        decision.prepend_vad_cache = starts_speech && has_vad_cache;
        decision.process_frame = true;
        return decision;
    }

    void SuppressUntilSilence()
    {
        speech_active_ = false;
        speech_frames_ = 0;
        suppress_until_silence_ = true;
    }

    void Reset()
    {
        speech_active_ = false;
        suppress_until_silence_ = false;
        speech_frames_ = 0;
    }

    bool IsSpeechActive() const { return speech_active_; }
    bool IsSuppressed() const { return suppress_until_silence_; }
    std::size_t SpeechFrames() const { return speech_frames_; }

private:
    bool speech_active_ = false;
    bool suppress_until_silence_ = false;
    std::size_t speech_frames_ = 0;
};

}  // namespace davie::audio
