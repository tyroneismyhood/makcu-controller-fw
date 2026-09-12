// Official MAKCU legacy + V2 host protocol.
//
// No private wire commands live here. Physical controller state is translated
// into MAKCU's existing five-button mouse mask and right-stick velocity is
// translated into its existing mouse/axis streams.

#include "km_host_api.h"
#include "km_pad_translate.h"

#include <stdatomic.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "esp_random.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

extern int km_uart_write_raw(const void *data, size_t len);

#define API_TASK_TICK_MS       1u
#define STREAM_PERIOD_MIN_MS   1u
#define STREAM_PERIOD_MAX_MS   1000u
#define V2_PERIOD_MAX_MS       255u

enum {
    TRANSPORT_NONE   = 0,
    TRANSPORT_LEGACY = 1,
    TRANSPORT_V2     = 2,
};

enum {
    CMD_V2_AXIS    = 0x01,
    CMD_V2_BUTTONS = 0x02,
    CMD_V2_CLICK   = 0x04,
    CMD_V2_LEFT    = 0x08,
    CMD_V2_MIDDLE  = 0x0A,
    CMD_V2_MO      = 0x0B,
    CMD_V2_MOUSE   = 0x0C,
    CMD_V2_MOVE    = 0x0D,
    CMD_V2_RIGHT   = 0x11,
    CMD_V2_SIDE1   = 0x12,
    CMD_V2_SIDE2   = 0x13,
    CMD_V2_DEVICE  = 0xB3,
    CMD_V2_ECHO    = 0xB4,
    CMD_V2_VERSION = 0xBF,
};

typedef struct {
    atomic_uint mode;       // 0=off, 1=raw, 2=constructed
    atomic_uint period_ms;
    atomic_uint transport;
    atomic_uint last_ms;
    atomic_uint last_seq;
} stream_cfg_t;

static stream_cfg_t s_buttons = {
    ATOMIC_VAR_INIT(0), ATOMIC_VAR_INIT(1), ATOMIC_VAR_INIT(TRANSPORT_NONE),
    ATOMIC_VAR_INIT(0), ATOMIC_VAR_INIT(0),
};
static stream_cfg_t s_axis = {
    ATOMIC_VAR_INIT(0), ATOMIC_VAR_INIT(1), ATOMIC_VAR_INIT(TRANSPORT_NONE),
    ATOMIC_VAR_INIT(0), ATOMIC_VAR_INIT(0),
};
static stream_cfg_t s_mouse = {
    ATOMIC_VAR_INIT(0), ATOMIC_VAR_INIT(1), ATOMIC_VAR_INIT(TRANSPORT_NONE),
    ATOMIC_VAR_INIT(0), ATOMIC_VAR_INIT(0),
};

static atomic_int  s_pad_rx;
static atomic_int  s_pad_ry;
static atomic_uint s_pad_buttons;
static atomic_uint s_pad_online;
static atomic_uint s_pad_seq;
static atomic_uint s_last_button_mask = ATOMIC_VAR_INIT(0x100u);
static atomic_uint s_echo = ATOMIC_VAR_INIT(1u);

typedef struct {
    atomic_uint count;
    atomic_uint delay_ms;
    atomic_uint next_ms;
    atomic_uint pressed;
} click_cfg_t;

static click_cfg_t s_clicks[5];

static inline uint16_t rd_le16(const uint8_t *p) {
    return (uint16_t)p[0] | ((uint16_t)p[1] << 8);
}

static inline void wr_le16(uint8_t *p, int16_t v) {
    p[0] = (uint8_t)((uint16_t)v & 0xFFu);
    p[1] = (uint8_t)((uint16_t)v >> 8);
}

static uint32_t now_ms(void) {
    return (uint32_t)(esp_timer_get_time() / 1000ULL);
}

static uint32_t clamp_period(long value) {
    if (value < (long)STREAM_PERIOD_MIN_MS) return STREAM_PERIOD_MIN_MS;
    if (value > (long)STREAM_PERIOD_MAX_MS) return STREAM_PERIOD_MAX_MS;
    return (uint32_t)value;
}

