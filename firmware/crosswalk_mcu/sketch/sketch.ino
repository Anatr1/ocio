// OCCHIO - real-time side of the crosswalk node (STM32U585 on the Arduino UNO Q, Zephyr core).
//
// The Linux side (vision pipeline, crosswalk/mcu.py) talks to this sketch through the arduino-router
// (MessagePack-RPC). This sketch owns everything that must stay deterministic and safe:
//   * the signal lamps (vehicle R/Y/G + pedestrian R/G) and the driver warning beacon
//   * an audible accessible-pedestrian-signal (ticks while walking, fast ticks during clearance)
//   * the pedestrian push button (fallback call when the camera is blind)
//   * the 8x13 LED matrix (frames rendered on Linux)
//   * a FAIL-SAFE WATCHDOG: if Linux stops sending heartbeats for 2 s (crash, reboot, cable), the lamps
//     go to flashing amber - exactly what real traffic controllers do on a fault.
//
// RPC methods provided (called from Python):
//   set_signal(veh, ped)  veh: 0 off 1 red 2 yellow 3 green 4 flashing-yellow   ped: 0 off 1 red 2 green 3 flashing
//   set_warning(level)    0 off, 1 caution (amber slow blink), 2 danger (RED fast blink + beeps)
//   set_audio(on)         enable / disable the accessible pedestrian signal
//   draw(frame)           104 bytes, values 0..7 (row-major 8x13)
//   heartbeat(ms) -> int  returns MCU millis()
//   ping() -> int
// Notifications sent to Python:
//   ped_button(millis)    physical push button pressed

#include <Arduino_RouterBridge.h>
#include <Arduino_LED_Matrix.h>
#include <vector>
#include "hardware.h"
#if OCCHIO_HAS_OLED
#include <Wire.h>
#include <U8g2lib.h>
U8G2_SSD1306_128X64_NONAME_F_HW_I2C oled(U8G2_R0, U8X8_PIN_NONE);
#endif

// Pin assignments and optional peripherals are selected in hardware.h.

const unsigned long HEARTBEAT_TIMEOUT_MS = 2000;

// Buzzer: 0 = ACTIVE buzzer (on/off with digitalWrite - always compiles), 1 = passive piezo with tone()
// (set to 1 only if tone() is available in the installed arduino:zephyr core)
#define USE_TONE 0

Arduino_LED_Matrix matrix;
const uint8_t FRAME_SIZE = 8 * 13;

// state written by RPC handlers, applied in loop()
volatile int vehState = 4;          // start in flashing amber until Linux takes over
volatile int pedState = 0;
volatile int warnLevel = 0;
volatile bool audioOn = true;
volatile unsigned long lastHeartbeat = 0;
volatile bool frameDirty = true;   // load the fail-safe icon on the first loop, before any heartbeat
uint8_t frame[FRAME_SIZE] = {0};
uint8_t frameIn[FRAME_SIZE] = {0};

bool failsafe = true;
unsigned long lastButton = 0;
int lastButtonLevel = HIGH;
unsigned long nextTick = 0;
unsigned long beepOff = 0;
unsigned int beepHalfPeriodUs = 0;
int audioMode = 0;
bool matrixBlank = false;
unsigned long lastOled = 0;

void stopBeep() {
#if USE_TONE
  noTone(PIN_BUZZER);
#endif
  digitalWrite(PIN_BUZZER, LOW);
  beepOff = 0;
}

void beep(unsigned long now, unsigned int ms, unsigned int freq) {
  beepOff = now + ms;
#if OCCHIO_SOFT_BUZZER
  beepHalfPeriodUs = 500000UL / freq;
#elif USE_TONE
  tone(PIN_BUZZER, freq, ms);
#else
  (void)freq;
  digitalWrite(PIN_BUZZER, HIGH);
#endif
}

void serviceBeep(unsigned long now) {
  if (!beepOff) return;
  if ((int32_t)(now - beepOff) >= 0) {
    stopBeep();
    return;
  }
#if OCCHIO_SOFT_BUZZER
  // One bounded cycle, at most ~1.14 ms at 880 Hz. Re-enter the control loop
  // between cycles so the watchdog and lamps are serviced throughout a beep.
  digitalWrite(PIN_BUZZER, HIGH);
  delayMicroseconds(beepHalfPeriodUs);
  digitalWrite(PIN_BUZZER, LOW);
  delayMicroseconds(beepHalfPeriodUs);
#endif
}

