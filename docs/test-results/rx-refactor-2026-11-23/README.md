# RX capture extraction: short verification

2026-11-23. No production source changes in this verification turn.

- Focused review found no immediate corrective change in the extracted RX capture paths.
- RX host:45 normal +51 PERF cases passed. Both firmware builds reported no work remaining.
- Actual board:10s load plus recovery checks,476 valid measurements matched,481 TRACK reports,11 STATUS reports. Board internal/delivery/evidence passed; CRC and all final STATUS errors0, capture loss0.
- Host diagnostics: RTT p99 75.441ms/max308.973ms,27 skipped load slots; requested50Hz qualification inconclusive. Host RTT does not affect observed-board pass.
- Raw wire/CSV, console/JSON and verdict replay matched (`smoke/audit.json`).
- Normal firmware restored, STATUS zero (`smoke/restored-status.json`). No long test or CRC-cause claim.

Sources identified by `source-sha256.json`; runner/acceptance and ELF hashes are saved under `smoke/`. Host output is in `normal-host.log` and `perf-host.log`.
