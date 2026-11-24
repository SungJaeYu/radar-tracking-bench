#include "tracking/estimators/filters/ekf_ct_2d.h"

#include <float.h>
#include <math.h>
#include <stdbool.h>
#include <zephyr/sys/__assert.h>

#include "tracking/angle_utils.h"

#define CT_MEASUREMENT_DIM 2U
#define CT_TURN_INDEX 4U
#define CT_SERIES_ANGLE_RAD 0.05f

static bool covariance_valid(const struct matrix *p_covariance);
static bool filter_valid(const struct ekf_ct_2d_filter *p_filter);
static bool finish_covariance(struct matrix *p_covariance);
static void motion_jacobian(const struct ekf_ct_2d_filter *p_filter, float interval_s,
                            struct ekf_ct_2d_filter *out_predicted, struct matrix *out_transition);
static bool calculate_gain(const struct matrix *p_covariance, const float p_observation[CT_MEASUREMENT_DIM][2],
                            float range_variance, float azimuth_variance,
                            float out_gain[EKF_CT_2D_STATE_DIM][CT_MEASUREMENT_DIM]);
static bool correct_covariance(const struct matrix *p_prior, const float p_observation[CT_MEASUREMENT_DIM][2],
                                const float p_gain[EKF_CT_2D_STATE_DIM][CT_MEASUREMENT_DIM],
                                float range_variance, float azimuth_variance, struct matrix *out_covariance);

#if __ASSERT_ON
static void assert_init_inputs(const struct ekf_ct_2d_filter *p_filter, float range_m, float azimuth_rad,
                                float vx_mps, float vy_mps, float turn_rate_radps, const struct matrix *p_covariance);
static void assert_predict_inputs(const struct ekf_ct_2d_filter *p_filter, float interval_s,
                                   float acceleration_variance, float angular_acceleration_variance);
static void assert_correct_inputs(const struct ekf_ct_2d_filter *p_filter, float range_m, float azimuth_rad,
                                   float range_variance, float azimuth_variance);
#define ASSERT_INIT(...) assert_init_inputs(__VA_ARGS__)
#define ASSERT_PREDICT(...) assert_predict_inputs(__VA_ARGS__)
#define ASSERT_CORRECT(...) assert_correct_inputs(__VA_ARGS__)
#else
#define ASSERT_INIT(...) ((void)0)
#define ASSERT_PREDICT(...) ((void)0)
#define ASSERT_CORRECT(...) ((void)0)
#endif

void ekf_ct_2d_init(struct ekf_ct_2d_filter *p_filter, float initial_range_m,
                    float initial_azimuth_rad, float initial_vx_mps, float initial_vy_mps,
                    float initial_turn_rate_radps, const struct matrix *p_initial_covariance)
{
    ASSERT_INIT(p_filter, initial_range_m, initial_azimuth_rad, initial_vx_mps, initial_vy_mps,
                initial_turn_rate_radps, p_initial_covariance);
    const bool invalid_inputs = p_filter == NULL || !isfinite(initial_range_m) || initial_range_m <= 0.0f ||
        !isfinite(initial_azimuth_rad) || !isfinite(initial_vx_mps) || !isfinite(initial_vy_mps) ||
        !isfinite(initial_turn_rate_radps) || !covariance_valid(p_initial_covariance);
    if (invalid_inputs) {
        return;
    }
    p_filter->x_m = initial_range_m * sinf(initial_azimuth_rad);
    p_filter->y_m = initial_range_m * cosf(initial_azimuth_rad);
    p_filter->vx_mps = initial_vx_mps;
    p_filter->vy_mps = initial_vy_mps;
    p_filter->turn_rate_radps = initial_turn_rate_radps;
    p_filter->covariance = *p_initial_covariance;
}

