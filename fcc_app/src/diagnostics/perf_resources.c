#include "diagnostics/perf_resources.h"

#include <stdint.h>
#include <zephyr/kernel.h>
#include <zephyr/logging/log.h>

LOG_MODULE_REGISTER(radar_resources, LOG_LEVEL_INF);

// Main owns these objects; avoid placing the runtime snapshot on its small stack.
static k_thread_runtime_stats_t cpu_stats;
static size_t min_main_unused = SIZE_MAX;

void perf_resources_log_summary(void)
{
    const int cpu_ret = k_thread_runtime_stats_all_get(&cpu_stats);
    if (cpu_ret == 0) {
        LOG_INF("PERF cpu: uptime_ms=%lld total_cycles=%llu busy_cycles=%llu idle_cycles=%llu",
                (long long)k_uptime_get(),
                (unsigned long long)cpu_stats.execution_cycles,
                (unsigned long long)cpu_stats.total_cycles,
                (unsigned long long)cpu_stats.idle_cycles);
    } else {
        LOG_INF("PERF cpu: status=unavailable error=%d", cpu_ret);
    }

    size_t unused_bytes;
    const int stack_ret = k_thread_stack_space_get(k_current_get(), &unused_bytes);
    if (stack_ret == 0) {
        if (unused_bytes < min_main_unused) {
            min_main_unused = unused_bytes;
        }
        LOG_INF("PERF stack main: unused_bytes=%u min_unused_bytes=%u",
                (unsigned int)unused_bytes, (unsigned int)min_main_unused);
    } else {
        LOG_INF("PERF stack main: status=unavailable error=%d", stack_ret);
    }
}
