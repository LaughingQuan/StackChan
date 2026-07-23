#pragma once

#include <esp_err.h>
#include <sdmmc_cmd.h>

#include <cstdint>
#include <mutex>
#include <string>

class DavieTfStorage {
public:
    static constexpr const char* kMountPoint = "/tf";

    esp_err_t Mount();
    esp_err_t Unmount();
    esp_err_t RunSelfTest();

    bool mounted() const;
    std::string StatusJson() const;

private:
    esp_err_t EnsureDirectoriesLocked();
    esp_err_t RunSelfTestLocked();
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
