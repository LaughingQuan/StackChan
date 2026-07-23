#include "davie_tf_storage.h"
#include "davie_tf_text.h"

#include <driver/sdspi_host.h>
#include <esp_log.h>
#include <esp_vfs_fat.h>

#include <cerrno>
#include <cstdlib>
#include <ctime>
#include <cstdio>
#include <cstring>
#include <fcntl.h>
#include <string>
#include <sys/stat.h>
#include <unistd.h>
#include <vector>

namespace {

constexpr char kTag[] = "DavieTfStorage";
constexpr gpio_num_t kChipSelectPin = GPIO_NUM_4;
constexpr char kDavieRoot[] = "/tf/davie";
constexpr char kLibraryRoot[] = "/tf/davie/library";
constexpr char kCacheRoot[] = "/tf/davie/cache";
constexpr char kDiagnosticsRoot[] = "/tf/davie/diag";
constexpr char kProbePath[] = "/tf/davie/diag/probe.tmp";
constexpr char kProbePayload[] = "davie-tf-storage-v1\n";
constexpr char kNotesPath[] = "/tf/davie/notes.log";
constexpr char kReaderCheckpointPath[] = "/tf/davie/reader.chk";
constexpr char kDiagnosticsPath[] = "/tf/davie/diag/events.log";
constexpr size_t kMaxNoteBytes = 480;
constexpr size_t kMaxNotes = 32;
constexpr size_t kMaxNotesFileBytes = 24 * 1024;
constexpr size_t kMaxDiagnosticEventBytes = 96;
constexpr size_t kMaxDiagnosticDetailBytes = 240;
constexpr size_t kMaxDiagnostics = 48;
constexpr size_t kMaxDiagnosticsFileBytes = 24 * 1024;

esp_err_t EnsureDirectory(const char* path)
{
    if (mkdir(path, 0755) == 0 || errno == EEXIST) {
        return ESP_OK;
    }
    ESP_LOGE(kTag, "mkdir %s failed: errno=%d", path, errno);
    return ESP_FAIL;
}

std::string RecordText(const std::string& record)
{
    const size_t separator = record.find('\t');
    return separator == std::string::npos ? record : record.substr(separator + 1);
}

long long RecordTimestamp(const std::string& record)
{
    const size_t separator = record.find('\t');
    if (separator == std::string::npos) {
        return 0;
    }
    return strtoll(record.substr(0, separator).c_str(), nullptr, 10);
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
    if (writable_) {
        const std::string boot_record =
            std::to_string(static_cast<long long>(time(nullptr))) + "\tboot: storage_ready";
        const esp_err_t diagnostic_result =
            AppendBoundedRecordLocked(kDiagnosticsPath, boot_record, kMaxDiagnostics,
                                      kMaxDiagnosticsFileBytes);
        if (diagnostic_result != ESP_OK) {
            ESP_LOGW(kTag, "Unable to record bounded TF startup diagnostic");
        }
    }
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
    const size_t note_count = mounted_ ? CountRecordsLocked(kNotesPath, kMaxNotes) : 0;
    const size_t diagnostic_count =
        mounted_ ? CountRecordsLocked(kDiagnosticsPath, kMaxDiagnostics) : 0;
    struct stat checkpoint_stat = {};
    const bool checkpoint_present =
        mounted_ && stat(kReaderCheckpointPath, &checkpoint_stat) == 0 && checkpoint_stat.st_size > 0;

    char numeric[384];
    snprintf(numeric, sizeof(numeric),
             R"("mount_attempted":%s,"mounted":%s,"writable":%s,"self_test_passed":%s,"total_bytes":%llu,"free_bytes":%llu,"note_count":%u,"diagnostic_count":%u,"reader_checkpoint_present":%s)",
             mount_attempted_ ? "true" : "false", mounted_ ? "true" : "false", writable_ ? "true" : "false",
             self_test_passed_ ? "true" : "false", static_cast<unsigned long long>(total_bytes_),
             static_cast<unsigned long long>(free_bytes_), static_cast<unsigned>(note_count),
             static_cast<unsigned>(diagnostic_count), checkpoint_present ? "true" : "false");

    return std::string("{\"enabled\":true,\"mount_point\":\"") + kMountPoint + "\"," + numeric +
           ",\"last_error\":\"" + davie::tf::JsonEscape(last_error_) + "\"}";
}

std::string DavieTfStorage::SaveNote(const std::string& text)
{
    std::lock_guard<std::mutex> lock(mutex_);
    if (!mounted_ || !writable_) {
        return R"({"ok":false,"error":"storage_not_writable"})";
    }
    if (text.size() > kMaxNoteBytes) {
        return R"({"ok":false,"error":"note_too_long","max_bytes":480})";
    }
    const std::string normalized = davie::tf::NormalizeSingleLineUtf8(text, kMaxNoteBytes);
    if (normalized.empty()) {
        return R"({"ok":false,"error":"note_empty"})";
    }

    const std::string record =
        std::to_string(static_cast<long long>(time(nullptr))) + "\t" + normalized;
    const esp_err_t result =
        AppendBoundedRecordLocked(kNotesPath, record, kMaxNotes, kMaxNotesFileBytes);
    if (result != ESP_OK) {
        SetErrorLocked("save_note", result);
        return R"({"ok":false,"error":"note_write_failed"})";
    }
    RefreshCapacityLocked();
    return std::string(R"({"ok":true,"saved":true,"text":")") +
           davie::tf::JsonEscape(normalized) +
           R"(","note_count":)" + std::to_string(CountRecordsLocked(kNotesPath, kMaxNotes)) + "}";
}