static void write_v2(uint8_t cmd, const uint8_t *payload, uint16_t len) {
    // Official V2 TX frame: 50 CMD LEN_LO LEN_HI PAYLOAD.
    uint8_t frame[4 + 16];
    if (len > 16) len = 16;
    frame[0] = 0x50;
    frame[1] = cmd;
    frame[2] = (uint8_t)(len & 0xFFu);
    frame[3] = (uint8_t)(len >> 8);
    if (len) memcpy(frame + 4, payload, len);
    km_uart_write_raw(frame, (size_t)len + 4u);
}

static void v2_status(uint8_t cmd, bool ok) {
    uint8_t status = ok ? 0x00 : 0x01;
    write_v2(cmd, &status, 1);
}

static void legacy_prompt(void) {
    static const char prompt[] = ">>> ";
    km_uart_write_raw(prompt, sizeof(prompt) - 1);
}

static void legacy_value_u32(const char *line, uint16_t len, uint32_t value) {
    char out[144];
    if (len > 96) len = 96;
    int n;
    if (len && line[0] == '.') {
        n = snprintf(out, sizeof(out), "km%.*s\r\n%lu\r\n>>> ",
                     (int)len, line, (unsigned long)value);
    } else {
        n = snprintf(out, sizeof(out), "%.*s\r\n%lu\r\n>>> ",
                     (int)len, line, (unsigned long)value);
    }
    if (n > 0) km_uart_write_raw(out, (size_t)n);
}

static void legacy_ack(const char *line, uint16_t len) {
    if (!atomic_load(&s_echo)) {
        legacy_prompt();
        return;
    }
    char out[112];
    if (len > 96) len = 96;
    int n;
    if (len && line[0] == '.') {
        n = snprintf(out, sizeof(out), "km%.*s\r\n>>> ", (int)len, line);
    } else {
        n = snprintf(out, sizeof(out), "%.*s\r\n>>> ", (int)len, line);
    }
    if (n > 0) km_uart_write_raw(out, (size_t)n);
}

static const char *command_body(const char *line, uint16_t len) {
    if (len >= 3 && memcmp(line, "km.", 3) == 0) return line + 3;
    if (len >= 1 && line[0] == '.') return line + 1;
    return NULL;
}

static bool command_is(const char *body, const char *name) {
    size_t n = strlen(name);
    return strncmp(body, name, n) == 0 && body[n] == '(';
}

static bool parse_mode_period(const char *body, uint32_t *mode, uint32_t *period,
                              bool *query) {
    const char *p = strchr(body, '(');
    if (!p) return false;
    ++p;
    if (*p == ')') {
        *query = true;
        return true;
    }
    char *end = NULL;
    long m = strtol(p, &end, 10);
    if (end == p) return false;
    *query = false;
    *mode = (m == 1 || m == 2) ? (uint32_t)m : 0u;
    *period = 1u;
    while (*end == ' ' || *end == '\t') ++end;
    if (*end == ',') {
        long v = strtol(end + 1, &end, 10);
        *period = clamp_period(v);
    }
    return true;
}

static void configure_stream(stream_cfg_t *cfg, uint32_t mode,
                             uint32_t period, uint32_t transport) {
    atomic_store(&cfg->mode, mode);
    atomic_store(&cfg->period_ms, clamp_period((long)period));
    atomic_store(&cfg->transport, mode ? transport : TRANSPORT_NONE);
    atomic_store(&cfg->last_ms, 0);
    atomic_store(&cfg->last_seq, 0);
}

static uint8_t raw_button_mask(void) {
    return (uint8_t)(atomic_load(&s_pad_buttons) & 0x1Fu);
}

static uint8_t full_button_mask(void) {
    return (uint8_t)((raw_button_mask() | km_api_injected_button_mask()) & 0x1Fu);
}

