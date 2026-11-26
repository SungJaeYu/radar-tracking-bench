# Changelog

## v1.2.0 — 2026-11-26

Published from merge commit `a14ec2be32c4dd13d9012c8b7e81eb58aa1cdcc6`; see the [GitHub release](https://github.com/SungJaeYu/radar-tracking-bench/releases/tag/v1.2.0).

### Added

- Unified `python -m pc_sim` commands and GUI test presets, including configurable straight and turn measurement noise.
- Saved truth, measurement, sensor timestamp and CRC frames with integrity validation; FIFO replay and segmented position-error evaluation for straight/turn/straight inputs.
- Build-time polar CV KF / Cartesian CV EKF selection through a shared estimator API, with Kconfig measurement variances and owned fixed-capacity covariance matrices.
- EKF acceleration variance in Kconfig (default 100 preserved), four configuration checks and a 24-run production-C host sweep over the prior saved board inputs.
- Cartesian CT-EKF with a five-state constant-turn model, a shared estimator API, and build-time Kconfig selection.
- Expanded PC truth motion with along-track acceleration and turn-rate acceleration, 20 named presets, and schema-2 storage while retaining schema-1 input support.

### Changed

- Organized simulator and Python tests by responsibility; improved GUI panel sizing, section navigation, position zoom, console ANSI handling and port suggestions.
- Moved fixed initial covariance to `static const`; aligned filter argument names and extracted input assertions into private helpers omitted when assertions are disabled.
- Kept conversation, audit and handoff notes in ignored local storage; updated public usage, architecture and verification documents.

### Validation and remaining work

- Python: 1,058 tests and 9 subtests; host C: 244 CTest executions plus 2 assertion-disabled checks. Both STM32 KF and EKF builds pass. [Validation and reproduction](docs/validation-2026-11-24-estimators.md).
- A separate four-run STM32 comparison matched all 3,020 inputs, with zero gate rejections, lost tracks or communication errors; normal KF firmware was restored. Current CV-EKF tuning reduced pre-turn straight error but increased turn error. An independent float64 calculation reproduced the board results. [Data and figures](docs/hardware-test-2026-11-24-kf-ekf.md).
- The Q follow-up passes 95 affected CTest executions plus 2 assertion-disabled checks, the same Python suite, and KF/default-EKF/Q=10000 STM32 builds. Host default traces remain byte-identical; 10000 and 30000 are exploratory candidates, with no default retune; that initial sweep did not include a new board run. [Q results](docs/test-results/ekf-q-2026-11-24/README.md).
- Fixed Q candidates now have 336 independent-seed/control host runs and 44 primary plus 2 post-hoc STM32 runs, including initially receding noisy turns. All 34,730 board measurements matched; normal KF was restored after both campaigns. Raw UART replay, six figures and the two single gate-rejection diagnostics are preserved. [Results and reproduction](docs/test-results/ekf-q-board-2026-11-24/README.md).
- Release-candidate host regression: 1,091 Python tests; host C tracking 31/31, CT-EKF 22/22 and matrix 1/1 CTest entries. These are host checks, not firmware builds or board qualification.
- The fixed-turn CT comparison and expanded 80-case STM32 maneuver/noise comparison are separate evidence sets. The expanded grid uses one noise seed and is not a general ranking or WCET result. See [conditions, results and firmware provenance](docs/release-v1.2.0.md).
- GUI evaluation presets for expanded scenarios and the results-based LinkedIn post/video/images remain open in issue #10. Issue #8's general lockstep/deferred-recording requirements are separate follow-up work.

## v1.1.0 — 2026-11-23

### Added

- Constant-turn target motion with exact arc integration and stable small-angle displacement.
- Bank-angle/TAS conversion for a no-wind, constant-altitude, constant-speed scenario.
- Timed motion segments and a straight/right-90-degree-turn/straight CLI scenario.
- Predict/correct execution-time aggregation and periodic diagnostics in PERF firmware.
- RX residence/ISR/parser and TX queue/polling timing, scheduler non-idle observations,
  main-stack sampling, and explicit board/delivery/evidence/requested-load verdicts.
- Python coding standard adapted from the firmware's naming, units, ownership and validation rules.

### Changed

- The PERF fixture returns immediately when receive work reaches its deadline, avoiding an unnecessary `sleep(0)`. Four boundary cases cover this correction.
- Release scope follows observed STM32 board/delivery/evidence qualification. Host input completeness remains separately reported; sender improvements are planned for v1.1.1.
- Added a 40-second silent recorded GUI replay, five analysis figures, source tables and provenance.

- Host input gaps reaching the configured receive timeout, or forward sensor-time
  jumps exceeding the prediction limit, now stop the PERF fixture as inconclusive.
  Known board violations remain failures; stored raw verdicts are preserved.
  [Correction and replay](docs/test-results/host-input-verdict-2026-11-23/README.md).

- GUI controls, plot labels, status and error messages are in English.
- Python source comments/docstrings are in English; current GUI captures are refreshed.
- Tracking diagnostics interfaces and structured log messages are clarified.
- Project naming and English/Korean overview and architecture documentation are aligned.
- UART ISR timing capture is bounded; aggregation runs in the RX thread. Collector
  updates and snapshots use a thread-only mutex instead of an IRQ-masking spinlock.
- Performance recording uses a bounded asynchronous writer with explicit loss/error checks.
- `passed` reflects `board_qualification` for the observed load. Requested 50 Hz/full-duration
  qualification is separate; PC RTT is diagnostic only and never a STM32 or release gate.

### Compatibility and validation

- Final Python regression: 928 tests plus 9 subtests; C host: 204 CTest entries (224 internal executions). Final 60-second board check: 27/27 checks, all 2,993 valid measurements matched, zero board errors; raw evidence audited and normal firmware restored. [Final record](docs/release-v1.1.0.md).

- A new 30-minute PERF run passed board/delivery/evidence checks for all 89,057
  measurements. The host skipped 943 slots, leaving the complete requested 50 Hz
  profile inconclusive. A controlled 1.2-second host pause verified inconclusive
  handling and normal-image restoration. [Latest evidence](docs/test-results/host-input-retest-2026-11-23/README.md).
- The earlier hook-cleanup regression passed functional/recovery checks; its load
  attempt stopped after 25 min 38 s on the documented RESET misclassification.
  [Original capture](docs/test-results/final-validation-2026-11-23/README.md) remains unchanged.

- Measurement and TRACK/STATUS wire layouts are unchanged.
- Existing CLI scenarios retain their behavior. New turn scenarios are selected in `run_sim`;
  the GUI and standard evaluator still use fixed azimuth and constant range rate.
- The turn test recorded 755 matched measurements on STM32. Accuracy is observational,
  without a new accuracy acceptance threshold.
- The [dated v1.1.0 report](docs/hardware-test-2026-11-23-v1.1.0.md) preserves the original
  30-minute result and its then-current RTT-based verdict. Current policy does not use RTT
  to block release; its diagnostic limits remain p99 ≤20 ms and maximum ≤100 ms.
- The subsequent 300 s run matched all 14,802 valid measurements with zero board CRC errors
  and passed observed-load board/delivery/evidence checks. Skipped host slots leave requested
  50 Hz qualification inconclusive; earlier CRC events have not recurred after instrumentation corrections; resolution is suspected, but their causal mechanism remains unconfirmed.
  [릴리스 검증과 실패 분석](docs/release-v1.1.0.md).

## v1.0.0 — 2026-11-19

Single-target measurement/result round trips, quantitative evaluation, major error recovery,
30-minute load observations and reproducible documentation established the V1 baseline.
See [the completed scope and acceptance limits](docs/roadmap.md#v1-acceptance).
