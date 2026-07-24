#pragma once

#include <cstddef>
#include <cstdint>
#include <mutex>
#include <vector>

namespace davie::audio {

inline constexpr std::size_t kPostWakePreRollMs = 500;
inline constexpr std::size_t kPostWakeMaxCaptureMs = 5000;

// Keeps a bounded slice of raw input while the application transitions from
// local wake detection to the conversation audio processor.
class PostWakeAudioBridge {
public:
    PostWakeAudioBridge(
        std::size_t sample_rate_hz = 16000,
        std::size_t pre_roll_ms = kPostWakePreRollMs,
        std::size_t max_capture_ms = kPostWakeMaxCaptureMs);

    void Begin(std::size_t channels);
    bool Append(const std::vector<int16_t>& interleaved_pcm);
    std::vector<int16_t> Take();
    void Cancel();

    bool IsActive() const;
    std::size_t BufferedMilliseconds() const;
    std::size_t PreRollMilliseconds() const { return pre_roll_ms_; }
    std::size_t MaxCaptureMilliseconds() const { return max_capture_ms_; }

private:
    const std::size_t sample_rate_hz_;
    const std::size_t pre_roll_ms_;
    const std::size_t max_capture_ms_;

    mutable std::mutex mutex_;
    std::vector<int16_t> ring_;
    std::size_t channels_ = 0;
    std::size_t write_index_ = 0;
    std::size_t buffered_samples_ = 0;
    std::size_t total_captured_samples_ = 0;
    std::size_t max_capture_samples_ = 0;
    bool active_ = false;

    void ResetLocked();
};

}  // namespace davie::audio
