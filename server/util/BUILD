load("@rules_cc//cc:defs.bzl", "cc_library")

cc_library(
    name = "util",
    srcs = [
        "assertions.h",
        "constants.h",
        "dates.h",
        "death.h",
        "env.h",
        "logging.h",
        "types.h",
        "validation.h",
    ],
    visibility = ["//server:__subpackages__", "//tests:__pkg__"],
    deps = [
        "@boost.asio",
        "@nlohmann_json//:json",
    ],
)
