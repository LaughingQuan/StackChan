#include "hal/board/davie_tf_text.h"

#include <cassert>
#include <string>

int main()
{
    using davie::tf::JsonEscape;
    using davie::tf::NormalizeSingleLineUtf8;

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
    return 0;
}
