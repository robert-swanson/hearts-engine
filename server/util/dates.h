#pragma once
#include <iomanip>
#include <chrono>
#include <iostream>
#include <sstream>

namespace Common::Dates
{
static std::string GetStrDate(const char delimiter)
{
    time_t now = time(nullptr);
    tm *ltm = localtime(&now);
    std::string year = std::to_string(1900 + ltm->tm_year);
    std::string month = std::to_string(1 + ltm->tm_mon);
    std::string day = std::to_string(ltm->tm_mday);
    return year + delimiter + month + delimiter + day;
}

static std::string GetStrTime(const char delimiter)
{
    time_t now = time(nullptr);
    tm *ltm = localtime(&now);
    std::string hour = std::to_string(ltm->tm_hour);
    std::string minute = std::to_string(ltm->tm_min);
    std::string second = std::to_string(ltm->tm_sec);

    auto currentTime = std::chrono::system_clock::now();
    auto currentTimeMs = std::chrono::time_point_cast<std::chrono::milliseconds>(currentTime);
    auto epoch = currentTimeMs.time_since_epoch();
    long milliseconds = std::chrono::duration_cast<std::chrono::milliseconds>(epoch).count() % 1000;

    char time[13];
    snprintf(time, 13, "%02d%c%02d%c%02d.%03lu", ltm->tm_hour, delimiter, ltm->tm_min, delimiter, ltm->tm_sec, milliseconds);
    return {time};
}

static std::string LogTimePrefix() {
        return "[" + Dates::GetStrDate('-') + " " + Dates::GetStrTime(':') + "]";
}

#define DATED_PRINT(file, type, message, ...) \
    do { \
        vfprintf(file, "%s [%s]: " message "\n",  Common::Dates::LogTimePrefix().c_str(), type, ##__VA_ARGS__); \
    } while (false)

}
