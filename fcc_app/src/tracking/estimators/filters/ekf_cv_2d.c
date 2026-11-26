#include "tracking/estimators/filters/ekf_cv_2d.h"

#include <float.h>
#include <math.h>
#include <stddef.h>

#include <zephyr/sys/__assert.h>

#include "common/matrix.h"
#include "tracking/angle_utils.h"

// Input contract checks are compiled only when Zephyr assertions are enabled.
#if __ASSERT_ON
static void assert_init_inputs(struct ekf_cv_2d_filter *p_filter, float initial_range_m, float initial_azimuth_rad,
                               float initial_vx_mps, float initial_vy_mps,
                               const struct matrix *p_initial_covariance);
static void assert_predict_inputs(const struct ekf_cv_2d_filter *p_filter, float interval_s,
                                  float process_noise_variance);
static void assert_correct_inputs(const struct ekf_cv_2d_filter *p_filter, float measured_range_m,
                                  float measured_azimuth_rad, float range_measurement_noise_variance,
                                  float azimuth_measurement_noise_variance);

#define ASSERT_INIT_INPUTS(...) assert_init_inputs(__VA_ARGS__)
#define ASSERT_PREDICT_INPUTS(...) assert_predict_inputs(__VA_ARGS__)
#define ASSERT_CORRECT_INPUTS(...) assert_correct_inputs(__VA_ARGS__)
#else
#define ASSERT_INIT_INPUTS(...) ((void)0)
#define ASSERT_PREDICT_INPUTS(...) ((void)0)
#define ASSERT_CORRECT_INPUTS(...) ((void)0)
#endif

static bool calculate_gain(const struct matrix *p_covariance_measurement,
                           const struct matrix *p_innovation_covariance, struct matrix *out_gain);

void ekf_cv_2d_init(
    struct ekf_cv_2d_filter *p_filter,
    float initial_range_m,
    float initial_azimuth_rad,
    float initial_vx_mps,
    float initial_vy_mps,
    const struct matrix *p_initial_covariance)
{
    ASSERT_INIT_INPUTS(p_filter, initial_range_m, initial_azimuth_rad,
                       initial_vx_mps, initial_vy_mps, p_initial_covariance);

    p_filter->x_m = initial_range_m * sinf(initial_azimuth_rad);
    p_filter->y_m = initial_range_m * cosf(initial_azimuth_rad);
    p_filter->vx_mps = initial_vx_mps;
    p_filter->vy_mps = initial_vy_mps;

    p_filter->covariance = *p_initial_covariance;
}

void ekf_cv_2d_predict(
    struct ekf_cv_2d_filter *p_filter,
    float interval_s,
    float process_noise_variance)
{
    ASSERT_PREDICT_INPUTS(p_filter, interval_s, process_noise_variance);

    if (interval_s == 0.0f) {
        return;
    }

    const struct matrix *covariance = &p_filter->covariance;
    const bool dimensions_valid = covariance->rows == EKF_CV_2D_STATE_DIM &&
                                  covariance->columns == EKF_CV_2D_STATE_DIM;
    __ASSERT(dimensions_valid, "Invalid prediction matrix dimensions");
    if (!dimensions_valid) {
        return;
    }

    // State order: [x, y, vx, vy]. F adds dt times each velocity row to its position row.
    // F^T makes the same additions to columns. Keep the two products in that order.
    const float *prior = covariance->data;
    float product[EKF_CV_2D_STATE_DIM * EKF_CV_2D_STATE_DIM];
    for (size_t column = 0; column < EKF_CV_2D_STATE_DIM; ++column) {
        product[column] = prior[column] + interval_s * prior[8 + column];
        product[4 + column] = prior[4 + column] + interval_s * prior[12 + column];
        product[8 + column] = prior[8 + column];
        product[12 + column] = prior[12 + column];
    }

    struct matrix predicted_covariance = {.rows = EKF_CV_2D_STATE_DIM, .columns = EKF_CV_2D_STATE_DIM};
    for (size_t row = 0; row < EKF_CV_2D_STATE_DIM; ++row) {
        const float *product_row = &product[row * EKF_CV_2D_STATE_DIM];
        float *predicted_row = &predicted_covariance.data[row * EKF_CV_2D_STATE_DIM];
        predicted_row[0] = product_row[0] + product_row[2] * interval_s;
        predicted_row[1] = product_row[1] + product_row[3] * interval_s;
        predicted_row[2] = product_row[2];
        predicted_row[3] = product_row[3];
    }

    // Q: independent x/y accelerations with equal variance, constant over dt.
    // Each [position, velocity] block is q * [[dt^4/4, dt^3/2], [dt^3/2, dt^2]].
    const float dt_squared = interval_s * interval_s;
    const float velocity_variance = process_noise_variance * dt_squared;
    const float position_velocity_covariance = velocity_variance * interval_s / 2.0f;
    const float position_variance = velocity_variance * dt_squared / 4.0f;
    for (size_t axis = 0; axis < 2; ++axis) {
        matrix_set(&predicted_covariance, axis, axis,
                   matrix_get(&predicted_covariance, axis, axis) + position_variance);
        matrix_set(&predicted_covariance, axis, axis + 2,
                   matrix_get(&predicted_covariance, axis, axis + 2) + position_velocity_covariance);
        matrix_set(&predicted_covariance, axis + 2, axis,
                   matrix_get(&predicted_covariance, axis + 2, axis) + position_velocity_covariance);
        matrix_set(&predicted_covariance, axis + 2, axis + 2,
                   matrix_get(&predicted_covariance, axis + 2, axis + 2) + velocity_variance);
    }

    p_filter->x_m += p_filter->vx_mps * interval_s;
    p_filter->y_m += p_filter->vy_mps * interval_s;
    p_filter->covariance = predicted_covariance;
}

