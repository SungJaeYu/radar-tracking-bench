#ifndef REPLAY_PRINTK_H
#define REPLAY_PRINTK_H

// Offline replay suppresses logging; it does not emulate Zephyr scheduling or I/O.
static inline int printk(const char *p_format, ...)
{
    (void)p_format;
    return 0;
}

#endif
