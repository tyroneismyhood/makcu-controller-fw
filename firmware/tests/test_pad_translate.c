#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#include "km_pad_translate.h"

static void test_gip_buttons(void) {
    uint8_t report[16] = {0};
    report[2] = 64;
    assert(km_map_gip_buttons(report) == 0x02); // LT -> right
    memset(report, 0, sizeof(report));
    report[4] = 64;
    assert(km_map_gip_buttons(report) == 0x01); // RT -> left
    report[0] = 0x40;
    report[1] = 0x30;
    assert(km_map_gip_buttons(report) == 0x1D);
    memset(report, 0, sizeof(report));
    assert(km_map_gip_buttons(report) == 0);
}

static void test_xinput_buttons(void) {
    uint8_t report[20] = {0};
    report[4] = 16;
    assert(km_map_xinput_buttons(report) == 0x02);
    memset(report, 0, sizeof(report));
    report[5] = 16;
    assert(km_map_xinput_buttons(report) == 0x01);
    report[2] = 0x00;
    report[3] = 0x43; // X + LB + RB
    assert(km_map_xinput_buttons(report) == 0x1D);
}

static void test_sony_buttons(void) {
    uint8_t report[64] = {0};
    report[8] = 16; // DS4 LT
    assert(km_map_sony_buttons(report, 1) == 0x02);
    memset(report, 0, sizeof(report));
    report[9] = 16; // DS4 RT
    assert(km_map_sony_buttons(report, 1) == 0x01);
    report[5] = 0x10;
    report[6] = 0x03;
    assert(km_map_sony_buttons(report, 1) == 0x1D);

    memset(report, 0, sizeof(report));
    report[5] = 16; // DS5 LT
    assert(km_map_sony_buttons(report, 0) == 0x02);
    memset(report, 0, sizeof(report));
    report[6] = 16; // DS5 RT
    assert(km_map_sony_buttons(report, 0) == 0x01);
    report[8] = 0x10;
    report[9] = 0x03;
    assert(km_map_sony_buttons(report, 0) == 0x1D);
}

static void test_stick_curve(void) {
    int16_t dx, dy;
    km_stick_to_delta(0, 0, 1, &dx, &dy);
    assert(dx == 0 && dy == 0);
    km_stick_to_delta(KM_STICK_DEADZONE, 0, 1, &dx, &dy);
    assert(dx == 0 && dy == 0);

    int16_t low, high;
    km_stick_to_delta(8000, 0, 10, &low, &dy);
    km_stick_to_delta(20000, 0, 10, &high, &dy);
    assert(low > 0 && high > low && dy == 0);
    km_stick_to_delta(-20000, 0, 10, &dx, &dy);
    assert(dx == -high && dy == 0);
    km_stick_to_delta(0, -20000, 10, &dx, &dy);
    assert(dx == 0 && dy == -high);

    km_stick_to_delta(KM_STICK_MAX, 0, 1000, &dx, &dy);
    assert(dx == KM_MOUSE_MAX_COUNTS_SEC && dy == 0);
}

int main(void) {
    test_gip_buttons();
    test_xinput_buttons();
    test_sony_buttons();
    test_stick_curve();
    puts("pad translation vectors: ok");
    return 0;
}
