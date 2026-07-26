#include "davie_device_heartbeat.h"

#include "board/davie_device_attestation.h"
#include "board/hal_bridge.h"
#include "board.h"
#include "settings.h"
#include "system_info.h"

#include <esp_log.h>
#include <freertos/FreeRTOS.h>
#include <freertos/task.h>
#include <http.h>

#include <algorithm>
#include <memory>
#include <string>

namespace {

constexpr char kTag[] = "DavieHeartbeat";
constexpr int kDefaultIntervalSeconds = 30;
constexpr int kMinimumIntervalSeconds = 10;
constexpr int kConfigurationRetrySeconds = 5;
constexpr int kHttpTimeoutMilliseconds = 5000;
constexpr uint32_t kTaskStackDepth = 6144;

TaskHandle_t heartbeat_task = nullptr;

int bounded_interval(int configured)
{
    return std::max(kMinimumIntervalSeconds, configured);
}

void wait_seconds(int seconds)
{
    vTaskDelay(pdMS_TO_TICKS(std::max(1, seconds) * 1000));
}

bool post_heartbeat(
    std::unique_ptr<Http>& http,
    const std::string& url,
    const std::string& token)
{
    auto& board = Board::GetInstance();
    auto* network = board.GetNetwork();
    if (network == nullptr) {
        ESP_LOGW(kTag, "Network interface is not ready");
        return false;
    }

    if (!http) {
        http = network->CreateHttp(0);
    }
    if (!http) {
        ESP_LOGW(kTag, "HTTP client is not available");
        return false;
    }
    http->SetTimeout(kHttpTimeoutMilliseconds);
    http->SetHeader("Authorization", "Bearer " + token);
    http->SetHeader("Device-Id", SystemInfo::GetMacAddress());
    http->SetHeader("Client-Id", board.GetUuid());
    http->SetHeader("Content-Type", "application/json");
    http->SetContent(
        hal_bridge::board_get_davie_device_attestation_json());
    if (!http->Open("POST", url)) {
        ESP_LOGW(
            kTag,
            "Heartbeat request failed to open: error=0x%x",
            http->GetLastError());
        return false;
    }

    const int status = http->GetStatusCode();
    http->ReadAll();
    // Keep the client alive while the transport finishes its asynchronous
    // disconnect callback. Closing it here can deadlock the HTTP mutex.
    if (status != 200) {
        ESP_LOGW(kTag, "Heartbeat rejected: status=%d", status);
        return false;
    }
    return true;
}

void heartbeat_loop(void*)
{
    int retry_seconds = kConfigurationRetrySeconds;
    std::unique_ptr<Http> http;
    while (true) {
        Settings settings("websocket", false);
        const std::string url = settings.GetString("heartbeat_url");
        const std::string token = settings.GetString("token");
        const int interval_seconds = bounded_interval(
            settings.GetInt("heartbeat_sec", kDefaultIntervalSeconds));

        if (url.empty() || token.empty() || !hal_bridge::is_xiaozhi_ready()) {
            wait_seconds(kConfigurationRetrySeconds);
            continue;
        }

        // An active voice WebSocket already proves reachability. Avoid adding
        // HTTP contention to full-duplex audio and report as soon as idle.
        if (!hal_bridge::is_xiaozhi_idle()) {
            wait_seconds(kConfigurationRetrySeconds);
            continue;
        }

        if (post_heartbeat(http, url, token)) {
            retry_seconds = kConfigurationRetrySeconds;
            ESP_LOGI(
                kTag,
                "Idle device heartbeat accepted; next=%ds",
                interval_seconds);
            wait_seconds(interval_seconds);
            continue;
        }

        wait_seconds(retry_seconds);
        retry_seconds = std::min(interval_seconds, retry_seconds * 2);
    }
}

}  // namespace

namespace davie::device {

void StartHeartbeat()
{
    if (heartbeat_task != nullptr) {
        return;
    }
    const BaseType_t created = xTaskCreatePinnedToCore(
        heartbeat_loop,
        "davie_heartbeat",
        kTaskStackDepth,
        nullptr,
        1,
        &heartbeat_task,
        0);
    if (created != pdPASS) {
        heartbeat_task = nullptr;
        ESP_LOGE(kTag, "Failed to create heartbeat task");
        return;
    }
    ESP_LOGI(kTag, "Idle heartbeat task started");
}

}  // namespace davie::device
