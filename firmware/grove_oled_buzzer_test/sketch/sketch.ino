#include <Arduino.h>
#include <Wire.h>
#include <U8g2lib.h>

// Grove Base Shield V2: supply switch at 3.3V, buzzer in D4, OLED in I2C.
// Driver recommended by Seeed for the Grove SSD1315 128x64 OLED.
U8G2_SSD1306_128X64_NONAME_F_HW_I2C oled(U8G2_R0, U8X8_PIN_NONE);
constexpr int BUZZER_PIN = 4;
constexpr int LED_GREEN = 2;
constexpr int LED_YELLOW = 3;
constexpr int LED_RED = 6;
constexpr int LED_WHITE = 7;
constexpr unsigned long SIGNAL_STEP_MS = 2000;
constexpr unsigned long ALERT_HALF_PERIOD_MS = 500;
unsigned long startedAt;
unsigned long lastDisplayAt;
bool beepPlayed = false;
long randomValue = 0;

void updateLeds(unsigned long elapsed) {
  unsigned int phase = (elapsed / SIGNAL_STEP_MS) % 3;
  // Turn all lamps off before selecting the next one.
  digitalWrite(LED_GREEN, LOW);
  digitalWrite(LED_YELLOW, LOW);
  digitalWrite(LED_RED, LOW);
  digitalWrite(phase == 0 ? LED_GREEN : phase == 1 ? LED_YELLOW : LED_RED, HIGH);
  digitalWrite(LED_WHITE, (elapsed / ALERT_HALF_PERIOD_MS) % 2 == 0 ? HIGH : LOW);
}

void drawDisplay(unsigned long elapsed) {
  oled.clearBuffer();
  oled.setFont(u8g2_font_6x12_tr);
  oled.drawStr(0, 12, "Grove / UNO Q");
  oled.setCursor(0, 29);
  oled.print("Casuale: ");
  oled.print(randomValue);
  oled.setCursor(0, 45);
  oled.print("Tempo: ");
  oled.print(elapsed / 1000);
  oled.print(" s");
  oled.drawStr(0, 61, beepPlayed ? "Beep: eseguito" : "Beep: attesa 5 s");
  oled.sendBuffer();
}

void playStartupBeep() {
  // Software waveform avoids dependence on tone() support in the Zephyr core.
  // 810 cycles at ~2700 Hz produce one ~300 ms beep.
  for (unsigned int i = 0; i < 810; ++i) {
    // Keep the alert blinking even during the startup sound.
    if (i % 20 == 0) updateLeds(millis() - startedAt);
    digitalWrite(BUZZER_PIN, HIGH);
    delayMicroseconds(185);
    digitalWrite(BUZZER_PIN, LOW);
    delayMicroseconds(185);
  }
  digitalWrite(BUZZER_PIN, LOW);
}

void setup() {
  startedAt = millis();
  pinMode(BUZZER_PIN, OUTPUT);
  digitalWrite(BUZZER_PIN, LOW);
  const int ledPins[] = {LED_GREEN, LED_YELLOW, LED_RED, LED_WHITE};
  for (int pin : ledPins) {
    pinMode(pin, OUTPUT);
    digitalWrite(pin, LOW);
  }
  updateLeds(millis() - startedAt);
  oled.begin();
  randomSeed(micros());  // Demo values only; not cryptographic randomness.
  randomValue = random(0, 10000);
  lastDisplayAt = millis();
  drawDisplay(lastDisplayAt - startedAt);
}

void loop() {
  unsigned long now = millis();
  updateLeds(now - startedAt);
  if (!beepPlayed && now - startedAt >= 5000UL) {
    beepPlayed = true;
    playStartupBeep();
    now = millis();
    drawDisplay(now - startedAt);
  }
  if (now - lastDisplayAt >= 1000UL) {
    lastDisplayAt = now;
    randomValue = random(0, 10000);
    drawDisplay(now - startedAt);
  }
  delay(1);
}
