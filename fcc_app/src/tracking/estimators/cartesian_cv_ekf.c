#include "tracking/estimator.h"

#include <math.h>

#include "tracking/angle_utils.h"

void estimator_init(struct estimator *p_estimator, float initial_range_m, float initial_azimuth_rad)
{
    const float sin_azimuth = sinf(initial_azimuth_rad);
    const float cos_azimuth = cosf(initial_azimuth_rad);
    const float range_squared = initial_range_m * initial_range_m;
    // Transform the existing polar initial uncertainties at zero initial velocity.
    // x = r*sin(theta), y = r*cos(theta); P_cartesian = J*P_polar*J^T.
    const float range_variance = 25.0f;  // [m^2], independent of measurement R
    const float cross_range_variance = range_squared * 0.00121847f;  // r^2 * P_theta
    const float radial_velocity_variance = 10000.0f;  // [(m/s)^2]
    const float tangential_velocity_variance = range_squared * 0.03046174f;  // r^2 * P_theta_rate
    const float position_xy_covariance = sin_azimuth * cos_azimuth * (range_variance - cross_range_variance);
    const float velocity_xy_covariance =
        sin_azimuth * cos_azimuth * (radial_velocity_variance - tangential_velocity_variance);
    const struct matrix initial_covariance = {
        .rows = EKF_CV_2D_STATE_DIM,
        .columns = EKF_CV_2D_STATE_DIM,
        .data = {
            sin_azimuth * sin_azimuth * range_variance + cos_azimuth * cos_azimuth * cross_range_variance,
            position_xy_covariance, 0.0f, 0.0f,

            position_xy_covariance,
            cos_azimuth * cos_azimuth * range_variance + sin_azimuth * sin_azimuth * cross_range_variance,
            0.0f, 0.0f,

            0.0f, 0.0f,
            sin_azimuth * sin_azimuth * radial_velocity_variance + cos_azimuth * cos_azimuth * tangential_velocity_variance,
            velocity_xy_covariance,

            0.0f, 0.0f, velocity_xy_covariance,
            cos_azimuth * cos_azimuth * radial_velocity_variance + sin_azimuth * sin_azimuth * tangential_velocity_variance,
        },
    };
    ekf_cv_2d_init(&p_estimator->filter, initial_range_m, initial_azimuth_rad,
                0.0f, 0.0f, &initial_covariance);
}

void estimator_predict(struct estimator *p_estimator, float interval_s)
{
    // Independent x/y acceleration variance [(m/s^2)^2]; not polar angular Q.
    ekf_cv_2d_predict(&p_estimator->filter, interval_s, 100.0f);
}

void estimator_correct(struct estimator *p_estimator, float measured_range_m, float measured_azimuth_rad)
{
    ekf_cv_2d_correct(&p_estimator->filter, measured_range_m, measured_azimuth_rad,
                  (float)CONFIG_RADAR_RANGE_MEASUREMENT_VARIANCE_M_SQUARED,
                  (float)(CONFIG_RADAR_AZIMUTH_MEASUREMENT_VARIANCE_RAD_SQUARED_SCALED_1E9 / 1000000000.0));
}

struct estimator_output estimator_get_output(const struct estimator *p_estimator)
{
    const struct ekf_cv_2d_filter *p_filter = &p_estimator->filter;
    struct estimator_output output = {.range_m = hypotf(p_filter->x_m, p_filter->y_m)};
    // At the origin direction and polar rates are undefined. Avoid division by zero.
    if (output.range_m == 0.0f) {
        return output;
    }
    const float direction_x = p_filter->x_m / output.range_m;
    const float direction_y = p_filter->y_m / output.range_m;
    output.azimuth_rad = wrap_angle_rad(atan2f(p_filter->x_m, p_filter->y_m));
    output.range_rate_mps = direction_x * p_filter->vx_mps + direction_y * p_filter->vy_mps;
    output.azimuth_rate_radps = (direction_y * p_filter->vx_mps - direction_x * p_filter->vy_mps) / output.range_m;
    return output;
}
