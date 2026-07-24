#include "davie_tf_text.h"

#include <algorithm>

namespace {

size_t ValidUtf8SequenceLength(const std::string& value, size_t offset)
{
    const auto byte = [&value](size_t index) {
        return static_cast<unsigned char>(value[index]);
    };
    const size_t remaining = value.size() - offset;
    const unsigned char lead = byte(offset);
    if (lead < 0x80) {
        return 1;
    }
    if (lead >= 0xc2 && lead <= 0xdf && remaining >= 2 &&
        byte(offset + 1) >= 0x80 && byte(offset + 1) <= 0xbf) {
        return 2;
    }
    if (remaining >= 3 && lead == 0xe0 && byte(offset + 1) >= 0xa0 &&
        byte(offset + 1) <= 0xbf && byte(offset + 2) >= 0x80 &&
        byte(offset + 2) <= 0xbf) {
        return 3;
    }
    if (remaining >= 3 && ((lead >= 0xe1 && lead <= 0xec) ||
                           (lead >= 0xee && lead <= 0xef)) &&
        byte(offset + 1) >= 0x80 && byte(offset + 1) <= 0xbf &&
        byte(offset + 2) >= 0x80 && byte(offset + 2) <= 0xbf) {
        return 3;
    }
    if (remaining >= 3 && lead == 0xed && byte(offset + 1) >= 0x80 &&
        byte(offset + 1) <= 0x9f && byte(offset + 2) >= 0x80 &&
        byte(offset + 2) <= 0xbf) {
        return 3;
    }
    if (remaining >= 4 && lead == 0xf0 && byte(offset + 1) >= 0x90 &&
        byte(offset + 1) <= 0xbf && byte(offset + 2) >= 0x80 &&
        byte(offset + 2) <= 0xbf && byte(offset + 3) >= 0x80 &&
        byte(offset + 3) <= 0xbf) {
        return 4;
    }
    if (remaining >= 4 && lead >= 0xf1 && lead <= 0xf3 &&
        byte(offset + 1) >= 0x80 && byte(offset + 1) <= 0xbf &&
        byte(offset + 2) >= 0x80 && byte(offset + 2) <= 0xbf &&
        byte(offset + 3) >= 0x80 && byte(offset + 3) <= 0xbf) {
        return 4;
    }
    if (remaining >= 4 && lead == 0xf4 && byte(offset + 1) >= 0x80 &&
        byte(offset + 1) <= 0x8f && byte(offset + 2) >= 0x80 &&
        byte(offset + 2) <= 0xbf && byte(offset + 3) >= 0x80 &&
        byte(offset + 3) <= 0xbf) {
        return 4;
    }
    return 0;
}

}  // namespace

namespace davie::tf {

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

std::string NormalizeSingleLineUtf8(const std::string& value, size_t max_bytes)
{
    std::string normalized;
    normalized.reserve(std::min(value.size(), max_bytes));
    bool pending_space = false;
    for (size_t offset = 0; offset < value.size();) {
        const unsigned char lead = static_cast<unsigned char>(value[offset]);
        if (lead < 0x20 || lead == 0x7f || lead == ' ') {
            pending_space = !normalized.empty();
            ++offset;
            continue;
        }

        const size_t sequence_length = ValidUtf8SequenceLength(value, offset);
        if (sequence_length == 0) {
            ++offset;
            continue;
        }
        const size_t separator_bytes = pending_space ? 1 : 0;
        if (normalized.size() + separator_bytes + sequence_length > max_bytes) {
            break;
        }
        if (pending_space) {
            normalized.push_back(' ');
        }
        pending_space = false;
        normalized.append(value, offset, sequence_length);
        offset += sequence_length;
    }
    return normalized;
}

std::string BuildStorageStatusJson(const StorageStatus& status)
{
    const auto json_bool = [](bool value) {
        return value ? "true" : "false";
    };

    std::string payload;
    payload.reserve(384 + status.last_error.size());
    payload += "{\"enabled\":true,\"mount_point\":\"";
    payload += JsonEscape(status.mount_point);
    payload += "\",";
    payload += "\"mount_attempted\":";
    payload += json_bool(status.mount_attempted);
    payload += ",\"mounted\":";
    payload += json_bool(status.mounted);
    payload += ",\"writable\":";
    payload += json_bool(status.writable);
    payload += ",\"self_test_passed\":";
    payload += json_bool(status.self_test_passed);
    payload += ",\"total_bytes\":";
    payload += std::to_string(status.total_bytes);
    payload += ",\"free_bytes\":";
    payload += std::to_string(status.free_bytes);
    payload += ",\"note_count\":";
    payload += std::to_string(status.note_count);
    payload += ",\"diagnostic_count\":";
    payload += std::to_string(status.diagnostic_count);
    payload += ",\"reader_checkpoint_present\":";
    payload += json_bool(status.reader_checkpoint_present);
    payload += ",\"last_error\":\"";
    payload += JsonEscape(status.last_error);
    payload += "\"}";
    return payload;
}

}  // namespace davie::tf
