#ifndef TEST_RESOURCE_KERNEL_H
#define TEST_RESOURCE_KERNEL_H
#include <stddef.h>
#include <stdint.h>
struct k_thread { int unused; };
typedef struct k_thread *k_tid_t;
typedef struct {
    uint64_t execution_cycles;
    uint64_t total_cycles;
    uint64_t idle_cycles;
} k_thread_runtime_stats_t;
int k_thread_runtime_stats_all_get(k_thread_runtime_stats_t *out_stats);
int k_thread_stack_space_get(const struct k_thread *p_thread, size_t *out_unused);
k_tid_t k_current_get(void);
int64_t k_uptime_get(void);
#endif
