// Compile the actual sketch with fake peripherals; this cannot prove electrical behaviour or target compilation.
#include <cassert>
#include <string>
#include "sketch.ino"

void at(unsigned long ms) { fakeUs = (uint64_t)ms * 1000; }

int main(int argc, char** argv) {
  assert(argc == 2);
  std::string test = argv[1];
  setup(); at(10); loop();
  if (test == "audio") {
    at(1000); heartbeat(1); failsafe = false;
    beep(millis(), 80, 880); serviceBeep(millis());
    set_audio(false); applyAudio(millis());
    assert(pins[PIN_BUZZER] == LOW && beepOff == 0);
    audioOn = true; beep(millis(), 80, 880); failsafe = true; applyAudio(millis());
    assert(pins[PIN_BUZZER] == LOW && beepOff == 0);
    return 0;
  }
#ifndef OCCHIO_TEST_OLD_SOURCE
  if (test == "danger_audio") {
    at(1000); heartbeat(1); failsafe = false; nextTick = 0;
    set_signal(1, 2); set_warning(0); loop();
    assert(beepOff == 1040);
    at(1020); set_warning(2); loop();
    assert(beepOff == 1080); // danger must interrupt the pending one-second walk schedule
    return 0;
  }
  if (test == "lamps") {
    assert(pins[PIN_VEH_Y] == HIGH && pins[PIN_VEH_G] == LOW && pins[PIN_VEH_R] == LOW);
    set_signal(3, 1); heartbeat(1); at(20); loop();
    assert(!failsafe && pins[PIN_VEH_G] == HIGH && pins[PIN_VEH_Y] == LOW);
    set_signal(2, 1); at(30); loop();
    assert(pins[PIN_VEH_Y] == HIGH && pins[PIN_VEH_G] == LOW);
    set_signal(1, 2); at(40); loop();
    assert(pins[PIN_VEH_R] == HIGH && pins[PIN_VEH_Y] == LOW && pins[PIN_VEH_G] == LOW);
    if (PIN_PED_G >= 0) assert(pins[PIN_PED_G] == HIGH);
    return 0;
  }
  if (test == "watchdog") {
    at(100); heartbeat(1); set_signal(3, 1); loop();
    at(2101); set_signal(3, 2); loop(); // commands without heartbeat cannot defeat the watchdog
    assert(failsafe && pins[PIN_VEH_G] == LOW && pins[PIN_BUZZER] == LOW);
    auto before = lastHeartbeat;
    auto status = get_status();
    assert(status[0] == 1 && status[1] == OCCHIO_GROVE_PROFILE && status[2] == 1);
    assert(status[3] == 4 && status[4] == 0 && status[5] == 0 && lastHeartbeat == before);
    at(2120); heartbeat(1); loop(); assert(!failsafe && pins[PIN_VEH_G] == HIGH);
    return 0;
  }
  if (test == "warning") {
    at(800); heartbeat(1); set_signal(0, 0); set_warning(1); loop();
    assert(pins[PIN_BEACON] == HIGH);
    at(1200); heartbeat(1); loop(); assert(pins[PIN_BEACON] == LOW);
    at(1440); heartbeat(1); set_warning(2); loop();
    if (OCCHIO_GROVE_PROFILE) {
      assert(PIN_VEH_G == 3 && PIN_VEH_Y == 2 && PIN_VEH_R == 6 && PIN_BUZZER == 4 && PIN_BEACON == 7);
      assert(PIN_BUTTON < 0 && PIN_PED_G < 0 && PIN_PED_R < 0 && PIN_BEACON_RED < 0);
      assert(pins[7] == HIGH);
      auto started = fakeUs; writes.clear(); serviceBeep(millis());
      assert(fakeUs - started < 2000 && writes.size() == 2); // bounded passive waveform cycle
      assert(writes[0] == std::make_pair(4, HIGH) && writes[1] == std::make_pair(4, LOW));
      at(1560); loop(); assert(pins[7] == LOW);
#if OCCHIO_HAS_OLED
      stopBeep(); at(1800); updateOled(millis());
      assert(std::find(displayText.begin(), displayText.end(), "ocio / vision RPC") != displayText.end());
      failsafe = true; at(2100); updateOled(millis());
      assert(std::find(displayText.begin(), displayText.end(), "ocio / FAILSAFE") != displayText.end());
#endif
    } else {
      assert(pins[PIN_BEACON] == LOW && pins[PIN_BEACON_RED] == HIGH);
    }
    return 0;
  }
#endif
  return 2;
}
