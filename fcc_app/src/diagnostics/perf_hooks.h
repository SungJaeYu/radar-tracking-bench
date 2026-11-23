#ifndef PERF_HOOKS_H
#define PERF_HOOKS_H

#include <stdint.h>

#include "diagnostics/perf_monitor.h"

struct k_msgq;
struct tx_frame;

// Thread-context adapters keep optional clock reads and metadata access out of callers.
// Pass values or addresses: arguments are still evaluated when a hook is disabled.
#if defined(CONFIG_RADAR_PERF_MONITOR)
#include <zephyr/kernel.h>
#include <zephyr/timing/timing.h>

#include "transport/uart_tx.h"

static inline int64_t perf_hook_uptime_ms(void)
{
    return k_uptime_get();
}

static inline void perf_hook_measurement_begin(int64_t received_ms)
{
    perf_monitor_begin_measurement(received_ms, k_uptime_get());
}

static inline void perf_hook_measurement_end(void)
{
    perf_monitor_end_measurement();
}

static inline void perf_hook_queue_submit(PerfQueue queue, int result, struct k_msgq *p_queue)
{
    perf_monitor_record_queue(queue, result, k_msgq_num_used_get(p_queue));
}

static inline void perf_hook_track_origin(struct tx_frame *p_frame)
{
    p_frame->measurement_origin_valid = perf_monitor_get_measurement_origin(&p_frame->parsed_uptime_ms);
}

static inline void perf_hook_track_submit(int result)
{
    perf_monitor_record_track_submit(k_uptime_get(), result);
}

static inline void perf_hook_tx_encode_failed(void)
{
    perf_monitor_record_tx(false);
}

static inline void perf_hook_tx_completed(const struct tx_frame *p_frame, int64_t dequeued_ms)
{
    const int64_t completed_ms = k_uptime_get();
    perf_monitor_record_tx_timing(p_frame->queued_uptime_ms, dequeued_ms, completed_ms,
                                  p_frame->measurement_origin_valid, p_frame->parsed_uptime_ms);
    perf_monitor_record_tx(true);
}

static inline uint64_t perf_hook_parser_start(void)
{
    return timing_counter_get();
}

static inline uint64_t perf_hook_elapsed_cycles(timing_t start)
{
    timing_t end = timing_counter_get();
    return timing_cycles_get(&start, &end);
}

static inline void perf_hook_parser_end(uint64_t start)
{
    perf_monitor_record_rx_parser(perf_hook_elapsed_cycles(start));
}

#else
static inline int64_t perf_hook_uptime_ms(void) { return 0; }
static inline void perf_hook_measurement_begin(int64_t received_ms) { (void)received_ms; }
static inline void perf_hook_measurement_end(void) { }
static inline void perf_hook_queue_submit(PerfQueue queue, int result, struct k_msgq *p_queue)
{
    (void)queue;
    (void)result;
    (void)p_queue;
}
static inline void perf_hook_track_origin(struct tx_frame *p_frame) { (void)p_frame; }
static inline void perf_hook_track_submit(int result) { (void)result; }
static inline void perf_hook_tx_encode_failed(void) { }
static inline void perf_hook_tx_completed(const struct tx_frame *p_frame, int64_t dequeued_ms)
{
    (void)p_frame;
    (void)dequeued_ms;
}
static inline uint64_t perf_hook_parser_start(void) { return 0U; }
static inline void perf_hook_parser_end(uint64_t start) { (void)start; }
#endif

// Preserve the estimator's timing guard for standalone builds without Kconfig.
#if defined(CONFIG_RADAR_PERF_MONITOR) && defined(CONFIG_TIMING_FUNCTIONS)
static inline uint64_t perf_hook_estimator_start(void)
{
    return timing_counter_get();
}

static inline void perf_hook_predict_end(uint64_t start)
{
    perf_monitor_record_predict(perf_hook_elapsed_cycles(start));
}

static inline void perf_hook_correct_end(uint64_t start)
{
    perf_monitor_record_correct(perf_hook_elapsed_cycles(start));
}
#else
static inline uint64_t perf_hook_estimator_start(void) { return 0U; }
static inline void perf_hook_predict_end(uint64_t start) { (void)start; }
static inline void perf_hook_correct_end(uint64_t start) { (void)start; }
#endif

#endif
