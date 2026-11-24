# Bind one estimator implementation and its owned state layout to a target.
# Firmware and host tests use the same source selection.
function(radar_target_estimator target backend)
    set(tracking_dir "${CMAKE_CURRENT_FUNCTION_LIST_DIR}/../src/tracking")
    if(backend STREQUAL "KF_CV")
        target_compile_definitions(${target} PRIVATE CONFIG_RADAR_ESTIMATOR_KF_CV=1)
        target_sources(${target} PRIVATE
            ${tracking_dir}/estimators/polar_cv_kf.c
            ${tracking_dir}/estimators/filters/kf_cv_1d.c)
    elseif(backend STREQUAL "EKF_CV")
        target_compile_definitions(${target} PRIVATE CONFIG_RADAR_ESTIMATOR_EKF_CV=1)
        target_sources(${target} PRIVATE
            ${tracking_dir}/estimators/cartesian_cv_ekf.c
            ${tracking_dir}/estimators/filters/ekf_cv_2d.c
            ${tracking_dir}/../common/matrix.c)
    else()
        message(FATAL_ERROR "Unknown estimator backend: ${backend}")
    endif()
endfunction()
