#include "../../common/test_runner.h"

#include <assert.h>
#include <float.h>
#include <math.h>
#include <string.h>

#include "tracking/track.h"

static struct ekf_ct_2d_filter initial_filter(void)
{
    struct matrix initial = {.rows = EKF_CT_2D_STATE_DIM, .columns = EKF_CT_2D_STATE_DIM};
    for (size_t index = 0; index < EKF_CT_2D_STATE_DIM; ++index) {
        matrix_set(&initial, index, index, index == 4 ? 0.01f : 25.0f);
    }
    struct ekf_ct_2d_filter filter = {0};
    ekf_ct_2d_init(&filter, 1000.0f, 0.0f, 0.0f, 100.0f, 1.0f, &initial);
    return filter;
}

static void close_value(float actual, float expected)
{
    assert(isfinite(actual));
    assert(fabsf(actual - expected) <= fmaxf(0.0001f, fabsf(expected) * 0.00001f));
}

static void test_ownership(void)
{
    struct ekf_ct_2d_filter filter = initial_filter();
    struct matrix initial = filter.covariance;
    ekf_ct_2d_init(&filter, 1000.0f, 0.0f, 0.0f, 100.0f, 0.0f, &initial);
    matrix_set(&initial, 0, 0, 9876.0f);
    close_value(matrix_get(&filter.covariance, 0, 0), 25.0f);
    struct ekf_ct_2d_filter copy = filter;
    ekf_ct_2d_predict(&copy, 1.0f, 0.0f, 0.0f);
    close_value(filter.y_m, 1000.0f);
    close_value(copy.y_m, 1100.0f);
}

static void test_quarter_turn(void)
{
    struct ekf_ct_2d_filter filter = initial_filter();
    ekf_ct_2d_predict(&filter, 1.5707963267948966f, 0.0f, 0.0f);
    close_value(filter.x_m, 100.0f);
    close_value(filter.y_m, 1100.0f);
    close_value(filter.vx_mps, 100.0f);
    close_value(filter.vy_mps, 0.0f);
    filter = initial_filter();
    filter.turn_rate_radps = -1.0f;
    ekf_ct_2d_predict(&filter, 1.5707963267948966f, 0.0f, 0.0f);
    close_value(filter.x_m, -100.0f);
    close_value(filter.y_m, 1100.0f);
    close_value(filter.vx_mps, -100.0f);
}

static void test_noise(void)
{
    struct ekf_ct_2d_filter filter = initial_filter();
    filter.turn_rate_radps = 0.0f;
    memset(filter.covariance.data, 0, sizeof(filter.covariance.data));
    ekf_ct_2d_predict(&filter, 0.5f, 64.0f, 4.0f);
    for (size_t axis = 0; axis < 2; ++axis) {
        close_value(matrix_get(&filter.covariance, axis, axis), 1.0f);
        close_value(matrix_get(&filter.covariance, axis, axis + 2), 4.0f);
        close_value(matrix_get(&filter.covariance, axis + 2, axis + 2), 16.0f);
    }
    close_value(matrix_get(&filter.covariance, 4, 4), 1.0f);
}

static void test_zero_interval(void)
{
    struct ekf_ct_2d_filter filter = initial_filter();
    const struct ekf_ct_2d_filter before = filter;
    ekf_ct_2d_predict(&filter, 0.0f, 100.0f, 0.1f);
    assert(memcmp(&filter, &before, sizeof(filter)) == 0);
}

static void test_wrapped(void)
{
    struct ekf_ct_2d_filter filter = initial_filter();
    filter.x_m = 0.01f;
    filter.y_m = -1000.0f;
    ekf_ct_2d_correct(&filter, 1000.0f, -3.1415f, 25.0f, 0.00121847f);
    assert(fabsf(filter.x_m) < 1.0f && fabsf(filter.y_m + 1000.0f) < 1.0f);
}

static void test_numerical_failure(void)
{
    struct ekf_ct_2d_filter filter = initial_filter();
    filter.x_m = filter.y_m = 0.0f;
    struct ekf_ct_2d_filter before = filter;
    ekf_ct_2d_correct(&filter, 1.0f, 0.0f, 25.0f, 0.00121847f);
    assert(memcmp(&filter, &before, sizeof(filter)) == 0);
    filter = initial_filter();
    matrix_set(&filter.covariance, 0, 1, 1e20f);
    matrix_set(&filter.covariance, 1, 0, 1e20f);
    before = filter;
    ekf_ct_2d_correct(&filter, 1000.0f, 0.0f, 25.0f, 0.00121847f);
    assert(memcmp(&filter, &before, sizeof(filter)) == 0);
    filter = initial_filter();
    before = filter;
    ekf_ct_2d_predict(&filter, FLT_MAX, FLT_MAX, FLT_MAX);
    assert(memcmp(&filter, &before, sizeof(filter)) == 0);
    filter = initial_filter();
    filter.turn_rate_radps = NAN;
    before = filter;
    ekf_ct_2d_correct(&filter, 1000.0f, 0.0f, 25.0f, 0.00121847f);
    assert(memcmp(&filter, &before, sizeof(filter)) == 0);
}

