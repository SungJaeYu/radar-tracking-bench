# Consistency review evidence — 2026-11-23

[릴리스 검증과 실패 분석](../../release-v1.1.0.md).

- `regression-before.log`: new regression failures before corrections (preserved).
- `python.log`:904 passed,9 subtests passed. Final runner snapshot addition also passed its24 focused tests.
- `analyze_failures.py`, `failure-analysis.json`: independent CRC/CSV replay of8 prior sessions; host RTT and CRC evidence analysis.
- `acceptance-before.py`, `before-sha256.json`: evaluator/source identity before this review.
- `irq-300s-reassessment.json`: previous300s capture interpreted under current policy, not a new board execution; original result preserved.
- `board-60s/`: new actual-board run, exit0, board/delivery/evidence pass,2981 valid measurements matched,CRC0. Host RTT maximum117.529ms is diagnostic only;22 skipped slots leave requested profile inconclusive. Normal firmware restored.
- `board-60s/audit.json`: raw wire→CSV, console→summaries and original evaluator verdict match.
- `manifest.py`, `working-tree-manifest.json`: complete nonignored changed/new working-tree file inventory with hashes, including prior-turn changes. Build products excluded.

`passed` now means observed-load board qualification only. Requested-load qualification, RTT diagnostics and full-coverage limits are explicitly separate; thresholds are unchanged. Known board failures and incomplete evidence are not turned into passes. Earlier source snapshots/raw evidence remain historical.
