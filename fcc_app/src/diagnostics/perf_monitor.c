#include "diagnostics/perf_monitor.h"

#include <errno.h>
#include <stddef.h>

#include <zephyr/kernel.h>
#include <zephyr/sys/__assert.h>

// Thread-only serialization: aggregation and snapshot copies do not mask IRQs.
// Zephyr may briefly mask IRQs internally while acquiring/releasing the mutex.
K_MUTEX_DEFINE(stats_lock);

static void lock_stats(void)
{
    __ASSERT(!k_is_in_isr(), "Performance aggregation requires thread context");
    (void)k_mutex_lock(&stats_lock, K_FOREVER);
}
static struct perf_stats stats;

// Only the handler starts/ends a context. The lock also makes snapshots coherent.
static struct {
    bool active;
    bool submitted;
    bool valid_time;
    int64_t received_uptime_ms;
    int64_t handler_start_uptime_ms;
} measurement;

static void increment(uint32_t *p_value)
{
    if (*p_value != UINT32_MAX) {
        ++*p_value;
    }
}

static void record_latency(struct perf_latency_stats *p_latency, int64_t elapsed_ms)
{
    __ASSERT(p_latency != NULL, "Latency statistics pointer is NULL");

    if (elapsed_ms < 0) {
        __ASSERT(false, "Latency must be nonnegative: %lld ms", (long long)elapsed_ms);
        return;
    }

    // Stop the whole aggregate together so histogram counts still match count.
    if (p_latency->sample_count == UINT32_MAX) {
        return;
    }

    const uint32_t sample_elapsed_ms = elapsed_ms > UINT32_MAX ? UINT32_MAX : (uint32_t)elapsed_ms;

    ++p_latency->sample_count;
    // Each sample is clamped to uint32, so count * sample fits in uint64.
    p_latency->total_ms += sample_elapsed_ms;

    if (sample_elapsed_ms > p_latency->max_ms) {
        p_latency->max_ms = sample_elapsed_ms;
    }

    const uint32_t bin = sample_elapsed_ms > PERF_LATENCY_BUDGET_MS ? PERF_LATENCY_BUDGET_MS + 1U : sample_elapsed_ms;
    ++p_latency->histogram_counts[bin];

    if (sample_elapsed_ms > PERF_LATENCY_BUDGET_MS) {
        ++p_latency->over_budget_count;
    }
}

// The caller holds stats_lock across all aggregate updates.
static void record_execution(struct perf_execution_stats *p_stats, uint64_t elapsed_cycles)
{
    __ASSERT(p_stats != NULL, "Execution statistics pointer is NULL");

    if (p_stats->sample_count >= UINT32_MAX) {
        return;
    }

    if (elapsed_cycles > UINT64_MAX - p_stats->total_cycles) {
        return;
    }

    if (p_stats->sample_count == 0) {
        p_stats->min_cycles = UINT64_MAX;
        p_stats->max_cycles = 0;
    }

    p_stats->min_cycles = (p_stats->min_cycles <= elapsed_cycles) ? p_stats->min_cycles : elapsed_cycles;
    p_stats->max_cycles = (p_stats->max_cycles >= elapsed_cycles) ? p_stats->max_cycles : elapsed_cycles;

    ++p_stats->sample_count;
    p_stats->total_cycles += elapsed_cycles;
}

void perf_monitor_record_predict(uint64_t elapsed_cycles)
{
    lock_stats();

    record_execution(&stats.estimator_predict, elapsed_cycles);

    k_mutex_unlock(&stats_lock);
}

void perf_monitor_record_correct(uint64_t elapsed_cycles)
{
    lock_stats();

    record_execution(&stats.estimator_correct, elapsed_cycles);

    k_mutex_unlock(&stats_lock);
}

void perf_monitor_begin_measurement(int64_t received_uptime_ms, int64_t handler_start_uptime_ms)
{
    lock_stats();

    measurement.active = true;
    measurement.submitted = false;
    measurement.valid_time = received_uptime_ms >= 0 && handler_start_uptime_ms >= received_uptime_ms;
    measurement.received_uptime_ms = received_uptime_ms;
    measurement.handler_start_uptime_ms = handler_start_uptime_ms;

    increment(&stats.measurements);

    if (measurement.valid_time) {
        record_latency(&stats.queue_wait, handler_start_uptime_ms - received_uptime_ms);
    } else {
        increment(&stats.invalid_timestamps);
    }

    k_mutex_unlock(&stats_lock);
}

