#include "audio/davie_post_wake_audio_bridge.h"

#include <cassert>
#include <cstdint>
#include <vector>

namespace {

std::vector<int16_t> Sequence(int16_t start, std::size_t count)
{
    std::vector<int16_t> values;
    values.reserve(count);
    for (std::size_t index = 0; index < count; ++index) {
        values.push_back(static_cast<int16_t>(start + index));
    }
    return values;
}

}  // namespace

int main()
{
    using davie::audio::PostWakeAudioBridge;

    PostWakeAudioBridge bridge(1000, 500, 2000);
    assert(!bridge.IsActive());
    bridge.Begin(2);
    assert(bridge.IsActive());
    assert(bridge.PreRollMilliseconds() == 500);
    assert(bridge.MaxCaptureMilliseconds() == 2000);

    assert(bridge.Append(Sequence(0, 400)));
    assert(bridge.BufferedMilliseconds() == 200);
    auto first = bridge.Take();
    assert(first.size() == 400);
    assert(first.front() == 0);
    assert(first.back() == 399);
    assert(!bridge.IsActive());

    bridge.Begin(1);
    assert(bridge.Append(Sequence(0, 400)));
    assert(bridge.Append(Sequence(400, 400)));
    auto wrapped = bridge.Take();
    assert(wrapped.size() == 500);
    assert(wrapped.front() == 300);
    assert(wrapped.back() == 799);

    bridge.Begin(2);
    assert(bridge.Append(Sequence(0, 1600)));
    auto stereo_wrapped = bridge.Take();
    assert(stereo_wrapped.size() == 1000);
    assert(stereo_wrapped.front() == 600);
    assert(stereo_wrapped[1] == 601);
    assert(stereo_wrapped[stereo_wrapped.size() - 2] == 1598);
    assert(stereo_wrapped.back() == 1599);

    bridge.Begin(2);
    assert(!bridge.Append(Sequence(0, 3)));
    assert(!bridge.IsActive());
    assert(bridge.Take().empty());

    bridge.Begin(1);
    assert(bridge.Append(Sequence(0, 1500)));
    assert(!bridge.Append(Sequence(1500, 500)));
    assert(!bridge.IsActive());
    assert(bridge.Take().empty());

    bridge.Begin(0);
    assert(!bridge.IsActive());
    bridge.Begin(1);
    bridge.Cancel();
    assert(!bridge.IsActive());
    assert(bridge.Take().empty());
    return 0;
}
