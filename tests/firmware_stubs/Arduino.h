#pragma once
#include <algorithm>
#include <cstdint>
#include <cstring>
#include <string>
#include <utility>
#include <vector>
using std::min;
constexpr int HIGH = 1, LOW = 0, OUTPUT = 1, INPUT_PULLUP = 2;
inline uint64_t fakeUs = 0;
inline int pins[32] = {};
inline std::vector<std::pair<int, int>> writes;
inline std::vector<std::string> displayText;
inline unsigned long millis() { return (unsigned long)(fakeUs / 1000); }
inline unsigned long micros() { return (unsigned long)fakeUs; }
inline void delay(unsigned long ms) { fakeUs += ms * 1000; }
inline void delayMicroseconds(unsigned int us) { fakeUs += us; }
inline void pinMode(int pin, int mode) { if (mode == INPUT_PULLUP) pins[pin] = HIGH; }
inline void digitalWrite(int pin, int value) {
  if (pin < 0 || pin >= 32) throw "invalid GPIO";
  pins[pin] = value; writes.emplace_back(pin, value);
}
inline int digitalRead(int pin) { return pins[pin]; }
inline void tone(int, unsigned int, unsigned int) {}
inline void noTone(int) {}
