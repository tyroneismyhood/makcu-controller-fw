#pragma once

#include <stdint.h>

#define KM_STICK_DEADZONE       4096
#define KM_STICK_MAX            32767
#define KM_MOUSE_MAX_COUNTS_SEC 16000

static inline uint8_t km_map_gip_buttons(const uint8_t *gp) {
    uint16_t buttons = (uint16_t)gp[0] | ((uint16_t)gp[1] << 8);
    uint16_t lt = (uint16_t)gp[2] | ((uint16_t)gp[3] << 8);
    uint16_t rt = (uint16_t)gp[4] | ((uint16_t)gp[5] << 8);
    uint8_t out = 0;
    if (rt >= 64) out |= 0x01;
    if (lt >= 64) out |= 0x02;
    if (buttons & 0x0040) out |= 0x04;  // X
    if (buttons & 0x1000) out |= 0x08;  // LB
    if (buttons & 0x2000) out |= 0x10;  // RB
    return out;
}

static inline uint8_t km_map_xinput_buttons(const uint8_t *report) {
    uint16_t buttons = (uint16_t)report[2] | ((uint16_t)report[3] << 8);
    uint8_t out = 0;
    if (report[5] >= 16) out |= 0x01;  // RT
    if (report[4] >= 16) out |= 0x02;  // LT
    if (buttons & 0x4000) out |= 0x04; // X
    if (buttons & 0x0100) out |= 0x08; // LB
    if (buttons & 0x0200) out |= 0x10; // RB
    return out;
}

static inline uint8_t km_map_sony_buttons(const uint8_t *report, int ds4) {
    uint8_t face = ds4 ? report[5] : report[8];
    uint8_t shoulder = ds4 ? report[6] : report[9];
    uint8_t lt = ds4 ? report[8] : report[5];
    uint8_t rt = ds4 ? report[9] : report[6];
    uint8_t out = 0;
    if (rt >= 16) out |= 0x01;
    if (lt >= 16) out |= 0x02;
    if (face & 0x10) out |= 0x04;      // Square
    if (shoulder & 0x01) out |= 0x08;  // L1
    if (shoulder & 0x02) out |= 0x10;  // R1
    return out;
}

// Absolute controller right-stick position to relative MAKCU mouse counts.
// Radial deadzone plus a 25% linear / 75% quadratic progressive curve.
static inline void km_stick_to_delta(int32_t x, int32_t y, uint32_t period_ms,
                                     int16_t *dx, int16_t *dy) {
    int32_t ax = x < 0 ? -x : x;
    int32_t ay = y < 0 ? -y : y;
    int32_t hi = ax > ay ? ax : ay;
    int32_t lo = ax > ay ? ay : ax;
    int32_t mag = hi + ((lo * 3) >> 3);
    if (mag > KM_STICK_MAX) mag = KM_STICK_MAX;
    if (mag <= KM_STICK_DEADZONE) {
        *dx = 0;
        *dy = 0;
        return;
    }

    int32_t norm = (int32_t)(((int64_t)(mag - KM_STICK_DEADZONE) *
                              KM_STICK_MAX) /
                             (KM_STICK_MAX - KM_STICK_DEADZONE));
    int32_t shaped = (norm >> 2) +
        (int32_t)(((int64_t)norm * norm * 3) /
                  (4LL * KM_STICK_MAX));
    if (norm == KM_STICK_MAX) shaped = KM_STICK_MAX;
    int32_t vx = (int32_t)(((int64_t)x * shaped) / mag);
    int32_t vy = (int32_t)(((int64_t)y * shaped) / mag);
    int64_t scale = (int64_t)KM_MOUSE_MAX_COUNTS_SEC * period_ms;
    int32_t ox = (int32_t)(((int64_t)vx * scale) /
                           ((int64_t)KM_STICK_MAX * 1000LL));
    int32_t oy = (int32_t)(((int64_t)vy * scale) /
                           ((int64_t)KM_STICK_MAX * 1000LL));
    if (vx && !ox) ox = vx < 0 ? -1 : 1;
    if (vy && !oy) oy = vy < 0 ? -1 : 1;
    if (ox < -32767) ox = -32767;
    if (ox > 32767) ox = 32767;
    if (oy < -32767) oy = -32767;
    if (oy > 32767) oy = 32767;
    *dx = (int16_t)ox;
    *dy = (int16_t)oy;
}
