/*
 * SPDX-FileCopyrightText: 2026 M5Stack Technology CO LTD
 *
 * SPDX-License-Identifier: MIT
 */
#pragma once

#include <string>

namespace hal_bridge {

// Returns a bounded, read-only device identity/configuration receipt.
// Credentials, SSID, audio, transcripts, and user content are intentionally omitted.
std::string board_get_davie_device_attestation_json();

}  // namespace hal_bridge