static void test_malformed_covariance_dimensions(void)
{
    const size_t dimensions[][2] = {{0, 5}, {4, 5}, {5, 4}, {6, 5}, {5, 6}};
    for (size_t index = 0; index < sizeof(dimensions) / sizeof(dimensions[0]); ++index) {
        struct ekf_ct_2d_filter filter = initial_filter();
        filter.covariance.rows = dimensions[index][0];
        filter.covariance.columns = dimensions[index][1];
        const struct ekf_ct_2d_filter before = filter;
        ekf_ct_2d_predict(&filter, 0.1f, 100.0f, 0.0001f);
        assert(memcmp(&filter, &before, sizeof(filter)) == 0);
        ekf_ct_2d_correct(&filter, 1010.0f, 0.01f, 25.0f, 0.00121847f);
        assert(memcmp(&filter, &before, sizeof(filter)) == 0);
    }
}

static void test_nonfinite_covariance(void)
{
    struct ekf_ct_2d_filter filter = initial_filter();
    matrix_set(&filter.covariance, 0, 4, NAN);
    const struct ekf_ct_2d_filter before = filter;
    ekf_ct_2d_predict(&filter, 0.1f, 100.0f, 0.0001f);
    assert(memcmp(&filter, &before, sizeof(filter)) == 0);
    ekf_ct_2d_correct(&filter, 1010.0f, 0.01f, 25.0f, 0.00121847f);
    assert(memcmp(&filter, &before, sizeof(filter)) == 0);
}

static void test_correction_overflow(void)
{
    struct ekf_ct_2d_filter filter = initial_filter();
    // SPD y/vy block: determinant 25*1000 - 100^2 > 0. Range-to-vy gain is 2.
    // The finite FLT_MAX measurement therefore overflows the corrected velocity.
    matrix_set(&filter.covariance, 1, 3, 100.0f);
    matrix_set(&filter.covariance, 3, 1, 100.0f);
    matrix_set(&filter.covariance, 3, 3, 1000.0f);
    const struct ekf_ct_2d_filter before = filter;
    ekf_ct_2d_correct(&filter, FLT_MAX, 0.0f, 25.0f, 0.00121847f);
    assert(memcmp(&filter, &before, sizeof(filter)) == 0);
}

static void test_lifecycle(void)
{
    struct track track = {0};
    track_init(&track);
    track_start(&track, 1000.0f, 0.0f, 0);
    track_apply_measurement(&track, 1000.0f, 0.0f);
    track_apply_measurement(&track, 1000.0f, 0.0f);
    assert(track.state == TRACK_STATE_CONFIRMED);
    const struct track before = track;
    struct track next = track_predict_next(&track, 100);
    assert(memcmp(&track, &before, sizeof(track)) == 0);
    assert(next.estimate_sensor_ms == 100);
    track_apply_miss(&next);
    assert(next.state == TRACK_STATE_COASTING);
    track_apply_measurement(&next, 1000.0f, 0.0f);
    assert(next.state == TRACK_STATE_CONFIRMED && next.miss_count == 0);
    for (int index = 0; index < 5; ++index) {
        track_apply_miss(&next);
    }
    assert(next.state == TRACK_STATE_LOST);
    track_init(&next);
    track_start(&next, 2000.0f, 0.3f, 500);
    close_value(next.estimator.filter.turn_rate_radps, 0.0f);
    assert(next.state == TRACK_STATE_TENTATIVE && next.hit_count == 1);
}

static void test_configuration(void)
{
    struct estimator estimator;
    estimator_init(&estimator, 1000.0f, 0.0f);
    assert(estimator.filter.covariance.rows == 5 && MATRIX_MAX_ROWS == 5 && MATRIX_MAX_COLUMNS == 5);
    close_value(matrix_get(&estimator.filter.covariance, 4, 4), 0.01f);
    close_value(matrix_get(&estimator.filter.covariance, 1, 1), 25.0f);
    close_value(matrix_get(&estimator.filter.covariance, 3, 3), 10000.0f);
    estimator_predict(&estimator, 1.0f);
    close_value(matrix_get(&estimator.filter.covariance, 4, 4), 0.0101f);
    close_value(matrix_get(&estimator.filter.covariance, 3, 3), 10100.0f);
    const struct estimator_output output = estimator_get_output(&estimator);
    close_value(output.range_m, 1000.0f);
    close_value(output.azimuth_rad, 0.0f);
}

static const struct test_case cases[] = {
    TEST_CASE(test_ownership),
    TEST_CASE(test_quarter_turn),
    TEST_CASE(test_noise),
    TEST_CASE(test_zero_interval),
    TEST_CASE(test_wrapped),
    TEST_CASE(test_numerical_failure),
    TEST_CASE(test_malformed_covariance_dimensions),
    TEST_CASE(test_nonfinite_covariance),
    TEST_CASE(test_correction_overflow),
    TEST_CASE(test_lifecycle),
    TEST_CASE(test_configuration),
};

int main(int argc, char **p_argv)
{
    return run_tests(argc, p_argv, cases, sizeof(cases) / sizeof(cases[0]));
}
