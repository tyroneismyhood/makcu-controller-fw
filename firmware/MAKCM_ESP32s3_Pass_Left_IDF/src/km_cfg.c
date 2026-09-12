// km_cfg.c — XIM-style on-device configuration via the flash BOOT buttons.
//
// Pipeline gate: USB1 host-visible (Left enumerated) AND controller ready
// on Right (FRAME_DEVICE_READY). USB2 (CH343) is not VBUS-sensed on this
// board; plug it so status lines print on the communicator COM port.
//
// Left BOOT (GPIO0, next to USB1):
//   long-press ~2 s  → enter config (when gated) / save+exit (when active)
//   short-press      → next setting category
// Right BOOT (GPIO0, next to USB3) via FRAME_BTN:
//   short-press      → next value in the current category
//
// Settings persist in NVS namespace "makcu".

#include "km_cfg.h"

#include <stdio.h>
#include <string.h>
#include <stdatomic.h>

#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "driver/gpio.h"
#include "esp_timer.h"
#include "nvs.h"
#include "nvs_flash.h"

extern int km_uart_write_raw(const void *data, size_t len);
extern void km_apply_cfg_live(void);

#define BOOT_BTN_GPIO     GPIO_NUM_0
#define LONG_PRESS_MS     2000
#define DEBOUNCE_MS       30
#define NVS_NS            "makcu"

#define CAT_TELEM         0
#define CAT_STEADY        1
#define CAT_GAIN          2
#define CAT_COUNT         3

// Gain presets: C in rx = C * |accum|^0.40 (XIM curve). Preset 1 = Matrix default.
static const float GAIN_C[3] = { 3200.0f, 5046.0f, 7800.0f };

static atomic_uint s_host_visible;
static atomic_uint s_device_ready;
static atomic_uint s_active;
static atomic_uint s_category;

static atomic_uint s_telem;
static atomic_uint s_steady;
static atomic_int  s_steady_a;
static atomic_int  s_steady_d;
static atomic_int  s_trim_x;
static atomic_int  s_trim_y;
static atomic_uint s_gain_preset;

static atomic_uint s_led_period_ms;
static atomic_int  s_led_level;

static void cfg_log(const char *msg) {
    km_uart_write_raw(msg, strlen(msg));
}

static bool pipeline_ready(void) {
    return atomic_load(&s_host_visible) && atomic_load(&s_device_ready);
}

static void cfg_save(void) {
    nvs_handle_t h;
    if (nvs_open(NVS_NS, NVS_READWRITE, &h) != ESP_OK) return;
    nvs_set_u8(h, "telem", (uint8_t)atomic_load(&s_telem));
    nvs_set_u8(h, "steady", (uint8_t)atomic_load(&s_steady));
    nvs_set_u8(h, "gain", (uint8_t)atomic_load(&s_gain_preset));
    nvs_set_i32(h, "sa", (int32_t)atomic_load(&s_steady_a));
    nvs_set_i32(h, "sd", (int32_t)atomic_load(&s_steady_d));
    nvs_set_i32(h, "tx", (int32_t)atomic_load(&s_trim_x));
    nvs_set_i32(h, "ty", (int32_t)atomic_load(&s_trim_y));
    nvs_commit(h);
    nvs_close(h);
}

static void cfg_load(void) {
    atomic_store(&s_telem, 0);
    atomic_store(&s_steady, 0);
    atomic_store(&s_steady_a, 70);
    atomic_store(&s_steady_d, 6000);
    atomic_store(&s_trim_x, 0);
    atomic_store(&s_trim_y, 0);
    atomic_store(&s_gain_preset, 1);

    nvs_handle_t h;
    if (nvs_open(NVS_NS, NVS_READONLY, &h) != ESP_OK) { km_apply_cfg_live(); return; }
    uint8_t u8 = 0;
    int32_t i32 = 0;
    if (nvs_get_u8(h, "telem", &u8) == ESP_OK) atomic_store(&s_telem, u8);
    if (nvs_get_u8(h, "steady", &u8) == ESP_OK) atomic_store(&s_steady, u8);
    if (nvs_get_u8(h, "gain", &u8) == ESP_OK) {
        if (u8 > 2) u8 = 1;
        atomic_store(&s_gain_preset, u8);
    }
    if (nvs_get_i32(h, "sa", &i32) == ESP_OK) atomic_store(&s_steady_a, i32);
    if (nvs_get_i32(h, "sd", &i32) == ESP_OK) atomic_store(&s_steady_d, i32);
    if (nvs_get_i32(h, "tx", &i32) == ESP_OK) atomic_store(&s_trim_x, i32);
    if (nvs_get_i32(h, "ty", &i32) == ESP_OK) atomic_store(&s_trim_y, i32);
    nvs_close(h);
    km_apply_cfg_live();
}

