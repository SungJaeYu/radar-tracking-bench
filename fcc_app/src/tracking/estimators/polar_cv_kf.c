#include "tracking/estimator.h"

void estimator_init(struct estimator *p_estimator, float initial_range_m, float initial_azimuth_rad)
{
    // Range tuning defaults: p00 = 25 m^2, p11 = 10000 (m/s)^2,
    // q = 100 (m/s^2)^2; these are initial tuning values, not sensor calibration data.
    // Keep fixed initial P read-only; each filter receives its own copy.
    static const struct matrix INITIAL_RANGE_COVARIANCE = {
        .rows = KF_CV_1D_STATE_DIM,
        .columns = KF_CV_1D_STATE_DIM,
        .data = {
            25.0f, 0.0f,       // p00: range uncertainty [m^2], p01
            0.0f, 10000.0f,    // p10, p11: range-rate uncertainty [(m/s)^2]
        },
    };
    kf_cv_1d_init(
        &p_estimator->range_filter,
        initial_range_m,
        0.0f,      // initial_range_rate
        &INITIAL_RANGE_COVARIANCE,
        100.0f,    // q: acceleration noise variance
        (float)CONFIG_RADAR_RANGE_MEASUREMENT_VARIANCE_M_SQUARED  // R: measurement noise variance: default std dev = 5 m, R = 5^2 [m^2]
    );

    static const struct matrix INITIAL_AZIMUTH_COVARIANCE = {
        .rows = KF_CV_1D_STATE_DIM,
        .columns = KF_CV_1D_STATE_DIM,
        .data = {
            0.00121847f, 0.0f,  // p00: std dev = 2 deg, (2 * PI / 180)^2 [rad^2], p01
            0.0f, 0.03046174f,  // p10, p11: std dev = 10 deg/s, (10 * PI / 180)^2 [(rad/s)^2]
        },
    };
    kf_cv_1d_init(
        &p_estimator->azimuth_filter,
        initial_azimuth_rad,
        0.0f,      // initial_azimuth_rate
        &INITIAL_AZIMUTH_COVARIANCE,
        0.00761544f,    // q: angular acceleration noise variance: std dev = 5 deg/s^2, q = (5 * PI / 180)^2 [(rad/s^2)^2]
        (float)(CONFIG_RADAR_AZIMUTH_MEASUREMENT_VARIANCE_RAD_SQUARED_SCALED_1E9 / 1000000000.0)  // R: measurement noise variance: default std dev = 2 deg, R = (2 * PI / 180)^2 [rad^2]
    );
}

void estimator_predict(struct estimator *p_estimator, float interval_s)
{
    kf_cv_1d_predict(&p_estimator->range_filter, interval_s);
    kf_cv_1d_predict_angle(&p_estimator->azimuth_filter, interval_s);
}

void estimator_correct(struct estimator *p_estimator, float measured_range_m, float measured_azimuth_rad)
{
    kf_cv_1d_correct(&p_estimator->range_filter, measured_range_m);
    kf_cv_1d_correct_angle(&p_estimator->azimuth_filter, measured_azimuth_rad);
}

struct estimator_output estimator_get_output(const struct estimator *p_estimator)
{
    const struct estimator_output output = {
        .range_m = p_estimator->range_filter.estimate,
        .range_rate_mps = p_estimator->range_filter.rate,
        .azimuth_rad = p_estimator->azimuth_filter.estimate,
        .azimuth_rate_radps = p_estimator->azimuth_filter.rate,
    };

    return output;
}
