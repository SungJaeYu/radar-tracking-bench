# Paired STM32 EKF timing for the v1.2.1 candidate

With the same 755 synthetic measurements, the candidate reduced the mean time spent in prediction plus correction by 47.18% for CV-EKF and 30.66% for CT-EKF. Within each estimator, all four runs returned identical UART bytes.

동일한 합성 입력 755개를 재생했을 때 예측·보정 평균 시간의 합은 CV-EKF에서 330.651 µs, CT-EKF에서 375.549 µs 줄었다. 추정기별 네 번의 시험에서 UART 응답 전체가 바이트 단위로 일치했다.

| Estimator | MCU operation | Baseline (µs) | Candidate (µs) | Reduction |
| --- | --- | ---: | ---: | ---: |
| CV-EKF | Prediction | 176.583 | 31.840 | 81.97% |
| CV-EKF | Correction | 524.236 | 338.328 | 35.46% |
| CV-EKF | Prediction + correction | 700.819 | 370.168 | 47.18% |
| CT-EKF | Prediction | 523.254 | 330.282 | 36.88% |
| CT-EKF | Correction | 701.479 | 518.902 | 26.03% |
| CT-EKF | Prediction + correction | 1224.733 | 849.184 | 30.66% |

## Evidence and limits

Each run began with a fresh flash on the STM32F746G-DISCO. Round one ran baseline CV, candidate CV, candidate CT, baseline CT. Round two reversed that order. All eight runs sent the same UART bytes. Each matched 755 unique measurements in order (6,040 total), recorded zero gate rejections and zero LOST transitions, and included 735 estimates in the position error calculation after a 2 s warm-up. Baseline and candidate position RMSE were equal within each estimator (CV 22.252835 m, CT 13.540277 m). The normal polar KF firmware was restored and every STATUS counter read zero.

Each final cumulative PERF snapshot covered 754 predictions and 754 corrections after track initialization. The firmware converts integer mean cycles per hook to nanoseconds. The table averages the two full-run means per image, converts them to microseconds, and calculates the percentage reduction from the unrounded values. The sum covers computation inside the two MCU hooks. Host round-trip latency, worst-case timing and performance across other seeds require separate evidence. The [80-condition maneuver comparison](../maneuver-grid-20261126/README.md) records the earlier firmware's performance.

## Reproducing the comparison

The baseline was v1.2.0 firmware at `a14ec2be32c4dd13d9012c8b7e81eb58aa1cdcc6`. The candidate was built from `d6e4b62d660f6b7c2c1eff4cde24d9d5b35a1769` with a working-tree patch to the CV and CT filter sources (patch SHA-256 `06e453a54cddf817265982fc60aef5e42c39801b6668a8be2ee9b68dc716ed40`). Check the two source file hashes, image hashes and per-run results against the [measurement summary](summary.json).

Generate the nominal seed-6 input from the repository root. Its range and azimuth noise standard deviations were 10 m and 0.01 rad. The 80 s request ends at the scenario boundary of 75.487 s.

```sh
python -m pc_sim input generate runs/inputs/nominal6 --scenario straight_turn_straight --duration 80 --dt 0.1 --noise 10 --azimuth-noise 0.01 --seed 6
python -m pc_sim input verify runs/inputs/nominal6
```

The generated `samples.jsonl` must have SHA-256 `4161a5e04882526144fcd7cd1a9cab134ef2a630600b527fc07219d737e43586`. Build each revision for `stm32f746g_disco` with [PERF](../../../fcc_app/perf.conf) plus the [CV](../../test-results/ct-ekf-2026-11-24/configs/ekf10000.conf) or [CT](../../test-results/ct-ekf-2026-11-24/configs/ct.conf) overlay in that order. For each trial, capture the board console across the flash, replay with `python -m pc_sim turn-noise --port PORT --input runs/inputs/nominal6`, and continue capturing until the PERF endpoint reaches 755 measurements. Compare the received byte streams within each estimator and restore normal firmware after the final run. [Board bring-up](../../board-bringup.md).
