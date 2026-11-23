#ifndef TEST_PERF_MUTEX_H
#define TEST_PERF_MUTEX_H
#include <assert.h>
#include <stdbool.h>
#include <pthread.h>
#ifndef K_FOREVER
#define K_FOREVER (-1)
#endif
struct k_mutex { pthread_mutex_t native; };
#define K_MUTEX_DEFINE(name) struct k_mutex name = {PTHREAD_MUTEX_INITIALIZER}
#if defined(TEST_RX_TIMING)
extern unsigned int irq_locked;
extern bool test_in_isr;
#endif
static inline bool k_is_in_isr(void)
{
#if defined(TEST_RX_TIMING)
    return test_in_isr;
#else
    return false;
#endif
}
static inline int k_mutex_lock(struct k_mutex *lock, int timeout)
{
    (void)timeout;
#if defined(TEST_RX_TIMING)
    assert(!irq_locked && !test_in_isr);
#endif
    return pthread_mutex_lock(&lock->native);
}
static inline int k_mutex_unlock(struct k_mutex *lock)
{
    return pthread_mutex_unlock(&lock->native);
}
#endif
