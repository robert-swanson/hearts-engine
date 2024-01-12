#pragma once

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
    char time[9];
    snprintf(time, 9, "%02d%c%02d%c%02d", ltm->tm_hour, delimiter, ltm->tm_min, delimiter, ltm->tm_sec);
    return {time};
}

}