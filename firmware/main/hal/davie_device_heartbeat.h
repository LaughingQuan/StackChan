#pragma once

namespace davie::device {

// Starts one low-priority task that reports idle device availability without
// keeping a conversational WebSocket open.
void StartHeartbeat();

}  // namespace davie::device
