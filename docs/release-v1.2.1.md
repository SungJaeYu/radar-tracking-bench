# v1.2.1 release record

Published on 2026-11-27 from the verified mainline change in commit
`aee7523440f34c714939b16ea6401dfaa761ce8f`. This maintenance release
specializes fixed-size matrix operations in the Cartesian CV-EKF and CT-EKF
prediction and correction paths. The measured improvement is limited to the
documented input, board, firmware configurations and PERF hooks; it is not a
WCET guarantee or a qualification of the requested full 50 Hz profile.

## Included change

- Replace generic matrix products in the CV-EKF and CT-EKF hot paths with
  fixed-size operations that use the known matrix dimensions and structure.
- Preserve the shared estimator API and compare estimator output through
  numerical host checks and matched UART replays.

## Paired STM32 timing result

The STM32F746G-DISCO comparison used the same saved 755-measurement input for
each of two estimators, two revisions and two rounds (eight runs total). Within
each estimator, all before/after UART response bytes matched. Each run matched
755 unique measurements in order; gate rejections and LOST transitions were
zero. Normal polar KF firmware was restored and all STATUS counters read zero.

| Estimator | Predict + correct before (µs) | Predict + correct after (µs) | Observed reduction |
|---|---:|---:|---:|
| CV-EKF | 700.819 | 370.168 | 47.18% |
| CT-EKF | 1224.733 | 849.184 | 30.66% |

These are means reconstructed from cumulative PERF counters for this input.
Host round-trip latency, worst-case timing and performance across other seeds
were not established by this comparison. The full conditions, per-operation
timings and reproduction procedure are in the [paired STM32 timing report](analysis/ekf-timing-20261126/README.md).

## Validation and provenance

The released change passed a 100,000-prediction and 100,000-correction CV
numeric comparison. Host CTest passed CV 2/2, CT 22/22 and tracking 31/31;
CV and CT firmware builds succeeded. The paired board run used baseline
v1.2.0 firmware and the optimized candidate corresponding to commit
`aee7523440f34c714939b16ea6401dfaa761ce8f`. The source comparison details,
image hashes and per-run summaries are recorded in the [timing report](analysis/ekf-timing-20261126/README.md)
and its [measurement summary](analysis/ekf-timing-20261126/summary.json).

This release does not claim a new full Python regression, a full requested
50 Hz qualification, or WCET. The earlier 80-condition estimator comparison
and its limits remain documented in the [v1.2.0 release record](release-v1.2.0.md).

## Release integration

Issue [#13](https://github.com/SungJaeYu/radar-tracking-bench/issues/13) is
closed. The v1.2.1 milestone contains no open issues and was closed with this
release. The [GitHub release](https://github.com/SungJaeYu/radar-tracking-bench/releases/tag/v1.2.1)
and tag point to this release record commit.
