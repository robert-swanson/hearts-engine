#pragma once

#include <cstdio>

#include "dates.h"
#include "../server/message.h"
#include "death.h"

namespace Common {

class ThreadSafeLogger {
public:
    ThreadSafeLogger(const ThreadSafeLogger &) = delete;

    explicit ThreadSafeLogger(FILE *logFile) {
        mLogFile = logFile;
        if (mLogFile == nullptr) {
            DIE("Given log file is null");
        }
    }

    explicit ThreadSafeLogger(const std::filesystem::path& logFilePath) {
        std::filesystem::create_directories(logFilePath.parent_path());
        ASRT(!std::filesystem::exists(logFilePath), "log file %s already exists", logFilePath.c_str());
        mLogFile = fopen(logFilePath.c_str(), "w");
        if (mLogFile == nullptr) {
            DIE("Failed to open log file %s: %s", logFilePath.c_str(), strerror(errno));
        }
    }

    void Log(const char *message, ...)
    {
        va_list args;
        va_start(args, message);
        {
            std::lock_guard<std::mutex> lock(mLoggingMutex);
            vfprintf(mLogFile, (std::string(Common::Dates::LogTimePrefix() + " [LOG]: ") + message + "\n").c_str(), args);
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

class GameLogger : public ThreadSafeLogger {
public:
    GameLogger(const GameLogger &) = delete;

    explicit GameLogger(FILE *logFile) : ThreadSafeLogger(logFile) {}

    GameLogger(const std::filesystem::path& logFilePath) : ThreadSafeLogger(logFilePath) {}
};


#define LOG(message, ...) \
    do {                  \
        Common::PrintLogger.Log(message, ##__VA_ARGS__); \
    } while (false)


}
