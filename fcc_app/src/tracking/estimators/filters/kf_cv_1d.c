#include "tracking/estimators/filters/kf_cv_1d.h"

#include <math.h>
#include <stdbool.h>
#include <stddef.h>

#include <zephyr/sys/__assert.h>

#include "tracking/angle_utils.h"

// Input contract checks are compiled only when Zephyr assertions are enabled.
#if __ASSERT_ON
static void assert_init_inputs(struct kf_cv_1d_filter *p_filter, float initial_value, float initial_rate,
                               const struct matrix *p_initial_covariance,
                               float process_noise_variance, float measurement_noise_variance);
static void assert_predict_inputs(const struct kf_cv_1d_filter *p_filter, float interval_s);
static void assert_correct_inputs(const struct kf_cv_1d_filter *p_filter, float measured_value);

#define ASSERT_INIT_INPUTS(...) assert_init_inputs(__VA_ARGS__)
#define ASSERT_PREDICT_INPUTS(...) assert_predict_inputs(__VA_ARGS__)
#define ASSERT_CORRECT_INPUTS(...) assert_correct_inputs(__VA_ARGS__)
#else
#define ASSERT_INIT_INPUTS(...) ((void)0)
#define ASSERT_PREDICT_INPUTS(...) ((void)0)
#define ASSERT_CORRECT_INPUTS(...) ((void)0)
#endif

static void kf_cv_1d_predict_internal(struct kf_cv_1d_filter *p_filter, float interval_s, bool is_angle);
static void kf_cv_1d_correct_internal(struct kf_cv_1d_filter *p_filter, float measured_value, bool is_angle);

void kf_cv_1d_init(
    struct kf_cv_1d_filter *p_filter,
    float initial_value,
    float initial_rate,
    const struct matrix *p_initial_covariance,
    float process_noise_variance,
    float measurement_noise_variance)
{
    ASSERT_INIT_INPUTS(p_filter, initial_value, initial_rate, p_initial_covariance,
                       process_noise_variance, measurement_noise_variance);

    p_filter->estimate = initial_value;
    p_filter->rate = initial_rate;
    p_filter->covariance = *p_initial_covariance;
    p_filter->process_noise_variance = process_noise_variance;
    p_filter->measurement_noise_variance = measurement_noise_variance;
}

void kf_cv_1d_predict(struct kf_cv_1d_filter *p_filter, float interval_s)
{
    kf_cv_1d_predict_internal(p_filter, interval_s, false);
}

void kf_cv_1d_predict_angle(struct kf_cv_1d_filter *p_filter, float interval_s)
{
    kf_cv_1d_predict_internal(p_filter, interval_s, true);
}

void kf_cv_1d_correct(struct kf_cv_1d_filter *p_filter, float measured_value)
{
    kf_cv_1d_correct_internal(p_filter, measured_value, false);
}

void kf_cv_1d_correct_angle(struct kf_cv_1d_filter *p_filter, float measured_angle_rad)
{
    kf_cv_1d_correct_internal(p_filter, measured_angle_rad, true);
}

static void kf_cv_1d_predict_internal(struct kf_cv_1d_filter *p_filter, float interval_s, bool is_angle)
{
    ASSERT_PREDICT_INPUTS(p_filter, interval_s);

    // State Prediction
    p_filter->estimate += p_filter->rate * interval_s;
    if (is_angle) {
        p_filter->estimate = wrap_angle_rad(p_filter->estimate);
    }

    // Covariance Prediction
    // Discrete acceleration variance q uses Q = q * [[interval_s^4/4, interval_s^3/2], [interval_s^3/2, interval_s^2]].
    // P' = F P F(T) + Q
    const float old_p00 = matrix_get(&p_filter->covariance, 0, 0);
    const float old_p01 = matrix_get(&p_filter->covariance, 0, 1);
    const float old_p10 = matrix_get(&p_filter->covariance, 1, 0);
    const float old_p11 = matrix_get(&p_filter->covariance, 1, 1);
    const float q = p_filter->process_noise_variance;

    matrix_set(&p_filter->covariance, 0, 0, old_p00 +
        interval_s * old_p10 +
        interval_s * old_p01 +
        interval_s * interval_s * old_p11 +
        q * (interval_s * interval_s * interval_s * interval_s) / 4.0f);
    matrix_set(&p_filter->covariance, 0, 1, old_p01 +
        interval_s * old_p11 +
        q * (interval_s * interval_s * interval_s) / 2.0f);
    matrix_set(&p_filter->covariance, 1, 0, old_p10 +
        interval_s * old_p11 +
        q * (interval_s * interval_s * interval_s) / 2.0f);
    matrix_set(&p_filter->covariance, 1, 1, old_p11 +
        q * (interval_s * interval_s));
}

