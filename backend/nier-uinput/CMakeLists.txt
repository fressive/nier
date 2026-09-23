cmake_minimum_required(VERSION 3.22)

project(nier_uinput VERSION 0.1.0 LANGUAGES CXX)

include(GNUInstallDirs)
include(CTest)

add_library(nier_uinput STATIC
    src/uinput_device.cpp
)

target_compile_features(nier_uinput PUBLIC cxx_std_17)
target_include_directories(nier_uinput
    PUBLIC
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
        $<INSTALL_INTERFACE:${CMAKE_INSTALL_INCLUDEDIR}>
)
target_compile_options(nier_uinput PRIVATE -Wall -Wextra -Wpedantic -Wconversion -Wshadow)

add_executable(nier-uinput src/main.cpp)
target_link_libraries(nier-uinput PRIVATE nier_uinput)
target_compile_options(nier-uinput PRIVATE -Wall -Wextra -Wpedantic -Wconversion -Wshadow)

if(BUILD_TESTING)
    add_executable(nier_uinput_test tests/uinput_device_test.cpp)
    target_link_libraries(nier_uinput_test PRIVATE nier_uinput)
    target_compile_options(nier_uinput_test PRIVATE -Wall -Wextra -Wpedantic -Wconversion -Wshadow)
    add_test(NAME nier_uinput_unit COMMAND nier_uinput_test)
endif()

install(TARGETS nier_uinput nier-uinput)
install(FILES include/nier/uinput_device.h DESTINATION ${CMAKE_INSTALL_INCLUDEDIR}/nier)