// fail-safe frame: exclamation mark
const uint8_t FAILSAFE_FRAME[FRAME_SIZE] = {
  0,0,0,0,0,0,7,0,0,0,0,0,0,
  0,0,0,0,0,0,7,0,0,0,0,0,0,
  0,0,0,0,0,0,7,0,0,0,0,0,0,
  0,0,0,0,0,0,7,0,0,0,0,0,0,
  0,0,0,0,0,0,7,0,0,0,0,0,0,
  0,0,0,0,0,0,0,0,0,0,0,0,0,
  0,0,0,0,0,0,7,0,0,0,0,0,0,
  0,0,0,0,0,0,0,0,0,0,0,0,0,
};

// ------------------------------------------------------------------ RPC handlers (no hardware access here)
void set_signal(int veh, int ped) {
  vehState = veh;
  pedState = ped;
}

void set_warning(int level) { warnLevel = level; }

void set_audio(bool on) { audioOn = on; }

void draw(std::vector<uint8_t> f) {
  size_t n = min(f.size(), (size_t)FRAME_SIZE);
  memcpy(frameIn, f.data(), n);
  frameDirty = true;
}

int heartbeat(int ms) {
  lastHeartbeat = millis();
  return (int)millis();
}

int ping() { return (int)millis(); }

// Read-only diagnostic; does NOT refresh the heartbeat or command the outputs.
// schema, Grove profile, effective failsafe, vehicle, pedestrian, warning, audio, heartbeat age (ms).
std::vector<int> get_status() {
  unsigned long now = millis();
  bool fs = !lastHeartbeat || now - lastHeartbeat > HEARTBEAT_TIMEOUT_MS;
  return {1, OCCHIO_GROVE_PROFILE, (int)fs, fs ? 4 : vehState,
          fs ? 0 : pedState, fs ? 0 : warnLevel, (int)audioOn,
          lastHeartbeat ? (int)(now - lastHeartbeat) : -1};
}

// ------------------------------------------------------------------ helpers
void lamp(int pin, bool on) { if (pin >= 0) digitalWrite(pin, on ? HIGH : LOW); }

void applyLamps(unsigned long now) {
  bool blink1Hz = (now / 500) % 2 == 0;
  int veh = failsafe ? 4 : vehState;
  int ped = failsafe ? 0 : pedState;
  lamp(PIN_VEH_R, veh == 1);
  lamp(PIN_VEH_Y, veh == 2 || (veh == 4 && blink1Hz));
  lamp(PIN_VEH_G, veh == 3);
  lamp(PIN_PED_R, ped == 1);
  lamp(PIN_PED_G, ped == 2 || (ped == 3 && blink1Hz));
  int w = failsafe ? 0 : warnLevel;
  // B1 caution: amber slow blink; B2 danger: RED fast blink (amber off)
  lamp(PIN_BEACON, (w == 1 && (now / 400) % 2 == 0)
       || (OCCHIO_GROVE_PROFILE && w >= 2 && (now / 120) % 2 == 0));
  lamp(PIN_BEACON_RED, w >= 2 && (now / 120) % 2 == 0);
}

void applyAudio(unsigned long now) {
  if (failsafe || !audioOn) { stopBeep(); audioMode = 0; return; }
  int mode = warnLevel >= 2 ? 3 : pedState == 3 ? 2 : pedState == 2 ? 1 : 0;
  if (mode != audioMode) {
    audioMode = mode;
    stopBeep();
    nextTick = now;  // a danger/phase transition must not wait for the old walk tick
  }
  if (now < nextTick) return;
  if (warnLevel >= 2) {           // danger overrides walk/clearance audio
    beep(now, 60, 1760);
    nextTick = now + 300;
  } else if (pedState == 2) {     // walk: slow ticks
    beep(now, 40, 880);
    nextTick = now + 1000;
  } else if (pedState == 3) {     // clearance: fast ticks
    beep(now, 30, 880);
    nextTick = now + 250;
  } else {
    nextTick = now + 100;
  }
}