static void kf_cv_1d_correct_internal(struct kf_cv_1d_filter *p_filter, float measured_value, bool is_angle)
{
    ASSERT_CORRECT_INPUTS(p_filter, measured_value);

    // Residual
    float residual = measured_value - p_filter->estimate;

    if (is_angle) {
        residual = wrap_angle_rad(residual);
    }

    // Innovation covariance
    const float s = matrix_get(&p_filter->covariance, 0, 0) + p_filter->measurement_noise_variance;

    // Skip correction for nonfinite or near-zero/nonpositive innovation covariance.
    // Preserve the prior filter state; this does not repair an already invalid covariance.
    const bool innovation_finite = isfinite(s);
    if (!innovation_finite || s <= 1e-6f) {
        return;
    }

    // Kalman Gain
    const float k0 = matrix_get(&p_filter->covariance, 0, 0) / s;
    const float k1 = matrix_get(&p_filter->covariance, 1, 0) / s;

    // State Correction
    p_filter->estimate += k0 * residual;
    if (is_angle) {
        p_filter->estimate = wrap_angle_rad(p_filter->estimate);
    }

    p_filter->rate += k1 * residual;

    // Covariance Correction
    const float pred_p00 = matrix_get(&p_filter->covariance, 0, 0);
    const float pred_p01 = matrix_get(&p_filter->covariance, 0, 1);
    const float pred_p10 = matrix_get(&p_filter->covariance, 1, 0);
    const float pred_p11 = matrix_get(&p_filter->covariance, 1, 1);

    matrix_set(&p_filter->covariance, 0, 0, pred_p00 - k0 * pred_p00);
    matrix_set(&p_filter->covariance, 0, 1, pred_p01 - k0 * pred_p01);
    matrix_set(&p_filter->covariance, 1, 0, pred_p10 - k1 * pred_p00);
    matrix_set(&p_filter->covariance, 1, 1, pred_p11 - k1 * pred_p01);
}

#if __ASSERT_ON
static void assert_init_inputs(struct kf_cv_1d_filter *p_filter, float initial_value, float initial_rate,
                               const struct matrix *p_initial_covariance,
                               float process_noise_variance, float measurement_noise_variance)
{
    __ASSERT(p_filter != NULL, "Kalman filter pointer is NULL");
    __ASSERT(isfinite(initial_value), "Initial value must be finite");
    __ASSERT(isfinite(initial_rate), "Initial value rate must be finite");
    __ASSERT(p_initial_covariance != NULL, "Initial covariance pointer is NULL");
    __ASSERT(p_initial_covariance->rows == KF_CV_1D_STATE_DIM &&
             p_initial_covariance->columns == KF_CV_1D_STATE_DIM,
             "Initial covariance must be 2x2");
    for (size_t row = 0; row < KF_CV_1D_STATE_DIM; ++row) {
        for (size_t column = 0; column < KF_CV_1D_STATE_DIM; ++column) {
            __ASSERT(isfinite(matrix_get(p_initial_covariance, row, column)),
                     "Initial covariance element must be finite");
        }
        __ASSERT(matrix_get(p_initial_covariance, row, row) >= 0.0f,
                 "Initial covariance diagonal must be nonnegative");
    }
    __ASSERT(
        isfinite(process_noise_variance) && process_noise_variance >= 0.0f,
        "Process noise must be finite and nonnegative: %f", (double)process_noise_variance
    );
    __ASSERT(
        isfinite(measurement_noise_variance) && measurement_noise_variance > 0.0f,
        "Measurement noise must be finite and positive: %f", (double)measurement_noise_variance
    );
}

static void assert_predict_inputs(const struct kf_cv_1d_filter *p_filter, float interval_s)
{
    __ASSERT(p_filter != NULL, "Kalman filter pointer is NULL");
    __ASSERT(
        isfinite(interval_s) && interval_s >= 0.0f,
        "Prediction interval must be finite and nonnegative: %f s", (double)interval_s
    );
    __ASSERT(isfinite(p_filter->estimate), "Estimated value must be finite");
    __ASSERT(isfinite(p_filter->rate), "Estimated rate value must be finite");
}

static void assert_correct_inputs(const struct kf_cv_1d_filter *p_filter, float measured_value)
{
    __ASSERT(p_filter != NULL, "Kalman filter pointer is NULL");
    __ASSERT(isfinite(p_filter->estimate), "Estimated value must be finite");
    __ASSERT(isfinite(p_filter->rate), "Estimated rate value must be finite");
    __ASSERT(isfinite(measured_value), "Measurement value must be finite");
}
#endif
