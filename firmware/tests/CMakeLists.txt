cmake_minimum_required(VERSION 3.16)

project(stackchan_firmware_tests LANGUAGES CXX)

enable_testing()

add_executable(motion_math_test
    motion_math_test.cpp
    ../main/stackchan/motion/motion_math.cpp
)

target_include_directories(motion_math_test PRIVATE
    ../main
)

target_compile_features(motion_math_test PRIVATE cxx_std_17)

add_test(NAME motion_math_test COMMAND $<TARGET_FILE:motion_math_test>)

add_executable(davie_tf_text_test
    davie_tf_text_test.cpp
    ../main/hal/board/davie_tf_text.cc
)

target_include_directories(davie_tf_text_test PRIVATE
    ../main
)

target_compile_features(davie_tf_text_test PRIVATE cxx_std_17)

add_test(NAME davie_tf_text_test COMMAND $<TARGET_FILE:davie_tf_text_test>)

add_executable(davie_post_wake_audio_bridge_test
    davie_post_wake_audio_bridge_test.cpp
    ../main/audio/davie_post_wake_audio_bridge.cc
)

target_include_directories(davie_post_wake_audio_bridge_test PRIVATE
    ../main
)

target_compile_features(davie_post_wake_audio_bridge_test PRIVATE cxx_std_17)

add_test(
    NAME davie_post_wake_audio_bridge_test
    COMMAND $<TARGET_FILE:davie_post_wake_audio_bridge_test>
)
