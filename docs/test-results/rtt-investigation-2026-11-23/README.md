# RTT tail investigation — 2026-11-23

## Finding and limits

Host waits can delay the single-threaded measurement/receive loop. This was
observed directly in a diagnostic board run and in a UART-free timer control.
The exact cause of the original 220.246 ms sample is **not established**: the
original capture did not time individual host operations or empty reads.
No firmware, production test, acceptance threshold or recorder behavior was changed.
The original 30-minute failure remains a release blocker.

## Original failure

- 89,592 measurements matched; PC RTT p99 9.080 ms, maximum 220.246 ms.
- 21 RTT samples exceeded 100 ms. See [all 21 correlated samples](original-tail.json).
- For the maximum sample, the next measurement write was 219.419 ms later;
  the old response was read another 0.827 ms later.
- Board RX-to-TX-submit maximum was 1 ms, without queue rejection or STATUS errors.
- TX-submit does not measure UART transmission or USB/host delivery. A 1 ms board
  observation alone cannot rule out every device/transport delay.

## Instrumented board run

[probe.py](probe.py) loads the existing `fcc_app/tests/test_perf_monitor/board_check.py`
and times serial read/write/in_waiting, recorder row writes, sample generation,
console parsing, sleep and GC. Only slow events are retained in memory until exit.
Wall duration includes blocking/descheduling; thread CPU duration measures CPU use
by that thread. Neither measurement alone identifies a kernel or scheduling cause.
Instrumentation itself has overhead; this run is diagnostic, not a replacement
30-minute acceptance run.

The existing workload ran for 180 seconds, requesting 50 Hz plus STATUS at 1 Hz.
All 8,985 measurements matched. RTT p99 was 8.736 ms, maximum 83.700 ms;
the 100 ms failure did not recur. Normal firmware was restored and STATUS was zero.
[Full result](run-1/results.json), [timings](run-1/host-timing.json),
[largest RTT samples with overlapping operations](run-1/correlated-tail.json).

| Observed operation | Wall time | Thread CPU | Associated RTT |
|---|---:|---:|---:|
| Requested 1 ms sleep | 55.620 ms | 0.036 ms | 58.734 ms |
| Requested 1 ms sleep | 15.652 ms | 0.022 ms | 44.524 ms |
| Sample CSV row in the same 44.524 ms interval | 24.566 ms | 0.083 ms | 44.524 ms |
| Serial write overlapping the largest RTT | 19.381 ms | 0.079 ms | 83.700 ms |

The last row does not explain the whole 83.700 ms interval. Uninstrumented Python
bookkeeping and time between calls remain. Slow CSV wall time does not prove a
disk bottleneck: thread descheduling while inside that call gives the same result.
Likewise, serial-call wall time alone does not identify USB as the cause.
Longer intentional 50/300 ms sleeps during flash/restore are outside the load and
must not be mistaken for 1 ms polling oversleep.

## UART-free control

[timer_control.py](timer_control.py) ran for 60 seconds with no UART, Qt or CSV
activity during measurement. Of 46,877 requested 1 ms sleeps, 28 took at least
5 ms. Maximum elapsed time was 21.577 ms with only 0.026 ms of thread CPU.
[Raw result](timer-control.json).

This demonstrates host wake-up/execution latency independently of the radar board.
The process was not computing for the full observed wait. It does not distinguish
OS scheduling, timer coalescing/power policy or competing host work.

## Next diagnostic boundary

The original tester services console, data UART, CSV and polling sleep in one
thread. Any long host wait postpones both new measurements and response reads;
the defined write-to-read RTT correctly includes that delay.

To attribute a future >100 ms sample exactly, retain per-loop timestamps, separate
console flush timing, and collect host scheduler/run-queue evidence alongside the
instrumented run. Compare controlled host conditions before changing I/O or
scheduling architecture. Do not lower the budget, subtract host stalls from the
metric, or treat this shorter passing run as proof that the original failure is fixed.

