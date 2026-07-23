#pragma once

#include <esp_err.h>
#include <sdmmc_cmd.h>

#include <cstdint>
#include <mutex>
#include <string>
#include <vector>

class DavieTfStorage {
public:
    static constexpr const char* kMountPoint = "/tf";

    esp_err_t Mount();
    esp_err_t Unmount();
    esp_err_t RunSelfTest();

    bool mounted() const;
    std::string StatusJson() const;
    std::string SaveNote(const std::string& text);
    std::string RecentNotesJson(int limit) const;
    std::string SaveReaderCheckpoint(const std::string& title, int index, int total,
                                     const std::string& state);
    std::string ReaderCheckpointJson() const;
    std::string AppendDiagnostic(const std::string& event, const std::string& detail);
    std::string RecentDiagnosticsJson(int limit) const;

private:
    esp_err_t EnsureDirectoriesLocked();
    esp_err_t RunSelfTestLocked();
    esp_err_t AppendBoundedRecordLocked(const char* path, const std::string& record,
                                        size_t max_records, size_t max_bytes);
    esp_err_t WriteAtomicFileLocked(const char* path, const std::string& payload);
    std::vector<std::string> ReadRecordsLocked(const char* path, size_t max_records) const;
    std::string ReadSmallFileLocked(const char* path, size_t max_bytes) const;
    size_t CountRecordsLocked(const char* path, size_t max_records) const;
    void RefreshCapacityLocked();
    void SetErrorLocked(const char* operation, esp_err_t error);

    mutable std::mutex mutex_;
    sdmmc_card_t* card_ = nullptr;
    bool mount_attempted_ = false;
    bool mounted_ = false;
    bool writable_ = false;
    bool self_test_passed_ = false;
    uint64_t total_bytes_ = 0;
    uint64_t free_bytes_ = 0;
    std::string last_error_;
};