static void announce_state(void) {
    char m[128];
    uint32_t cat = atomic_load(&s_category);
    int n;
    if (cat == CAT_TELEM) {
        n = snprintf(m, sizeof(m),
            "[CFG] telem=%u  (Left short=next, Right short=toggle)\n",
            (unsigned)atomic_load(&s_telem));
    } else if (cat == CAT_STEADY) {
        n = snprintf(m, sizeof(m),
            "[CFG] steady=%u  (Right short=toggle)\n",
            (unsigned)atomic_load(&s_steady));
    } else {
        static const char *names[] = { "low", "xim", "high" };
        uint32_t g = atomic_load(&s_gain_preset);
        if (g > 2) g = 1;
        n = snprintf(m, sizeof(m),
            "[CFG] gain=%u(%s) C=%.0f  (Right short=cycle)\n",
            (unsigned)g, names[g], (double)GAIN_C[g]);
    }
    if (n > 0) km_uart_write_raw(m, (size_t)n);
    km_apply_cfg_live();
}

static void enter_cfg(void) {
    atomic_store(&s_active, 1);
    atomic_store(&s_category, CAT_TELEM);
    cfg_log("[CFG] enter — long-press Left BOOT again to save & exit\n");
    announce_state();
}

static void exit_cfg(bool save) {
    if (save) {
        cfg_save();
        cfg_log("[CFG] saved to NVS — exit\n");
    } else {
        cfg_log("[CFG] exit\n");
    }
    atomic_store(&s_active, 0);
    km_cfg_dump();
}

static void next_category(void) {
    uint32_t c = (atomic_load(&s_category) + 1) % CAT_COUNT;
    atomic_store(&s_category, c);
    announce_state();
}

static void next_value(void) {
    uint32_t c = atomic_load(&s_category);
    if (c == CAT_TELEM) {
        atomic_store(&s_telem, atomic_load(&s_telem) ? 0u : 1u);
    } else if (c == CAT_STEADY) {
        atomic_store(&s_steady, atomic_load(&s_steady) ? 0u : 1u);
    } else {
        atomic_store(&s_gain_preset, (atomic_load(&s_gain_preset) + 1) % 3);
    }
    announce_state();
}

static void on_left_long(void) {
    if (atomic_load(&s_active)) {
        exit_cfg(true);
        return;
    }
    if (!pipeline_ready()) {
        cfg_log("[CFG] locked — need USB1 (host) + controller on Right\n");
        return;
    }
    enter_cfg();
}

static void on_left_short(void) {
    if (!atomic_load(&s_active)) return;
    next_category();
}

static void on_right_short(void) {
    if (!atomic_load(&s_active)) {
        if (pipeline_ready()) {
            cfg_log("[CFG] hold Left BOOT ~2s to enter config\n");
        }
        return;
    }
    next_value();
}

static void boot_btn_task(void *arg) {
    (void)arg;
    gpio_config_t io = {
        .pin_bit_mask = 1ULL << BOOT_BTN_GPIO,
        .mode = GPIO_MODE_INPUT,
        .pull_up_en = GPIO_PULLUP_ENABLE,
        .pull_down_en = GPIO_PULLDOWN_DISABLE,
        .intr_type = GPIO_INTR_DISABLE,
    };
    gpio_config(&io);

    int stable = 1;  // idle high
    uint32_t change_ms = 0;
    uint32_t press_ms = 0;
    bool long_fired = false;

    for (;;) {
        int raw = gpio_get_level(BOOT_BTN_GPIO);
        uint32_t now = (uint32_t)(esp_timer_get_time() / 1000ULL);

        if (raw != stable) {
            if (change_ms == 0) change_ms = now;
            else if ((now - change_ms) >= DEBOUNCE_MS) {
                stable = raw;
                change_ms = 0;
                if (stable == 0) {
                    press_ms = now;
                    long_fired = false;
                } else {
                    if (!long_fired && press_ms &&
                        (now - press_ms) < LONG_PRESS_MS) {
                        on_left_short();
                    }
                    press_ms = 0;
                }
            }
        } else {
            change_ms = 0;
        }

        if (stable == 0 && !long_fired && press_ms &&
            (now - press_ms) >= LONG_PRESS_MS) {
            long_fired = true;
            on_left_long();
        }

        if (atomic_load(&s_active)) {
            uint32_t cat = atomic_load(&s_category);
            uint32_t period;
            if (cat == CAT_TELEM) {
                period = atomic_load(&s_telem) ? 70u : 500u;
            } else if (cat == CAT_STEADY) {
                period = atomic_load(&s_steady) ? 90u : 450u;
            } else {
                uint32_t g = atomic_load(&s_gain_preset);
                period = (g == 0) ? 350u : (g == 1) ? 160u : 60u;
            }
            atomic_store(&s_led_period_ms, period);
            atomic_store(&s_led_level, ((now / period) & 1u) ? 1 : 0);
        }

        vTaskDelay(pdMS_TO_TICKS(10));
    }
}

