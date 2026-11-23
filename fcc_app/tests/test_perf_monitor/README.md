# Performance monitor host tests

Run from the repository root:

```sh
cmake -G Ninja -S fcc_app/tests/test_perf_monitor -B /tmp/radar-perf-tests
cmake --build /tmp/radar-perf-tests
ctest --test-dir /tmp/radar-perf-tests --output-on-failure

cmake -G Ninja -S fcc_app/tests/test_frame_handler -B /tmp/radar-handler-perf-tests -DPERF_TEST_ENABLED=ON
cmake --build /tmp/radar-handler-perf-tests
ctest --test-dir /tmp/radar-handler-perf-tests --output-on-failure

cmake -G Ninja -S fcc_app/tests/test_uart_tx -B /tmp/radar-tx-perf-tests -DPERF_TEST_ENABLED=ON
cmake --build /tmp/radar-tx-perf-tests
ctest --test-dir /tmp/radar-tx-perf-tests --output-on-failure

cmake -G Ninja -S fcc_app/tests/test_uart_rx -B /tmp/radar-rx-perf-tests -DPERF_TEST_ENABLED=ON
cmake --build /tmp/radar-rx-perf-tests
ctest --test-dir /tmp/radar-rx-perf-tests --output-on-failure

cmake -G Ninja -S fcc_app/tests/test_perf_resources -B /tmp/radar-resource-tests
cmake --build /tmp/radar-resource-tests
ctest --test-dir /tmp/radar-resource-tests --output-on-failure
```

The monitor suite registers 13 CTest cases. `perf_monitor_tests` runs ten collector cases, and `perf_reporter_tests` runs the existing reporter case and the cycle-summary case; `perf_reporter_timing_tests` checks ns conversion with a synthetic 100 MHz timer. These executables use the common test runner: no argument runs all cases, a case name selects one, and an unknown name returns 2. The collector fixture resets private state through an included production source; firmware has no diagnostic reset API.

| Case | Behavior checked |
|---|---|
| `test_extended_path_timing` | RX residence, ISR/parser samples, TX queue/polling/origin timing, invalid timestamps and count saturation |
| `test_execution_aggregation` | Independent predict/correct aggregates, zero/UINT64_MAX samples, count/total overflow exclusion |
| `test_execution_summary_cycles/ns` | Empty samples, independent summaries, integer mean and unit conversion with/without timing support |
| `test_counter_saturation` | Counters do not wrap; timing aggregate freezes consistently; huge elapsed values clamp |
| `test_timing_boundaries` | 0/1/19/20/21ms, strict >20ms budget, separate queue/processing/total time |
| `test_failed_and_missing_submit` | Failed submit is excluded from successful timing; missing submit is separate |
| `test_context_cleanup` | No previous measurement reuse after end; duplicate completion ignored |
| `test_invalid_timestamps` | Negative receive time and backwards start/completion excluded |
| `test_queue_and_tx_counts` | Independent RX/TX queues, sampled depth, polling completion vs encode failure |
| `test_snapshot_contract` | NULL returns -EINVAL; reading does not clear counters |
| `test_concurrent_snapshots` | Two pthread producers, 20,000 updates, snapshots preserve the count/depth invariant |
| `test_summary_and_stack_queries` | Empty samples, nearest-rank percentile boundaries, overflow bin, stack minimum, unavailable query and recovery |

The handler's `PERF_TEST_ENABLED=ON` build runs the existing 31 cases plus `test_perf_measurement_paths`: real timing hooks across success, stale/invalid input, encoder failure, full queue, recovery, controls/timeout, and RX submit validation. The TX variant reuses four cases and adds assertions for queue rejection, observed occupancy, successful polling and encoder failure. The RX PERF variant runs 51 cases across DRAIN/DISCARD, including raw capture deferral, sticky loss, timer wrap/service gaps, and byte/timestamp alignment through overflow recovery. Resource sampling adds three cases for scheduler values/query errors and main-stack minima. Total performance-enabled executions: 13 + 32 + 4 + 51 + 3 = 103; these are separate from the 121 default-build executions.

A pthread mutex models the thread-only Zephyr mutex; this checks concurrent host updates/snapshots but not RTOS scheduling or IRQ latency. RX tests additionally reject collector calls or uptime queries from ISR/IRQ-masked context. Handler/TX scheduling, uptime, stack queries and UART are mocked. Firmware builds check the actual Zephyr APIs. No host test establishes board stack headroom, physical delivery, latency, or 30-minute load stability. See [measurement contract and board procedure](../../../docs/performance-monitoring.md).

The separate `tests/test_perf_latency_guard.py` suite checks negative inputs with assertions on/off and signed/unsigned boundaries (12 cases). Run it with `python -m pytest -q tests/test_perf_latency_guard.py`. These tests do not establish actual estimator execution times.

## Real-board check

Build `build_perf` with `perf.conf` and a separate normal `build` image first. The bench script verifies both configurations, flashes the performance image, records both UARTs, and attempts normal-image restoration even on failure. Forced process termination or power loss can prevent restoration.

