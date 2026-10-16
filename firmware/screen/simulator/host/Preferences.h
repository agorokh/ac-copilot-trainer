#pragma once

#include <map>
#include <stdint.h>
#include <string>

// Exercise production persistence consumers without writing real NVS or user files.
// Values live only for this simulator process; power-cycle persistence is not proved.
class Preferences {
    std::map<std::string, uint8_t> values_;
public:
    bool begin(const char*, bool) { return true; }
    uint8_t getUChar(const char* key, uint8_t fallback = 0) {
        auto found = values_.find(key);
        return found == values_.end() ? fallback : found->second;
    }
    size_t putUChar(const char* key, uint8_t value) {
        values_[key] = value;
        return 1;
    }
};
