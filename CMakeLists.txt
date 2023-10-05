cmake_minimum_required(VERSION 3.12)

project(HeartsEngine)

set (CMAKE_CXX_STANDARD 17)

add_executable(Main main.cpp)

# Add Google Test
include(GoogleTest)
enable_testing()

add_subdirectory(externals/googletest)
include_directories(\${gtest_SOURCE_DIR}/include \${gtest_SOURCE_DIR})

# Add your test files and link with Google Test
add_executable(GoogleTest tests/card_collection_gtest.cpp)
target_link_libraries(GoogleTest gtest gtest_main)
gtest_discover_tests(GoogleTest)
