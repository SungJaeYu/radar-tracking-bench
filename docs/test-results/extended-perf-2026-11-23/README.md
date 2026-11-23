# Extended STM32 performance verification — 2026-11-23

The existing 20ms board and 20/100ms PC RTT budgets are unchanged. Independent board/delivery/evidence/RTT/requested-load verdicts, new RX/TX observations, scheduler <=80% and sampled application stack >=25% reserve are specified in [the coverage contract](../../stm32-performance-coverage.md). Missing evidence never passes. Full coverage is not established.

- Host Python: final `python-final.log` records 893 tests plus 9 subtests. Initial `python.log` recorded 890 tests plus 9 subtests; three later regressions cover runtime failures and partial counters.
- C host: `host.json`, 200 registered CTest entries across nine builds, 220 internal executions, all passed. The initial tracking configuration error is preserved; corrected configuration used TRACK_TEST_HOST=ON.
- Firmware: normal/PERF/DEBUG/log-stress/transport-stress builds succeeded. FLASH/RAM bytes respectively: 43124/15696, 47532/20096, 59952/16976, 60404/18192, 43856/16912. These linker sizes do not establish runtime safety.
- `smoke-1`: 60s. Four groups passed; requested load inconclusive (2993/3000 scheduled slots, 7 skipped). No aggregate pass. RTT p99 8.671ms/max77.928ms; maximum sampled scheduler non-idle23.604%. Wire/CSV, console/JSON and verdict replay verified in `audit.json`. Normal image restored, STATUS zero.
- `load-30min`: requested 1800s, aborted around159s when STM32 STATUS reported CRC errors=1. This is a failed attempted sustained run, not a completed 30-minute test. Host-captured TX/RX reparse with CRC/length0; physical link versus MCU receive cause remains unresolved. `abort-audit.json` contains counts. Normal image restored, STATUS zero.

- `smoke-2`: another board RX CRC error after about19s; 931 measurements sent, 930 matched before abort. PC RTT p99 25.616ms/max101.118ms exceed the unchanged budgets. Normal image restored, STATUS zero. `audit.json` verifies original wire/CSV and console/JSON records. `verdict-reassessment.json` applies the subsequent partial-snapshot correction without changing the original result.

The interrupted run exposed an assessment bug: known runtime guard failures had been classified only as inconclusive, and final metrics were absent. The runner now records failed category checks before aborting and preserves partial observations. Its original `load-30min/results.json` is not rewritten. A second fix prevents a pre-abort cumulative snapshot from being compared as if it included all final traffic; such incomplete counts remain inconclusive, while observed CRC and RTT violations remain failed. Incomplete validation remains inconclusive alongside the known failure.

`source-sha256.json`, `board_check-snapshot.py`, and `perf_acceptance-snapshot.py` preserve the pre-abort-fix sources. Each run identifies the runner, acceptance logic and ELF hashes. `source-final-sha256.json` identifies subsequent fixes. `audit.py RUN_DIRECTORY` replays a completed run without overwriting its original verdict. Neither a later short pass nor a host-only test erases the sustained CRC failure.

Main merge, push and v1.1.0 tagging remain pending. Physical UART boundaries, strict periodic input, full system stacks and WCET require additional evidence; see the coverage matrix.
