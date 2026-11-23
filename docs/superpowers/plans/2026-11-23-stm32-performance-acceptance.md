# STM32 Performance Acceptance Implementation Plan

> **For agentic workers:** Follow the independent firmware and Python tasks below; root integrates and owns hardware access.

**Goal:** Separate MCU, delivery/evidence and host RTT verdicts without weakening budgets, and expose missing MCU performance coverage.

**Architecture:** PERF-only board-clock hooks extend RX and TX timing. The runner preserves strict aggregate HIL success while publishing independent, non-vacuous verdicts and explicit coverage gaps. Existing raw runs remain immutable.

**Tech Stack:** Zephyr C, Python3.12, pytest/CTest, STM32F746G-DISCO.

**Spec:** User-approved verdict separation and request for comprehensive STM32 performance verification; conversation2026-11-23.

## Global constraints

- Keep PC RTT p99≤20ms/max≤100ms and existing MCU20ms budget. No increased thresholds to obtain a pass.
- No wire layout or normal-build instrumentation changes. PERF-only additions must compile out of normal firmware.
- `passed` remains strict aggregate HIL success for compatibility. RTT-only failure cannot turn a fully evaluated MCU group into failure.
- Unknown/missing observations are inconclusive, never pass. No full MCU timing/WCET claim from partial software timestamps.
- Measured RX byte residence, TX queue/poll and parsed-frame-to-TX-poll budgets use the existing20ms project budget, declared before runs.
- Physical UART last-stop-bit timing, pre-ISR delay, true WCET/CPU utilization and hardware fault campaigns are explicit coverage gaps unless separately measured.

## Review focus

- Missing or zero new PERF samples cannot pass the extended profile.
- Valid sensor timestamp zero must not be mistaken for missing correlation.
- Rejected queue entries do not contribute successful latency; normal and stress builds preserve existing behavior.
- Host starvation or incomplete logging cannot be reclassified as verified board performance.
- Worker failures, restoration failures and early aborts cannot yield vacuous group passes.

## Tasks

- [x] Firmware: add PERF RX byte-ring residence, RX ISR/parser cycle observations, TX queue wait/poll duration, correlated parsed-RX→TX-poll measurement latency; preserve existing collector saturation and timestamp validation. Add host regression tests and compile all affected variants.
- [x] Python: retain old parser compatibility, require new fields for new extended profile; separate board/delivery/evidence/RTT verdicts; collect failures rather than stop on first end-of-run assertion; test missing evidence, boundary values, independent RTT failure and fatal aborts.
- [x] Integrate: run full Python and affected/all C host suites, normal/PERF/DEBUG/stress firmware builds. Review diff and configuration/hash metadata.
- [ ] Hardware: fresh short run first, raw-record reconciliation and normal restore. Run sustained30-minute extended profile only after measured board/delivery/evidence gates succeed; preserve RTT outcome separately and the strict overall verdict.
- [x] Documentation: coverage matrix, budgets and measured boundaries, separate outcomes, unverified external measurements, exact evidence. Do not call full coverage or release complete while required coverage is absent.

Source changes and evidence stay on the existing authorized feature branch. Commit/merge/release remain conditional on the documented acceptance scope; no force push or rewriting prior evidence.

## Execution outcome

Short extended run completed; sustained run attempted but aborted on board RX CRC error after about159s. Normal firmware restored. Hardware task remains incomplete; no threshold relaxation or release. Known runtime failure classification was fixed and regression-tested, with original failed evidence preserved.