static void emit_legacy_button(uint8_t mask) {
    // Physically verified legacy MAKCU framing: literal "km." + raw snapshot.
    uint8_t frame[4] = {'k', 'm', '.', mask};
    km_uart_write_raw(frame, sizeof(frame));
}

static void emit_v2_button(uint8_t mask) {
    uint8_t payload[2] = {mask, 0};
    write_v2(CMD_V2_BUTTONS, payload, sizeof(payload));
}

static void emit_axis(uint32_t transport, uint32_t mode, int16_t dx, int16_t dy) {
    if (transport == TRANSPORT_V2) {
        uint8_t payload[5];
        wr_le16(payload, dx);
        wr_le16(payload + 2, dy);
        payload[4] = 0;
        write_v2(CMD_V2_AXIS, payload, sizeof(payload));
        return;
    }
    char out[64];
    int n = snprintf(out, sizeof(out), "km.%s(%d,%d,0)\r\n>>> ",
                     mode == 1 ? "raw" : "mut", (int)dx, (int)dy);
    if (n > 0) km_uart_write_raw(out, (size_t)n);
}

static void emit_mouse(uint32_t transport, uint8_t buttons,
                       int16_t dx, int16_t dy) {
    uint8_t payload[8] = {buttons, 0, 0, 0, 0, 0, 0, 0};
    wr_le16(payload + 1, dx);
    wr_le16(payload + 3, dy);
    if (transport == TRANSPORT_V2) {
        write_v2(CMD_V2_MOUSE, payload, sizeof(payload));
        return;
    }
    uint8_t frame[22] = {'k', 'm', '.', 'm', 'o', 'u', 's', 'e'};
    memcpy(frame + 8, payload, sizeof(payload));
    memcpy(frame + 16, "\r\n>>> ", 6);
    km_uart_write_raw(frame, sizeof(frame));
}

static bool stream_due(stream_cfg_t *cfg, uint32_t now) {
    uint32_t last = atomic_load(&cfg->last_ms);
    uint32_t period = atomic_load(&cfg->period_ms);
    return last == 0 || (uint32_t)(now - last) >= period;
}

static void service_clicks(uint32_t now) {
    for (uint8_t i = 0; i < 5; ++i) {
        click_cfg_t *click = &s_clicks[i];
        uint32_t count = atomic_load(&click->count);
        if (!count) continue;
        uint32_t next = atomic_load(&click->next_ms);
        if ((int32_t)(now - next) < 0) continue;

        bool pressed = atomic_load(&click->pressed) != 0;
        if (!pressed) {
            km_api_set_click((uint8_t)(i + 1), true);
            atomic_fetch_add(&s_pad_seq, 1);
            atomic_store(&click->pressed, 1);
        } else {
            km_api_set_click((uint8_t)(i + 1), false);
            atomic_fetch_add(&s_pad_seq, 1);
            atomic_store(&click->pressed, 0);
            atomic_store(&click->count, count - 1);
        }
        atomic_store(&click->next_ms,
                     now + atomic_load(&click->delay_ms));
    }
}

static void schedule_clicks(uint8_t button, uint8_t count, uint16_t delay_ms) {
    if (button < 1 || button > 5 || count == 0) return;
    click_cfg_t *click = &s_clicks[button - 1];
    if (atomic_exchange(&click->pressed, 0)) {
        km_api_set_click(button, false);
        atomic_fetch_add(&s_pad_seq, 1);
    }
    if (delay_ms == 0) delay_ms = (uint16_t)(35u + esp_random() % 41u);
    atomic_store(&click->delay_ms, delay_ms);
    atomic_store(&click->count, count);
    atomic_store(&click->next_ms, now_ms());
}

