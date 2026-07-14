#pragma once

#include <cstdio>
#include <cstring>
#include <filesystem>
#include <system_error>

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
        // Log-file setup must never take the process down: the server runs many
        // concurrent games, and aborting them all because one log file could not
        // be created (disk full, permissions, name collision) turns a local
        // problem into a total outage. Fall back to stderr and keep serving.
        std::error_code ec;
        std::filesystem::create_directories(logFilePath.parent_path(), ec);
        if (ec)
        {
            fprintf(stderr, "Could not create log directory %s (%s); logging to stderr\n",
                    logFilePath.parent_path().c_str(), ec.message().c_str());
            mLogFile = stderr;
            return;
        }
        if (std::filesystem::exists(logFilePath, ec))
            fprintf(stderr, "Log file %s already exists; appending\n", logFilePath.c_str());
        mLogFile = fopen(logFilePath.c_str(), "a");
        if (mLogFile == nullptr)
        {
            fprintf(stderr, "Failed to open log file %s (%s); logging to stderr\n",
                    logFilePath.c_str(), strerror(errno));
            mLogFile = stderr;
        }
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
