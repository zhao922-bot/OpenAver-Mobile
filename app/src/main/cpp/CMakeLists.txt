cmake_minimum_required(VERSION 3.22.1)

project(openaver_mobile LANGUAGES CXX)

add_library(openaver_mobile SHARED abi_stub.cpp)

target_compile_features(openaver_mobile PRIVATE cxx_std_17)
target_link_libraries(openaver_mobile PRIVATE log)
