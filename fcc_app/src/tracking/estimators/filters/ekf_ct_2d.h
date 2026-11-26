#ifndef EKF_CT_2D_H
#define EKF_CT_2D_H

#include "common/matrix.h"

#define EKF_CT_2D_STATE_DIM 5U

_Static_assert(MATRIX_MAX_ROWS >= EKF_CT_2D_STATE_DIM && MATRIX_MAX_COLUMNS >= EKF_CT_2D_STATE_DIM,
               "CT target requires five-by-five matrix capacity in all translation units");

struct ekf_ct_2d_filter {
    float x_m;
    float y_m;
    float vx_mps;
    float vy_mps;
    float turn_rate_radps;
    // State order [x, y, vx, vy, omega]; positive omega turns clockwise.
    struct matrix covariance;
};

// Copy the five-by-five covariance; retain no caller-owned storage.
void ekf_ct_2d_init(struct ekf_ct_2d_filter *p_filter, float initial_range_m,
                    float initial_azimuth_rad, float initial_vx_mps, float initial_vy_mps,
                    float initial_turn_rate_radps, const struct matrix *p_initial_covariance);

// Exact constant-turn mean, linearized covariance, additive per-step disturbances.
// Variances: Cartesian acceleration [m^2/s^4], angular acceleration [rad^2/s^4].
// Invalid/nonfinite calculations leave the prior unchanged, including with ASSERT off.
void ekf_ct_2d_predict(struct ekf_ct_2d_filter *p_filter, float interval_s,
                       float acceleration_variance, float angular_acceleration_variance);

// Polar measurement R in [m^2] and [rad^2], wrapped angle residual, Joseph update.
// Require a symmetric PSD prior. Origin/unsolvable/nonfinite cases preserve it.
// Gating and lifecycle belong to the common tracker, not this numerical filter.
void ekf_ct_2d_correct(struct ekf_ct_2d_filter *p_filter, float measured_range_m,
                       float measured_azimuth_rad, float range_measurement_variance,
                       float azimuth_measurement_variance);

#endif
