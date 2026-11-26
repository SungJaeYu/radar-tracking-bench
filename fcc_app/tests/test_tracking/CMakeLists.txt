# SPDX-License-Identifier: Apache-2.0
cmake_minimum_required(VERSION 3.20.0)
option(TRACK_TEST_HOST "Run the pure C tests without Zephyr" OFF)
include(../../cmake/estimator.cmake)

if(TRACK_TEST_HOST)
    project(test_tracking C)
    enable_testing()
    add_executable(track_tests src/main.c)
    target_compile_definitions(track_tests PRIVATE TRACK_TEST_HOST)
    # Existing tracking scenarios exercise the unchanged production defaults.
    target_compile_definitions(track_tests PRIVATE
        CONFIG_RADAR_RANGE_GATE_M=100 CONFIG_RADAR_AZIMUTH_GATE_DEG=10
        CONFIG_RADAR_RANGE_MEASUREMENT_VARIANCE_M_SQUARED=25
        CONFIG_RADAR_AZIMUTH_MEASUREMENT_VARIANCE_RAD_SQUARED_SCALED_1E9=1218470)
    target_include_directories(track_tests PRIVATE ../common/include)
    target_compile_options(track_tests PRIVATE -Wall -Wextra -Werror)
    target_link_libraries(track_tests PRIVATE m)
    set(TEST_TARGET track_tests)
    add_test(NAME tracking COMMAND track_tests)
    # Detect regressions to nonterminating angle normalization loops.
    set_tests_properties(tracking PROPERTIES TIMEOUT 10)

    # Compile the real gate implementation separately for each tuning combination.
    function(add_gate_tests name range_m azimuth_deg)
        add_executable(gating_${name} src/gating_cases.c
            ../../src/tracking/gating.c ../../src/tracking/angle_utils.c)
        target_include_directories(gating_${name} PRIVATE ../../src ../common/include)
        target_compile_definitions(gating_${name} PRIVATE
            CONFIG_RADAR_RANGE_GATE_M=${range_m}
            CONFIG_RADAR_AZIMUTH_GATE_DEG=${azimuth_deg})
        target_compile_features(gating_${name} PRIVATE c_std_11)
        target_compile_options(gating_${name} PRIVATE -Wall -Wextra -Werror -UNDEBUG)
        target_link_libraries(gating_${name} PRIVATE m)
        foreach(case IN ITEMS range_boundary angle_boundary both_required wrapped_error)
            add_test(NAME gating_${name}_${case} COMMAND gating_${name} ${case})
        endforeach()
    endfunction()
    function(add_estimator_config_tests name range_r angle_scaled angle_r)
        add_executable(estimator_${name} src/estimator_config_cases.c
            ../../src/tracking/angle_utils.c)
        radar_target_estimator(estimator_${name} KF_CV)
        target_include_directories(estimator_${name} PRIVATE ../../src ../common/include)
        target_compile_definitions(estimator_${name} PRIVATE
            CONFIG_RADAR_RANGE_MEASUREMENT_VARIANCE_M_SQUARED=${range_r}
            CONFIG_RADAR_AZIMUTH_MEASUREMENT_VARIANCE_RAD_SQUARED_SCALED_1E9=${angle_scaled}
            EXPECTED_RANGE_R=${range_r}.0f EXPECTED_AZIMUTH_R=${angle_r})
        target_compile_options(estimator_${name} PRIVATE -Wall -Wextra -Werror -UNDEBUG)
        target_link_libraries(estimator_${name} PRIVATE m)
        add_test(NAME estimator_${name} COMMAND estimator_${name})
    endfunction()
    add_estimator_config_tests(default 25 1218470 0.00121847f)
    add_estimator_config_tests(weak 9 9000 0.000009f)
    add_estimator_config_tests(medium 100 100000 0.0001f)
    add_estimator_config_tests(strong 900 900000 0.0009f)

    function(add_ekf_estimator_tests name range_r angle_scaled angle_r)
        add_executable(estimator_ekf_${name} src/ekf_estimator_cases.c
            ../../src/tracking/angle_utils.c ../../src/tracking/track.c)
        radar_target_estimator(estimator_ekf_${name} EKF_CV)
        target_include_directories(estimator_ekf_${name} PRIVATE ../../src ../common/include)
        target_compile_definitions(estimator_ekf_${name} PRIVATE
            CONFIG_RADAR_EKF_ACCELERATION_VARIANCE_M_SQUARED_PER_S_FOURTH=100
            CONFIG_RADAR_RANGE_MEASUREMENT_VARIANCE_M_SQUARED=${range_r}
            CONFIG_RADAR_AZIMUTH_MEASUREMENT_VARIANCE_RAD_SQUARED_SCALED_1E9=${angle_scaled}
            EXPECTED_RANGE_R=${range_r}.0f EXPECTED_AZIMUTH_R=${angle_r})
        target_compile_options(estimator_ekf_${name} PRIVATE -Wall -Wextra -Werror -UNDEBUG)
        target_link_libraries(estimator_ekf_${name} PRIVATE m)
        add_test(NAME estimator_ekf_${name} COMMAND estimator_ekf_${name})
    endfunction()
    add_ekf_estimator_tests(default 25 1218470 0.00121847f)
    add_ekf_estimator_tests(strong 900 900000 0.0009f)

    # Check the adapter's Q setting independently through predicted covariance.
    function(add_ekf_process_noise_tests name acceleration_variance)
        add_executable(estimator_ekf_q_${name} src/ekf_process_noise_cases.c
            ../../src/tracking/angle_utils.c)
        radar_target_estimator(estimator_ekf_q_${name} EKF_CV)
        target_include_directories(estimator_ekf_q_${name} PRIVATE ../../src ../common/include)
        target_compile_definitions(estimator_ekf_q_${name} PRIVATE
            CONFIG_RADAR_EKF_ACCELERATION_VARIANCE_M_SQUARED_PER_S_FOURTH=${acceleration_variance}
            EXPECTED_ACCELERATION_VARIANCE=${acceleration_variance}
            CONFIG_RADAR_RANGE_MEASUREMENT_VARIANCE_M_SQUARED=25
            CONFIG_RADAR_AZIMUTH_MEASUREMENT_VARIANCE_RAD_SQUARED_SCALED_1E9=1218470)
        target_compile_options(estimator_ekf_q_${name} PRIVATE -Wall -Wextra -Werror -UNDEBUG)
        target_link_libraries(estimator_ekf_q_${name} PRIVATE m)
        add_test(NAME estimator_ekf_q_${name} COMMAND estimator_ekf_q_${name})
    endfunction()
    add_ekf_process_noise_tests(zero 0)
    add_ekf_process_noise_tests(default 100)
    add_ekf_process_noise_tests(changed 10000)
    add_ekf_process_noise_tests(maximum 2147483647)

    add_gate_tests(default 100 10)
    add_gate_tests(minimum 1 1)
    add_gate_tests(narrow 50 5)
    add_gate_tests(wide 250 30)
    add_gate_tests(maximum 65535 180)
else()
    find_package(Zephyr REQUIRED HINTS $ENV{ZEPHYR_BASE})
    project(test_tracking)
    target_sources(app PRIVATE src/main.c)
    set(TEST_TARGET app)
endif()

radar_target_estimator(${TEST_TARGET} KF_CV)
target_sources(${TEST_TARGET} PRIVATE
    ../../src/tracking/angle_utils.c
    ../../src/tracking/gating.c
    ../../src/tracking/track.c
    ../../src/protocol/measurement_message.c
)
target_include_directories(${TEST_TARGET} PRIVATE ../../src)
