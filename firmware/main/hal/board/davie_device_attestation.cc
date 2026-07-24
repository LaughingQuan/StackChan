/*
 * SPDX-FileCopyrightText: 2026 M5Stack Technology CO LTD
 *
 * SPDX-License-Identifier: MIT
 */
#include "davie_device_attestation.h"

#include "audio/davie_post_wake_audio_bridge.h"
#include "audio/davie_wake_inference_gate.h"
#include "config.h"
#include "hal_bridge.h"

#include <cJSON.h>
#include <esp_app_desc.h>
#include <esp_heap_caps.h>
#include <esp_system.h>
#include <esp_timer.h>
#include <wifi_manager.h>

#include <cstdio>
#include <memory>

#ifndef STACKCHAN_DAVIE_SOURCE_REVISION
#define STACKCHAN_DAVIE_SOURCE_REVISION "unknown"
#endif

namespace {

struct CJsonDeleter {
    void operator()(cJSON* value) const
    {
        cJSON_Delete(value);
    }
};

using CJsonPtr = std::unique_ptr<cJSON, CJsonDeleter>;

const char* reset_reason_name(esp_reset_reason_t reason)
{
    switch (reason) {
        case ESP_RST_UNKNOWN:
            return "unknown";
        case ESP_RST_POWERON:
            return "power_on";
        case ESP_RST_EXT:
            return "external";
        case ESP_RST_SW:
            return "software";
        case ESP_RST_PANIC:
            return "panic";
        case ESP_RST_INT_WDT:
            return "interrupt_watchdog";
        case ESP_RST_TASK_WDT:
            return "task_watchdog";
        case ESP_RST_WDT:
            return "watchdog";
        case ESP_RST_DEEPSLEEP:
            return "deep_sleep";
        case ESP_RST_BROWNOUT:
            return "brownout";
        case ESP_RST_SDIO:
            return "sdio";
        default:
            return "other";
    }
}

void add_bool(cJSON* object, const char* name, bool value)
{
    cJSON_AddBoolToObject(object, name, value);
}

std::string print_json(cJSON* root)
{
    char* rendered = cJSON_PrintUnformatted(root);
    if (rendered == nullptr) {
        return R"({"schema_version":1,"status":"serialization_failed"})";
    }
    std::string result(rendered);
    cJSON_free(rendered);
    return result;
}

}  // namespace

