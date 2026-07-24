#pragma once

#include <cstddef>
#include <cstdint>
#include <string>

namespace davie::tf {

struct StorageStatus {
    std::string mount_point = "/tf";
    bool mount_attempted = false;
    bool mounted = false;
    bool writable = false;
    bool self_test_passed = false;
    uint64_t total_bytes = 0;
    uint64_t free_bytes = 0;
    size_t note_count = 0;
    size_t diagnostic_count = 0;
    bool reader_checkpoint_present = false;
    std::string last_error;
};

std::string JsonEscape(const std::string& value);
std::string NormalizeSingleLineUtf8(const std::string& value, size_t max_bytes);
std::string BuildStorageStatusJson(const StorageStatus& status);

}  // namespace davie::tf
