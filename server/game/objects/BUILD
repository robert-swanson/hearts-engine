load("@rules_cc//cc:defs.bzl", "cc_library")

cc_library(
    name = "objects",
    srcs = [
        "card.h",
        "card_collection.h",
        "constants.h",
        "player.h",
        "types.h",
    ],
    visibility = [
        "//server/api:__pkg__",
        "//server/game:__pkg__",
        "//tests:__pkg__",
    ],
    deps = [
        "//server/util",
    ],
)
