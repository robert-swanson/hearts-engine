#pragma once

#include <cassert>
#include <cstdio>

#define ASRT(condition, message, ...) \
    do { \
        if (!(condition)) { \
            fprintf(stderr, message, ##__VA_ARGS__); \
            fprintf(stderr, "\n"); \
            assert(condition); \
        } \
    } while (false)


#define ASRT_CMP(condition, actual, expected, comparison) \
    do { \
        if (!(condition)) {                               \
            std::cerr << "Assertion failed: " << actual << " " << comparison << " " << expected << std::endl; \
            assert(condition); \
        } \
    } while (false)

#define ASRT_EQ(actual, expected) \
    ASRT_CMP(actual == expected, actual, expected, "==")

#define ASRT_GT(actual, expected) \
    ASRT_CMP(actual > expected, actual, expected, ">")

#define ASRT_GE(actual, expected) \
    ASRT_CMP(actual >= expected, actual, expected, ">=")

#define ASRT_LT(actual, expected) \
    ASRT_CMP(actual < expected, actual, expected, "<")

#define ASRT_LE(actual, expected) \
    ASRT_CMP(actual <= expected, actual, expected, "<=")
