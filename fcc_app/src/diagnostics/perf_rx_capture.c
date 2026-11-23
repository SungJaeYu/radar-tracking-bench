#include "diagnostics/perf_rx_capture.h"

#include <stdatomic.h>
#include <zephyr/kernel.h>

#include "common/ring_buffer.h"
#include "diagnostics/perf_monitor.h"

// The Cortex-M timing source is a direct DWT counter read, not kernel uptime.
static uint32_t rx_stored_cycles[RING_BUFFER_SIZE];
#define RX_ISR_CAPTURE_COUNT 256U
struct rx_isr_capture { uint32_t start; uint32_t end; };
static struct rx_isr_capture rx_isr_captures[RX_ISR_CAPTURE_COUNT];
// Single UART ISR producer, single RX-thread consumer. No collector lock in ISR.
_Static_assert(ATOMIC_INT_LOCK_FREE == 2, "ISR capture indices must be lock free");
static atomic_uint capture_head;
static atomic_uint capture_tail;
static atomic_uint capture_lost;
static int64_t last_capture_service_ms;

void perf_rx_capture_isr(uint32_t start, uint32_t end)
{
    const unsigned int head = atomic_load_explicit(&capture_head, memory_order_relaxed);
    const unsigned int next = (head + 1U) % RX_ISR_CAPTURE_COUNT;
    if (next == atomic_load_explicit(&capture_tail, memory_order_acquire)) {
        atomic_store_explicit(&capture_lost, 1U, memory_order_relaxed);
        return;
    }
    rx_isr_captures[head] = (struct rx_isr_capture){start, end};
    atomic_store_explicit(&capture_head, next, memory_order_release);
}

void perf_rx_capture_collect_isr(void)
{
    const int64_t now_ms = k_uptime_get();
    // DWT wraps after about19.9s at216MHz. Reject an unobserved service gap
    // of1s or more so a full counter wrap cannot become a small valid latency.
    if (now_ms - last_capture_service_ms >= 1000 || now_ms < last_capture_service_ms) {
        perf_monitor_record_rx_capture_lost();
    }
    last_capture_service_ms = now_ms;
    if (atomic_load_explicit(&capture_lost, memory_order_relaxed) != 0U) {
        perf_monitor_record_rx_capture_lost();
    }
    unsigned int tail = atomic_load_explicit(&capture_tail, memory_order_relaxed);
    // Bounded batch: new ISR captures are handled on the next RX iteration.
    const unsigned int head = atomic_load_explicit(&capture_head, memory_order_acquire);
    while (tail != head) {
        const struct rx_isr_capture sample = rx_isr_captures[tail];
        tail = (tail + 1U) % RX_ISR_CAPTURE_COUNT;
        atomic_store_explicit(&capture_tail, tail, memory_order_release);
        timing_t start = sample.start, end = sample.end;
        perf_monitor_record_rx_isr(timing_cycles_get(&start, &end));
    }
}

void perf_rx_capture_collect_byte(uint32_t stored_cycles)
{
    timing_t start = stored_cycles, end = timing_counter_get();
    const uint64_t ns = timing_cycles_to_ns(timing_cycles_get(&start, &end));
    // Convert only in the thread, rounding up so the20ms limit is not relaxed.
    perf_monitor_record_rx_byte(0, (int64_t)((ns + UINT64_C(999999)) / UINT64_C(1000000)));
}

// Startup only: protocol INIT/RESET must not clear boot-lifetime diagnostics.
void perf_rx_capture_init(void)
{
    last_capture_service_ms = k_uptime_get();
}

// These accessors only copy a timestamp. The UART owns the matching ring slot.
void perf_rx_capture_store_byte(uint8_t slot, uint32_t stored_cycles)
{
    rx_stored_cycles[slot] = stored_cycles;
}

uint32_t perf_rx_capture_load_byte(uint8_t slot)
{
    return rx_stored_cycles[slot];
}
