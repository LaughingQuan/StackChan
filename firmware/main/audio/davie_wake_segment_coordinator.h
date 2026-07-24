#pragma once

#include <atomic>
#include <cstdint>

namespace davie::audio {

struct WakeSegmentIdentity {
    uint32_t generation = 0;
    uint32_t segment_id = 0;
    bool accepted = false;
    bool cancelled = false;
};

// Coordinates one capture segment with one asynchronous inference consumer.
// Capture-side methods must be serialized by the caller; inference queries are
// lock-free so the ESP32 audio front end never waits on the slower recognizer.
class DavieWakeSegmentCoordinator {
public:
    WakeSegmentIdentity BeginCapture()
    {
        if (capture_open_) {
            return CurrentCapture();
        }

        capture_open_ = true;
        capture_cancelled_ = false;
        capture_generation_ = generation_.load(std::memory_order_acquire);
        capture_segment_id_ = NextSegmentId();

        uint32_t expected = 0;
        capture_accepted_ = pending_segment_id_.compare_exchange_strong(
            expected,
            capture_segment_id_,
            std::memory_order_acq_rel,
            std::memory_order_acquire);
        if (!capture_accepted_) {
            capture_segment_id_ = 0;
        }
        return CurrentCapture();
    }

    void CancelCapture()
    {
        if (!capture_open_ || !capture_accepted_) {
            return;
        }
        capture_cancelled_ = true;
        cancelled_segment_id_.store(
            capture_segment_id_,
            std::memory_order_release);
    }

    WakeSegmentIdentity EndCapture()
    {
        WakeSegmentIdentity ended = CurrentCapture();
        capture_open_ = false;
        capture_accepted_ = false;
        capture_cancelled_ = false;
        capture_generation_ = 0;
        capture_segment_id_ = 0;
        return ended;
    }

    WakeSegmentIdentity CaptureIdentity() const
    {
        return CurrentCapture();
    }

    void Reset()
    {
        uint32_t next_generation =
            generation_.fetch_add(1, std::memory_order_acq_rel) + 1;
        if (next_generation == 0) {
            generation_.store(1, std::memory_order_release);
        }
        pending_segment_id_.store(0, std::memory_order_release);
        cancelled_segment_id_.store(0, std::memory_order_release);
        capture_open_ = false;
        capture_accepted_ = false;
        capture_cancelled_ = false;
        capture_generation_ = 0;
        capture_segment_id_ = 0;
    }

    bool IsCurrent(uint32_t generation, uint32_t segment_id) const
    {
        return segment_id != 0 &&
            generation_.load(std::memory_order_acquire) == generation &&
            pending_segment_id_.load(std::memory_order_acquire) == segment_id;
    }

    bool IsCancelled(uint32_t segment_id) const
    {
        return segment_id != 0 &&
            cancelled_segment_id_.load(std::memory_order_acquire) == segment_id;
    }

    bool FinishInference(uint32_t generation, uint32_t segment_id)
    {
        if (generation_.load(std::memory_order_acquire) != generation) {
            return false;
        }

        uint32_t expected = segment_id;
        if (!pending_segment_id_.compare_exchange_strong(
                expected,
                0,
                std::memory_order_acq_rel,
                std::memory_order_acquire)) {
            return false;
        }
        uint32_t cancelled = segment_id;
        cancelled_segment_id_.compare_exchange_strong(
            cancelled,
            0,
            std::memory_order_acq_rel,
            std::memory_order_acquire);
        return true;
    }

    uint32_t Generation() const
    {
        return generation_.load(std::memory_order_acquire);
    }

    uint32_t PendingSegmentId() const
    {
        return pending_segment_id_.load(std::memory_order_acquire);
    }

private:
    WakeSegmentIdentity CurrentCapture() const
    {
        return {
            .generation = capture_generation_,
            .segment_id = capture_segment_id_,
            .accepted = capture_accepted_,
            .cancelled = capture_cancelled_,
        };
    }

    uint32_t NextSegmentId()
    {
        uint32_t segment_id = next_segment_id_++;
        if (segment_id == 0) {
            segment_id = next_segment_id_++;
        }
        return segment_id;
    }

    std::atomic<uint32_t> generation_{1};
    std::atomic<uint32_t> pending_segment_id_{0};
    std::atomic<uint32_t> cancelled_segment_id_{0};
    uint32_t next_segment_id_ = 1;
    uint32_t capture_generation_ = 0;
    uint32_t capture_segment_id_ = 0;
    bool capture_open_ = false;
    bool capture_accepted_ = false;
    bool capture_cancelled_ = false;
};

}  // namespace davie::audio
