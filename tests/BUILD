cc_library(
    name = "test",
    deps = [
        "//server",
        "@googletest//:gtest_main",
    ],
)

cc_test(
    name = "card_collection_test",
    srcs = ["card_collection_gtest.cpp"],
    copts = ["-std=c++17"],
    deps = [":test"],
)

cc_test(
    name = "trick_test",
    srcs = ["trick_gtest.cpp"],
    copts = ["-std=c++17"],
    deps = [
        ":test",
        "//tests/mocks",
    ],
)