```sh
python fcc_app/tests/test_perf_monitor/board_check.py \
  --data-port DATA --console-port CONSOLE --workspace /path/to/zephyrproject \
  --output /tmp/new-perf-smoke --duration 10 --smoke
# Run separately after the short check passes. Do not reuse an existing output directory.
python fcc_app/tests/test_perf_monitor/board_check.py \
  --data-port DATA --console-port CONSOLE --workspace /path/to/zephyrproject \
  --output /tmp/new-perf-load --duration 1800
```

Use `--west /path/to/west` and `--git /path/to/git` when they are not on PATH. Keep the host awake for the sustained run (on macOS, prefix the command with `caffeinate -i`). Both serial ports are exclusively owned by this process.

The UART owner timestamps writes/reads and enqueues immutable recording events.
A separate worker owns all session CSVs and the raw console file. Its queue is
bounded to 1,024 events; saturation or file errors fail the run rather than silently
discarding evidence or waiting for disk in the UART loop. Shutdown drains accepted
events and joins the worker (10-second timeout). Final enqueued/written counts are
saved in `results.json`; metadata identifies the recording mode and source hash.
Console parsing and protocol validation remain in the UART owner. Host scheduling
and polling sleep can still delay that thread; asynchronous recording does not
guarantee the host RTT diagnostic limits. `tests/test_async_recording.py` covers ownership, ordering,
snapshot values, backpressure, error propagation and draining without hardware.

The fixed load is a stationary 1,000m/15-degree target, 50Hz MEAS_REPORT and 1Hz STATUS at 115200 8N1. Missed slots are skipped rather than sent in catch-up bursts. The extended policy reports independent `board_internal`, `delivery`, `evidence`, `host_rtt`, and `requested_load` verdicts. `passed=true` means `board_qualification` passed: board internal, delivery and evidence checks succeeded at the observed load. `requested_profile_qualification` additionally requires every scheduled 50Hz slot and the full requested duration. Missing slots make this separate qualification inconclusive, even if the board handled every delivered input. Host RTT is diagnostic only and never gates STM32 qualification or release.

Policy `2026-11-23-host-input-v3` stops the nominal load when the host pre-write
gap reaches the PERF image's `CONFIG_RADAR_MEASUREMENT_TIMEOUT_MS` (currently
1,000ms), or a forward sensor timestamp interval exceeds the firmware's 1,000ms
prediction limit. The script reads and validates the receive timeout before
flashing. It records the transmitted input before checking continuity and saves
the two timestamps, gaps, limits and reasons in `host_input_interruption`.
Normal timestamp wrap remains valid; duplicate/backward inputs receive no exemption.

Interrupted input leaves the unfinished assessment inconclusive, with
`run_completed=false`, `passed=false` and a nonzero CLI exit. Existing observed
CRC, queue, latency, resource, recording or restore failures still take precedence.
The runner does not whitelist RESET responses, change pacing or relax limits.
The host pre-write timestamp is not a physical UART arrival timestamp. Normal
image restoration is still attempted. Boundary and cleanup tests cover this
path; [capture reassessment](../../../docs/test-results/host-input-verdict-2026-11-23/README.md)
documents the original misclassification without claiming a new board run.

Existing limits remain: board software latency <=20ms, host RTT diagnostic p99 <=20ms and max <=100ms. CLI overrides may tighten but cannot relax RTT diagnostic limits. Every extended summary is required. RX byte/parser counts must reconcile with sent wire bytes; TX timing counts must reconcile with completed reports. Scheduler non-idle use must remain <=80% in observed summary windows, with >=25% minimum free space in each of the four sampled application stacks. See the [complete contract and explicit coverage gaps](../../../docs/stm32-performance-coverage.md) and [current review](../../../docs/review-2026-11-23.md). ISR/parser/filter timing distributions are observations, not WCET certification. `full_coverage` remains false.

The short mode also sends an invalid range and INIT/RESET, verifies recovery, and checks that one invalid measurement increments `without_submit` while controls and the timeout event do not add timing samples. Queue saturation and stale injection remain covered by the separate transport stress test; this fixture does not pause consumers.

Raw console text, session CSVs, configurations, ELF/script hashes, complete parsed summaries and assertions are saved. `tests/test_perf_monitor.py` checks summary chunk boundaries, incomplete records, stack query failures, fatal/log-loss detection and percentile rank without serial access. These Python cases also check old/new summary compatibility. Parsing old logs remains supported, but the current extended acceptance policy requires all extended fields and coherent nonempty execution observations in a load run; it does not define execution WCET thresholds. `tests/test_perf_acceptance.py` checks the independent verdicts, missing/invalid evidence and policy boundaries. These Python suites are distinct from the 13 C collector/reporter cases.

Console output now uses `PERF summary:`, `over_budget_count`, `unused_bytes`, and `min_unused_bytes`. The parser accepts old and new spellings and preserves legacy JSON keys. Empty execution aggregates use `status=no_samples`; latency aggregates also expose sample status.

The [2026-11-23 board retest](../../../docs/test-results/host-input-retest-2026-11-23/README.md)
passed a 1,800-second observed load and verified inconclusive handling of a
controlled 1.2-second host pause. The complete requested 50 Hz profile remains
inconclusive because the host skipped 943 scheduled slots.