namespace hal_bridge {

std::string board_get_davie_device_attestation_json()
{
    CJsonPtr root(cJSON_CreateObject());
    if (!root) {
        return R"({"schema_version":1,"status":"allocation_failed"})";
    }

    cJSON_AddNumberToObject(root.get(), "schema_version", 1);
    cJSON_AddStringToObject(root.get(), "status", "ready");
    cJSON_AddStringToObject(root.get(), "identity_source", "websocket_headers");

    const esp_app_desc_t* app = esp_app_get_description();
    cJSON* firmware = cJSON_AddObjectToObject(root.get(), "firmware");
    cJSON_AddStringToObject(firmware, "project", app->project_name);
    cJSON_AddStringToObject(firmware, "version", app->version);
    cJSON_AddStringToObject(firmware, "build_date", app->date);
    cJSON_AddStringToObject(firmware, "build_time", app->time);
    cJSON_AddStringToObject(firmware, "idf_version", app->idf_ver);
    cJSON_AddStringToObject(firmware, "source_revision", STACKCHAN_DAVIE_SOURCE_REVISION);
    char sha256[65] = {};
    for (size_t index = 0; index < 32; ++index) {
        std::snprintf(
            sha256 + (index * 2),
            sizeof(sha256) - (index * 2),
            "%02x",
            app->app_elf_sha256[index]);
    }
    cJSON_AddStringToObject(firmware, "elf_sha256", sha256);

    cJSON* runtime = cJSON_AddObjectToObject(root.get(), "runtime");
    const esp_reset_reason_t reset_reason = esp_reset_reason();
    cJSON_AddNumberToObject(runtime, "uptime_ms", esp_timer_get_time() / 1000);
    cJSON_AddNumberToObject(runtime, "reset_reason_code", reset_reason);
    cJSON_AddStringToObject(runtime, "reset_reason", reset_reason_name(reset_reason));
    cJSON_AddNumberToObject(runtime, "free_heap_bytes", esp_get_free_heap_size());
    cJSON_AddNumberToObject(runtime, "minimum_free_heap_bytes", esp_get_minimum_free_heap_size());

    cJSON* board = cJSON_AddObjectToObject(root.get(), "board");
#ifdef BOARD_TYPE
    cJSON_AddStringToObject(board, "type", BOARD_TYPE);
#else
    cJSON_AddStringToObject(board, "type", "unknown");
#endif
#ifdef BOARD_NAME
    cJSON_AddStringToObject(board, "name", BOARD_NAME);
#else
    cJSON_AddStringToObject(board, "name", "StackChan");
#endif
    cJSON_AddNumberToObject(board, "battery_level", board_get_battery_level());
    add_bool(board, "battery_charging", board_is_battery_charging());
    cJSON_AddNumberToObject(board, "speaker_volume", board_get_speaker_volume());

    cJSON* audio = cJSON_AddObjectToObject(root.get(), "audio");
    cJSON_AddNumberToObject(audio, "input_sample_rate_hz", AUDIO_INPUT_SAMPLE_RATE);
    cJSON_AddNumberToObject(audio, "output_sample_rate_hz", AUDIO_OUTPUT_SAMPLE_RATE);
    cJSON_AddNumberToObject(audio, "microphone_channels", 1);
    cJSON_AddNumberToObject(audio, "afe_output_channels", 1);
#ifdef CONFIG_USE_AUDIO_PROCESSOR
    add_bool(audio, "afe_enabled", true);
#else
    add_bool(audio, "afe_enabled", false);
#endif
#ifdef CONFIG_USE_DEVICE_AEC
    add_bool(audio, "device_aec", true);
#else
    add_bool(audio, "device_aec", false);
#endif
#ifdef CONFIG_USE_SERVER_AEC
    add_bool(audio, "server_aec", true);
#else
    add_bool(audio, "server_aec", false);
#endif
#if AUDIO_INPUT_REFERENCE
    add_bool(audio, "input_reference_channel", true);
    cJSON_AddNumberToObject(audio, "reference_channels", 1);
    cJSON_AddNumberToObject(audio, "codec_input_channels", 2);
#else
    add_bool(audio, "input_reference_channel", false);
    cJSON_AddNumberToObject(audio, "reference_channels", 0);
    cJSON_AddNumberToObject(audio, "codec_input_channels", 1);
#endif
#ifdef CONFIG_USE_DEVICE_AEC
    cJSON_AddStringToObject(audio, "expected_input_profile", "microphone_plus_reference");
#else
    cJSON_AddStringToObject(audio, "expected_input_profile", "microphone_only");
#endif

    cJSON* wake = cJSON_AddObjectToObject(root.get(), "wake");
#ifdef CONFIG_USE_CUSTOM_WAKE_WORD
    cJSON_AddStringToObject(wake, "engine", "multinet_afe_sr");
    cJSON_AddStringToObject(wake, "input_signal", "afe_processed_mono");
    cJSON_AddStringToObject(wake, "afe_type", "speech_recognition");
    cJSON_AddStringToObject(wake, "inference_policy", "vad_gated_bounded");
    cJSON_AddNumberToObject(
        wake,
        "max_speech_window_ms",
        davie::audio::kWakeInferenceMaxSpeechFrames * 32);
#ifdef CONFIG_USE_DEVICE_AEC
    add_bool(wake, "aec_configured", true);
#else
    add_bool(wake, "aec_configured", false);
#endif
    add_bool(wake, "noise_suppression_active", false);
    cJSON_AddStringToObject(
        wake,
        "noise_suppression_reason",
        "mr_sr_profile_uses_aec_and_vad");
    cJSON_AddStringToObject(wake, "phrase", CONFIG_CUSTOM_WAKE_WORD);
    cJSON_AddStringToObject(wake, "display", CONFIG_CUSTOM_WAKE_WORD_DISPLAY);
    cJSON_AddNumberToObject(wake, "threshold_percent", CONFIG_CUSTOM_WAKE_WORD_THRESHOLD);
    cJSON_AddNumberToObject(
        wake,
        "post_wake_pre_roll_ms",
        davie::audio::kPostWakePreRollMs);
    cJSON_AddNumberToObject(
        wake,
        "post_wake_max_capture_ms",
        davie::audio::kPostWakeMaxCaptureMs);
    cJSON_AddNumberToObject(wake, "discarded_warmup_ms", 0);
#elif defined(CONFIG_USE_AFE_WAKE_WORD)
    cJSON_AddStringToObject(wake, "engine", "wakenet_afe");
#elif defined(CONFIG_USE_ESP_WAKE_WORD)
    cJSON_AddStringToObject(wake, "engine", "wakenet");
#else
    cJSON_AddStringToObject(wake, "engine", "disabled");
#endif
#ifdef CONFIG_WAKE_WORD_DETECTION_IN_LISTENING
    add_bool(wake, "active_while_listening", true);
#else
    add_bool(wake, "active_while_listening", false);
#endif

    cJSON* connectivity = cJSON_AddObjectToObject(root.get(), "connectivity");
    auto& wifi = WifiManager::GetInstance();
    add_bool(connectivity, "wifi_connected", wifi.IsConnected());
    cJSON_AddNumberToObject(connectivity, "rssi_dbm", wifi.IsConnected() ? wifi.GetRssi() : 0);
#ifdef CONFIG_STACKCHAN_DAVIE_LOW_LATENCY_WIFI
    add_bool(connectivity, "low_latency_wifi", true);
#else
    add_bool(connectivity, "low_latency_wifi", false);
#endif

    const std::string storage_json = board_get_storage_status_json();
    CJsonPtr storage(cJSON_Parse(storage_json.c_str()));
    if (storage && cJSON_IsObject(storage.get())) {
        cJSON_AddItemToObject(root.get(), "storage", cJSON_Duplicate(storage.get(), true));
    } else {
        cJSON* fallback = cJSON_AddObjectToObject(root.get(), "storage");
        cJSON_AddStringToObject(fallback, "status", "unavailable");
    }

    return print_json(root.get());
}

}  // namespace hal_bridge