static void stream_task(void *arg) {
    (void)arg;
    for (;;) {
        uint32_t now = now_ms();
        service_clicks(now);
        uint32_t seq = atomic_load(&s_pad_seq);

        uint32_t button_mode = atomic_load(&s_buttons.mode);
        uint8_t buttons = button_mode == 1
                        ? raw_button_mask() : full_button_mask();
        if (button_mode && stream_due(&s_buttons, now)) {
            uint32_t last = atomic_load(&s_last_button_mask);
            if (last > 0xFFu || buttons != (uint8_t)last) {
                if (atomic_load(&s_buttons.transport) == TRANSPORT_V2) {
                    emit_v2_button(buttons);
                } else {
                    emit_legacy_button(buttons);
                }
                atomic_store(&s_last_button_mask, buttons);
            }
            atomic_store(&s_buttons.last_ms, now);
        }

        stream_cfg_t *streams[2] = {&s_axis, &s_mouse};
        for (size_t i = 0; i < 2; ++i) {
            stream_cfg_t *cfg = streams[i];
            uint32_t mode = atomic_load(&cfg->mode);
            if (!mode || !stream_due(cfg, now)) continue;

            int32_t x = atomic_load(&s_pad_rx);
            int32_t y = atomic_load(&s_pad_ry);
            uint32_t last_seq = atomic_load(&cfg->last_seq);
            // Held stick produces repeated relative motion; centered stick
            // emits once on a new report (needed to carry button releases).
            if (seq == last_seq && x == 0 && y == 0) continue;

            int16_t dx, dy;
            km_stick_to_delta(x, y, atomic_load(&cfg->period_ms), &dx, &dy);
            uint32_t transport = atomic_load(&cfg->transport);
            if (cfg == &s_axis) emit_axis(transport, mode, dx, dy);
            else {
                uint8_t mouse_buttons = mode == 1
                                      ? raw_button_mask() : full_button_mask();
                emit_mouse(transport, mouse_buttons, dx, dy);
            }
            atomic_store(&cfg->last_ms, now);
            atomic_store(&cfg->last_seq, seq);
        }

        vTaskDelay(pdMS_TO_TICKS(API_TASK_TICK_MS));
    }
}

void km_host_api_update_pad(int32_t rx, int32_t ry, uint8_t mouse_buttons) {
    if (rx < -KM_STICK_MAX) rx = -KM_STICK_MAX;
    if (rx > KM_STICK_MAX) rx = KM_STICK_MAX;
    if (ry < -KM_STICK_MAX) ry = -KM_STICK_MAX;
    if (ry > KM_STICK_MAX) ry = KM_STICK_MAX;
    atomic_store(&s_pad_rx, rx);
    atomic_store(&s_pad_ry, ry);
    atomic_store(&s_pad_buttons, mouse_buttons & 0x1Fu);
    atomic_store(&s_pad_online, 1);
    atomic_fetch_add(&s_pad_seq, 1);
}

void km_host_api_set_pad_online(bool online) {
    if (online) {
        atomic_store(&s_pad_online, 1u);
        return;
    }
    atomic_store(&s_pad_rx, 0);
    atomic_store(&s_pad_ry, 0);
    atomic_store(&s_pad_buttons, 0);
    atomic_store(&s_pad_online, 0u);
    atomic_fetch_add(&s_pad_seq, 1);
}

static int button_from_name(const char *body) {
    if (command_is(body, "left")) return 1;
    if (command_is(body, "right")) return 2;
    if (command_is(body, "middle")) return 3;
    if (command_is(body, "side1") || command_is(body, "ms1")) return 4;
    if (command_is(body, "side2") || command_is(body, "ms2")) return 5;
    return 0;
}

static bool handle_legacy_stream(const char *line, uint16_t len,
                                 const char *body, const char *name,
                                 stream_cfg_t *cfg) {
    if (!command_is(body, name)) return false;
    uint32_t mode = 0, period = 1;
    bool query = false;
    if (!parse_mode_period(body, &mode, &period, &query)) {
        legacy_prompt();
        return true;
    }
    if (query) {
        legacy_value_u32(line, len, atomic_load(&cfg->mode));
    } else {
        configure_stream(cfg, mode, period, TRANSPORT_LEGACY);
        if (cfg == &s_buttons) atomic_store(&s_last_button_mask, 0x100u);
        legacy_ack(line, len);
    }
    return true;
}

