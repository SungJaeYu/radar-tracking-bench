#ifndef TEST_TIMING_H
#define TEST_TIMING_H

#include <stdint.h>

typedef uint64_t timing_t;
#if defined(TEST_RX_TIMING)
extern uint64_t test_timing_cycles;
static inline timing_t timing_counter_get(void) { return test_timing_cycles; }
#else
static inline timing_t timing_counter_get(void) { static timing_t tick; return ++tick; }
#endif
static inline uint64_t timing_cycles_get(timing_t *start, timing_t *end) { return (uint32_t)*end - (uint32_t)*start; }

// The host fixture uses a synthetic 100 MHz timer, not the board clock.
static inline uint64_t timing_cycles_to_ns(uint64_t cycles)
{
    return cycles * UINT64_C(10);
}

#endif