void perf_monitor_record_track_submit(int64_t submit_uptime_ms, int result)
{
    lock_stats();

    // Ignore controls, late calls, and duplicate completions of the same input.
    if (measurement.active && !measurement.submitted) {
        measurement.submitted = true;

        if (result != 0) {
            increment(&stats.track_submit_failed);
        } else if (measurement.valid_time) {
            if (submit_uptime_ms >= measurement.handler_start_uptime_ms) {
                record_latency(&stats.processing, submit_uptime_ms - measurement.handler_start_uptime_ms);
                record_latency(&stats.rx_to_submit, submit_uptime_ms - measurement.received_uptime_ms);
            } else {
                increment(&stats.invalid_timestamps);
            }
        }
    }

    k_mutex_unlock(&stats_lock);
}

void perf_monitor_end_measurement(void)
{
    lock_stats();

    if (measurement.active && !measurement.submitted) {
        increment(&stats.without_submit);
    }

    measurement.active = false;

    k_mutex_unlock(&stats_lock);
}

void perf_monitor_record_queue(PerfQueue queue, int result, uint32_t used)
{
    if ((unsigned int)queue >= PERF_QUEUE_COUNT) {
        return;
    }

    lock_stats();

    struct perf_queue_stats *p_queue = &stats.queues[queue];

    increment(result == 0 ? &p_queue->accepted_count : &p_queue->rejected_count);

    if (used > p_queue->max_observed_depth) {
        p_queue->max_observed_depth = used;
    }

    k_mutex_unlock(&stats_lock);
}

void perf_monitor_record_tx(bool completed)
{
    lock_stats();

    increment(completed ? &stats.tx_poll_completed : &stats.tx_encode_failed);

    k_mutex_unlock(&stats_lock);
}

int perf_monitor_get_stats(struct perf_stats *out_stats)
{
    if (out_stats == NULL) {
        return -EINVAL;
    }

    lock_stats();

    *out_stats = stats;

    k_mutex_unlock(&stats_lock);

    return 0;
}

// Validate ordering before subtracting to avoid signed overflow on invalid inputs.
static void record_interval(struct perf_latency_stats *p_stats, int64_t start_ms, int64_t end_ms)
{
    if (start_ms < 0 || end_ms < start_ms) {
        increment(&stats.invalid_timestamps);
        return;
    }
    record_latency(p_stats, end_ms - start_ms);
}

bool perf_monitor_get_measurement_origin(int64_t *out_parsed_ms)
{
    if (out_parsed_ms == NULL) {
        return false;
    }
    lock_stats();
    const bool valid = measurement.active && measurement.valid_time;
    if (valid) {
        *out_parsed_ms = measurement.received_uptime_ms;
    }
    k_mutex_unlock(&stats_lock);
    return valid;
}

void perf_monitor_record_rx_byte(int64_t stored_ms, int64_t removed_ms)
{
    lock_stats();
    record_interval(&stats.rx_byte_wait, stored_ms, removed_ms);
    k_mutex_unlock(&stats_lock);
}

void perf_monitor_record_tx_timing(int64_t queued_ms, int64_t dequeued_ms,
                                   int64_t completed_ms, bool origin_valid, int64_t parsed_ms)
{
    lock_stats();
    record_interval(&stats.tx_queue_wait, queued_ms, dequeued_ms);
    record_interval(&stats.tx_poll, dequeued_ms, completed_ms);
    if (origin_valid) {
        record_interval(&stats.parsed_to_tx_poll, parsed_ms, completed_ms);
    }
    k_mutex_unlock(&stats_lock);
}

void perf_monitor_record_rx_isr(uint64_t elapsed_cycles)
{
    lock_stats();
    record_execution(&stats.rx_isr, elapsed_cycles);
    k_mutex_unlock(&stats_lock);
}

void perf_monitor_record_rx_parser(uint64_t elapsed_cycles)
{
    lock_stats();
    record_execution(&stats.rx_parser, elapsed_cycles);
    k_mutex_unlock(&stats_lock);
}

void perf_monitor_record_rx_capture_lost(void)
{
    lock_stats();
    stats.rx_capture_lost = 1U;
    k_mutex_unlock(&stats_lock);
}