void ekf_ct_2d_predict(struct ekf_ct_2d_filter *p_filter, float interval_s,
                       float acceleration_variance, float angular_acceleration_variance)
{
    ASSERT_PREDICT(p_filter, interval_s, acceleration_variance, angular_acceleration_variance);
    const bool invalid_inputs = !filter_valid(p_filter) || !isfinite(interval_s) || interval_s <= 0.0f ||
        !isfinite(acceleration_variance) || acceleration_variance < 0.0f ||
        !isfinite(angular_acceleration_variance) || angular_acceleration_variance < 0.0f;
    if (invalid_inputs) {
        return;
    }
    struct ekf_ct_2d_filter predicted = *p_filter;
    struct matrix transition = {.rows = EKF_CT_2D_STATE_DIM, .columns = EKF_CT_2D_STATE_DIM};
    struct matrix product = {.rows = EKF_CT_2D_STATE_DIM, .columns = EKF_CT_2D_STATE_DIM};
    motion_jacobian(p_filter, interval_s, &predicted, &transition);
    const bool product_calculated = matrix_multiply(&transition, &p_filter->covariance, &product);
    if (!product_calculated) {
        return;
    }
    // Multiply by F^T directly, avoiding another full matrix on the MCU stack.
    for (size_t row = 0; row < EKF_CT_2D_STATE_DIM; ++row) {
        for (size_t column = 0; column < EKF_CT_2D_STATE_DIM; ++column) {
            float value = 0.0f;
            for (size_t k = 0; k < EKF_CT_2D_STATE_DIM; ++k) {
                value += matrix_get(&product, row, k) * matrix_get(&transition, column, k);
            }
            matrix_set(&predicted.covariance, row, column, value);
        }
    }
    // G=[(.5dt^2,0,dt,0,0), (0,.5dt^2,0,dt,0), (0,0,0,0,dt)].
    // Angular acceleration perturbs next-step omega; it is not integrated within this arc.
    const float dt_squared = interval_s * interval_s;
    const float velocity_variance = acceleration_variance * dt_squared;
    const float cross_variance = velocity_variance * interval_s / 2.0f;
    const float position_variance = velocity_variance * dt_squared / 4.0f;
    for (size_t axis = 0; axis < 2; ++axis) {
        matrix_set(&predicted.covariance, axis, axis,
                    matrix_get(&predicted.covariance, axis, axis) + position_variance);
        matrix_set(&predicted.covariance, axis, axis + 2,
                    matrix_get(&predicted.covariance, axis, axis + 2) + cross_variance);
        matrix_set(&predicted.covariance, axis + 2, axis,
                    matrix_get(&predicted.covariance, axis + 2, axis) + cross_variance);
        matrix_set(&predicted.covariance, axis + 2, axis + 2,
                    matrix_get(&predicted.covariance, axis + 2, axis + 2) + velocity_variance);
    }
    matrix_set(&predicted.covariance, CT_TURN_INDEX, CT_TURN_INDEX,
                matrix_get(&predicted.covariance, CT_TURN_INDEX, CT_TURN_INDEX) +
                angular_acceleration_variance * dt_squared);
    const bool prediction_valid = finish_covariance(&predicted.covariance) && filter_valid(&predicted);
    if (prediction_valid) {
        *p_filter = predicted;
    }
}