void pollButton(unsigned long now) {
  if (PIN_BUTTON < 0) return;
  int lv = digitalRead(PIN_BUTTON);
  if (lv != lastButtonLevel && now - lastButton > 50) {
    lastButton = now;
    lastButtonLevel = lv;
    if (lv == LOW) {
      Bridge.notify("ped_button", (int)now);
      if (audioOn && !failsafe) beep(now, 80, 1320);  // acknowledge
    }
  }
}

#if OCCHIO_HAS_OLED
const char* vehicleName(int state) {
  switch (state) {
    case 1: return "RED";
    case 2: return "YELLOW";
    case 3: return "GREEN";
    case 4: return "FLASH AMBER";
    default: return "OFF";
  }
}

const char* pedestrianName(int state) {
  switch (state) {
    case 1: return "STOP";
    case 2: return "WALK";
    case 3: return "CLEARANCE";
    default: return "OFF";
  }
}

void updateOled(unsigned long now) {
  // Avoid pausing the passive waveform for an I2C transfer. OLED timing/overhead
  // still needs measurement on the board; GPIO and watchdog are served first.
  if (beepOff || now - lastOled < 250) return;
  lastOled = now;
  oled.clearBuffer();
  oled.setFont(u8g2_font_6x12_tr);
  oled.drawStr(0, 10, failsafe ? "ocio / FAILSAFE" : "ocio / vision RPC");
  oled.setCursor(0, 22); oled.print("Cars: "); oled.print(vehicleName(failsafe ? 4 : vehState));
  oled.setCursor(0, 34); oled.print("Peds: "); oled.print(pedestrianName(failsafe ? 0 : pedState));
  oled.setCursor(0, 46); oled.print("Alert: "); oled.print(failsafe ? 0 : warnLevel);
  const uint8_t* shown = failsafe ? FAILSAFE_FRAME : frameIn;
  for (int r = 0; r < 8; ++r) for (int c = 0; c < 13; ++c)
    if (shown[r * 13 + c]) oled.drawBox(98 + c * 2, 47 + r * 2, 2, 2);
  oled.drawStr(0, 61, "Grove D2/3/6/7");
  oled.sendBuffer();
}
#endif

// ------------------------------------------------------------------ setup / loop
void setup() {
  int outs[] = {PIN_VEH_R, PIN_VEH_Y, PIN_VEH_G, PIN_PED_R, PIN_PED_G, PIN_BEACON, PIN_BUZZER, PIN_BEACON_RED};
  for (int p : outs) {
    if (p < 0) continue;
    pinMode(p, OUTPUT);
    digitalWrite(p, LOW);
  }
  if (PIN_BUTTON >= 0) pinMode(PIN_BUTTON, INPUT_PULLUP);
  matrix.begin();
  matrix.setGrayscaleBits(3);
  matrix.clear();
  Bridge.begin();
  Bridge.provide("set_signal", set_signal);
  Bridge.provide("set_warning", set_warning);
  Bridge.provide("set_audio", set_audio);
  Bridge.provide("draw", draw);
  Bridge.provide("heartbeat", heartbeat);
  Bridge.provide("ping", ping);
  Bridge.provide("get_status", get_status);
#if OCCHIO_HAS_OLED
  oled.begin();
#endif
}

void loop() {
  unsigned long now = millis();
  bool fs = (lastHeartbeat == 0) || (now - lastHeartbeat > HEARTBEAT_TIMEOUT_MS);
  if (fs != failsafe) {
    failsafe = fs;
    frameDirty = true;
  }
  applyLamps(now);
  applyAudio(now);
  pollButton(now);
  serviceBeep(now);
  bool matrixChanged = frameDirty;
  if (frameDirty) {
    frameDirty = false;
    if (failsafe) {
      memcpy(frame, FAILSAFE_FRAME, FRAME_SIZE);
    } else {
      memcpy(frame, frameIn, FRAME_SIZE);
    }
  }
  bool blank = failsafe && (now / 500) % 2 == 1;
  if (matrixChanged || blank != matrixBlank) {
    matrixBlank = blank;
    if (blank) {
      uint8_t empty[FRAME_SIZE] = {0};
      matrix.draw(empty);
    } else {
      matrix.draw(frame);
    }
  }
#if OCCHIO_HAS_OLED
  updateOled(now);
#endif
#if OCCHIO_SOFT_BUZZER
  if (!beepOff) delay(1);
#else
  delay(10);
#endif
}