void ekf_cv_2d_correct(
    struct ekf_cv_2d_filter *p_filter,
    float measured_range_m,
    float measured_azimuth_rad,
    float range_measurement_noise_variance,
    float azimuth_measurement_noise_variance)
{
    ASSERT_CORRECT_INPUTS(p_filter, measured_range_m, measured_azimuth_rad,
                          range_measurement_noise_variance, azimuth_measurement_noise_variance);

    // Linearize polar measurements at the predicted Cartesian position.
    // Below 1 mm the azimuth Jacobian is not useful; preserve the prior state.
    const float predicted_range_m = hypotf(p_filter->x_m, p_filter->y_m);
    const bool prior_valid = isfinite(predicted_range_m) && predicted_range_m >= 1e-3f &&
                             isfinite(p_filter->vx_mps) && isfinite(p_filter->vy_mps) &&
                             p_filter->covariance.rows == EKF_CV_2D_STATE_DIM &&
                             p_filter->covariance.columns == EKF_CV_2D_STATE_DIM;
    if (!prior_valid) {
        return;
    }
    for (size_t row = 0; row < EKF_CV_2D_STATE_DIM; ++row) {
        for (size_t column = 0; column < EKF_CV_2D_STATE_DIM; ++column) {
            const bool entry_finite = isfinite(matrix_get(&p_filter->covariance, row, column));
            if (!entry_finite) {
                return;
            }
        }
    }
    const float direction_x = p_filter->x_m / predicted_range_m;
    const float direction_y = p_filter->y_m / predicted_range_m;
    const float range_residual_m = measured_range_m - predicted_range_m;
    const float azimuth_residual_rad = angle_diff_rad(measured_azimuth_rad,
                                                atan2f(p_filter->x_m, p_filter->y_m));
    // H has two position columns. Both velocity columns are zero.
    const float jacobian[2][2] = {
        {direction_x, direction_y},
        {direction_y / predicted_range_m, -direction_x / predicted_range_m},
    };
    const struct matrix *prior = &p_filter->covariance;
    struct matrix covariance_measurement = {.rows = EKF_CV_2D_STATE_DIM, .columns = 2};
    struct matrix innovation_covariance = {.rows = 2, .columns = 2};
    struct matrix gain = {.rows = EKF_CV_2D_STATE_DIM, .columns = 2};

    // S = H P H^T + R, with independent range/azimuth measurement noise.
    for (size_t row = 0; row < EKF_CV_2D_STATE_DIM; ++row) {
        const float covariance_x = matrix_get(prior, row, 0);
        const float covariance_y = matrix_get(prior, row, 1);
        for (size_t measurement = 0; measurement < 2; ++measurement) {
            matrix_set(&covariance_measurement, row, measurement,
                       covariance_x * jacobian[measurement][0] + covariance_y * jacobian[measurement][1]);
        }
    }
    for (size_t row = 0; row < 2; ++row) {
        for (size_t column = 0; column < 2; ++column) {
            matrix_set(&innovation_covariance, row, column,
                       jacobian[row][0] * matrix_get(&covariance_measurement, 0, column) +
                       jacobian[row][1] * matrix_get(&covariance_measurement, 1, column));
        }
    }
    matrix_set(&innovation_covariance, 0, 0, matrix_get(&innovation_covariance, 0, 0) + range_measurement_noise_variance);
    matrix_set(&innovation_covariance, 1, 1, matrix_get(&innovation_covariance, 1, 1) + azimuth_measurement_noise_variance);
    // Solve K S = P H^T without explicitly forming an inverse.
    const bool gain_computed = calculate_gain(&covariance_measurement, &innovation_covariance, &gain);
    if (!gain_computed) {
        return;
    }

    struct ekf_cv_2d_filter corrected = *p_filter;
    corrected.x_m += matrix_get(&gain, 0, 0) * range_residual_m + matrix_get(&gain, 0, 1) * azimuth_residual_rad;
    corrected.y_m += matrix_get(&gain, 1, 0) * range_residual_m + matrix_get(&gain, 1, 1) * azimuth_residual_rad;
    corrected.vx_mps += matrix_get(&gain, 2, 0) * range_residual_m + matrix_get(&gain, 2, 1) * azimuth_residual_rad;
    corrected.vy_mps += matrix_get(&gain, 3, 0) * range_residual_m + matrix_get(&gain, 3, 1) * azimuth_residual_rad;
    const bool corrected_finite = isfinite(corrected.x_m) && isfinite(corrected.y_m) &&
                                  isfinite(corrected.vx_mps) && isfinite(corrected.vy_mps);
    if (!corrected_finite) {
        return;
    }

    // Joseph covariance update: P+ = A P A^T + K R K^T, A = I - K H.
    // A's velocity columns remain the corresponding identity columns.
    float attenuation[EKF_CV_2D_STATE_DIM][2];
    float product[EKF_CV_2D_STATE_DIM][EKF_CV_2D_STATE_DIM];
    for (size_t row = 0; row < EKF_CV_2D_STATE_DIM; ++row) {
        const float range_gain = matrix_get(&gain, row, 0);
        const float azimuth_gain = matrix_get(&gain, row, 1);
        for (size_t column = 0; column < 2; ++column) {
            const float identity = row == column ? 1.0f : 0.0f;
            const float gain_jacobian = range_gain * jacobian[0][column] + azimuth_gain * jacobian[1][column];
            attenuation[row][column] = identity - gain_jacobian;
        }
        for (size_t column = 0; column < EKF_CV_2D_STATE_DIM; ++column) {
            float value = attenuation[row][0] * matrix_get(prior, 0, column) +
                          attenuation[row][1] * matrix_get(prior, 1, column);
            if (row >= 2) {
                value += matrix_get(prior, row, column);
            }
            product[row][column] = value;
        }
    }
    for (size_t row = 0; row < EKF_CV_2D_STATE_DIM; ++row) {
        for (size_t column = 0; column < EKF_CV_2D_STATE_DIM; ++column) {
            float covariance = product[row][0] * attenuation[column][0] +
                               product[row][1] * attenuation[column][1];
            if (column >= 2) {
                covariance += product[row][column];
            }
            // Diagonal R makes K R K^T a sum of two weighted outer products.
            const float noise = matrix_get(&gain, row, 0) * range_measurement_noise_variance * matrix_get(&gain, column, 0) +
                                matrix_get(&gain, row, 1) * azimuth_measurement_noise_variance * matrix_get(&gain, column, 1);
            const float value = covariance + noise;
            const bool entry_valid = isfinite(value) && (row != column || value >= 0.0f);
            if (!entry_valid) {
                return;
            }
            matrix_set(&corrected.covariance, row, column, value);
        }
    }
    // Remove roundoff asymmetry; this is not a repair for an invalid prior P.
    for (size_t row = 0; row < EKF_CV_2D_STATE_DIM; ++row) {
        for (size_t column = row + 1; column < EKF_CV_2D_STATE_DIM; ++column) {
            const float value = 0.5f * matrix_get(&corrected.covariance, row, column) +
                                0.5f * matrix_get(&corrected.covariance, column, row);
            matrix_set(&corrected.covariance, row, column, value);
            matrix_set(&corrected.covariance, column, row, value);
        }
    }
    *p_filter = corrected;
}

