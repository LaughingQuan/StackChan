#include "hal/board/davie_tf_text.h"

#include <cassert>
#include <string>

int main()
{
    using davie::tf::BuildStorageStatusJson;
    using davie::tf::JsonEscape;
    using davie::tf::NormalizeSingleLineUtf8;
    using davie::tf::StorageStatus;

    assert(NormalizeSingleLineUtf8("  remember\nthis\tplease  ", 64) ==
           "remember this please");
    assert(NormalizeSingleLineUtf8("你好", 6) == "你好");
    assert(NormalizeSingleLineUtf8("你好", 5) == "你");
    assert(NormalizeSingleLineUtf8("A🙂B", 5) == "A🙂");
    assert(NormalizeSingleLineUtf8("A🙂B", 4) == "A");

    const std::string invalid = std::string("A") + "\xe4\xbd" + "B";
    assert(NormalizeSingleLineUtf8(invalid, 8) == "AB");
    assert(JsonEscape("line\n\"quoted\"\\tail") == "line\\n\\\"quoted\\\"\\\\tail");
    assert(JsonEscape("中文🙂") == "中文🙂");

    StorageStatus snapshot;
    snapshot.mount_point = "/tf";
    snapshot.mount_attempted = true;
    snapshot.mounted = true;
    snapshot.writable = true;
    snapshot.self_test_passed = true;
    snapshot.total_bytes = 17179869184ULL;
    snapshot.free_bytes = 16000000000ULL;
    snapshot.note_count = 12;
    snapshot.diagnostic_count = 34;
    snapshot.reader_checkpoint_present = true;
    snapshot.last_error = "quote\" newline\n";
    const std::string status = BuildStorageStatusJson(snapshot);
    assert(status ==
           "{\"enabled\":true,\"mount_point\":\"/tf\",\"mount_attempted\":true,"
           "\"mounted\":true,\"writable\":true,\"self_test_passed\":true,"
           "\"total_bytes\":17179869184,\"free_bytes\":16000000000,"
           "\"note_count\":12,\"diagnostic_count\":34,"
           "\"reader_checkpoint_present\":true,"
           "\"last_error\":\"quote\\\" newline\\n\"}");
    return 0;
}
