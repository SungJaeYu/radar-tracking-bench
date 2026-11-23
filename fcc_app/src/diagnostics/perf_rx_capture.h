#ifndef PERF_RX_CAPTURE_H
#define PERF_RX_CAPTURE_H

#include <stdint.h>

#if defined(CONFIG_RADAR_PERF_MONITOR)
#include <zephyr/timing/timing.h>

// Raw Cortex-M DWT read: no uptime lookup, conversion, or statistics.
static inline uint32_t perf_rx_capture_now(void)
{
    return (uint32_t)timing_counter_get();
}

// Call from the RX startup thread before enabling UART interrupts.
void perf_rx_capture_init(void);

// ISR-only publisher: bounded raw storage, no collector call or lock.
void perf_rx_capture_isr(uint32_t start, uint32_t end);
// Store after successful ring insertion. Slot must be a valid ring index.
void perf_rx_capture_store_byte(uint8_t slot, uint32_t stored_cycles);
// Copy alongside ring removal, before the ISR can reuse that slot. No clock/lock.
uint32_t perf_rx_capture_load_byte(uint8_t slot);

// RX-thread only, with interrupts enabled: convert and aggregate captured values.
void perf_rx_capture_collect_isr(void);
void perf_rx_capture_collect_byte(uint32_t stored_cycles);

#else
// Normal builds erase the hooks; no capture state or module is linked.
static inline uint32_t perf_rx_capture_now(void) { return 0U; }
static inline void perf_rx_capture_init(void) { }
static inline void perf_rx_capture_isr(uint32_t start, uint32_t end)
{
    (void)start;
    (void)end;
}
static inline void perf_rx_capture_store_byte(uint8_t slot, uint32_t stored_cycles)
{
    (void)slot;
    (void)stored_cycles;
}
static inline uint32_t perf_rx_capture_load_byte(uint8_t slot)
{
    (void)slot;
    return 0U;
}
static inline void perf_rx_capture_collect_isr(void) { }
static inline void perf_rx_capture_collect_byte(uint32_t stored_cycles)
{
    (void)stored_cycles;
}
#endif

#endif
