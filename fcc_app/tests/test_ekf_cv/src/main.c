#include <assert.h>
#include <math.h>
#include <string.h>
#include "tracking/estimators/filters/ekf_cv_2d.h"
#include "tracking/estimators/filters/kf_cv_1d.h"

static void near(float actual, float expected)
{
    assert(fabsf(actual - expected) <= 1e-5f * fmaxf(1.0f, fabsf(expected)));
}

int main(void)
{
    const struct matrix initial = {
        .rows = EKF_CV_2D_STATE_DIM,
        .columns = EKF_CV_2D_STATE_DIM,
        .data = {4, 1, 0.5f, 0.2f, 1, 9, 0.3f, 0.4f, 0.5f, 0.3f, 16, 2, 0.2f, 0.4f, 2, 25}};
    struct ekf_cv_2d_filter filter;
    ekf_cv_2d_init(&filter, 1000, 0, 20, -5, &initial);
    // A copied filter owns its P; modifying the copy must not affect its source.
    struct ekf_cv_2d_filter copied = filter;
    matrix_set(&copied.covariance, 0, 0, 999);
    assert(matrix_get(&filter.covariance, 0, 0) == 4);
    assert(matrix_get(&initial, 0, 0) == 4);
    const struct ekf_cv_2d_filter original = filter;
    ekf_cv_2d_predict(&filter, 0, 3);
    assert(memcmp(&filter, &original, sizeof(filter)) == 0);

    // Hand-calculated FPF^T + Q for dt=2, q=3; includes cross-axis terms.
    const float expected[4][4] = {
        {82, 10, 44.5f, 4.2f},
        {10, 122.6f, 4.3f, 62.4f},
        {44.5f, 4.3f, 28, 2},
        {4.2f, 62.4f, 2, 37},
    };
    ekf_cv_2d_predict(&filter, 2, 3);
    near(filter.x_m, 40);
    near(filter.y_m, 990);
    near(filter.vx_mps, 20);
    near(filter.vy_mps, -5);
    for (int row = 0; row < 4; row++) {
        for (int column = 0; column < 4; column++) {
            near(matrix_get(&filter.covariance, row, column), expected[row][column]);
        }
    }

    // With q=0 and deterministic state, prediction adds no uncertainty.
    const struct matrix zero = {.rows = EKF_CV_2D_STATE_DIM, .columns = EKF_CV_2D_STATE_DIM};
    ekf_cv_2d_init(&filter, 1000, 0, 20, -5, &zero);
    ekf_cv_2d_predict(&filter, 0.5f, 0);
    near(filter.x_m, 10);
    near(filter.y_m, 997.5f);
    for (int row = 0; row < 4; row++) {
        for (int column = 0; column < 4; column++) {
            assert(matrix_get(&filter.covariance, row, column) == 0);
        }
    }

    // Independent axes must match the existing 1D CV predictor over repeated steps.
    const struct matrix diagonal = {.rows = EKF_CV_2D_STATE_DIM,
                                    .columns = EKF_CV_2D_STATE_DIM,
                                    .data = {4, 0, 0, 0, 0, 9, 0, 0, 0, 0, 16, 0, 0, 0, 0, 25}};
    ekf_cv_2d_init(&filter, 1000, 0, 20, -5, &diagonal);
    struct kf_cv_1d_filter axes[2];
    kf_cv_1d_init(&axes[0], 0, 20,
                  &(const struct matrix){.rows = KF_CV_1D_STATE_DIM,
                                         .columns = KF_CV_1D_STATE_DIM,
                                         .data = {4, 0, 0, 16}},
                  3, 1);
    kf_cv_1d_init(&axes[1], 1000, -5,
                  &(const struct matrix){.rows = KF_CV_1D_STATE_DIM,
                                         .columns = KF_CV_1D_STATE_DIM,
                                         .data = {9, 0, 0, 25}},
                  3, 1);
    for (int step = 0; step < 50; step++) {
        const float dt = step % 2 ? 0.1f : 0.25f;
        ekf_cv_2d_predict(&filter, dt, 3);
        for (int axis = 0; axis < 2; axis++) {
            kf_cv_1d_predict(&axes[axis], dt);
            near(matrix_get(&filter.covariance, axis, axis),
                 matrix_get(&axes[axis].covariance, 0, 0));
            near(matrix_get(&filter.covariance, axis, axis + 2),
                 matrix_get(&axes[axis].covariance, 0, 1));
            near(matrix_get(&filter.covariance, axis + 2, axis),
                 matrix_get(&axes[axis].covariance, 1, 0));
            near(matrix_get(&filter.covariance, axis + 2, axis + 2),
                 matrix_get(&axes[axis].covariance, 1, 1));
        }
        near(filter.x_m, axes[0].estimate);
        near(filter.y_m, axes[1].estimate);
        assert(matrix_get(&filter.covariance, 0, 1) == 0 &&
               matrix_get(&filter.covariance, 2, 3) == 0);
    }
    return 0;
}
