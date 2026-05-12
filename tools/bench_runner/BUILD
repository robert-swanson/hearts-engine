load("@rules_cc//cc:defs.bzl", "cc_binary")

# In-process bench runner. See bench_runner.cpp for the design rationale.
# Reuses //server/game unchanged; the TCP server code path is not affected.
#
# Depends on //third_party/pybind11:pybind11_embed for the PyBridgePlayer,
# which embeds CPython 3.14 (Homebrew) into the binary so we can run the
# existing Python AIs (claude_v1, expert_player, …) in-process.
cc_binary(
    name = "bench_runner",
    srcs = [
        "bench_runner.cpp",
        "local_player.h",
        "py_bridge_player.h",
    ],
    copts = [
        "-std=c++17",
        "-Wall",
        "-Werror",
    ],
    features = [
        # pybind11/Python headers trip strict warnings on Apple Clang.
        # Treat the vendored `includes` paths as system headers so the
        # warnings don't escalate to errors under -Werror.
        "external_include_paths",
    ],
    visibility = ["//visibility:public"],
    deps = [
        "//server/api",
        "//server/game",
        "//server/util",
        "//third_party/pybind11",
        "//third_party/python:python_embed",
    ],
)
