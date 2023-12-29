#pragma once

#include <string>
#include <fstream>
#include <utility>

struct Variable
{
    std::string raw_value;
    bool used=false;
};

class EnvironmentLoader
{
public:
    EnvironmentLoader(std::filesystem::path env_file_path)
    {
        std::ifstream env_file(env_file_path);
        ASRT(env_file.is_open(), "Could not open env file '%s'", env_file_path.c_str());
        std::string line;
        while (std::getline(env_file, line))
        {
            auto delimiter = line.find('=');
            ASRT(delimiter != std::string::npos, "Invalid env file line: %s", line.c_str());
            auto key = line.substr(0, delimiter);
            auto value = line.substr(delimiter + 1);
            mVariables[key] = Variable{std::move(value)};
        }
    }

    std::string getString(std::string key)
    {
        auto variable = mVariables.find(key);
        ASRT(variable != mVariables.end(), "Env variable '%s' not specified", key.c_str());
        variable->second.used = true;
        return variable->second.raw_value;
    }

    int getInt(std::string key)
    {
        return std::stoi(getString(std::move(key)));
    }

    bool getBool(std::string key)
    {
        auto value = getString(key);
        if (value == "true")
        {
            return true;
        }
        else if (value == "false")
        {
            return false;
        }
        else
        {
            DIE("Env variable '%s' is not a boolean", key.c_str());
        }
    }

    void assertAllUsed()
    {
        for (auto & [key, variable] : mVariables)
        {
            ASRT(variable.used, "Env variable '%s' not used", key.c_str());
        }
    }
private:
std::unordered_map<std::string, Variable> mVariables;

};

static std::optional<EnvironmentLoader> EnvLoader = std::nullopt;

#define ENV_STRING(key) EnvLoader->getString(key)
#define ENV_INT(key) EnvLoader->getInt(key)
#define ENV_BOOL(key) EnvLoader->getBool(key)