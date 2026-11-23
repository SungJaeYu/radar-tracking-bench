#include "../../common/test_runner.h"
#include <assert.h>
#include <errno.h>
#include <stdarg.h>
#include <stdio.h>
#include <string.h>
#include <zephyr/kernel.h>
#include "diagnostics/perf_resources.h"

static struct k_thread main_thread;
static size_t stack_unused = 700;
static int cpu_result;
static int stack_result;
static char output[2048];
static size_t output_size;

int64_t k_uptime_get(void) { return 5000; }
k_tid_t k_current_get(void) { return &main_thread; }
int k_thread_runtime_stats_all_get(k_thread_runtime_stats_t *out_stats)
{
    *out_stats = (k_thread_runtime_stats_t){.execution_cycles = 1000,
                                        .total_cycles = 200, .idle_cycles = 800};
    return cpu_result;
}
int k_thread_stack_space_get(const struct k_thread *p_thread, size_t *out_unused)
{
    assert(p_thread == &main_thread);
    *out_unused = stack_unused;
    return stack_result;
}
int printk(const char *p_format, ...)
{
    va_list args;
    va_start(args, p_format);
    const int length = vsnprintf(output + output_size, sizeof(output) - output_size,
                                 p_format, args);
    va_end(args);
    assert(length >= 0 && (size_t)length < sizeof(output) - output_size);
    output_size += (size_t)length;
    return length;
}
static void clear_output(void) { output_size = 0; output[0] = '\0'; }
static void test_values(void)
{
    perf_resources_log_summary();
    assert(strstr(output, "PERF cpu: uptime_ms=5000 total_cycles=1000 busy_cycles=200 idle_cycles=800"));
    assert(strstr(output, "PERF stack main: unused_bytes=700 min_unused_bytes=700"));
}
static void test_query_failures(void)
{
    cpu_result = -ENOTSUP;
    stack_result = -ENOTSUP;
    perf_resources_log_summary();
    assert(strstr(output, "PERF cpu: status=unavailable error="));
    assert(strstr(output, "PERF stack main: status=unavailable error="));
    assert(strstr(output, "busy_cycles=") == NULL);
    assert(strstr(output, "unused_bytes=") == NULL);
}
static void test_stack_minimum(void)
{
    perf_resources_log_summary();
    clear_output();
    stack_unused = 400;
    perf_resources_log_summary();
    assert(strstr(output, "unused_bytes=400 min_unused_bytes=400"));
    clear_output();
    stack_unused = 600;
    perf_resources_log_summary();
    assert(strstr(output, "unused_bytes=600 min_unused_bytes=400"));
}
static const struct test_case cases[] = {
    TEST_CASE(test_values), TEST_CASE(test_query_failures), TEST_CASE(test_stack_minimum),
};
int main(int argc, char **p_argv)
{
    return run_tests(argc, p_argv, cases, sizeof(cases) / sizeof(cases[0]));
}
