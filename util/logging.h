#pragma once

#include <cstdio>

#define LOG(message, ...) \
    do { \
        fprintf(stdout, message, ##__VA_ARGS__); \
        fprintf(stdout, "\n"); \
    } while (false)

#define CONDITIONAL_LOG(condition, message, ...) \
    do { \
        if (condition) { \
            LOG(message, ##__VA_ARGS__); \
        } \
    } while (false)

#define DIE(message, ...) \
    do { \
        fprintf(stderr, message, ##__VA_ARGS__); \
        fprintf(stderr, "\n"); \
        exit(EXIT_FAILURE); \
    } while (false)