std::string DavieTfStorage::RecentNotesJson(int limit) const
{
    std::lock_guard<std::mutex> lock(mutex_);
    if (!mounted_) {
        return R"({"ok":false,"error":"storage_not_mounted","notes":[]})";
    }
    limit = std::max(1, std::min(limit, 10));
    const std::vector<std::string> records = ReadRecordsLocked(kNotesPath, kMaxNotes);
    const size_t start =
        records.size() > static_cast<size_t>(limit) ? records.size() - static_cast<size_t>(limit) : 0;
    std::string json = R"({"ok":true,"notes":[)";
    for (size_t i = records.size(); i > start; --i) {
        if (i != records.size()) {
            json += ",";
        }
        const std::string& record = records[i - 1];
        json += R"({"created_at":)" + std::to_string(RecordTimestamp(record)) + R"(,"text":")" +
                davie::tf::JsonEscape(RecordText(record)) + R"("})";
    }
    return json + "],\"note_count\":" + std::to_string(records.size()) + "}";
}

std::string DavieTfStorage::SaveReaderCheckpoint(const std::string& title, int index, int total,
                                                 const std::string& state)
{
    std::lock_guard<std::mutex> lock(mutex_);
    if (!mounted_ || !writable_) {
        return R"({"ok":false,"error":"storage_not_writable"})";
    }
    if (title.size() > 192 || state.size() > 32 || index < 0 || total < 0 || index > total) {
        return R"({"ok":false,"error":"checkpoint_invalid"})";
    }
    const std::string clean_title = davie::tf::NormalizeSingleLineUtf8(title, 192);
    const std::string clean_state = davie::tf::NormalizeSingleLineUtf8(state, 32);
    if (clean_title.empty() || clean_state.empty()) {
        return R"({"ok":false,"error":"checkpoint_invalid"})";
    }
    const std::string payload =
        std::string(R"({"ok":true,"title":")") + davie::tf::JsonEscape(clean_title) +
        R"(","index":)" +
        std::to_string(index) + R"(,"total":)" + std::to_string(total) + R"(,"state":")" +
        davie::tf::JsonEscape(clean_state) + R"(","updated_at":)" +
        std::to_string(static_cast<long long>(time(nullptr))) + "}";
    const esp_err_t result = WriteAtomicFileLocked(kReaderCheckpointPath, payload);
    if (result != ESP_OK) {
        SetErrorLocked("save_checkpoint", result);
        return R"({"ok":false,"error":"checkpoint_write_failed"})";
    }
    RefreshCapacityLocked();
    return payload;
}

std::string DavieTfStorage::ReaderCheckpointJson() const
{
    std::lock_guard<std::mutex> lock(mutex_);
    if (!mounted_) {
        return R"({"ok":false,"error":"storage_not_mounted"})";
    }
    const std::string payload = ReadSmallFileLocked(kReaderCheckpointPath, 1024);
    if (payload.empty()) {
        return R"({"ok":true,"checkpoint":null})";
    }
    if (payload.front() != '{' || payload.back() != '}') {
        return R"({"ok":false,"error":"checkpoint_corrupt"})";
    }
    return payload;
}

std::string DavieTfStorage::AppendDiagnostic(const std::string& event, const std::string& detail)
{
    std::lock_guard<std::mutex> lock(mutex_);
    if (!mounted_ || !writable_) {
        return R"({"ok":false,"error":"storage_not_writable"})";
    }
    if (event.size() > kMaxDiagnosticEventBytes || detail.size() > kMaxDiagnosticDetailBytes) {
        return R"({"ok":false,"error":"diagnostic_too_long"})";
    }
    const std::string clean_event =
        davie::tf::NormalizeSingleLineUtf8(event, kMaxDiagnosticEventBytes);
    const std::string clean_detail =
        davie::tf::NormalizeSingleLineUtf8(detail, kMaxDiagnosticDetailBytes);
    if (clean_event.empty()) {
        return R"({"ok":false,"error":"diagnostic_event_empty"})";
    }
    const std::string record = std::to_string(static_cast<long long>(time(nullptr))) + "\t" +
                               clean_event + (clean_detail.empty() ? "" : ": " + clean_detail);
    const esp_err_t result = AppendBoundedRecordLocked(kDiagnosticsPath, record, kMaxDiagnostics,
                                                        kMaxDiagnosticsFileBytes);
    if (result != ESP_OK) {
        SetErrorLocked("append_diagnostic", result);
        return R"({"ok":false,"error":"diagnostic_write_failed"})";
    }
    return R"({"ok":true,"saved":true})";
}