// S is 2x2; P H^T and K are 4x2. Scale out the different range/angle units,
// then use a 2x2 Cholesky solve for each row of K. Reject near-singular systems.
static bool calculate_gain(const struct matrix *p_covariance_measurement,
                           const struct matrix *p_innovation_covariance, struct matrix *out_gain)
{
    const float range_variance = matrix_get(p_innovation_covariance, 0, 0);
    const float angle_variance = matrix_get(p_innovation_covariance, 1, 1);
    const bool variances_valid = isfinite(range_variance) && range_variance > 0.0f &&
                                 isfinite(angle_variance) && angle_variance > 0.0f;
    if (!variances_valid) {
        return false;
    }
    const float range_scale = sqrtf(range_variance);
    const float angle_scale = sqrtf(angle_variance);
    const float cross = 0.5f * matrix_get(p_innovation_covariance, 0, 1) + 0.5f * matrix_get(p_innovation_covariance, 1, 0);
    const float correlation = cross / range_scale / angle_scale;
    const float remainder = 1.0f - correlation * correlation;
    const bool remainder_valid = isfinite(remainder) && remainder > 16.0f * FLT_EPSILON;
    if (!remainder_valid) {
        return false;
    }
    const float diagonal = sqrtf(remainder);
    for (size_t row = 0; row < EKF_CV_2D_STATE_DIM; ++row) {
        // Forward solve L u = D^-1 b, then backward solve L^T y = u.
        const float u0 = matrix_get(p_covariance_measurement, row, 0) / range_scale;
        const float u1 = (matrix_get(p_covariance_measurement, row, 1) / angle_scale - correlation * u0) / diagonal;
        const float y1 = u1 / diagonal;
        const float y0 = u0 - correlation * y1;
        const float k0 = y0 / range_scale;
        const float k1 = y1 / angle_scale;
        const bool gain_finite = isfinite(k0) && isfinite(k1);
        if (!gain_finite) {
            return false;
        }
        matrix_set(out_gain, row, 0, k0);
        matrix_set(out_gain, row, 1, k1);
    }
    return true;
}

