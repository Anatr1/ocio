#pragma once
#include "Arduino.h"
constexpr int U8G2_R0 = 0, U8X8_PIN_NONE = 0, u8g2_font_6x12_tr = 0;
struct U8G2_SSD1306_128X64_NONAME_F_HW_I2C {
  U8G2_SSD1306_128X64_NONAME_F_HW_I2C(int, int) {}
  void begin() {}
  void clearBuffer() { displayText.clear(); }
  void setFont(int) {}
  void drawStr(int, int, const char* s) { displayText.emplace_back(s); }
  void setCursor(int, int) {}
  void print(const char* s) { displayText.emplace_back(s); }
  void print(int n) { displayText.push_back(std::to_string(n)); }
  void drawBox(int, int, int, int) {}
  void sendBuffer() {}
};
