load("@rules_cc//cc:defs.bzl", "cc_binary")

# In-process bench runner. See bench_runner.cpp for the design rationale.
# Reuses //server/game unchanged; the TCP server code path is not affected.
cc_binary(
    name = "bench_runner",
    srcs = [
        "bench_runner.cpp",
        "local_player.h",
    ],
    copts = [
        "-std=c++17",
        "-Wall",
        "-Werror",
    ],
    visibility = ["//visibility:public"],
    deps = [
        "//server/api",
        "//server/game",
        "//server/util",
    ],
)
