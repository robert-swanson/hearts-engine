cc_binary(
    name = "server",
    srcs = ["server.cpp"],
    copts = [
        "-std=c++17",
        "-Wall",
        "-Werror",
    ],
    visibility = [
        "//tests:__subpackages__",
    ],
    deps = [
        "//server/api",
        "//server/matching",
        "//server/util",
    ],
)
