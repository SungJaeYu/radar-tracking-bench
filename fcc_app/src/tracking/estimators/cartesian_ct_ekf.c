#include "tracking/estimator.h"

#include <math.h>

#include "tracking/angle_utils.h"

void estimator_init(struct estimator *p_estimator, float initial_range_m, float initial_azimuth_rad)
{
    const float sine = sinf(initial_azimuth_rad);
    const float cosine = cosf(initial_azimuth_rad);
    const float range_squared = initial_range_m * initial_range_m;
    // Same polar-to-Cartesian initial P as CV, independent of measurement R.
    const float range_variance = 25.0f;
    const float cross_range_variance = range_squared * 0.00121847f;
    const float radial_velocity_variance = 10000.0f;
    const float tangential_velocity_variance = range_squared * 0.03046174f;
    const float position_cross = sine * cosine * (range_variance - cross_range_variance);
    const float velocity_cross = sine * cosine * (radial_velocity_variance - tangential_velocity_variance);
    struct matrix initial = {.rows = EKF_CT_2D_STATE_DIM, .columns = EKF_CT_2D_STATE_DIM};
    matrix_set(&initial, 0, 0, sine * sine * range_variance + cosine * cosine * cross_range_variance);
    matrix_set(&initial, 1, 1, cosine * cosine * range_variance + sine * sine * cross_range_variance);
    matrix_set(&initial, 0, 1, position_cross);
    matrix_set(&initial, 1, 0, position_cross);
    matrix_set(&initial, 2, 2, sine * sine * radial_velocity_variance + cosine * cosine * tangential_velocity_variance);
    matrix_set(&initial, 3, 3, cosine * cosine * radial_velocity_variance + sine * sine * tangential_velocity_variance);
    matrix_set(&initial, 2, 3, velocity_cross);
    matrix_set(&initial, 3, 2, velocity_cross);
    matrix_set(&initial, 4, 4,
                (float)(CONFIG_RADAR_CT_INITIAL_TURN_RATE_VARIANCE_RAD_SQUARED_PER_S_SQUARED_SCALED_1E9 / 1000000000.0));
    ekf_ct_2d_init(&p_estimator->filter, initial_range_m, initial_azimuth_rad, 0.0f, 0.0f, 0.0f, &initial);
}

void estimator_predict(struct estimator *p_estimator, float interval_s)
{
    ekf_ct_2d_predict(&p_estimator->filter, interval_s,
        (float)CONFIG_RADAR_CT_ACCELERATION_VARIANCE_M_SQUARED_PER_S_FOURTH,
        (float)(CONFIG_RADAR_CT_ANGULAR_ACCELERATION_VARIANCE_RAD_SQUARED_PER_S_FOURTH_SCALED_1E9 / 1000000000.0));
}

void estimator_correct(struct estimator *p_estimator, float measured_range_m, float measured_azimuth_rad)
{
    ekf_ct_2d_correct(&p_estimator->filter, measured_range_m, measured_azimuth_rad,
        (float)CONFIG_RADAR_RANGE_MEASUREMENT_VARIANCE_M_SQUARED,
        (float)(CONFIG_RADAR_AZIMUTH_MEASUREMENT_VARIANCE_RAD_SQUARED_SCALED_1E9 / 1000000000.0));
}

struct estimator_output estimator_get_output(const struct estimator *p_estimator)
{
    const struct ekf_ct_2d_filter *p_filter = &p_estimator->filter;
    struct estimator_output output = {.range_m = hypotf(p_filter->x_m, p_filter->y_m)};
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
