# IRQ-safe PERF regression — 2026-11-23

[계측 실행 문맥](../../performance-monitoring.md#인터럽트와-계측-실행-문맥). The UART ISR now only captures raw timing values; aggregation is deferred to RX thread. Common collector synchronization uses a thread-only mutex. Parser reset is outside the recovery IRQ mask. This does not remove existing kernel synchronization or establish CRC causality.

- Python:895 passed,9 subtests passed (`python.log`).
- C host: all nine variants passed,204 registered CTest items/224 internal executions. RX PERF adds four registration entries for both recovery policies. `host-final.json`, `host-*.log`, `host-tx-perf-final.log`, `rx-tests-final.log`. Initial TX mock declaration compile failure is preserved separately; corrected mock and production collector passed.
- Firmware: normal/PERF/DEBUG/log-stress/transport-stress builds passed. See `firmware-images.json` for linker sizes and ELF hashes. The first stress commands used incorrect overlay paths and failed configuration; corrected `*-final.log` records actual success, without deleting initial logs.
- ARM object inspection: `uart-rx-disassembly.txt` shows no uptime, collector/mutex, or atomic helper library calls in UART callback. Direct timer reads, bounded raw stores and existing UART/ring/semaphore operations remain. This is source/object evidence, not a physical IRQ latency measurement.
- ISR capture overflow and long service gaps are sticky failures. RX residence uses conservative ceiling-to-ms conversion;20ms limit unchanged. PC RTT limits remain p99≤20ms/max≤100ms; missed50Hz slots remain inconclusive.

## Real-board300s PERF run

`run-300s/results.json` and `audit.json`: run completed, all14,802 valid measurements matched (14,799 load +3 recovery),14,807 TRACK reports,301 STATUS reports,223,875 sent wire bytes,62 complete summaries. CRC/length/timeout/queue/ring/drop/stale counters0, ISR capture loss0. Normal firmware restored and STATUS zero.

Board internal/delivery/evidence passed **for observed load**. PC RTT p99 14.727ms passed, max328.516ms failed. Host skipped201 of15,000 scheduled slots: requested-load qualification inconclusive. Aggregate passed=false, full_coverage=false. No budget was relaxed.

Observed maxima: RX byte residence2ms, handler queue1ms, processing2ms, parsed→TX submit2ms, TX queue7ms, TX polling5ms, parsed→TX polling10ms. RX ISR min/mean/max6,129/17,430/22,097ns (capture-publication tail excluded). Maximum scheduler non-idle25.249%. These are observations, not WCET guarantees.

Raw wire independently reparses to all saved CSVs; raw console reproduces parsed summaries; the saved verdict is reproducible. See `run-300s/audit.json`. The earlier CRC failures remain in `../extended-perf-2026-11-23/`; a later clean run cannot erase them or prove the physical cause.

## Real-board transport recovery regression

`transport/results.json`:95 assertions passed, including real ring overflow/discard accounting, RX queue saturation, stale measurement rejection, TX queue saturation and recovery to CONFIRMED tracking. This deliberately injects faults and is separate from the clean PERF run. Normal image was restored and STATUS counters were zero. Neither serial port remained owned after completion.
