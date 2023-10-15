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
#file(GLOB GTEST_SOURCES "tests/*_gtest.cpp")
#add_executable(AllGTests ${GTEST_SOURCES})
#target_link_libraries(AllGTests gtest gtest_main gmock)

#add_executable(GoogleTest tests/card_collection_gtest.cpp)
#target_link_libraries(GoogleTest gtest gtest_main gmock)
#gtest_discover_tests(GoogleTest)
#
#add_executable(GoogleTestTrick tests/trick_gtest.cpp)
#target_link_libraries(GoogleTestTrick gtest gtest_main gmock)
#gtest_discover_tests(GoogleTestTrick)
