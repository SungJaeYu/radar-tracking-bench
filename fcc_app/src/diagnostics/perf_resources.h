#ifndef PERF_RESOURCES_H
#define PERF_RESOURCES_H

// Main alone calls this after each PERF snapshot. Scheduler accounting is not
// isolated ISR utilization or WCET; stack values are sampled high-water marks.
void perf_resources_log_summary(void);

#endif