void ekf_ct_2d_correct(struct ekf_ct_2d_filter *p_filter, float measured_range_m,
                       float measured_azimuth_rad, float range_measurement_variance,
                       float azimuth_measurement_variance)
{
    ASSERT_CORRECT(p_filter, measured_range_m, measured_azimuth_rad,
                   range_measurement_variance, azimuth_measurement_variance);
    const bool invalid_inputs = !filter_valid(p_filter) || !isfinite(measured_range_m) || measured_range_m <= 0.0f ||
        !isfinite(measured_azimuth_rad) || !isfinite(range_measurement_variance) ||
        range_measurement_variance <= 0.0f || !isfinite(azimuth_measurement_variance) ||
        azimuth_measurement_variance <= 0.0f;
    if (invalid_inputs) {
        return;
    }
    const float radius = hypotf(p_filter->x_m, p_filter->y_m);
    const bool radius_valid = isfinite(radius) && radius >= 1e-3f;
    if (!radius_valid) {
        return;
    }
    const float direction_x = p_filter->x_m / radius;
    const float direction_y = p_filter->y_m / radius;
    // Remaining H columns are zero: radar directly observes only position.
    const float observation[CT_MEASUREMENT_DIM][2] = {
        {direction_x, direction_y}, {direction_y / radius, -direction_x / radius},
    };
    float gain[EKF_CT_2D_STATE_DIM][CT_MEASUREMENT_DIM];
    const bool gain_calculated = calculate_gain(&p_filter->covariance, observation, range_measurement_variance,
                                                azimuth_measurement_variance, gain);
    if (!gain_calculated) {
        return;
    }
    const float range_residual = measured_range_m - radius;
    const float angle_residual = angle_diff_rad(measured_azimuth_rad, atan2f(p_filter->x_m, p_filter->y_m));
    struct ekf_ct_2d_filter corrected = *p_filter;
    corrected.x_m += gain[0][0] * range_residual + gain[0][1] * angle_residual;
    corrected.y_m += gain[1][0] * range_residual + gain[1][1] * angle_residual;
    corrected.vx_mps += gain[2][0] * range_residual + gain[2][1] * angle_residual;
    corrected.vy_mps += gain[3][0] * range_residual + gain[3][1] * angle_residual;
    corrected.turn_rate_radps += gain[CT_TURN_INDEX][0] * range_residual + gain[CT_TURN_INDEX][1] * angle_residual;
    const bool correction_valid = correct_covariance(&p_filter->covariance, observation, gain, range_measurement_variance,
                            azimuth_measurement_variance, &corrected.covariance) && filter_valid(&corrected);
    if (correction_valid) {
        *p_filter = corrected;
    }
}

static void motion_jacobian(const struct ekf_ct_2d_filter *p_filter, float interval_s,
                            struct ekf_ct_2d_filter *out_predicted, struct matrix *out_transition)
{
    const float angle = p_filter->turn_rate_radps * interval_s;
    const float sine = sinf(angle);
    const float cosine = cosf(angle);
    float straight, cross, straight_derivative, cross_derivative;
    const float absolute_angle = fabsf(angle);
    if (absolute_angle < CT_SERIES_ANGLE_RAD) {
        const float squared = angle * angle;
        // sinc(a), (1-cos(a))/a, and their a derivatives; continuous at a=0.
        straight = 1.0f + squared * (-1.0f / 6.0f + squared / 120.0f);
        cross = angle * (0.5f + squared * (-1.0f / 24.0f + squared / 720.0f));
        straight_derivative = angle * (-1.0f / 3.0f + squared * (1.0f / 30.0f - squared / 840.0f));
        cross_derivative = 0.5f + squared * (-1.0f / 8.0f + squared / 144.0f);
    } else {
        straight = sine / angle;
        // Half-angle form avoids cancellation in 1-cos(a).
        const float half_sine = sinf(angle / 2.0f);
        cross = 2.0f * half_sine * half_sine / angle;
        straight_derivative = (cosine - straight) / angle;
        cross_derivative = (sine - cross) / angle;
    }
    const float a = interval_s * straight;
    const float b = interval_s * cross;
    const float da = interval_s * interval_s * straight_derivative;
    const float db = interval_s * interval_s * cross_derivative;
    const float vx = p_filter->vx_mps;
    const float vy = p_filter->vy_mps;
    out_predicted->x_m += a * vx + b * vy;
    out_predicted->y_m += -b * vx + a * vy;
    out_predicted->vx_mps = cosine * vx + sine * vy;
    out_predicted->vy_mps = -sine * vx + cosine * vy;
    for (size_t index = 0; index < EKF_CT_2D_STATE_DIM; ++index) {
        matrix_set(out_transition, index, index, 1.0f);
    }
    matrix_set(out_transition, 0, 2, a);
    matrix_set(out_transition, 0, 3, b);
    matrix_set(out_transition, 1, 2, -b);
    matrix_set(out_transition, 1, 3, a);
    matrix_set(out_transition, 0, CT_TURN_INDEX, da * vx + db * vy);
    matrix_set(out_transition, 1, CT_TURN_INDEX, -db * vx + da * vy);
    matrix_set(out_transition, 2, 2, cosine);
    matrix_set(out_transition, 2, 3, sine);
    matrix_set(out_transition, 3, 2, -sine);
    matrix_set(out_transition, 3, 3, cosine);
    matrix_set(out_transition, 2, CT_TURN_INDEX, interval_s * (-sine * vx + cosine * vy));
    matrix_set(out_transition, 3, CT_TURN_INDEX, interval_s * (-cosine * vx - sine * vy));
}

