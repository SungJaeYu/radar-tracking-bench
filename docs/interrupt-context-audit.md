# Interrupt context audit — 2026-11-23

The expanded PERF instrumentation incorrectly aggregated RX timing inside an IRQ-masked byte-pop section and inside the UART ISR. The collector also used one spinlock for all updates and its large snapshot copy. These paths were changed; CRC causality is not established by source review alone.

| Path | Review and resulting behavior |
|---|---|
| USART6 callback | Direct Cortex-M DWT reads and bounded raw sample stores only for PERF. No uptime lookup, histogram/64-bit aggregation, collector lock, conversion or logging. Existing UART reads, ring insertion, overflow counters and semaphore notification remain. |
| ISR duration transfer | 256-slot single-producer/single-consumer buffer, 255 usable entries, lock-free C11 acquire/release indices. ISR stores two 32-bit counter values. RX thread converts and aggregates. Full buffer sets sticky capture loss; it never silently overwrites unread samples. |
| Byte-pop IRQ section | Copy byte plus its paired 32-bit timestamp; retain existing ring/overflow synchronization. Counter read, conversion and collector call occur after IRQ restoration. The extra timestamp copy is bounded instrumentation overhead, not zero overhead. |
| RX overflow recovery | RX-owned parser reset moved before IRQ masking. Shared ring reset, discarded-byte count and overflow release remain protected. No parsing/logging inside the section. |
| Common PERF collector | Thread-only mutex replaces spinlock across RX/handler/TX/main. Histogram updates and full snapshot copying run with interrupts enabled. An ISR-context assertion rejects misuse. Mutex acquisition/release still uses Zephyr's internal short synchronization. |
| Parser, predict/correct, handler and TX hooks | Called from their owning threads. Inherit the collector mutex change. No new application IRQ masking. |
| Main summary and stack scan | Logging and scans are outside the collector mutex. Deferred logging is enabled. Source review of Zephyr stack-space query found no enclosing IRQ mask across the stack scan. |
| Scheduler usage API | Zephyr internally uses a spinlock for runtime-accounting snapshots. Application does not hold an outer IRQ mask. This kernel synchronization remains; no claim that all firmware interrupt masking is eliminated or its WCET measured. |
| UART polling/log backend | Existing driver briefly masks IRQs around the register write after waiting for TX readiness. It does not mask IRQs throughout the polling wait. No application logging from ISR was found. |

RX residence now uses DWT elapsed cycles, converted in the RX thread and **rounded up** to integer milliseconds. Its endpoint is after IRQ restoration, so intervening preemption can make it conservative relative to the exact pop instant. The20ms budget is unchanged. Other uptime-based fields retain their previous boundary definitions.

At216MHz the32-bit DWT counter wraps about every19.9s. Unsigned cycle subtraction handles a single wrap. A service gap of1s or more is conservatively marked as lost timing evidence, preventing an unobserved full wrap from passing as a short delay. Capture loss is sticky in `PERF summary: ... rx_capture_lost=1`; the acceptance policy fails it and requires the field in every summary. DWT timing is specific to this configured Cortex-M target and remains affected by preemption/debugger behavior.

Tests enforce no uptime lookup in ISR/IRQ-masked context and no collector mutex acquisition there. Cases cover deferred publication, byte/timestamp alignment through ring wrap and both recovery policies, capture-buffer overflow, cycle wrap and excessive service gaps. Host tests cannot prove physical interrupt latency. ARM object inspection confirms no uptime/collector/mutex calls or atomic helper library calls in the compiled UART callback.

[Execution evidence](test-results/irq-safe-perf-2026-11-23/) · [Performance coverage and gaps](stm32-performance-coverage.md).

Validation completed: Python895 +9 subtests, CTest204 entries (224 internal executions), five firmware builds;300s observed-load PERF board/delivery/evidence pass with CRC0, but host RTT failed and requested-load remained inconclusive. Transport recovery passed95 assertions. Normal image restored. Previous CRC causality remains unproven; see the linked evidence.

Current acceptance interpretation: host RTT is diagnostic only. `passed` mirrors observed-load board/delivery/evidence qualification; requested-load qualification is separate. Historical saved aggregate flags are not rewritten. See [latest review](review-2026-11-23.md).

## RX capture module extraction

After the above board runs, RX-specific raw capture storage, ISR publication, thread collection and timer conversion were moved from `transport/uart_rx.c` to `diagnostics/perf_rx_capture.c/.h`. UART retains byte/ring ownership and short hooks. Thresholds, failure rules and capture ordering are unchanged; function boundaries may change instruction timing. Normal builds erase the hooks and do not link capture state. RX host regression before/after:45 normal +51 PERF cases passed; normal/PERF firmware builds passed. This refactored image has not been flashed or board-tested; prior board captures describe the pre-extraction image.

Follow-up after extraction: the user requested a short check. RX host45+51 passed;10s real-board smoke matched476 valid measurements with CRC/status/capture errors0 and observed-board qualification passed. Normal firmware restored. Host RTT and27 skipped slots remain separate diagnostics/profile limitations. [Short-test evidence](test-results/rx-refactor-2026-11-23/README.md).

## Thread hook cleanup

The same optional-hook pattern now covers `frame_handler.c`, `report_sender.c`,
`rx_frame_processor.c`, `uart_tx.c` and `track.c`. `diagnostics/perf_hooks.h`
contains enabled inline adapters and disabled no-op equivalents. Clock reads,
queue-depth queries and PERF-only TX metadata access stay inside enabled hooks;
callers pass existing values or addresses. The collector API, counters, sampling
boundaries, failure paths and acceptance thresholds are unchanged. ISR capture
continues to use its separate `perf_rx_capture.h` interface.

The TX queue layout and timestamped submission copy retain their configuration
guards, as does main's one-second normal / five-second PERF loop. These guards
select storage or execution behavior rather than optional recording calls. Host
queue mocks were adjusted to support the shared typed hook header; test criteria
were not changed.

Validation: all 204 existing CTest entries passed before and after cleanup, and
normal/PERF firmware builds passed. The normal flash binary is byte-for-byte
identical to the pre-cleanup binary (43,148 bytes; RAM 15,696 bytes), with no PERF
symbols linked. PERF flash changed from 48,480 to 48,504 bytes; RAM remains 21,184
bytes. All new hooks were inlined in both firmware builds. At that host-check stage, the cleanup had not yet
been flashed or tested on the board; the follow-up board evidence is linked below.

Follow-up board verification after the thread-hook cleanup is now recorded in the
[latest validation](test-results/final-validation-2026-11-23/README.md). Functional
and recovery checks passed; the 30-minute PERF attempt aborted at 25 min 38 s
on documented RESET behavior after a host input discontinuity. This does not
establish a board defect or a completed sustained-load qualification. Normal
firmware was restored and all 48 final smoke checks passed.

A further [30-minute board retest](test-results/host-input-retest-2026-11-23/README.md)
passed observed-load board, delivery and evidence checks with 89,057 measurements.
The host skipped 943 slots, so the complete requested 50 Hz profile remains
inconclusive. Controlled host-interruption handling and normal restoration were
also verified. These results do not establish the cause of the earlier CRC errors.
