#pragma once

// The packager selects Grove explicitly; direct use of this app retains the original wiring.
#ifndef OCCHIO_GROVE_PROFILE
#define OCCHIO_GROVE_PROFILE 0
#endif

#if OCCHIO_GROVE_PROFILE
const int PIN_VEH_R = 6;
const int PIN_VEH_Y = 2;       // operator-confirmed wiring, 2026-10-11
const int PIN_VEH_G = 3;
const int PIN_PED_R = -1;       // no separate pedestrian lamps in the proven Grove wiring
const int PIN_PED_G = -1;
const int PIN_BEACON = 7;      // WHITE shared alert: B1 slow / B2 fast, not an amber/red beacon
const int PIN_BEACON_RED = -1;
const int PIN_BUZZER = 4;      // passive buzzer, software waveform (no tone() dependency)
const int PIN_BUTTON = -1;     // absent in setup-GPIO-app; dashboard Call remains available
#define OCCHIO_SOFT_BUZZER 1
#ifndef OCCHIO_HAS_OLED
#define OCCHIO_HAS_OLED 1
#endif
#else
const int PIN_VEH_R = 2;
const int PIN_VEH_Y = 3;
const int PIN_VEH_G = 4;
const int PIN_PED_R = 5;
const int PIN_PED_G = 6;
const int PIN_BEACON = 7;
const int PIN_BUZZER = 8;
const int PIN_BUTTON = 9;
const int PIN_BEACON_RED = 10;
#define OCCHIO_SOFT_BUZZER 0
#ifndef OCCHIO_HAS_OLED
#define OCCHIO_HAS_OLED 0
#endif
#endif
