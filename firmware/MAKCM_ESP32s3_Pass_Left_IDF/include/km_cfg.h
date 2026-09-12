// km_cfg — XIM-style on-device configuration via the flash BOOT buttons.
//
// Unlock when the passthrough pipeline is live (USB1 host-visible + controller
// ready on Right). Long-press Left BOOT (~2 s, same feel as XIM Matrix pairing)
// enters config mode; short presses and the Right BOOT button navigate; long-
// press again saves to NVS and exits.
//
// See docs/ON_DEVICE_CONFIG.md for the button map and LED legend.

#pragma once
#include <stdbool.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

void km_cfg_init(void);

// Called from the IPC path when Right reports its BOOT button.
void km_cfg_on_right_btn(uint8_t pressed);

// Pipeline readiness — set from main.c as USB/device state changes.
void km_cfg_set_host_visible(bool on);
void km_cfg_set_device_ready(bool on);

bool km_cfg_active(void);

// LED override: return true if km_cfg owns the Left diag LED this tick.
bool km_cfg_led_override(uint32_t *period_ms, int *force_level);

// Runtime settings consumed by km_inject (loaded from NVS at boot).
float    km_cfg_gain_c(void);
uint8_t  km_cfg_gain_preset(void);   // 0=low 1=xim 2=high
uint32_t km_cfg_telem_on(void);
uint32_t km_cfg_steady_on(void);
int32_t  km_cfg_steady_alpha(void);
int32_t  km_cfg_steady_dead(void);
int32_t  km_cfg_trim_x(void);
int32_t  km_cfg_trim_y(void);

// Persist helpers for km.* serial commands (keep NVS in sync).
void km_cfg_store_telem(uint32_t on);
void km_cfg_store_steady(uint32_t on);
void km_cfg_store_steady_a(int32_t a);
void km_cfg_store_steady_d(int32_t d);
void km_cfg_store_trim(int32_t x, int32_t y);
void km_cfg_store_gain_preset(uint8_t preset);

void km_cfg_dump(void);

#ifdef __cplusplus
}
#endif