bool km_host_api_handle_legacy(const char *line, uint16_t len) {
    const char *body = command_body(line, len);
    if (!body) return false;

    if (command_is(body, "version")) {
        static const char version[] = "km.MAKCU\r\n>>> ";
        km_uart_write_raw(version, sizeof(version) - 1);
        return true;
    }
    if (command_is(body, "device")) {
        static const char device[] = "km.device(mouse)\r\n>>> ";
        km_uart_write_raw(device, sizeof(device) - 1);
        return true;
    }
    if (handle_legacy_stream(line, len, body, "buttons", &s_buttons) ||
        handle_legacy_stream(line, len, body, "axis", &s_axis) ||
        handle_legacy_stream(line, len, body, "mouse", &s_mouse)) {
        return true;
    }
    if (command_is(body, "echo")) {
        const char *p = strchr(body, '(') + 1;
        if (*p == ')') legacy_value_u32(line, len, atomic_load(&s_echo));
        else {
            atomic_store(&s_echo, strtol(p, NULL, 10) ? 1u : 0u);
            legacy_ack(line, len);
        }
        return true;
    }

    int button = button_from_name(body);
    if (button) {
        const char *p = strchr(body, '(') + 1;
        if (*p == ')') {
            legacy_value_u32(line, len,
                (full_button_mask() & (1u << (button - 1))) != 0);
        } else {
            long state = strtol(p, NULL, 10);
            km_api_set_button((uint8_t)button, (uint8_t)state);
            atomic_fetch_add(&s_pad_seq, 1);
            legacy_ack(line, len);
        }
        return true;
    }

    if (command_is(body, "move")) {
        const char *p = strchr(body, '(') + 1;
        char *end = NULL;
        long x = strtol(p, &end, 10);
        if (end != p && *end == ',') {
            long y = strtol(end + 1, NULL, 10);
            km_api_move((int32_t)x, (int32_t)y);
            legacy_ack(line, len);
        } else legacy_prompt();
        return true;
    }
    if (command_is(body, "click")) {
        const char *p = strchr(body, '(') + 1;
        char *end = NULL;
        long button_num = strtol(p, &end, 10);
        long count = 1;
        long delay = 0;
        if (*end == ',') {
            count = strtol(end + 1, &end, 10);
            if (*end == ',') delay = strtol(end + 1, &end, 10);
        }
        if (button_num < 1 || button_num > 5 ||
            count < 1 || count > 255 || delay < 0 || delay > 5000) {
            legacy_prompt();
            return true;
        }
        schedule_clicks((uint8_t)button_num, (uint8_t)count, (uint16_t)delay);
        legacy_ack(line, len);
        return true;
    }
    return false;
}

static void handle_v2_stream(uint8_t cmd, const uint8_t *payload, uint16_t len,
                             stream_cfg_t *cfg) {
    if (len == 0) {
        uint8_t out[2] = {
            (uint8_t)atomic_load(&cfg->mode),
            (uint8_t)atomic_load(&cfg->period_ms),
        };
        write_v2(cmd, out, sizeof(out));
        return;
    }
    if (len > 2) {
        v2_status(cmd, false);
        return;
    }
    uint32_t mode = payload[0];
    uint32_t period = len >= 2 ? payload[1] : 1;
    if (mode > 2 || (mode != 0 && period == 0)) {
        v2_status(cmd, false);
        return;
    }
    if (period > V2_PERIOD_MAX_MS) period = V2_PERIOD_MAX_MS;
    configure_stream(cfg, mode, period, TRANSPORT_V2);
    if (cfg == &s_buttons) atomic_store(&s_last_button_mask, 0x100u);
    v2_status(cmd, true);
}

