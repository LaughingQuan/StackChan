#include "davie_tf_storage.h"

#include <driver/sdspi_host.h>
#include <esp_log.h>
#include <esp_vfs_fat.h>

#include <cerrno>
#include <cstdio>
#include <cstring>
#include <fcntl.h>
#include <string>
#include <sys/stat.h>
#include <unistd.h>

namespace {

constexpr char kTag[] = "DavieTfStorage";
constexpr gpio_num_t kChipSelectPin = GPIO_NUM_4;
constexpr char kDavieRoot[] = "/tf/davie";
constexpr char kLibraryRoot[] = "/tf/davie/library";
constexpr char kCacheRoot[] = "/tf/davie/cache";
constexpr char kDiagnosticsRoot[] = "/tf/davie/diag";
constexpr char kProbePath[] = "/tf/davie/diag/probe.tmp";
constexpr char kProbePayload[] = "davie-tf-storage-v1\n";

std::string JsonEscape(const std::string& value)
{
    std::string escaped;
    escaped.reserve(value.size() + 8);
    for (const char c : value) {
        switch (c) {
        case '\\':
            escaped += "\\\\";
            break;
        case '"':
            escaped += "\\\"";
            break;
        case '\n':
            escaped += "\\n";
            break;
        case '\r':
            escaped += "\\r";
            break;
        case '\t':
            escaped += "\\t";
            break;
        default:
            if (static_cast<unsigned char>(c) >= 0x20) {
                escaped += c;
            }
            break;
        }
    }
    return escaped;
}

esp_err_t EnsureDirectory(const char* path)
{
    if (mkdir(path, 0755) == 0 || errno == EEXIST) {
        return ESP_OK;
    }
    ESP_LOGE(kTag, "mkdir %s failed: errno=%d", path, errno);
    return ESP_FAIL;
}

}  // namespace

esp_err_t DavieTfStorage::Mount()
{
    std::lock_guard<std::mutex> lock(mutex_);
    mount_attempted_ = true;
    if (mounted_) {
        return ESP_OK;
    }

    last_error_.clear();
    writable_ = false;
    self_test_passed_ = false;
    total_bytes_ = 0;
    free_bytes_ = 0;

    sdmmc_host_t host = SDSPI_HOST_DEFAULT();
    host.slot = SPI3_HOST;

    sdspi_device_config_t slot = SDSPI_DEVICE_CONFIG_DEFAULT();
    slot.host_id = SPI3_HOST;
    slot.gpio_cs = kChipSelectPin;
    slot.gpio_cd = SDSPI_SLOT_NO_CD;
    slot.gpio_wp = SDSPI_SLOT_NO_WP;
    slot.gpio_int = SDSPI_SLOT_NO_INT;

    const esp_vfs_fat_sdmmc_mount_config_t mount_config = {
        .format_if_mount_failed = false,
        .max_files = 8,
        .allocation_unit_size = 16 * 1024,
        .disk_status_check_enable = false,
        .use_one_fat = false,
    };

    const esp_err_t mount_result =
        esp_vfs_fat_sdspi_mount(kMountPoint, &host, &slot, &mount_config, &card_);
    if (mount_result != ESP_OK) {
        card_ = nullptr;
        SetErrorLocked("mount", mount_result);
        ESP_LOGW(kTag, "TF card unavailable; Davie continues without edge storage: %s",
                 esp_err_to_name(mount_result));
        return mount_result;
    }

    mounted_ = true;
    RefreshCapacityLocked();

    const esp_err_t directory_result = EnsureDirectoriesLocked();
    if (directory_result != ESP_OK) {
        SetErrorLocked("prepare_directories", directory_result);
        ESP_LOGW(kTag, "TF card mounted but Davie directories are not writable");
        return ESP_OK;
    }

#ifdef CONFIG_STACKCHAN_DAVIE_TF_STARTUP_SELF_TEST
    const esp_err_t test_result = RunSelfTestLocked();
    if (test_result != ESP_OK) {
        ESP_LOGW(kTag, "TF card mounted read-only/degraded: %s", last_error_.c_str());
        return ESP_OK;
    }
#else
    writable_ = true;
#endif

    const uint32_t total_mib = static_cast<uint32_t>(total_bytes_ / (1024 * 1024));
    const uint32_t free_mib = static_cast<uint32_t>(free_bytes_ / (1024 * 1024));
    ESP_LOGI(kTag, "TF card ready: total=%u MiB free=%u MiB writable=%d", total_mib, free_mib,
             writable_);
    return ESP_OK;
}

