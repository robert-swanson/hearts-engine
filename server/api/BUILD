load("@rules_cc//cc:defs.bzl", "cc_library")

cc_library(
    name = "api",
    srcs = [
        "connection.h",
        "game_session.h",
        "managed_connection.h",
        "message.h",
    ],
    visibility = ["//server:__subpackages__", "//tests:__pkg__"],
    deps = ["//server/game/objects"],
)