std::string DavieTfStorage::RecentDiagnosticsJson(int limit) const
{
    std::lock_guard<std::mutex> lock(mutex_);
    if (!mounted_) {
        return R"({"ok":false,"error":"storage_not_mounted","events":[]})";
    }
    limit = std::max(1, std::min(limit, 10));
    const std::vector<std::string> records = ReadRecordsLocked(kDiagnosticsPath, kMaxDiagnostics);
    const size_t start =
        records.size() > static_cast<size_t>(limit) ? records.size() - static_cast<size_t>(limit) : 0;
    std::string json = R"({"ok":true,"events":[)";
    for (size_t i = records.size(); i > start; --i) {
        if (i != records.size()) {
            json += ",";
        }
        const std::string& record = records[i - 1];
        json += R"({"created_at":)" + std::to_string(RecordTimestamp(record)) + R"(,"event":")" +
                davie::tf::JsonEscape(RecordText(record)) + R"("})";
    }
    return json + "],\"event_count\":" + std::to_string(records.size()) + "}";
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

esp_err_t DavieTfStorage::AppendBoundedRecordLocked(const char* path, const std::string& record,
                                                    size_t max_records, size_t max_bytes)
{
    std::vector<std::string> records = ReadRecordsLocked(path, max_records);
    records.push_back(record);
    size_t bytes = 0;
    for (const auto& item : records) {
        bytes += item.size() + 1;
    }
    while (records.size() > max_records || (bytes > max_bytes && records.size() > 1)) {
        bytes -= records.front().size() + 1;
        records.erase(records.begin());
    }

    std::string payload;
    payload.reserve(bytes);
    for (const auto& item : records) {
        payload += item;
        payload.push_back('\n');
    }
    return WriteAtomicFileLocked(path, payload);
}

esp_err_t DavieTfStorage::WriteAtomicFileLocked(const char* path, const std::string& payload)
{
    std::string temporary(path);
    const size_t separator = temporary.find_last_of('/');
    const size_t extension = temporary.find_last_of('.');
    if (extension != std::string::npos &&
        (separator == std::string::npos || extension > separator)) {
        temporary.replace(extension, std::string::npos, ".tmp");
    } else {
        temporary += ".tmp";
    }
    FILE* output = fopen(temporary.c_str(), "wb");
    if (output == nullptr) {
        return ESP_FAIL;
    }
    const bool write_ok = fwrite(payload.data(), 1, payload.size(), output) == payload.size();
    const bool flush_ok = fflush(output) == 0;
    const bool sync_ok = fsync(fileno(output)) == 0;
    const bool close_ok = fclose(output) == 0;
    if (!write_ok || !flush_ok || !sync_ok || !close_ok) {
        unlink(temporary.c_str());
        return ESP_FAIL;
    }
    unlink(path);
    if (rename(temporary.c_str(), path) != 0) {
        unlink(temporary.c_str());
        return ESP_FAIL;
    }
    return ESP_OK;
}

std::vector<std::string> DavieTfStorage::ReadRecordsLocked(const char* path,
                                                           size_t max_records) const
{
    std::vector<std::string> records;
    FILE* input = fopen(path, "rb");
    if (input == nullptr) {
        return records;
    }
    char buffer[768];
    while (fgets(buffer, sizeof(buffer), input) != nullptr) {
        std::string line(buffer);
        while (!line.empty() && (line.back() == '\n' || line.back() == '\r')) {
            line.pop_back();
        }
        if (!line.empty()) {
            records.push_back(line);
            if (records.size() > max_records) {
                records.erase(records.begin());
            }
        }
    }
    fclose(input);
    return records;
}

std::string DavieTfStorage::ReadSmallFileLocked(const char* path, size_t max_bytes) const
{
    FILE* input = fopen(path, "rb");
    if (input == nullptr) {
        return "";
    }
    std::string result;
    result.resize(max_bytes);
    const size_t bytes_read = fread(result.data(), 1, max_bytes, input);
    const bool has_more = fgetc(input) != EOF;
    fclose(input);
    if (has_more) {
        return "";
    }
    result.resize(bytes_read);
    return result;
}

size_t DavieTfStorage::CountRecordsLocked(const char* path, size_t max_records) const
{
    return ReadRecordsLocked(path, max_records).size();
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
