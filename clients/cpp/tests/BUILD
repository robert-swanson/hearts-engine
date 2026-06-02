load("@rules_cc//cc:defs.bzl", "cc_library", "cc_test")

# In-memory MessageChannel shared by the protocol and game-runner tests.
cc_library(
    name = "mock_channel",
    testonly = True,
    hdrs = ["mock_channel.h"],
    copts = ["-std=c++17"],
    deps = ["//clients/cpp/sdk"],
)

# Card / CardSet value-type tests (no channel needed).
cc_test(
    name = "card_test",
    srcs = ["card_test.cpp"],
    copts = ["-std=c++17"],
    deps = [
        "//clients/cpp/sdk",
        "@googletest//:gtest_main",
    ],
)

# Framing split + Session sequence-counter behavior.
cc_test(
    name = "protocol_test",
    srcs = ["protocol_test.cpp"],
    copts = ["-std=c++17"],
    deps = [
        ":mock_channel",
        "//clients/cpp/sdk",
        "@googletest//:gtest_main",
    ],
)

# Full scripted game through GameRunner, plus RandomPlayer legality.
cc_test(
    name = "game_runner_test",
    srcs = ["game_runner_test.cpp"],
    copts = ["-std=c++17"],
    deps = [
        ":mock_channel",
        "//clients/cpp/players:random_player",
        "//clients/cpp/sdk",
        "@googletest//:gtest_main",
    ],
)