#if __ASSERT_ON
static void assert_init_inputs(struct ekf_cv_2d_filter *p_filter, float initial_range_m, float initial_azimuth_rad,
                               float initial_vx_mps, float initial_vy_mps,
                               const struct matrix *p_initial_covariance)
{
    __ASSERT(p_filter != NULL, "Filter pointer is NULL");
    __ASSERT(isfinite(initial_range_m) && initial_range_m > 0.0f,
             "Initial range must be finite and positive: %f", (double)initial_range_m);
    __ASSERT(isfinite(initial_azimuth_rad), "Initial azimuth must be finite");
    __ASSERT(isfinite(initial_vx_mps), "Initial x velocity must be finite");
    __ASSERT(isfinite(initial_vy_mps), "Initial y velocity must be finite");
    __ASSERT(p_initial_covariance != NULL, "Initial covariance pointer is NULL");
    __ASSERT(p_initial_covariance->rows == EKF_CV_2D_STATE_DIM &&
             p_initial_covariance->columns == EKF_CV_2D_STATE_DIM,
             "Initial covariance must be 4x4");

    for (size_t row = 0; row < EKF_CV_2D_STATE_DIM; ++row) {
        for (size_t column = 0; column < EKF_CV_2D_STATE_DIM; ++column) {
            __ASSERT(isfinite(matrix_get(p_initial_covariance, row, column)),
                     "Initial covariance element must be finite");
        }
        __ASSERT(matrix_get(p_initial_covariance, row, row) >= 0.0f,
                 "Initial covariance diagonal must be nonnegative");
    }
}

static void assert_predict_inputs(const struct ekf_cv_2d_filter *p_filter, float interval_s,
                                  float process_noise_variance)
{
    __ASSERT(p_filter != NULL, "Filter pointer is NULL");
    __ASSERT(isfinite(interval_s) && interval_s >= 0.0f,
             "Prediction interval must be finite and nonnegative: %f", (double)interval_s);
    __ASSERT(isfinite(process_noise_variance) && process_noise_variance >= 0.0f,
             "Acceleration noise variance must be finite and nonnegative: %f",
             (double)process_noise_variance);
}

static void assert_correct_inputs(const struct ekf_cv_2d_filter *p_filter, float measured_range_m,
                                  float measured_azimuth_rad, float range_measurement_noise_variance,
                                  float azimuth_measurement_noise_variance)
{
    __ASSERT(p_filter != NULL, "Filter pointer is NULL");
    __ASSERT(isfinite(measured_range_m) && measured_range_m > 0.0f,
             "Measured range must be finite and positive: %f", (double)measured_range_m);
    __ASSERT(isfinite(measured_azimuth_rad), "Measured azimuth must be finite");
    __ASSERT(isfinite(range_measurement_noise_variance) && range_measurement_noise_variance > 0.0f,
             "Range measurement variance must be finite and positive: %f",
             (double)range_measurement_noise_variance);
    __ASSERT(isfinite(azimuth_measurement_noise_variance) && azimuth_measurement_noise_variance > 0.0f,
             "Azimuth measurement variance must be finite and positive: %f",
             (double)azimuth_measurement_noise_variance);
}
#endif