static bool calculate_gain(const struct matrix *p_covariance, const float p_observation[CT_MEASUREMENT_DIM][2],
                            float range_variance, float azimuth_variance,
                            float out_gain[EKF_CT_2D_STATE_DIM][CT_MEASUREMENT_DIM])
{
    float cross[EKF_CT_2D_STATE_DIM][CT_MEASUREMENT_DIM];
    for (size_t row = 0; row < EKF_CT_2D_STATE_DIM; ++row) {
        for (size_t column = 0; column < CT_MEASUREMENT_DIM; ++column) {
            cross[row][column] = matrix_get(p_covariance, row, 0) * p_observation[column][0] +
                                  matrix_get(p_covariance, row, 1) * p_observation[column][1];
        }
    }
    const float s00 = p_observation[0][0] * cross[0][0] + p_observation[0][1] * cross[1][0] + range_variance;
    const float s11 = p_observation[1][0] * cross[0][1] + p_observation[1][1] * cross[1][1] + azimuth_variance;
    const float s01 = 0.5f * (p_observation[0][0] * cross[0][1] + p_observation[0][1] * cross[1][1]) +
                      0.5f * (p_observation[1][0] * cross[0][0] + p_observation[1][1] * cross[1][0]);
    const bool innovation_valid = isfinite(s00) && isfinite(s11) && s00 > 0.0f && s11 > 0.0f;
    if (!innovation_valid) {
        return false;
    }
    const float range_scale = sqrtf(s00);
    const float angle_scale = sqrtf(s11);
    const float correlation = s01 / range_scale / angle_scale;
    const float remainder = 1.0f - correlation * correlation;
    const bool remainder_valid = isfinite(remainder) && remainder > 16.0f * FLT_EPSILON;
    if (!remainder_valid) {
        return false;
    }
    const float diagonal = sqrtf(remainder);
    for (size_t row = 0; row < EKF_CT_2D_STATE_DIM; ++row) {
        const float u0 = cross[row][0] / range_scale;
        const float u1 = (cross[row][1] / angle_scale - correlation * u0) / diagonal;
        const float y1 = u1 / diagonal;
        out_gain[row][0] = (u0 - correlation * y1) / range_scale;
        out_gain[row][1] = y1 / angle_scale;
        const bool gain_finite = isfinite(out_gain[row][0]) && isfinite(out_gain[row][1]);
        if (!gain_finite) {
            return false;
        }
    }
    return true;
}

static bool correct_covariance(const struct matrix *p_prior, const float p_observation[CT_MEASUREMENT_DIM][2],
                                const float p_gain[EKF_CT_2D_STATE_DIM][CT_MEASUREMENT_DIM],
                                float range_variance, float azimuth_variance, struct matrix *out_covariance)
{
    struct matrix attenuation = {.rows = EKF_CT_2D_STATE_DIM, .columns = EKF_CT_2D_STATE_DIM};
    struct matrix product = {.rows = EKF_CT_2D_STATE_DIM, .columns = EKF_CT_2D_STATE_DIM};
    for (size_t row = 0; row < EKF_CT_2D_STATE_DIM; ++row) {
        matrix_set(&attenuation, row, row, 1.0f);
        for (size_t column = 0; column < 2; ++column) {
            matrix_set(&attenuation, row, column, (row == column ? 1.0f : 0.0f) -
                        p_gain[row][0] * p_observation[0][column] - p_gain[row][1] * p_observation[1][column]);
        }
    }
    const bool product_calculated = matrix_multiply(&attenuation, p_prior, &product);
    if (!product_calculated) {
        return false;
    }
    for (size_t row = 0; row < EKF_CT_2D_STATE_DIM; ++row) {
        for (size_t column = 0; column < EKF_CT_2D_STATE_DIM; ++column) {
            float value = 0.0f;
            for (size_t k = 0; k < EKF_CT_2D_STATE_DIM; ++k) {
                value += matrix_get(&product, row, k) * matrix_get(&attenuation, column, k);
            }
            value += p_gain[row][0] * range_variance * p_gain[column][0] +
                      p_gain[row][1] * azimuth_variance * p_gain[column][1];
            matrix_set(out_covariance, row, column, value);
        }
    }
    return finish_covariance(out_covariance);
}

