#pragma once

#include <cstdio>
#include "../server/message.h"
#include "death.h"

namespace Common {

class ThreadSafeLogger {
public:
    ThreadSafeLogger(const ThreadSafeLogger &) = delete;

    explicit ThreadSafeLogger(FILE *logFile) {
        mLogFile = logFile;
        if (mLogFile == nullptr) {
            DIE("Failed to open log file");
        }
    }

    explicit ThreadSafeLogger(const std::filesystem::path& logFilePath) {
        std::filesystem::create_directories(logFilePath.parent_path());
        ASRT(!std::filesystem::exists(logFilePath), "Log file %s already exists", logFilePath.c_str());
        mLogFile = fopen(logFilePath.c_str(), "w");
        if (mLogFile == nullptr) {
            DIE("Failed to open log file %s", logFilePath.c_str());
        }
    }

    void Log(const char *message, ...) {
        va_list args;
        va_start(args, message);
        {
            std::lock_guard<std::mutex> lock(mLoggingMutex);
            vfprintf(mLogFile, message, args);
            fprintf(mLogFile, "\n");
        }
        va_end(args);
        fflush(mLogFile);
    }

protected:
    ThreadSafeLogger() = default;

    std::mutex mLoggingMutex;
    FILE *mLogFile = nullptr;
};

static ThreadSafeLogger PrintLogger = ThreadSafeLogger(stdout);

class MessageLogger : ThreadSafeLogger {
public:
    MessageLogger(const MessageLogger &) = delete;

    explicit MessageLogger(FILE *logFile) : ThreadSafeLogger(logFile) {}

    MessageLogger(const std::filesystem::path& logFilePath) : ThreadSafeLogger(logFilePath) {}

    void logMessage(std::string &prefix, const Server::Message::SessionMessage &message) {
        Log("%15s%4d.%4d\t%20s\t\t\t%s", prefix.c_str(), message.getSessionID(), message.getSeqNum(), message.getMsgType().c_str(), message.getJson().dump().c_str());
    }

private:
    MessageLogger() = default;
};


#define LOG(message, ...) \
    do {                  \
        Common::PrintLogger.Log(message, ##__VA_ARGS__); \
    } while (false)

#define CONDITIONAL_LOG(condition, message, ...) \
    do { \
        if (condition) { \
            LOG(message, ##__VA_ARGS__); \
        } \
    } while (false)

}
