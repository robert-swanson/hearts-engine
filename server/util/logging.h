#pragma once

#include <cstdio>

#include "dates.h"
#include "server/api/message.h"
#include "death.h"

namespace Common {

class ThreadSafeLogger {
public:
    ThreadSafeLogger(const ThreadSafeLogger &) = delete;

    explicit ThreadSafeLogger(FILE *logFile) {
        mLogFile = logFile;
        if (mLogFile == nullptr) DIE("Given log file is null");
    }

    explicit ThreadSafeLogger(const std::filesystem::path& logFilePath) {
        std::filesystem::create_directories(logFilePath.parent_path());
        ASRT(!std::filesystem::exists(logFilePath), "log file %s already exists", logFilePath.c_str());
        mLogFile = fopen(logFilePath.c_str(), "w");
        if (mLogFile == nullptr)
            DIE("Failed to open log file %s: %s", logFilePath.c_str(), strerror(errno));
    }

    void Log(const char *message, ...)
    {
        va_list args;
        va_start(args, message);
        {
            std::lock_guard<std::mutex> lock(mLoggingMutex);
            vfprintf(mLogFile,
                (std::string(Common::Dates::LogTimePrefix() + " ") + message + "\n").c_str(),
                args);
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
    explicit MessageLogger(const std::filesystem::path& logFilePath) : ThreadSafeLogger(logFilePath) {}

    void logMessage(std::string &prefix, const Server::Message::SessionMessage &message) {
        // JSON line: {"dir":"Sent","session":1,"seq":2,"type":"move_request"}
        nlohmann::json entry;
        entry["dir"]     = prefix;
        entry["session"] = message.getSessionID();
        entry["seq"]     = message.getSeqNum();
        entry["type"]    = message.getMsgType();
        Log("%s", entry.dump().c_str());
    }

private:
    MessageLogger() = default;
};

// GameLogger: writes JSON-Lines entries for game events.
// High-level connection/error events still go through LOG() → stdout.
class GameLogger : public ThreadSafeLogger {
public:
    GameLogger(const GameLogger &) = delete;
    explicit GameLogger(FILE *logFile) : ThreadSafeLogger(logFile) {}
    explicit GameLogger(const std::filesystem::path& logFilePath) : ThreadSafeLogger(logFilePath) {}

    void LogJson(const nlohmann::json& entry)
    {
        Log("%s", entry.dump().c_str());
    }
};


#define LOG(message, ...) \
    do {                  \
        Common::PrintLogger.Log(message, ##__VA_ARGS__); \
    } while (false)

}