void km_host_api_handle_v2(uint8_t cmd, const uint8_t *payload, uint16_t len) {
    if (cmd == CMD_V2_BUTTONS) {
        handle_v2_stream(cmd, payload, len, &s_buttons);
        return;
    }
    if (cmd == CMD_V2_AXIS) {
        handle_v2_stream(cmd, payload, len, &s_axis);
        return;
    }
    if (cmd == CMD_V2_MOUSE) {
        handle_v2_stream(cmd, payload, len, &s_mouse);
        return;
    }
    if (cmd == CMD_V2_VERSION) {
        static const uint8_t version[] = "MAKCU V1_3_CONTROLLER";
        write_v2(cmd, version, sizeof(version) - 1);
        return;
    }
    if (cmd == CMD_V2_DEVICE) {
        uint8_t type = atomic_load(&s_pad_online) ? 2 : 0; // 2=mouse
        write_v2(cmd, &type, 1);
        return;
    }
    if (cmd == CMD_V2_ECHO) {
        if (len == 0) {
            uint8_t echo = (uint8_t)atomic_load(&s_echo);
            write_v2(cmd, &echo, 1);
        } else {
            atomic_store(&s_echo, payload[0] ? 1u : 0u);
            v2_status(cmd, true);
        }
        return;
    }

    uint8_t button = 0;
    if (cmd == CMD_V2_LEFT) button = 1;
    else if (cmd == CMD_V2_RIGHT) button = 2;
    else if (cmd == CMD_V2_MIDDLE) button = 3;
    else if (cmd == CMD_V2_SIDE1) button = 4;
    else if (cmd == CMD_V2_SIDE2) button = 5;
    if (button) {
        if (len == 0) {
            uint8_t bit = (uint8_t)(1u << (button - 1));
            uint8_t state = (raw_button_mask() & bit ? 1u : 0u) |
                            (km_api_injected_button_mask() & bit ? 2u : 0u);
            write_v2(cmd, &state, 1);
        } else {
            km_api_set_button(button, payload[0]);
            atomic_fetch_add(&s_pad_seq, 1);
            v2_status(cmd, true);
        }
        return;
    }
    if (cmd == CMD_V2_MOVE) {
        // x:i16, y:i16, segments:u8, cx1:i8, cy1:i8.
        if (len != 7 || payload[4] == 0) {
            v2_status(cmd, false);
            return;
        }
        km_api_move((int16_t)rd_le16(payload), (int16_t)rd_le16(payload + 2));
        v2_status(cmd, true);
        return;
    }
    if (cmd == CMD_V2_MO) {
        if (len != 8) {
            v2_status(cmd, false);
            return;
        }
        uint8_t mask = payload[0] & 0x1Fu;
        for (uint8_t b = 1; b <= 5; ++b) {
            km_api_set_button(b, mask & (1u << (b - 1)) ? 1 : 0);
        }
        atomic_fetch_add(&s_pad_seq, 1);
        km_api_move((int16_t)rd_le16(payload + 1),
                    (int16_t)rd_le16(payload + 3));
        // Controller passthrough has no wheel/pan/tilt target. Do not claim
        // success if the caller requested axes this bridge cannot represent.
        v2_status(cmd, payload[5] == 0 && payload[6] == 0 && payload[7] == 0);
        return;
    }
    if (cmd == CMD_V2_CLICK) {
        if (len != 3 || payload[0] < 1 || payload[0] > 5 ||
            payload[1] == 0) {
            v2_status(cmd, false);
            return;
        }
        schedule_clicks(payload[0], payload[1], payload[2]);
        v2_status(cmd, true);
        return;
    }
    v2_status(cmd, false);
}

void km_host_api_init(void) {
    atomic_store(&s_pad_rx, 0);
    atomic_store(&s_pad_ry, 0);
    atomic_store(&s_pad_buttons, 0);
    atomic_store(&s_pad_online, 0);
    atomic_store(&s_pad_seq, 1);
    xTaskCreatePinnedToCore(stream_task, "km_api", 4096, NULL, 4, NULL, 0);
}
