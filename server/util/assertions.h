#pragma once

#include <cassert>
#include <cstdio>
#include <cstdlib>
#include <iostream>
#include "dates.h"

#define ASRT(condition, message, ...) \
    do { \
        if (!(condition)) { \
            fprintf(stderr, "%s [%s]: " message "\n", Common::Dates::LogTimePrefix().c_str(), " [ASSERT_FAIL] ", ##__VA_ARGS__); \
            assert(condition); \
        } \
    } while (false)


#define ASRT_CMP(condition, actual, expected, comparison) \
    do { \
        if (!(condition)) {                               \
            std::cerr << Common::Dates::LogTimePrefix() << " [ASSERT_FAIL] " << actual << " " << comparison << " " << expected << std::endl; \
            assert(condition); \
        } \
    } while (false)

#define ASRT_EQ(actual, expected) \
    ASRT_CMP(actual == expected, actual, expected, "==")

#define ASRT_NE(actual, expected) \
    ASRT_CMP(actual != expected, actual, expected, "!=")

#define ASRT_GT(actual, expected) \
    ASRT_CMP(actual > expected, actual, expected, ">")

#define ASRT_GE(actual, expected) \
    ASRT_CMP(actual >= expected, actual, expected, ">=")

#define ASRT_LT(actual, expected) \
    ASRT_CMP(actual < expected, actual, expected, "<")

#define ASRT_LE(actual, expected) \
    ASRT_CMP(actual <= expected, actual, expected, "<=")
