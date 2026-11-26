# v1.2.0 release record

Prepared on 2026-11-26 from `feat/prepared-input`. This release adds build-time
selection among three tracking estimators and a PC truth-model grid used for a
paired STM32 comparison. Results are conditional on the tested motion, one noise
seed, firmware configurations and board setup; they do not establish a universally
best estimator, WCET, or qualification of the requested full 50 Hz profile.

## Included changes

- Build-time selection among polar CV KF, Cartesian CV-EKF and Cartesian CT-EKF
  through the shared estimator interface.
- Configurable EKF process-noise parameters; the existing default polar KF and
  CV-EKF defaults remain unchanged.
- Saved measurement input support and validated PC truth presets for straight,
  constant-rate turns, S-turn, acceleration/deceleration and turn-rate ramps.
- Paired STM32 comparison across 80 expanded maneuver/noise cases, with
  accuracy, estimator timing and host round-trip observations reported below.

## Expanded maneuver comparison

The paired grid contains 10 maneuvers × two initial directions × four noise
profiles: noiseless, weak (range σ=5 m, azimuth σ=0.005 rad), medium (10 m,
0.01 rad) and strong (20 m, 0.02 rad). Every condition used seed 6 and a 0.1 s
sensor interval. All three firmware variants received the same saved wire input
for each condition. The analysis excluded each case's first 2 s and compared
53,400 common valid timestamps. Across the three variants, each received and
matched 55,000 measurements; gate rejections and LOST transitions were zero.

| Estimator | Pooled position RMSE (m) | Position error P95 (m) | Lowest RMSE cases / 80 | Mean predict / correct (µs) | Host RTT P95 (ms) |
|---|---:|---:|---:|---:|---:|
| Polar CV KF | 40.68 | 83.93 | 6 | 28.29 / 33.75 | 6.14 |
| Cartesian CV-EKF | 29.27 | 55.10 | 41 | 176.56 / 516.59 | 6.56 |
| CT-EKF | 93.50 | 189.58 | 33 | 521.02 / 692.59 | 7.09 |

CV-EKF had the lowest pooled RMSE in this grid, while the polar KF used the
least observed estimator time. CT-EKF was competitive on constant-rate turns,
but its position error increased sharply on acceleration/deceleration: RMSE was
99.73 m at ±2 m/s² and 240.21 m at ±5 m/s², versus 25.91 m and 28.16 m for
CV-EKF. This is consistent with a possible mismatch between the constant-speed
turn model and speed changes; the experiment did not isolate that cause from
model tuning. Results are one seed and should not be generalized to the noise
seed distribution. Detailed conditions, segment summaries, timing bounds,
figures and reproduction commands are in the [analysis report](analysis/maneuver-grid-20261126/README.md).

The estimator times are means reconstructed from cumulative PERF counters; the
rounding bounds and counter reconciliation are documented in the analysis
methods. PC RTT includes serial and host scheduling. Reported maxima are
observed values for a boot or run, not WCET or deadline proof.

## Validation and firmware provenance

| Check | Result | Scope |
|---|---|---|
| Python full suite | 1,091 passed | Release-candidate source checkout; Zephyr Python 3.12.14, pytest 9.1.1 |
| Host C tracking | 31/31 CTest entries passed | KF/CV-EKF estimator configurations and gating cases; AppleClang, CMake/Ninja |
| Host C CT-EKF | 22/22 CTest entries passed | CT-EKF and tracker ownership/configuration cases; AppleClang, CMake/Ninja |
| Host C matrix | 1/1 CTest entry passed | Matrix arithmetic; AppleClang, CMake/Ninja |
| Firmware build in this release-candidate pass | Not run | Existing board evidence below is from the recorded prebuilt images, not a new firmware build |
| New board test in this release-candidate pass | Not run | The 80-case STM32 campaign is the separate recorded experiment below |

The 80-case board campaign provenance records source checkout
`b3a092162a96846d2d18c4a60a486c82cdc2b83f`, STM32F746G-DISCO and 115200 baud.
It used prebuilt KF, CV-EKF and CT-EKF PERF images. Their configuration and HEX
hashes matched the capture manifest, and their corresponding local ELF hashes
matched at analysis time. The campaign restored the normal KF image; the
restore record is true and all eight recorded STATUS error fields are zero.
These are the images used for the analysis, not firmware artifacts produced by
the release-candidate host test run. See the [provenance record](analysis/maneuver-grid-20261126/provenance.json)
and [analysis methods](analysis/maneuver-grid-20261126/METHODS.md).

The earlier fixed-turn CT experiment remains separate: it records 252 paired
host runs and 18 STM32 runs with 13,590/13,590 board measurements matched, zero
gate rejections, LOST states or STATUS errors, and restoration of the normal KF
image. See [CT-EKF fixed-turn results](test-results/ct-ekf-2026-11-24/README.md).

## Issue #10 completion state

The noise/maneuver grid and its speed, turn-rate, acceleration, direction,
noise, seed and sample-period settings are now documented. The expanded STM32
comparison records all three estimators on identical inputs, pooled and
condition-level position metrics, estimator timing, PC RTT, complete coverage,
and the absence of gate rejection/LOST events. The existing multi-seed fixed-
turn comparison remains documented separately. The 2026-11-26 expanded grid
itself uses seed 6 only; it does not measure variation across independent noise
seeds.

Issue [#10](https://github.com/SungJaeYu/radar-tracking-bench/issues/10) remains
open for these accepted deliverables:

- Add GUI **evaluation presets** for the expanded scenarios and test conditions.
  This means choosing evaluation conditions/settings in the GUI; it does not
  require a GUI control to switch the estimator in already-flashed firmware.
- Publish the requested results-based LinkedIn post, video and images.

The PC GUI evaluates the estimator in the flashed image; estimator selection is
build-time. General sender policy, deferred recording and lockstep work tracked
by issue #8, and 3D work in issues #4–#7, remain separate scope.

## Release integration

The release commit, main merge, tag, publication date and final remote state are
recorded after integration. The corresponding v1.1.0 board results and historical
verdicts remain in [the v1.1.0 record](release-v1.1.0.md).
