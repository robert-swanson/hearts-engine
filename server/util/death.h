#pragma once
#include "dates.h"

#define DIE(message, ...) \
    do { \
        fprintf(stderr, "%s [%s]: " message "\n", Common::Dates::LogTimePrefix().c_str(), " [DEATH] ", ##__VA_ARGS__); \
        exit(EXIT_FAILURE); \
    } while (false)
