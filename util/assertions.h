#pragma once

#include <cassert>
#include <cstdio>

#define ASRT(condition, message, ...) \
    do { \
        if (!(condition)) { \
            fprintf(stderr, message, ##__VA_ARGS__); \
            assert(condition); \
        } \
    } while (false)

#define ASRT_EQ(actual, expected) \
    ASRT((actual) == (expected), "Assertion failed: %d == %d\n", (actual), (expected))

#define ASRT_GE(actual, expected) \
    ASRT((actual) >= (expected), "Assertion failed: %d >= %d\n", (actual), (expected))

#define ASRT_LE(actual, expected) \
    ASRT((actual) <= (expected), "Assertion failed: %d <= %d\n", (actual), (expected))

#define ASRT_GT(actual, expected) \
    ASRT((actual) > (expected), "Assertion failed: %d > %d\n", (actual), (expected))

#define ASRT_LT(actual, expected) \
    ASRT((actual) < (expected), "Assertion failed: %d < %d\n", (actual), (expected))
