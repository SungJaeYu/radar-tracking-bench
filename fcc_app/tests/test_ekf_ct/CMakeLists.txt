cmake_minimum_required(VERSION 3.20.0)
project(test_ekf_ct C)
enable_testing()
include(../../cmake/estimator.cmake)

foreach(assertions IN ITEMS 0 2)
    set(target ct_tests_${assertions})
    add_executable(${target} src/main.c ../../src/tracking/angle_utils.c ../../src/tracking/track.c)
    radar_target_estimator(${target} EKF_CT)
    target_include_directories(${target} PRIVATE ../../src ../common/include)
    target_compile_features(${target} PRIVATE c_std_11)
    target_compile_options(${target} PRIVATE -Wall -Wextra -Werror -UNDEBUG -fstack-usage)
    target_compile_definitions(${target} PRIVATE __ASSERT_ON=${assertions}
        CONFIG_RADAR_CT_ACCELERATION_VARIANCE_M_SQUARED_PER_S_FOURTH=100
        CONFIG_RADAR_CT_ANGULAR_ACCELERATION_VARIANCE_RAD_SQUARED_PER_S_FOURTH_SCALED_1E9=100000
        CONFIG_RADAR_CT_INITIAL_TURN_RATE_VARIANCE_RAD_SQUARED_PER_S_SQUARED_SCALED_1E9=10000000
        CONFIG_RADAR_RANGE_MEASUREMENT_VARIANCE_M_SQUARED=25
        CONFIG_RADAR_AZIMUTH_MEASUREMENT_VARIANCE_RAD_SQUARED_SCALED_1E9=1218470)
    target_link_libraries(${target} PRIVATE m)
    foreach(case IN ITEMS ownership quarter_turn noise zero_interval wrapped numerical_failure
            malformed_covariance_dimensions nonfinite_covariance correction_overflow lifecycle configuration)
        add_test(NAME ct_${assertions}_${case} COMMAND ${target} test_${case})
    endforeach()
endforeach()
