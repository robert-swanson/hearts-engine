load("@rules_cc//cc:defs.bzl", "cc_library")

cc_library(
    name = "game",
    srcs = ["game.h", "round.h", "trick.h", "remote_player.h"],
    deps = ["//server/game/objects"],
    visibility = [
        "//server:__pkg__",
        "//server/matching:__pkg__",
        "//tests:__pkg__",
        "//tools/bench_runner:__pkg__",
    ],
)