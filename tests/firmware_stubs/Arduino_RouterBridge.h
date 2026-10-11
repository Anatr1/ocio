#pragma once
#include "Arduino.h"
struct FakeBridge {
  void begin() {}
  template<class F> void provide(const char*, F) {}
  template<class T> void notify(const char*, T) {}
};
inline FakeBridge Bridge;
