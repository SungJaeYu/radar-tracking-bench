#ifndef EKF_CV_2D_H
#define EKF_CV_2D_H

#include "common/matrix.h"

#define EKF_CV_2D_STATE_DIM 4U

struct ekf_cv_2d_filter {
    float x_m;
    float y_m;
    float vx_mps;
    float vy_mps;

    // State order: [x, y, vx, vy].
    struct matrix covariance;
};

// Initialize from polar position, Cartesian velocity, and a 4x4 covariance
// ordered [x, y, vx, vy]. Copy the matrix; retain no pointer to the input.
void ekf_cv_2d_init(
    struct ekf_cv_2d_filter *p_filter,
    float initial_range_m,
    float initial_azimuth_rad,
    float initial_vx_mps,
    float initial_vy_mps,
    const struct matrix *p_initial_covariance
);

// Predict using elapsed seconds and acceleration variance [(m/s^2)^2].
void ekf_cv_2d_predict(
    struct ekf_cv_2d_filter *p_filter,
    float interval_s,
    float process_noise_variance
);

// Correct using polar measurements and measurement variances [m^2], [rad^2].
// Use a Joseph covariance update; require a valid symmetric PSD prior covariance.
// Preserve the prior state on near-origin geometry, unsolvable innovation, or
// nonfinite calculation results. This function does not perform gating.
void ekf_cv_2d_correct(
    struct ekf_cv_2d_filter *p_filter,
    float measured_range_m,
    float measured_azimuth_rad,
    float range_measurement_noise_variance,
    float azimuth_measurement_noise_variance
);

#endif
