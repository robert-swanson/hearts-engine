load("@rules_cc//cc:defs.bzl", "cc_library")

# Header-only client SDK: transport, session, game loop, and the Player
# interface. Depends only on nlohmann_json (the wire format) and POSIX sockets.
cc_library(
    name = "sdk",
    hdrs = [
        "card.h",
        "card_set.h",
        "client.h",
        "env.h",
        "game_runner.h",
        "player.h",
        "protocol.h",
        "session.h",
        "tcp_channel.h",
        "transport.h",
    ],
    copts = ["-std=c++17"],
    visibility = ["//visibility:public"],
    deps = ["@nlohmann_json//:json"],
)