## Recording-worker implementation and retest

`pc_sim/async_recording.py` now moves CSV and raw console storage to a bounded
worker queue. The UART thread still captures both RTT boundaries and owns serial
ports, decoding and validation. Eight new tests cover ordering, timestamp/payload
preservation, blocked storage, queue saturation, failure propagation and shutdown.
Full Python regression: **820 passed, 9 subtests passed**.

| Run | Load samples | RTT p99 / maximum (ms) | Recording events | Existing verdict |
|---|---:|---:|---:|---|
| 60 s smoke | 2,988 (+3 recovery samples) | 8.737 / 158.108 | 12,547/12,547 stored | RTT maximum failed |
| 60 s instrumented diagnostic | 2,989 | 8.382 / 83.282 | 12,510/12,510 stored | Passed |

Both restored normal firmware and zero STATUS. The diagnostic run observed a
requested 1 ms sleep taking75.000 ms with0.025 ms thread CPU. Splitting storage
therefore did not remove host wake-up delays, and these different short runs do
not establish a reliable improvement in RTT. Since the smoke failed the existing
budget, a new30-minute run was not started.

All TRACK/STATUS CSV records in both runs match independent parsing of raw RX
bytes, without CRC/length errors; both session metadata files are closed and all
accepted recording events were written. [Audit and source hashes](threaded-audit.json),
[smoke](threaded-smoke/results.json), [diagnostic](threaded-probe/results.json),
[diagnostic host timing](threaded-probe/host-timing.json).

## Acceptance review: STM32 versus host-inclusive HIL

The current runner combines board checks, evidence validity and PC RTT budgets
into one `passed` value. That value is a verdict on the configured HIL test; it
cannot attribute an RTT-only failure to STM32 processing. The old p99≤20 ms and
maximum≤100 ms are project HIL budgets, not independently derived MCU requirements.

Recommended separation, **not yet a change to executable acceptance policy**:

| Category | Relevant evidence | Interpretation |
|---|---|---|
| Board internal performance | Board-clock queue_wait/processing/rx_to_submit, queue rejection, submit failures, invalid times, boot/faults, sampled stack headroom | Judge measured board work under the applied load; keep20 ms as the declared project internal budget, not a certified deadline |
| HIL functional delivery | Every transmitted input answered once, sequence/CRC/length, estimate/state correctness, STATUS and TX/RX count reconciliation | Necessary integration checks; a failure needs attribution, not an automatic MCU blame assignment |
| Test validity | Closed recordings, no recording queue loss, continuous parseable logs, actual input rate/jitter/duration | Establish whether evidence and applied load support the claim; an inadequate run is inconclusive |
| Host-inclusive latency | PC write-to-read RTT, host send gaps, skipped slots | Keep full statistics; use as an independent host/HIL budget only when that end-to-end requirement is selected |

Recommended result fields are separate board, delivery/evidence and RTT verdicts;
RTT-only failure should not make the board-internal verdict fail. Existing raw
JSON verdicts must remain unchanged. Selecting the new policy for release needs
an explicit scope decision; no automatic main merge or release follows this review.

Important measurement gaps:

- `rx_frame_processor.c:95` timestamps a parsed frame, excluding time from physical
  RX arrival through ring buffering and parsing.
- `report_sender.c:98` timestamps return from `uart_tx_submit`, excluding TX queue
  waiting and physical serial transmission.
- `uart_tx.c:93` counts completion of polling calls; it does not timestamp the last
  stop bit or acknowledge peer reception.
- A host requesting50 Hz with observed jitter does not prove hard periodic50 Hz
  loading. A precise MCU boundary/deadline claim needs appropriate device-side
  timestamps or external capture and a controlled input source.

For the original30-minute and the new60-second smoke, the recorded internal board
checks passed, while the configured host-inclusive maximum RTT budget failed.
This is the supported conclusion; neither “STM32 processing failed” nor “all MCU
timing requirements passed” follows from those recordings.