esp_err_t DavieTfStorage::Unmount()
{
    std::lock_guard<std::mutex> lock(mutex_);
    if (!mounted_) {
        return ESP_OK;
    }

    const esp_err_t result = esp_vfs_fat_sdcard_unmount(kMountPoint, card_);
    if (result != ESP_OK) {
        SetErrorLocked("unmount", result);
        return result;
    }

    card_ = nullptr;
    mounted_ = false;
    writable_ = false;
    self_test_passed_ = false;
    total_bytes_ = 0;
    free_bytes_ = 0;
    return ESP_OK;
}

esp_err_t DavieTfStorage::RunSelfTest()
{
    std::lock_guard<std::mutex> lock(mutex_);
    return RunSelfTestLocked();
}

bool DavieTfStorage::mounted() const
{
    std::lock_guard<std::mutex> lock(mutex_);
    return mounted_;
}

std::string DavieTfStorage::StatusJson() const
{
    std::lock_guard<std::mutex> lock(mutex_);
    char numeric[256];
    snprintf(numeric, sizeof(numeric),
             R"("mount_attempted":%s,"mounted":%s,"writable":%s,"self_test_passed":%s,"total_bytes":%llu,"free_bytes":%llu)",
             mount_attempted_ ? "true" : "false", mounted_ ? "true" : "false", writable_ ? "true" : "false",
             self_test_passed_ ? "true" : "false", static_cast<unsigned long long>(total_bytes_),
             static_cast<unsigned long long>(free_bytes_));

    return std::string("{\"enabled\":true,\"mount_point\":\"") + kMountPoint + "\"," + numeric +
           ",\"last_error\":\"" + JsonEscape(last_error_) + "\"}";
}

esp_err_t DavieTfStorage::EnsureDirectoriesLocked()
{
    const char* directories[] = {kDavieRoot, kLibraryRoot, kCacheRoot, kDiagnosticsRoot};
    for (const char* directory : directories) {
        const esp_err_t result = EnsureDirectory(directory);
        if (result != ESP_OK) {
            return result;
        }
    }
    return ESP_OK;
}

esp_err_t DavieTfStorage::RunSelfTestLocked()
{
    self_test_passed_ = false;
    writable_ = false;
    if (!mounted_) {
        SetErrorLocked("self_test_not_mounted", ESP_ERR_INVALID_STATE);
        return ESP_ERR_INVALID_STATE;
    }

    FILE* output = fopen(kProbePath, "wb");
    if (output == nullptr) {
        SetErrorLocked("self_test_open_write", ESP_FAIL);
        return ESP_FAIL;
    }

    const size_t payload_size = strlen(kProbePayload);
    const bool write_ok = fwrite(kProbePayload, 1, payload_size, output) == payload_size;
    const bool flush_ok = fflush(output) == 0;
    const bool sync_ok = fsync(fileno(output)) == 0;
    const bool close_ok = fclose(output) == 0;
    if (!write_ok || !flush_ok || !sync_ok || !close_ok) {
        unlink(kProbePath);
        SetErrorLocked("self_test_write", ESP_FAIL);
        return ESP_FAIL;
    }

    FILE* input = fopen(kProbePath, "rb");
    if (input == nullptr) {
        unlink(kProbePath);
        SetErrorLocked("self_test_open_read", ESP_FAIL);
        return ESP_FAIL;
    }

    char buffer[sizeof(kProbePayload)] = {};
    const size_t bytes_read = fread(buffer, 1, payload_size, input);
    const bool read_close_ok = fclose(input) == 0;
    const bool content_ok = bytes_read == payload_size && memcmp(buffer, kProbePayload, payload_size) == 0;
    const bool delete_ok = unlink(kProbePath) == 0;
    if (!content_ok || !read_close_ok || !delete_ok) {
        SetErrorLocked("self_test_verify", ESP_FAIL);
        return ESP_FAIL;
    }

    writable_ = true;
    self_test_passed_ = true;
    last_error_.clear();
    RefreshCapacityLocked();
    return ESP_OK;
}

void DavieTfStorage::RefreshCapacityLocked()
{
    uint64_t total = 0;
    uint64_t free = 0;
    const esp_err_t result = esp_vfs_fat_info(kMountPoint, &total, &free);
    if (result == ESP_OK) {
        total_bytes_ = total;
        free_bytes_ = free;
    } else {
        ESP_LOGW(kTag, "Unable to read TF capacity: %s", esp_err_to_name(result));
    }
}

void DavieTfStorage::SetErrorLocked(const char* operation, esp_err_t error)
{
    last_error_ = std::string(operation) + ": " + esp_err_to_name(error);
}
