# SPDX-License-Identifier: Apache-2.0
cmake_minimum_required(VERSION 3.20.0)
find_package(Zephyr REQUIRED HINTS $ENV{ZEPHYR_BASE})
project(fcc_app)

target_sources(app PRIVATE
    src/main.c
    src/transport/uart_rx.c
    src/protocol/frame_parser.c
    src/common/ring_buffer.c
    src/application/frame_handler.c
    src/application/radar_processor.c
    src/application/report_sender.c
    src/protocol/measurement_message.c
    src/tracking/gating.c
    src/tracking/angle_utils.c
    src/tracking/track.c
    src/transport/rx_frame_processor.c
    src/transport/uart_tx.c
    src/protocol/protocol_frame.c
    src/common/crc16.c
    src/protocol/status_message.c
    src/protocol/track_message.c
)

include(cmake/estimator.cmake)
if(CONFIG_RADAR_ESTIMATOR_EKF_CV)
    radar_target_estimator(app EKF_CV)
else()
    radar_target_estimator(app KF_CV)
endif()

# Resolve module-qualified includes from the application source root.
target_include_directories(app PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/src)

# Optional bench diagnostics; no collector or reporter is linked into normal firmware.
target_sources_ifdef(CONFIG_RADAR_PERF_MONITOR app PRIVATE
    src/diagnostics/perf_monitor.c
    src/diagnostics/perf_rx_capture.c
    src/diagnostics/perf_reporter.c
)

if(CONFIG_RADAR_PERF_MONITOR AND CONFIG_SCHED_THREAD_USAGE_ALL)
    target_sources(app PRIVATE src/diagnostics/perf_resources.c)
endif()

# Bench-only producer; excluded from normal and ordinary debug firmware.
target_sources_ifdef(CONFIG_RADAR_LOG_STRESS_TEST app PRIVATE tests/log_stress/log_stress.c)

target_sources_ifdef(CONFIG_RADAR_TRANSPORT_STRESS_TEST app PRIVATE tests/transport_stress/transport_stress.c)
