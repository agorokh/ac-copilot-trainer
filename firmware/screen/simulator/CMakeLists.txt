cmake_minimum_required(VERSION 3.20)
project(ac_screen_simulator LANGUAGES C CXX)

set(CMAKE_C_STANDARD 11)
set(CMAKE_CXX_STANDARD 17)
get_filename_component(FIRMWARE_ROOT "${CMAKE_CURRENT_SOURCE_DIR}/.." ABSOLUTE)

# Match platformio.ini exactly. FetchContent verifies the archive before extraction;
# no developer checkout, PlatformIO cache or machine-specific paths are required.
include(FetchContent)
FetchContent_Declare(lvgl_source
    URL https://codeload.github.com/lvgl/lvgl/tar.gz/refs/tags/v8.3.11
    URL_HASH SHA256=83b7325a4b78cbb19a39f3ac75346c8086926d7faeab5ff2d825c20da0bbdb46
    TIMEOUT 60
)
FetchContent_GetProperties(lvgl_source)
if(NOT lvgl_source_POPULATED)
    FetchContent_Populate(lvgl_source)
endif()

# Compile the actual firmware UI and config, not a second implementation.
file(GLOB_RECURSE LVGL_SOURCES CONFIGURE_DEPENDS "${lvgl_source_SOURCE_DIR}/src/*.c")
file(GLOB UI_SOURCES CONFIGURE_DEPENDS
    "${FIRMWARE_ROOT}/src/ui/*.cpp" "${FIRMWARE_ROOT}/src/ui/fonts/*.c")
add_library(screen_lvgl STATIC ${LVGL_SOURCES})
target_include_directories(screen_lvgl PUBLIC
    "${lvgl_source_SOURCE_DIR}" "${FIRMWARE_ROOT}/include")
target_compile_definitions(screen_lvgl PUBLIC LV_CONF_INCLUDE_SIMPLE)

add_executable(screen_simulator scenarios.cpp ${UI_SOURCES})
target_include_directories(screen_simulator BEFORE PRIVATE "${CMAKE_CURRENT_SOURCE_DIR}/host")
target_link_libraries(screen_simulator PRIVATE screen_lvgl)
if(MSVC)
    target_compile_definitions(screen_lvgl PUBLIC _CRT_SECURE_NO_WARNINGS)
    # Generated C fonts have C linkage. MSVC also mangles C++ data declarations.
    target_compile_options(screen_simulator PRIVATE
        "$<$<COMPILE_LANGUAGE:CXX>:/FI${CMAKE_CURRENT_SOURCE_DIR}/host/font_linkage.h>")
else()
    target_link_libraries(screen_simulator PRIVATE m)
endif()

enable_testing()
if(NOT SIMULATOR_ARTIFACT_DIR)
    set(SIMULATOR_ARTIFACT_DIR "${CMAKE_BINARY_DIR}/artifacts")
endif()
add_test(NAME screen_scenarios
    COMMAND screen_simulator "${SIMULATOR_ARTIFACT_DIR}")
set_tests_properties(screen_scenarios PROPERTIES TIMEOUT 30)
