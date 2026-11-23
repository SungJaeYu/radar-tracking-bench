# Analysis Media Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Produce a short silent GUI replay and reproducible tables/plots from board captures.

**Architecture:** Two documentation tools consume existing captures. One computes analysis and exports a report; the other renders the existing Qt window from recorded events and encodes MP4.

**Tech Stack:** Python3.12, NumPy/Matplotlib, PySide6, Pillow, FFmpeg; extra dependencies in a temporary directory.

**Spec:** `docs/superpowers/specs/2026-11-23-analysis-media-design.md`

## Global Constraints

- No firmware, acceptance-policy, GUI product, raw-capture or release-status changes.
- English chart/video labels; Korean report explanations; recorded replay always identified.
- Keep monotonic host time, sensor time and board uptime separate.

## Review Focus

- Validate matched timestamps and exact counts before plotting RTT.
- Derive interval means from cumulative deltas; label cumulative maxima correctly.
- Keep omitted input slots separate from delivered-but-missing responses.
- Label the video dataset and paused frames; do not suggest a new board run.
- Inspect all plots and sampled video frames for clipping and legibility.

## Task 1: Analysis report

- [x] Add `tools/docs/analyze_board_results.py`; read saved30min/turn captures and assert consistency with stored metrics.
- [x] Export summary/series CSVs, five figure groups, source hashes, Korean README and local HTML.
- [x] Recompute counts/percentiles/RMSE independently and inspect each figure.

## Task 2: GUI replay

- [x] Add `tools/docs/render_gui_video.py`; no serial connection, ordered captured events, deterministic replay clock.
- [x] Encode approximately40s silent H.264 MP4 and retain sampled frames/provenance.
- [x] Decode the entire output, inspect chapter frames, verify duration and absence of audio.

## Task 3: Publish local documentation

- [x] Link artifacts from docs/GUI/tool documentation; check links, whitespace and unchanged product/raw hashes.
- [x] Report source boundaries and current qualification without committing or merging.

## Completion evidence

- `docs/analysis/2026-11-23/verification.json`: full 600-frame decode, 40 s/15 fps/1600x1000, no audio; 137 product source hashes unchanged and 13 media input hashes matched.
- Five figures and seven decoded chapter frames inspected. HTML browser review unavailable; local references checked.
- Independent final review reproduced RTT, input coverage, turn RMSE and provenance; no material findings.
- GitHub issue #2 remains In Progress pending user review and repository publication. Public Project 1 contains seven issues, with 3D implementation deferred.
- No firmware/GUI behavior, raw captures, acceptance policy, commit, merge or release tag changes in this media task.
