# Maneuver and noise grid methods

Run from the repository root with Python 3.10 or later. The analyzer uses the archived capture and the repository's saved-input loader and UART decoder. It emits aggregate results and does not require a connected board.

```sh
python3 docs/analysis/maneuver-grid-20261126/analyze_grid.py runs/maneuver-noise-grid-20261126-full-capture
python3 docs/analysis/maneuver-grid-20261126/test_analyze_grid.py
```

- [runs.csv](runs.csv) has one row per firmware variant and input case. It records accuracy on the shared comparison set, post-warm-up coverage and full-session transport, tracking, and timing metrics.
- [paired-cases.csv](paired-cases.csv) has one row per input case. It records the measured baseline and all three estimator results on the same timestamps. The delta is variant RMSE minus KF RMSE in metres. Winners use unrounded values.
- [group-summary.csv](group-summary.csv) groups runs by variant and by maneuver, direction, noise, and maneuver × noise. [summary.json](summary.json) includes the same aggregates and the grid totals.
- [provenance.json](provenance.json) records manifest, configuration, HEX and ELF SHA-256 hashes, source commit, board, baud, seed and noise settings. The captured configuration and HEX hashes match the manifest. The corresponding local ELF hashes also matched at analysis time. The manifest records the checkout commit at capture and the flash driver used prebuilt images, so the image hashes identify the binaries used. The restore flag and STATUS values are recorded by the capture runner.

## Accuracy and coverage

The 80 cases combine ten maneuvers, two directions, and four input noise settings at seed 6. Sensor timestamps advance by 100 ms. The first 2.0 s of each case are excluded from accuracy and coverage metrics. Every eligible timestamp at or after 2.0 s enters the accuracy comparison when all three variants provide an estimate with the protocol validity flag. A valid coasting estimate qualifies under this rule. The individual coverage denominator is the number of archived samples at or after 2.0 s. Common coverage uses the intersection of all three validity sets and the same denominator. Gate rejects and LOST transitions use all recorded reports.

Position error is the Euclidean distance in metres from the simulator's saved Cartesian truth. Polar values map to `x = range × sin(azimuth)` and `y = range × cos(azimuth)` with azimuth in radians. The measured baseline is the quantized wire range and wire angle on those same timestamps. A noise-free simulated polar input can have nonzero Cartesian error after quantization. RMSE is the square root of the mean squared position distance. P95 is the nearest-rank position distance at rank `ceil(0.95 × sample count)`. Pooled RMSE and P95 give every eligible shared timestamp equal weight. The separate mean of case RMSE gives each case equal weight.

## Capture integrity

The analyzer validates input hashes and saved-input metadata across the archive and every session. It matches recorded TX measurement frames and timestamps to the capture, checks the entire TX sequence including controls, and decodes the saved RX chunks independently before comparing the results with TRACK and STATUS CSVs. It checks parser errors, complete framing, TRACK sequence continuity, exact input report coverage, reset boundaries, and the two STATUS snapshots per session. A capture invariant failure stops the analysis with a rule identifier.

## Timing

PC RTT is the elapsed host monotonic time from the recorded TX submission to the matching input-present TRACK reply, including UART, OS and capture overhead. The summary reports nearest-rank P50, P95, P99 and the observed maximum. RTT uses all input replies and excludes the control replies.

MCU timing covers the two estimator instrumentation hooks. The tested configurations enable PERF and platform timing at 216 MHz. The reporter emits cumulative counts and integer mean nanoseconds every five seconds. The first session of each flashed variant starts from zero. Subsequent sessions use the preceding session's final complete snapshot as their baseline. The final snapshot must reconcile cumulative measurement count, and the session difference must match the number of observed predictions (updates plus gate rejects) and corrections (updates). An unreconciled session is marked unavailable for stage timing.

The analysis subtracts the baseline product of count and mean from the final product, then divides by the change in count. The firmware rounds down the cumulative mean cycles and the conversion to nanoseconds. The per-session rounding bound propagates both cumulative errors. Aggregate means and bounds are weighted by the number of attributed stage calls. Final cumulative maxima describe the entire observed image boot. Per-session extrema and timing percentiles cannot be recovered from these PERF snapshots. MCU stage timings and PC RTT are observed measurements from this capture. WCET and deadline validation require separate evidence.
