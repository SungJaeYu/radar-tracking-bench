#ifndef KF_CV_1D_H
#define KF_CV_1D_H

#include "common/matrix.h"

#define KF_CV_1D_STATE_DIM 2U

// Constant-velocity state [value, rate] with covariance matrix [[p00, p01], [p10, p11]].
// Range mode uses m and m/s; angle mode uses rad and rad/s.
// process_noise_variance is acceleration variance; measurement_noise_variance is value variance.
// Covariance units follow the corresponding state products.
struct kf_cv_1d_filter {
    float estimate;
    float rate;

    // State order: [value, rate]. Owns a 2x2 covariance.
    struct matrix covariance;

    float process_noise_variance;
    float measurement_noise_variance;
};

// Initialize with a caller-selected 2x2 covariance ordered [value, rate].
// Copy the covariance; retain no pointer to the input. Call before predict/correct.
// The caller supplies physically valid covariance/noise parameters; assertions
// check dimensions, finite entries and nonnegative diagonal, not full PSD validity.
void kf_cv_1d_init(
    struct kf_cv_1d_filter *p_filter,
    float initial_value,
    float initial_rate,
    const struct matrix *p_initial_covariance,
    float process_noise_variance,
    float measurement_noise_variance
);

// Predict a non-NULL initialized linear filter forward by interval_s seconds.
// The caller validates the time interval before calling.
void kf_cv_1d_predict(struct kf_cv_1d_filter *p_filter, float interval_s);

// Predict an initialized angular filter using interval_s seconds; wrap the estimate to (-pi, pi].
void kf_cv_1d_predict_angle(struct kf_cv_1d_filter *p_filter, float interval_s);

// Correct an initialized linear filter with a measurement in the state value unit.
// Skip correction if innovation covariance is <= 1e-6; no status is returned.
void kf_cv_1d_correct(struct kf_cv_1d_filter *p_filter, float measured_value);

// Correct an initialized angular filter with a measurement in radians.
// Wrap the residual and updated estimate; the same covariance guard applies.
void kf_cv_1d_correct_angle(struct kf_cv_1d_filter *p_filter, float measured_angle_rad);

#endif
