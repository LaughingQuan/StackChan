#include "audio/davie_wake_segment_coordinator.h"

#include <cassert>

using davie::audio::DavieWakeSegmentCoordinator;

int main()
{
    DavieWakeSegmentCoordinator coordinator;

    const auto first = coordinator.BeginCapture();
    assert(first.accepted);
    assert(first.segment_id != 0);
    assert(coordinator.IsCurrent(first.generation, first.segment_id));

    const auto same_capture = coordinator.BeginCapture();
    assert(same_capture.accepted);
    assert(same_capture.segment_id == first.segment_id);

    const auto first_end = coordinator.EndCapture();
    assert(first_end.accepted);
    assert(first_end.segment_id == first.segment_id);

    const auto busy = coordinator.BeginCapture();
    assert(!busy.accepted);
    assert(busy.segment_id == 0);
    coordinator.CancelCapture();
    const auto busy_end = coordinator.EndCapture();
    assert(!busy_end.accepted);

    assert(coordinator.FinishInference(first.generation, first.segment_id));
    assert(coordinator.PendingSegmentId() == 0);

    const auto cancelled = coordinator.BeginCapture();
    assert(cancelled.accepted);
    coordinator.CancelCapture();
    const auto cancelled_end = coordinator.EndCapture();
    assert(cancelled_end.cancelled);
    assert(coordinator.IsCancelled(cancelled.segment_id));
    assert(coordinator.FinishInference(
        cancelled.generation,
        cancelled.segment_id));
    assert(!coordinator.IsCancelled(cancelled.segment_id));

    const auto stale = coordinator.BeginCapture();
    assert(stale.accepted);
    coordinator.EndCapture();
    coordinator.Reset();
    assert(!coordinator.IsCurrent(stale.generation, stale.segment_id));
    assert(!coordinator.FinishInference(stale.generation, stale.segment_id));

    const auto current = coordinator.BeginCapture();
    assert(current.accepted);
    coordinator.EndCapture();
    assert(!coordinator.FinishInference(stale.generation, stale.segment_id));
    assert(coordinator.IsCurrent(current.generation, current.segment_id));
    assert(coordinator.FinishInference(
        current.generation,
        current.segment_id));

    return 0;
}
