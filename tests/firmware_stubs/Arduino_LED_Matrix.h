#pragma once
#include "Arduino.h"
struct Arduino_LED_Matrix {
  int draws = 0;
  uint8_t pixels[104] = {};
  void begin() {}
  void setGrayscaleBits(int) {}
  void clear() {}
  void draw(const uint8_t* frame) { ++draws; memcpy(pixels, frame, 104); }
};
