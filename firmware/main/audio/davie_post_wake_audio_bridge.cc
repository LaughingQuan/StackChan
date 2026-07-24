#include "davie_post_wake_audio_bridge.h"

#include <algorithm>

namespace davie::audio {

PostWakeAudioBridge::PostWakeAudioBridge(
    std::size_t sample_rate_hz,
    std::size_t pre_roll_ms,
    std::size_t max_capture_ms)
    : sample_rate_hz_(sample_rate_hz),
      pre_roll_ms_(pre_roll_ms),
      max_capture_ms_(max_capture_ms)
{
}

void PostWakeAudioBridge::Begin(std::size_t channels)
{
    std::lock_guard<std::mutex> lock(mutex_);
    ResetLocked();
    if (sample_rate_hz_ == 0 || pre_roll_ms_ == 0 || max_capture_ms_ == 0 || channels == 0) {
        return;
    }

    channels_ = channels;
    const std::size_t capacity =
        (sample_rate_hz_ * pre_roll_ms_ / 1000) * channels_;
    max_capture_samples_ =
        (sample_rate_hz_ * max_capture_ms_ / 1000) * channels_;
    if (capacity == 0 || max_capture_samples_ == 0) {
        ResetLocked();
        return;
    }

    ring_.assign(capacity, 0);
    active_ = true;
}

bool PostWakeAudioBridge::Append(const std::vector<int16_t>& interleaved_pcm)
{
    std::lock_guard<std::mutex> lock(mutex_);
    if (!active_ || ring_.empty() || interleaved_pcm.empty()) {
        return active_;
    }
    if (channels_ == 0 || interleaved_pcm.size() % channels_ != 0) {
        // Never retain a partial interleaved frame; replaying one would swap
        // microphone/reference channel alignment for every following sample.
        ResetLocked();
        return false;
    }

    const std::size_t remaining =
        max_capture_samples_ > total_captured_samples_
            ? max_capture_samples_ - total_captured_samples_
            : 0;
    const std::size_t accepted = std::min(remaining, interleaved_pcm.size());
    for (std::size_t index = 0; index < accepted; ++index) {
        ring_[write_index_] = interleaved_pcm[index];
        write_index_ = (write_index_ + 1) % ring_.size();
        buffered_samples_ = std::min(buffered_samples_ + 1, ring_.size());
    }
    total_captured_samples_ += accepted;

    if (accepted < interleaved_pcm.size() ||
        total_captured_samples_ >= max_capture_samples_) {
        // A conversation that did not become ready within the bounded window
        // must not replay stale speech later.
        ResetLocked();
        return false;
    }
    return true;
}

std::vector<int16_t> PostWakeAudioBridge::Take()
{
    std::lock_guard<std::mutex> lock(mutex_);
    if (!active_ || buffered_samples_ == 0 || ring_.empty()) {
        ResetLocked();
        return {};
    }

    std::vector<int16_t> result;
    result.reserve(buffered_samples_);
    const std::size_t start =
        (write_index_ + ring_.size() - buffered_samples_) % ring_.size();
    for (std::size_t index = 0; index < buffered_samples_; ++index) {
        result.push_back(ring_[(start + index) % ring_.size()]);
    }
    ResetLocked();
    return result;
}

void PostWakeAudioBridge::Cancel()
{
    std::lock_guard<std::mutex> lock(mutex_);
    ResetLocked();
}

bool PostWakeAudioBridge::IsActive() const
{
    std::lock_guard<std::mutex> lock(mutex_);
    return active_;
}

std::size_t PostWakeAudioBridge::BufferedMilliseconds() const
{
    std::lock_guard<std::mutex> lock(mutex_);
    if (channels_ == 0 || sample_rate_hz_ == 0) {
        return 0;
    }
    return (buffered_samples_ / channels_) * 1000 / sample_rate_hz_;
}

void PostWakeAudioBridge::ResetLocked()
{
    ring_.clear();
    channels_ = 0;
    write_index_ = 0;
    buffered_samples_ = 0;
    total_captured_samples_ = 0;
    max_capture_samples_ = 0;
    active_ = false;
}

}  // namespace davie::audio
