cmake_minimum_required(VERSION 3.12)

project(HeartsEngine)

set (CMAKE_CXX_STANDARD 17)

add_executable(Main main.cpp)

# Add Google Test
include(GoogleTest)
enable_testing()

add_subdirectory(externals/googletest)
include_directories(\${gtest_SOURCE_DIR}/include \${gtest_SOURCE_DIR})

# Unit Tests
add_executable(CardCollection tests/card_collection_gtest.cpp)
target_link_libraries(CardCollection gtest gtest_main)
gtest_discover_tests(CardCollection)

add_executable(Trick tests/trick_gtest.cpp)
target_link_libraries(Trick gtest gtest_main gmock)
gtest_discover_tests(Trick)

