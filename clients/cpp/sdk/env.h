#pragma once

// Minimal env-file reader, matching the KEY=VALUE format used across the repo
// (config.env / local.config.env). Lines starting with '#' and blank lines are
// ignored. Used so the C++ client reads the same server address/port config as
// the Python clients and the server.

#include <fstream>
#include <stdexcept>
#include <string>
#include <unordered_map>

namespace hearts {

class EnvFile {
 public:
  explicit EnvFile(const std::string& path) {
    std::ifstream in(path);
    if (!in.is_open())
      throw std::runtime_error("could not open env file: " + path);
    std::string line;
    while (std::getline(in, line)) {
      if (line.empty() || line[0] == '#') continue;
      auto eq = line.find('=');
      if (eq == std::string::npos) continue;
      vars_[line.substr(0, eq)] = line.substr(eq + 1);
    }
  }

  std::string get(const std::string& key) const {
    auto it = vars_.find(key);
    if (it == vars_.end())
      throw std::runtime_error("env key not found: " + key);
    return it->second;
  }

  std::string getOr(const std::string& key, const std::string& fallback) const {
    auto it = vars_.find(key);
    return it == vars_.end() ? fallback : it->second;
  }

  int getInt(const std::string& key) const { return std::stoi(get(key)); }

 private:
  std::unordered_map<std::string, std::string> vars_;
};

}  // namespace hearts
