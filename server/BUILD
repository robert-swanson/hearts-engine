load("@rules_cc//cc:defs.bzl", "cc_binary")

cc_binary(
    name = "server",
    srcs = ["server.cpp"],
    copts = ["-std=c++17", "-Wall", "-Werror"],
    visibility = ["//tests:__subpackages__"],
    deps = [
        "//server/api",
        "//server/matching",
        "//server/util",
    ],
)

cc_binary(
    name = "tournament_server",
    srcs = ["tournament_server.cpp"],
    copts = ["-std=c++17", "-Wall", "-Werror"],
    deps = [
        "//server/api",
        "//server/game",
        "//server/util",
    ],
)
