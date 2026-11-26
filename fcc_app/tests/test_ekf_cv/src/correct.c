#include <assert.h>
#include <float.h>
#include <math.h>
#include <string.h>
#include "tracking/estimators/filters/ekf_cv_2d.h"
#include "common/math_constants.h"

static void near(float actual, float expected, float tolerance)
{
    assert(isfinite(actual));
    assert(fabsf(actual - expected) <= tolerance);
}

static struct ekf_cv_2d_filter initial_filter(void)
{
    const struct matrix p = {.rows = 4,
                             .columns = 4,
                             .data = {100, 0, 10, 0, 0, 100, 0, 20, 10, 0, 25, 0, 0, 20, 0, 36}};
    struct ekf_cv_2d_filter filter;
    ekf_cv_2d_init(&filter, 1000, 0, 0, 0, &p);
    return filter;
}

int main(void)
{
    // At north: H_range=[0,1,0,0], H_angle=[.001,0,0,0].
    struct ekf_cv_2d_filter filter = initial_filter();
    ekf_cv_2d_correct(&filter, 1010, 0, 100, 0.0001f);
    near(filter.x_m, 0, 1e-5f);
    near(filter.y_m, 1005, 1e-4f);
    near(filter.vx_mps, 0, 1e-5f);
    near(filter.vy_mps, 1, 1e-5f);
    near(matrix_get(&filter.covariance, 0, 0), 50, 1e-4f);
    near(matrix_get(&filter.covariance, 1, 1), 50, 1e-4f);
    near(matrix_get(&filter.covariance, 2, 2), 24.5f, 1e-4f);
    near(matrix_get(&filter.covariance, 3, 3), 34, 1e-4f);

    filter = initial_filter();
    ekf_cv_2d_correct(&filter, 1000, 0.01f, 100, 0.0001f);
    near(filter.x_m, 5, 1e-4f);
    near(filter.vx_mps, 0.5f, 1e-5f);
    near(filter.y_m, 1000, 1e-4f);

    // Oblique geometry and correlated P: independent double-precision oracle.
    filter = (struct ekf_cv_2d_filter){
        .x_m = 600,
        .y_m = 800,
        .vx_mps = 20,
        .vy_mps = -5,
        .covariance = {.rows = 4,
                       .columns = 4,
                       .data = {100, 30, 10, 4, 30, 144, 3, 12, 10, 3, 25, 1, 4, 12, 1, 36}}};
    ekf_cv_2d_correct(&filter, 1012, atan2f(600, 800) + 0.02f, 25, 0.0004f);
    near(filter.x_m, 608.4490165f, 0.0002f);
    near(filter.y_m, 806.5087045f, 0.0002f);
    near(filter.vx_mps, 20.84490165f, 0.0002f);
    near(filter.vy_mps, -4.344119376f, 0.0002f);
    const float expected_covariance[] = {51.74655211f,  -24.07867963f, 5.174655211f,  -1.098349537f,
                                         -24.07867963f, 40.69635994f,  -2.407867963f, 2.870449921f,
                                         5.174655211f,  -2.407867963f, 24.51746552f,  0.4901650463f,
                                         -1.098349537f, 2.870449921f,  0.4901650463f, 35.1880624f};
    for (int i = 0; i < 4; i++) {
        for (int j = 0; j < 4; j++) {
            near(matrix_get(&filter.covariance, i, j), expected_covariance[i * 4 + j], 0.0002f);
        }
    }

    // Wrap at south must use +.02 rad, not almost -2*pi.
    filter = initial_filter();
    filter.x_m = 1000 * sinf(MATH_PI_F - 0.01f);
    filter.y_m = 1000 * cosf(MATH_PI_F - 0.01f);
    ekf_cv_2d_correct(&filter, 1000, -MATH_PI_F + 0.01f, 100, 0.0001f);
    near(filter.x_m, 0, 0.003f);

    // Larger R must reduce the correction with otherwise identical inputs.
    struct ekf_cv_2d_filter low = initial_filter(), high = low;
    ekf_cv_2d_correct(&low, 1010, 0.01f, 1, 0.000001f);
    ekf_cv_2d_correct(&high, 1010, 0.01f, 10000, 0.01f);
    assert(fabsf(low.x_m) > fabsf(high.x_m));
    assert(fabsf(low.y_m - 1000) > fabsf(high.y_m - 1000));

    // Numerical failures must preserve the complete prior state.
    filter = initial_filter();
    filter.x_m = filter.y_m = 0;
    struct ekf_cv_2d_filter before = filter;
    ekf_cv_2d_correct(&filter, 1000, 0, 100, 0.0001f);
    assert(memcmp(&filter, &before, sizeof(filter)) == 0);
    filter = initial_filter();
    matrix_set(&filter.covariance, 0, 0, NAN);
    before = filter;
    ekf_cv_2d_correct(&filter, 1000, 0, 100, 0.0001f);
    assert(memcmp(&filter, &before, sizeof(filter)) == 0);
    filter = initial_filter();
    matrix_set(&filter.covariance, 0, 1, 200);
    matrix_set(&filter.covariance, 1, 0, 200);
    before = filter;
    ekf_cv_2d_correct(&filter, 1000, 0, 1, 0.000001f);
    assert(memcmp(&filter, &before, sizeof(filter)) == 0);

    // Origin cutoff boundary: below 1 mm skips; at 1 mm corrects.
    filter = initial_filter();
    filter.y_m = 0.000999f;
    before = filter;
    ekf_cv_2d_correct(&filter, 0.002f, 0, 100, 0.0001f);
    assert(memcmp(&filter, &before, sizeof(filter)) == 0);
    filter.y_m = 0.001f;
    ekf_cv_2d_correct(&filter, 0.002f, 0, 100, 0.0001f);
    near(filter.y_m, 0.0015f, 1e-8f);

    // Valid rank-one PSD P plus tiny positive R: normalized S is too close
    // to singular in float precision, so correction must be skipped atomically.
    filter = initial_filter();
    filter.covariance = (struct matrix){
        .rows = 4, .columns = 4, .data = {100, 100, 0, 0, 100, 100, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0}};
    before = filter;
    ekf_cv_2d_correct(&filter, 1010, 0.01f, 1e-12f, 1e-16f);
    assert(memcmp(&filter, &before, sizeof(filter)) == 0);

    // All inputs finite, but S overflows: preserve prior state.
    filter = initial_filter();
    matrix_set(&filter.covariance, 1, 1, FLT_MAX);
    before = filter;
    ekf_cv_2d_correct(&filter, 1010, 0, FLT_MAX, 0.0001f);
    assert(memcmp(&filter, &before, sizeof(filter)) == 0);

    // Repeated predictions/corrections: finite symmetric P and nonnegative
    // quadratic forms along a set of mixed position/velocity directions.
    filter = initial_filter();
    for (int step = 0; step < 500; step++) {
        ekf_cv_2d_predict(&filter, 0.1f, 3);
        const float x = 2.0f * step, y = 1000.0f + 0.5f * step;
        ekf_cv_2d_correct(&filter, hypotf(x, y), atan2f(x, y), 25, 0.0001f);
        for (int i = 0; i < 4; i++) {
            assert(matrix_get(&filter.covariance, i, i) >= 0);
            for (int j = 0; j < 4; j++) {
                near(matrix_get(&filter.covariance, i, j), matrix_get(&filter.covariance, j, i),
                     1e-5f);
            }
        }
        for (int direction = 0; direction < 16; direction++) {
            double quadratic = 0;
            for (int i = 0; i < 4; i++) {
                for (int j = 0; j < 4; j++) {
                    quadratic += ((direction >> i) & 1 ? 1.0 : -1.0) *
                                 matrix_get(&filter.covariance, i, j) *
                                 ((direction >> j) & 1 ? 1.0 : -1.0);
                }
            }
            assert(quadratic >= -1e-4);
        }
    }
    return 0;
}
