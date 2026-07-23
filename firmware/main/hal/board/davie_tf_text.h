#pragma once

#include <cstddef>
#include <string>

namespace davie::tf {

std::string JsonEscape(const std::string& value);
std::string NormalizeSingleLineUtf8(const std::string& value, size_t max_bytes);

}  // namespace davie::tf
