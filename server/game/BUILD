load("@rules_cc//cc:defs.bzl", "cc_library")

cc_library(
    name = "game",
    srcs = ["game.h", "round.h", "trick.h", "remote_player.h", "game_observer.h", "game_recorder.h"],
    deps = ["//server/game/objects", "@nlohmann_json//:json"],
    visibility = [
        "//server:__pkg__",
        "//server/matching:__pkg__",
        "//tests:__pkg__",
    ],
)