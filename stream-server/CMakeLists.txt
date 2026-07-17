cmake_minimum_required(VERSION 3.20)

project(
    distributed_audio_stream_server
    VERSION 0.1.0
    LANGUAGES CXX
)

add_executable(
    audio_stream_server
    src/main.cpp
)

target_compile_features(
    audio_stream_server
    PRIVATE
    cxx_std_17
)

target_include_directories(
    audio_stream_server
    PRIVATE
    "${CMAKE_CURRENT_SOURCE_DIR}/third_party"
)

if(MSVC)
    target_compile_options(
        audio_stream_server
        PRIVATE
        /W4
        /permissive-
    )
else()
    target_compile_options(
        audio_stream_server
        PRIVATE
        -Wall
        -Wextra
        -Wpedantic
    )
endif()

if(WIN32)
    target_link_libraries(
        audio_stream_server
        PRIVATE
        ws2_32
    )
endif()