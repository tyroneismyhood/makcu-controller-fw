// Official MAKCU KM host protocol bridge.
//
// Public wire formats are defined by https://makcu.com/en/api/.  This
// internal module does not add commands: it translates the physical
// controller snapshot into the existing buttons/axis/mouse streams for the
// communicator connected to the CH343 UART.

#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

void km_host_api_init(void);

// Update the physical controller snapshot. Values use mouse convention
// (+Y=down). mouse_buttons uses the official 5-bit MAKCU layout.
void km_host_api_update_pad(int32_t rx, int32_t ry, uint8_t mouse_buttons);
void km_host_api_set_pad_online(bool online);

// Return true when an official legacy command was handled.
bool km_host_api_handle_legacy(const char *line, uint16_t len);

// Handle one complete official V2 command frame.
void km_host_api_handle_v2(uint8_t cmd, const uint8_t *payload, uint16_t len);

// Injection callbacks implemented by km_inject.c.
void km_api_move(int32_t dx, int32_t dy);
void km_api_set_button(uint8_t button, uint8_t state);
void km_api_set_click(uint8_t button, bool pressed);
uint8_t km_api_injected_button_mask(void);

#ifdef __cplusplus
}
#endif
