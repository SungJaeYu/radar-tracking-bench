# Latest board validation and v1.1.0 readiness

후속 실보드 검증: [30분 관측 부하 통과·호스트 정지 처리 확인](../host-input-retest-2026-11-23/README.md). 요청50Hz 전체는 슬롯943개 누락으로 미확정이며 아래 기록은 당시 결과로 보존한다.

Follow-up: the fixture misclassification has now been corrected. [Offline reassessment](../host-input-verdict-2026-11-23/README.md) is inconclusive, not a new board pass. The original run and the historical account below are preserved.

2026-11-23, `feat/tracking-benchmark`, base `20f069f` with uncommitted changes.
**v1.1.0 is not complete.** The current firmware passed the functional/recovery
checks below, but the requested 1,800-second load stopped after 1,538.447 seconds.
The fixture classified a documented RESET response following a host input gap as
a board rejection. Its original failed verdict remains unchanged. A completed,
valid requested-load run is still missing; no commit, push, merge or tag was made.

## Executed checks

| Check | Result |
|---|---|
| Python | 904 passed + 9 subtests, fresh execution |
| C host regression | Reused the immediately preceding hook-cleanup run: 204 CTest entries passed; production/test source hashes remained unchanged during this validation |
| Firmware builds | Normal, PERF, DEBUG, log stress and transport stress passed; identities and memory sizes in `builds.json` |
| PERF smoke | 10 seconds plus recovery: 502 valid measurements, 507 TRACK, 11 STATUS; 27 checks and observed-board qualification passed. One requested slot was skipped |
| Transport saturation/recovery | STATUS mode 95/95; TRACK/control mode 112/112 |
| Logging | DEBUG traffic 11/11; forced producer saturation 13/13 |
| Normal / noisy / dropout | 120/120, 120/120 and 105/105 input responses; no missing/duplicate input responses or sequence gaps |
| Segmented turn | 755/755 inputs, 757 TRACK, 12/12 checks; wire replay matched. Position RMSE 4.5134 m overall and 1.3960 m during turn, excluding first 2 seconds; observational accuracy, no new accuracy threshold |
| Protocol error recovery | 8/8 checks: deliberate CRC/length/partial-frame faults and valid-frame recovery |
| PERF sustained load | Aborted at 25 min 38.447 s; requested 30-minute qualification incomplete |
| Restore | Normal image restored; final 48/48 checks, initial/final STATUS zero |
| Documents | 918 local file links resolved including this report; anchors were not checked. Existing English GUI captures were visually reviewed, not recaptured |

The earlier 100-run noise sweep and 49-run spike sweep were **not rerun**. Their
dated evidence remains in the [earlier report](../../hardware-test-2026-11-23-v1.1.0.md).
No production code, test criteria or acceptance limits were changed in this turn.

## Why the sustained test stopped

The recorded input and output sequence is explicit:

| Event | Recorded value / response |
|---|---|
| Last ordinary input | Sensor time 1,537,180 ms; UPDATED / CONFIRMED |
| PC write-timestamp gap | 1,159.582 ms |
| No-input report | Sequence 75,799: RESET / EMPTY, `flags=0`, consistent with the configured 1,000 ms receive-silence timeout |
| First input after the gap | Sensor time 1,537,200 ms; sequence 75,800: STARTED / TENTATIVE |
| Next input | Sensor time 1,538,340 ms, a 1,140 ms sensor-time jump; sequence 75,801: RESET / EMPTY, `flags=1` |
| Fixture decision | `Normal stationary measurement rejected`, classified as `board_internal` failure |

`radar_processor.c` explicitly clears an active track when the sensor-time
prediction interval exceeds 1,000 ms, without reusing that input to restart it.
The captured RESET therefore matches the implemented contract. The existing
`test_track_gap_reset_and_recovery` host case was rerun and passed.

The fixture assumes every stationary input must produce STARTED or UPDATED. Its
host-deadline skipping can create a sensor-time jump, and the recorded delayed
send used the earlier selected sensor time before the subsequent jump. The
fixture does not account for this documented RESET when classifying the failure.
The exact reason for the host pause (scheduling, blocking I/O, etc.) was not
captured; PC write timestamps are not physical UART arrival timestamps.

This is **not evidence of a new STM32 defect**, and it is **not a passing load
test**. A future fixture correction must keep the interrupted requested load
inconclusive and still reject unexplained resets or genuine board budget/errors.
It must not whitelist every RESET or relax existing thresholds. The fixture and
evaluator were left unchanged for review.

## Measurements and evidence boundary

- Sent 75,802 measurements; collected 75,800 input-associated reports. Two final
  input timestamps have no captured reply at abort. This is not proof of board
  loss, because the reader stopped immediately on the RESET assertion.
- All 1,538 collected STATUS responses have eight zero counters, including CRC.
  The final RX chunk ends partway through another STATUS payload (22/32 bytes).
- Recording drained successfully: 322,340 events enqueued and written. A closed
  recording preserves received bytes; it does not prove every final response was
  collected or complete.
- All 308 saved PERF summaries have zero capture loss. Observed maxima in ms:
  RX byte residence 2, parser-to-handler 2, processing 3, RX-to-submit 3, TX queue 7,
  TX polling 5, parsed-RX-to-polling 10. All are within the unchanged 20 ms limit,
  but the final snapshot does not cover every last input.
- Maximum observed scheduler non-idle window: 25.3105% (limit 80%). Minimum unused
  app stacks: RX 736, handler 1,360, TX 672, main 496 bytes; all exceed their 25%
  reserve requirements. These observations are not WCET or total stack safety
  certification.
- Host slots skipped: 1,118; actual average 49.2718 Hz. RTT p99 15.3277 ms,
  maximum 556.5714 ms remains a host diagnostic, not the board/release failure
  reason. Neither requested duration nor complete 50 Hz input was achieved.
- Wire/CSV and console/JSON replay matched, and the saved evaluator reproduced
  the original failure. Audit success means stored records agree, not that the
  board load test passed. This run does not explain the two historical CRC events.

## Files and remaining work

- [Suite and executed commands](suite.json), [source hashes](source-sha256.json),
  [build identities](builds.json), [Python output](python-tests.log), `host/` logs.
- [Original PERF result](perf-load/results.json), [original raw audit](perf-load/audit.json),
  [captured input/output analysis](interruption-analysis.json),
  [analysis reproducer](analyze_interruption.py), [session replay](wire-audit.json).
- [Restored STATUS](perf-load/restored-status.json), [final checks](final-smoke/checks.json).

The remaining release work is to review the fixture's handling/classification of
host input discontinuities, obtain the full requested-load evidence with unchanged
board limits, then finish the authorized commit/push/main merge/v1.1.0 tagging.
Broader physical IRQ/stop-bit timing, WCET and hardware-environment campaigns
remain explicitly outside the demonstrated coverage.

Documentation changes in this turn: this report and evidence; current-status
links in the two READMEs, changelog, document index, roadmap, review, verification
history and interrupt audit. One malformed `test_recording.py` requirement-table
row was corrected to REQ-PC-004. Firmware and runner/evaluator hashes are unchanged.
