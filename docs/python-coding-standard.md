# Python coding standard

This standard covers maintained Python code in `pc_sim/`, `tests/`, `tools/`,
and Python board-test helpers in `fcc_app/tests/`. Archived scripts under
`docs/test-results/` are historical evidence: preserve their original behavior
and provenance rather than reformatting them to satisfy new rules.

Apply these rules to new or changed code. This document does not claim a full
style migration of existing Python code.

## Rules adapted from firmware C

The [firmware standard](coding-standard.md) supplies the shared engineering
contracts, with Python-specific syntax and error handling:

| Shared principle | Python adaptation |
| --- | --- |
| Clear names and units | `snake_case` functions/variables, `PascalCase` classes, `UPPER_SNAKE_CASE` constants; unit suffixes on physical quantities |
| Explicit state ownership | One owner for serial ports and mutable run state; communicate across threads with queues or Qt signals |
| Validate external boundaries | Validate CLI, configuration, wire and file inputs; raise specific exceptions instead of negative errno values |
| Explicit wire layout | Use the shared protocol module and explicit widths, byte order, range checks and CRC rules |
| Meaningful English comments | `#` for comments, triple-double-quoted docstrings for module/API contracts |
| Separate action and decision | Store side-effecting or substantial operation results before branching; simple pure predicates may stay in conditions |
| Assertions for programmer errors | Use assertions only for internal invariants, never required input validation or side effects |
| Evidence-based verification | Separate Python tests, host C tests, firmware builds and board HIL results |

C pointer prefixes (`p_`, `out_`), braces, casts, `const`, `static inline`,
and errno conventions do not transfer mechanically to Python. Return results
directly where practical. Leading `_` marks internal helpers; it is not access control.

## Names, units and clocks

- Use descriptive names such as `turn_rate_radps`, `range_m`, and `interval_s`.
  Short mathematical locals such as `dt` are acceptable when their meaning and
  units are clear from the function contract.
- Distinguish truth, noisy measurements, and estimates in names and records.
  A target's heading/turn rate is not its radar line-of-sight azimuth/rate.
- Keep established public names such as `timestamp_ms`, `input_timestamp_ms`,
  and `estimate_timestamp_ms` compatible with PC/CSV consumers.
- Distinguish sensor simulation time, host monotonic time, board uptime and
  wall-clock time. Never subtract timestamps from different clock domains.
- Use monotonic clocks for elapsed time and deadlines. Wall-clock timestamps
  identify runs; they do not measure transport latency.
- Document coordinate axes, angle signs, radians/degrees and conversion boundaries.

## Formatting, imports and types

- Use four spaces, no trailing whitespace, and a final newline. Separate logical
  phases with blank lines; use two blank lines between top-level definitions.
- Prefer readable lines around 100 characters; do not split simple expressions
  or rewrite untouched code solely to meet a width target.
- Group standard-library, third-party and project imports. Import dependencies
  explicitly; avoid wildcard imports and import-time I/O or thread startup.
- Add type hints to new public functions and dataclass fields. Use built-in
  collection annotations for new APIs where the supported Python version allows.
  Type hints do not validate runtime inputs.
- Use dataclasses for data/state with clear ownership. Use `@property` for cheap
  derived values; do not store redundant values that can disagree with the state.
- Avoid shared mutable defaults, including random generators. Create per-instance
  state with a factory, or accept/inject it explicitly.

## Comments and docstrings

- Write source comments and docstrings in English, including tests and tools.
- Explain assumptions, units, constraints, ownership and non-obvious reasoning;
  do not narrate self-evident statements.
- Document public API inputs, mutation and failure behavior when the signature
  alone is insufficient. Keep short contracts short.
- UI labels, CLI help, user-facing errors and localized test fixtures are runtime
  strings, not comments. Their language follows the product's interface policy.
  Do not translate them as part of a comment-only change.

## Validation, resources and state

- Reject non-finite floats and out-of-range values at external boundaries where
  physical or wire constraints require it. Do not silently clamp invalid inputs
  unless clipping is an explicit sensor/model contract.
- Raise `ValueError` for invalid values and catch specific expected exceptions.
  CLI entry points should report actionable errors and unsuccessful exit status.
  Do not silently turn failures into valid measurements or successful runs.
- Preserve short-circuit evaluation when separating function calls from conditions.
- Use context managers or `try/finally` to close ports/files and stop workers.
  Bound waits and queues; document timeout, saturation and cancellation behavior.
- Python queues transfer object references, unlike copying Zephyr message queues.
  Do not mutate an object after handing it to another owner unless synchronization
  and shared ownership are explicit. The GIL is not an ownership contract.
- Reset per-run state explicitly. Document whether counters and pending reports
  survive reset. A successful write/flush is not board processing or receipt proof.

## Simulation, protocol and diagnostics

- Separate physical truth generation, sensor noise/detection, wire encoding and
  result evaluation. Keep ground-truth IDs on the PC for the current protocol.
- Keep randomness reproducible through explicit seeds/generators. Compare models
  with identical truth, measurement sequences and timing conditions.
- State model assumptions. `Target.update(dt)` holds speed and turn rate constant
  within one step. Split a step at maneuver changes. The bank/TAS scenario assumes
  no wind, constant altitude and constant TAS; it does not model aircraft energy.
- Keep field widths, byte order and CRC definitions in the protocol module.
  Python integers are unbounded, so validate before packing fixed-width fields.
- For machine-consumed diagnostics, follow `event: key=value` conventions with
  units in keys. Preserve existing output contracts; update parsers, tests and
  documentation together when changing them.
- Separate queued, written, received and processed events. Log observed facts;
  do not label a timing sample as a worst-case execution-time guarantee.

## Verification and current adoption

- Test observable behavior and boundary conditions, not a duplicate of the
  implementation. Use tolerances for floating-point results and fixed seeds for
  random scenarios. Keep physical-board tests explicit and separate from pytest.
- Comment-only changes should preserve the executable AST after excluding
  docstrings, and preserve UI strings, protocol bytes and recorded evidence.
- Run the affected tests; changes shared by PC tools should also pass the Python
  regression suite (`QT_QPA_PLATFORM=offscreen python -m pytest`).
- This change translates the remaining Korean comments/docstrings in tracked
  Python files and adds constant-turn motion tests. Existing API naming, formatting,
  and shared random-default cleanup are not claimed as fully migrated.