static bool covariance_valid(const struct matrix *p_covariance)
{
    if (p_covariance == NULL || p_covariance->rows != EKF_CT_2D_STATE_DIM ||
        p_covariance->columns != EKF_CT_2D_STATE_DIM) {
        return false;
    }
    for (size_t row = 0; row < EKF_CT_2D_STATE_DIM; ++row) {
        for (size_t column = 0; column < EKF_CT_2D_STATE_DIM; ++column) {
            const float value = matrix_get(p_covariance, row, column);
            const bool value_valid = isfinite(value) && !(row == column && value < 0.0f);
            if (!value_valid) {
                return false;
            }
        }
    }
    return true;
}

static bool filter_valid(const struct ekf_ct_2d_filter *p_filter)
{
    return p_filter != NULL && isfinite(p_filter->x_m) && isfinite(p_filter->y_m) &&
            isfinite(p_filter->vx_mps) && isfinite(p_filter->vy_mps) && isfinite(p_filter->turn_rate_radps) &&
            covariance_valid(&p_filter->covariance);
}

static bool finish_covariance(struct matrix *p_covariance)
{
    const bool prior_valid = covariance_valid(p_covariance);
    if (!prior_valid) {
        return false;
    }
    for (size_t row = 0; row < EKF_CT_2D_STATE_DIM; ++row) {
        for (size_t column = row + 1; column < EKF_CT_2D_STATE_DIM; ++column) {
            const float average = 0.5f * matrix_get(p_covariance, row, column) +
                                   0.5f * matrix_get(p_covariance, column, row);
            matrix_set(p_covariance, row, column, average);
            matrix_set(p_covariance, column, row, average);
        }
    }
    return true;
}

#if __ASSERT_ON
static void assert_init_inputs(const struct ekf_ct_2d_filter *p_filter, float range_m, float azimuth_rad,
                                float vx_mps, float vy_mps, float turn_rate_radps, const struct matrix *p_covariance)
{
    __ASSERT(p_filter != NULL, "Filter pointer is NULL");
    __ASSERT(isfinite(range_m) && range_m > 0.0f, "Initial range must be finite and positive");
    __ASSERT(isfinite(azimuth_rad) && isfinite(vx_mps) && isfinite(vy_mps) && isfinite(turn_rate_radps),
              "Initial state must be finite");
    __ASSERT(covariance_valid(p_covariance), "Initial covariance must be finite 5x5 with nonnegative diagonal");
}

static void assert_predict_inputs(const struct ekf_ct_2d_filter *p_filter, float interval_s,
                                   float acceleration_variance, float angular_acceleration_variance)
{
    __ASSERT(p_filter != NULL, "Filter pointer is NULL");
    __ASSERT(isfinite(interval_s) && interval_s >= 0.0f, "Prediction interval must be finite and nonnegative");
    __ASSERT(isfinite(acceleration_variance) && acceleration_variance >= 0.0f,
              "Acceleration variance must be finite and nonnegative");
    __ASSERT(isfinite(angular_acceleration_variance) && angular_acceleration_variance >= 0.0f,
              "Angular acceleration variance must be finite and nonnegative");
}

static void assert_correct_inputs(const struct ekf_ct_2d_filter *p_filter, float range_m, float azimuth_rad,
                                   float range_variance, float azimuth_variance)
{
    __ASSERT(p_filter != NULL, "Filter pointer is NULL");
    __ASSERT(isfinite(range_m) && range_m > 0.0f && isfinite(azimuth_rad), "Measurement must be finite with positive range");
    __ASSERT(isfinite(range_variance) && range_variance > 0.0f, "Range variance must be finite and positive");
    __ASSERT(isfinite(azimuth_variance) && azimuth_variance > 0.0f, "Azimuth variance must be finite and positive");
}
#endif