void km_cfg_init(void) {
    esp_err_t err = nvs_flash_init();
    if (err == ESP_ERR_NVS_NO_FREE_PAGES ||
        err == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        nvs_flash_erase();
        nvs_flash_init();
    }
    atomic_store(&s_host_visible, 0);
    atomic_store(&s_device_ready, 0);
    atomic_store(&s_active, 0);
    atomic_store(&s_category, 0);
    atomic_store(&s_led_period_ms, 100);
    atomic_store(&s_led_level, 0);
    cfg_load();
    xTaskCreatePinnedToCore(boot_btn_task, "boot_btn", 3072, NULL, 2, NULL, 1);
    cfg_log("[CFG] ready — USB1+controller required; long-press Left BOOT\n");
}

void km_cfg_on_right_btn(uint8_t pressed) {
    if (pressed) on_right_short();
}

void km_cfg_set_host_visible(bool on) {
    atomic_store(&s_host_visible, on ? 1u : 0u);
    if (!pipeline_ready() && atomic_load(&s_active)) {
        exit_cfg(false);
        cfg_load();
    }
}

void km_cfg_set_device_ready(bool on) {
    atomic_store(&s_device_ready, on ? 1u : 0u);
    if (!pipeline_ready() && atomic_load(&s_active)) {
        exit_cfg(false);
        cfg_load();
    }
}

bool km_cfg_active(void) {
    return atomic_load(&s_active) != 0;
}

bool km_cfg_led_override(uint32_t *period_ms, int *force_level) {
    if (!atomic_load(&s_active)) return false;
    if (period_ms) *period_ms = atomic_load(&s_led_period_ms);
    if (force_level) *force_level = atomic_load(&s_led_level);
    return true;
}

float km_cfg_gain_c(void) {
    uint32_t g = atomic_load(&s_gain_preset);
    if (g > 2) g = 1;
    return GAIN_C[g];
}

uint8_t km_cfg_gain_preset(void) {
    return (uint8_t)atomic_load(&s_gain_preset);
}

uint32_t km_cfg_telem_on(void) { return atomic_load(&s_telem); }
uint32_t km_cfg_steady_on(void) { return atomic_load(&s_steady); }
int32_t  km_cfg_steady_alpha(void) { return atomic_load(&s_steady_a); }
int32_t  km_cfg_steady_dead(void) { return atomic_load(&s_steady_d); }
int32_t  km_cfg_trim_x(void) { return atomic_load(&s_trim_x); }
int32_t  km_cfg_trim_y(void) { return atomic_load(&s_trim_y); }

void km_cfg_store_telem(uint32_t on) {
    atomic_store(&s_telem, on ? 1u : 0u);
    cfg_save();
    km_apply_cfg_live();
}
void km_cfg_store_steady(uint32_t on) {
    atomic_store(&s_steady, on ? 1u : 0u);
    cfg_save();
    km_apply_cfg_live();
}
void km_cfg_store_steady_a(int32_t a) {
    if (a < 0) a = 0;
    if (a > 99) a = 99;
    atomic_store(&s_steady_a, a);
    cfg_save();
    km_apply_cfg_live();
}
void km_cfg_store_steady_d(int32_t d) {
    if (d < 0) d = 0;
    if (d > 32000) d = 32000;
    atomic_store(&s_steady_d, d);
    cfg_save();
    km_apply_cfg_live();
}
void km_cfg_store_trim(int32_t x, int32_t y) {
    if (x < -32767) x = -32767;
    if (x > 32767) x = 32767;
    if (y < -32767) y = -32767;
    if (y > 32767) y = 32767;
    atomic_store(&s_trim_x, x);
    atomic_store(&s_trim_y, y);
    cfg_save();
    km_apply_cfg_live();
}
void km_cfg_store_gain_preset(uint8_t preset) {
    if (preset > 2) preset = 1;
    atomic_store(&s_gain_preset, preset);
    cfg_save();
    km_apply_cfg_live();
}

void km_cfg_dump(void) {
    char m[160];
    uint32_t g = atomic_load(&s_gain_preset);
    if (g > 2) g = 1;
    int n = snprintf(m, sizeof(m),
        "[CFG] telem=%u steady=%u gain=%u C=%.0f sa=%ld sd=%ld trim=%ld,%ld active=%u ready=%u\n",
        (unsigned)atomic_load(&s_telem),
        (unsigned)atomic_load(&s_steady),
        (unsigned)g,
        (double)GAIN_C[g],
        (long)atomic_load(&s_steady_a),
        (long)atomic_load(&s_steady_d),
        (long)atomic_load(&s_trim_x),
        (long)atomic_load(&s_trim_y),
        (unsigned)atomic_load(&s_active),
        (unsigned)pipeline_ready());
    if (n > 0) km_uart_write_raw(m, (size_t)n);
}
