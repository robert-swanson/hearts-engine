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

# Boost
find_package(Boost REQUIRED COMPONENTS system filesystem)
include_directories(${Boost_INCLUDE_DIRS})

# nlohmann/json
find_package(nlohmann_json REQUIRED)
include_directories(${nlohmann_json_INCLUDE_DIRS})

# Server
add_executable(Server server/server.cpp)
target_link_libraries(Server ${Boost_LIBRARIES} ${nlohmann_json_LIBRARIES})

