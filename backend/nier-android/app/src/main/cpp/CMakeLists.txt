cmake_minimum_required(VERSION 3.22.1)
project(nier_uinput)

add_library(nier_uinput SHARED uinput_device.cpp)
target_compile_features(nier_uinput PRIVATE cxx_std_17)
find_library(log-lib log)
target_link_libraries(nier_uinput ${log-lib})

