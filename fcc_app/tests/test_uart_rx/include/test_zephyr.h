#ifndef TEST_ZEPHYR_H
#define TEST_ZEPHYR_H
// Synchronous test doubles only: no real IRQ scheduling or atomic memory model.
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
#include <string.h>
// Device lookup uses one host-only placeholder.
struct device {
    int unused;
};
static const struct device test_device;
#define DT_NODELABEL(x) 0
#define DEVICE_DT_GET(x) (&test_device)
#define ARG_UNUSED(x) (void)(x)
#define K_FOREVER (-1)
#define K_MSEC(x) (x)
#define K_THREAD_DEFINE(...)

// RX tests replace frame submission directly, so the shared queue hook stays unused.
struct k_msgq;
static inline uint32_t k_msgq_num_used_get(struct k_msgq *p_queue)
{
    (void)p_queue;
    assert(false);
    return 0U;
}

// Semaphores record readiness; they do not block or schedule threads.
struct k_sem {
    unsigned int count;
};
#define K_SEM_DEFINE(name, initial, limit) struct k_sem name = {initial}

static inline void k_sem_give(struct k_sem *p_sem)
{
    p_sem->count = 1;
}

static inline int k_sem_take(struct k_sem *p_sem, int timeout)
{
    (void)timeout;
    p_sem->count = 0;
    return 0;
}

// Record lock state so tests can check critical-section boundaries.
extern unsigned int irq_locked;
extern bool test_in_isr;
static inline unsigned int irq_lock(void)
{
    unsigned int old = irq_locked;
    irq_locked = 1;
    return old;
}

static inline void irq_unlock(unsigned int key)
{
    irq_locked = key;
}

// Tests advance board uptime explicitly; no wall-clock sleeps are needed.
static int64_t test_uptime_ms = 100;
static inline int64_t k_uptime_get(void)
{
    assert(!irq_locked && !test_in_isr);
    return test_uptime_ms;
}

// Single-threaded counter storage; this does not model atomic concurrency.
typedef int atomic_t;
typedef int atomic_val_t;
#define ATOMIC_INIT(x) (x)
static inline atomic_val_t atomic_get(const atomic_t *p_value)
{
    return *p_value;
}

// This single-threaded mock returns the previous value, like Zephyr.
static inline int atomic_inc(atomic_t *p_value)
{
    return (*p_value)++;
}

// Match the previous-value return contract; no concurrent access is simulated.
static inline int atomic_add(atomic_t *p_value, int amount)
{
    const int previous = *p_value;
    *p_value += amount;
    return previous;
}

static inline void atomic_set(atomic_t *p_value, int value)
{
    *p_value = value;
}

static inline void atomic_clear(atomic_t *p_value)
{
    assert(irq_locked);
    *p_value = 0;
}

static inline int printk(const char *p_format, ...)
{
    (void)p_format;
    assert(!irq_locked);
    return 0;
}

// Tests control initialization results and inspect driver call counts.
static bool test_device_ready = true;
static int test_callback_result;
static unsigned int test_callback_calls, test_rx_enable_calls;
static inline bool device_is_ready(const struct device *p_dev)
{
    (void)p_dev;
    return test_device_ready;
}

static inline int uart_irq_callback_user_data_set(const struct device *p_dev,
                                           void (*p_callback)(const struct device *, void *),
                                           void *p_data)
{
    (void)p_dev;
    (void)p_callback;
    (void)p_data;
    test_callback_calls++;
    return test_callback_result;
}

static inline void uart_irq_rx_enable(const struct device *p_dev)
{
    (void)p_dev;
    test_rx_enable_calls++;
}

static inline void uart_irq_update(const struct device *p_dev)
{
    (void)p_dev;
}

// Read injected bytes from an array instead of a hardware FIFO.
static const uint8_t *p_fifo_bytes;
static size_t fifo_size, fifo_position;
static inline bool uart_irq_is_pending(const struct device *p_dev)
{
    (void)p_dev;
    return fifo_position < fifo_size;
}

static inline bool uart_irq_rx_ready(const struct device *p_dev)
{
    return uart_irq_is_pending(p_dev);
}

static inline int uart_fifo_read(const struct device *p_dev, uint8_t *out_byte, int count)
{
    (void)p_dev;
    assert(count == 1);
    if (fifo_position == fifo_size) {
        return 0;
    }

    *out_byte = p_fifo_bytes[fifo_position++];
    return 1;
}

#endif

#if defined(CONFIG_RADAR_PERF_MONITOR)
#include <test_perf_mutex.h>
#endif
