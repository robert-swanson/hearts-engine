cmake_minimum_required(VERSION 3.12)
project(HeartsEngine)
set (CMAKE_CXX_STANDARD 17)

# Main Target
add_executable(Main main.cpp)

# Server
add_executable(Server server/server.cpp)
target_link_libraries(Server ${Boost_LIBRARIES} ${nlohmann_json_LIBRARIES})


# Boost
set(BOOST_ROOT ${CMAKE_CURRENT_SOURCE_DIR}/externals/boost)
find_package(Boost REQUIRED COMPONENTS filesystem system)
include_directories(${Boost_INCLUDE_DIRS})
target_link_libraries(Server PRIVATE ${Boost_LIBRARIES})

# nlohmann/json
set(NLOHMANN_JSON_ROOT ${CMAKE_CURRENT_SOURCE_DIR}/externals/json)
include_directories(${NLOHMANN_JSON_ROOT}/single_include)

# Google Test
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

