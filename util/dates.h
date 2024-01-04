#pragma once

namespace Common::Dates
{
static std::string GetStrDate(const std::string& delimiter)
{
    time_t now = time(0);
    tm *ltm = localtime(&now);
    std::string year = std::to_string(1900 + ltm->tm_year);
    std::string month = std::to_string(1 + ltm->tm_mon);
    std::string day = std::to_string(ltm->tm_mday);
    return year + delimiter + month + delimiter + day;
}

static std::string GetStrTime(const std::string& delimiter)
{
    time_t now = time(0);
    tm *ltm = localtime(&now);
    std::string hour = std::to_string(ltm->tm_hour);
    std::string minute = std::to_string(ltm->tm_min);
    std::string second = std::to_string(ltm->tm_sec);
    return hour + delimiter + minute + delimiter + second;
}

}