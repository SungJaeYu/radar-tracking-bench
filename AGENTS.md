# Repository Guidelines

## Project Structure

- `fcc_app/src/` contains the Zephyr C firmware for STM32F746G-DISCO. Application, transport, protocol, tracking, and diagnostics code live in separate modules. Estimator implementations are under `tracking/estimators/`.
- `pc_sim/` contains the Python simulator, CLI, Qt UI, evaluation, transport, and recording tools. Use `python -m pc_sim` as the CLI entry point.
- Python tests live in `tests/`. Firmware and host C tests live in `fcc_app/tests/`. Design notes and published test evidence live in `docs/`; keep ordinary device captures in the ignored `runs/` directory.

## Build, Test, and Run

- From your Zephyr workspace, build firmware with `west build -b stm32f746g_disco -d <repo>/build <repo>/fcc_app`. Use separate build directories for estimator variants and select them with the corresponding extra configuration file.
- From the repository root, run `QT_QPA_PLATFORM=offscreen python -m pytest` for Python tests.
- For host C tracking tests, configure with `cmake -S fcc_app/tests/test_tracking -B /tmp/radar-track-tests -DTRACK_TEST_HOST=ON`, then run `cmake --build /tmp/radar-track-tests` and `ctest --test-dir /tmp/radar-track-tests --output-on-failure`.
- Preview frames without a board using `python -m pc_sim simulate --scenario straight_turn_straight --duration 80`. Launch the optional Qt interface with `python -m pc_sim gui`.

## Style and Testing

Use four spaces for indentation and snake_case for functions and variables. Follow [the firmware coding standard](docs/coding-standard.md) for C naming, brace placement, and units in identifiers. Match nearby Python style. Name Python tests `test_*.py` and register new host C cases with the shared `TEST_CASE` runner.

Cover changed behavior and relevant compatibility boundaries. For protocol changes, verify both the C and Python paths. Report host tests, firmware builds, and real-board tests separately. For hardware comparisons, record the configuration, input seed, and raw evidence.

## Hardware Test Data

Do not open, dump, or inspect rows directly from hardware-test CSV files under `docs/analysis/`, including compressed CSV files. To check the data, run the corresponding analysis program and inspect its summary, statistics, or plots. If no suitable program exists, write a small analysis script that reads the file and emits only the results needed for the check.

## Commits and Pull Requests

Write short, imperative subjects using prefixes found in history, such as `feat:`, `test:`, and `docs:`. Explain the behavior change, link relevant issues, and list the checks actually run. Include screenshots for visible GUI changes and link reproducible evidence for measurement claims.
