load("@rules_cc//cc:defs.bzl", "cc_binary", "cc_library")

# RandomPlayer: the reference AI and template, usable as a library by tests and
# other players.
cc_library(
    name = "random_player",
    hdrs = ["random_player.h"],
    copts = ["-std=c++17"],
    visibility = ["//visibility:public"],
    deps = ["//clients/cpp/sdk"],
)

# CLI entry point: joins a lobby by code and plays with RandomPlayer.
cc_binary(
    name = "random_player_bin",
    srcs = ["random_player_main.cpp"],
    copts = ["-std=c++17"],
    visibility = ["//visibility:public"],
    deps = [
        ":random_player",
        "//clients/cpp/sdk",
    ],
)
