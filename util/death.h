#pragma once

#define DIE(message, ...) \
    do { \
        fprintf(stderr, message, ##__VA_ARGS__); \
        fprintf(stderr, "\n"); \
        exit(EXIT_FAILURE); \
    } while (false)
