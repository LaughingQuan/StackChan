#pragma once

#include <algorithm>
#include <cstddef>
#include <cstdint>

namespace davie::audio {

constexpr std::size_t kWakeInferencePreRollFrames = 8;
constexpr std::size_t kWakeInferenceStartFrames = 2;
constexpr std::size_t kWakeInferenceEndSilenceFrames = 8;
constexpr std::size_t kWakeInferenceMaxSpeechFrames = 96;
constexpr std::size_t kWakeInferenceRearmQuietFrames = 16;
constexpr uint32_t kWakeInferenceMinimumRms = 280;

struct WakeInferenceDecision {
    bool starts_segment = false;
    bool flush_pre_roll = false;
    bool process_frame = false;
    bool ends_segment = false;
    uint32_t threshold_rms = kWakeInferenceMinimumRms;
};

// MultiNet is slower than real time on the CoreS3 when its model resides in
// PSRAM, so idle audio must not enter the inference queue. This gate uses raw
// microphone energy only to locate bounded candidate phrases; MultiNet remains
// the authority that decides whether the phrase is "Davie".
class DavieWakeInferenceGate {
public:
    WakeInferenceDecision OnFrame(uint32_t rms)
    {
        WakeInferenceDecision decision;
        decision.threshold_rms = DetectionThresholdRms();

        if (suppressed_until_quiet_) {
            if (rms < decision.threshold_rms) {
                UpdateNoiseFloor(rms);
                ++rearm_quiet_frames_;
                if (rearm_quiet_frames_ >= kWakeInferenceRearmQuietFrames) {
                    suppressed_until_quiet_ = false;
                    rearm_quiet_frames_ = 0;
                }
            } else {
                rearm_quiet_frames_ = 0;
            }
            return decision;
        }

        if (!speech_active_) {
            if (rms < decision.threshold_rms) {
                UpdateNoiseFloor(rms);
            }

            if (rms >= decision.threshold_rms) {
                ++start_frames_;
            } else {
                start_frames_ = 0;
            }
            if (start_frames_ < kWakeInferenceStartFrames) {
                return decision;
            }

            speech_active_ = true;
            speech_frames_ = start_frames_;
            start_frames_ = 0;
            silence_frames_ = 0;
            decision.starts_segment = true;
            decision.flush_pre_roll = true;
            return decision;
        }

        decision.process_frame = true;
        ++speech_frames_;
        if (rms >= decision.threshold_rms) {
            silence_frames_ = 0;
        } else {
            ++silence_frames_;
        }

        const bool ended_by_silence =
            silence_frames_ >= kWakeInferenceEndSilenceFrames;
        const bool ended_by_limit =
            speech_frames_ >= kWakeInferenceMaxSpeechFrames;
        if (ended_by_silence || ended_by_limit) {
            decision.ends_segment = true;
            speech_active_ = false;
            start_frames_ = 0;
            silence_frames_ = 0;
            speech_frames_ = 0;
            if (ended_by_limit) {
                // A fan, TV, or other sustained loud source must not enqueue a
                // fresh maximum-length candidate every few seconds. Require a
                // real quiet window before arming another candidate.
                suppressed_until_quiet_ = true;
                rearm_quiet_frames_ = 0;
            }
        }
        return decision;
    }

    void Reset()
    {
        speech_active_ = false;
        start_frames_ = 0;
        silence_frames_ = 0;
        speech_frames_ = 0;
        suppressed_until_quiet_ = false;
        rearm_quiet_frames_ = 0;
        noise_floor_rms_ = kInitialNoiseFloorRms;
    }

    bool IsSpeechActive() const { return speech_active_; }
    bool IsSuppressed() const { return suppressed_until_quiet_; }
    std::size_t SpeechFrames() const { return speech_frames_; }
    uint32_t DetectionThresholdRms() const
    {
        const float dynamic_threshold =
            noise_floor_rms_ * kNoiseMultiplier + kNoiseMarginRms;
        return std::max(
            kWakeInferenceMinimumRms,
            static_cast<uint32_t>(dynamic_threshold));
    }
    float NoiseFloorRms() const { return noise_floor_rms_; }

private:
    void UpdateNoiseFloor(uint32_t rms)
    {
        noise_floor_rms_ =
            noise_floor_rms_ * (1.0f - kNoiseLearningRate) +
            static_cast<float>(rms) * kNoiseLearningRate;
    }

    static constexpr float kInitialNoiseFloorRms = 24.0f;
    static constexpr float kNoiseLearningRate = 0.02f;
    static constexpr float kNoiseMultiplier = 4.0f;
    static constexpr float kNoiseMarginRms = 64.0f;

    bool speech_active_ = false;
    std::size_t start_frames_ = 0;
    std::size_t silence_frames_ = 0;
    std::size_t speech_frames_ = 0;
    bool suppressed_until_quiet_ = false;
    std::size_t rearm_quiet_frames_ = 0;
    float noise_floor_rms_ = kInitialNoiseFloorRms;
};

}  // namespace davie::audio
