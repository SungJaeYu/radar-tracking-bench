#include <assert.h>
#include <math.h>

#include "tracking/estimator.h"

static void check_close(float actual, float expected);

int main(void)
{
    struct estimator estimator;
    estimator_init(&estimator, 1000.0f, 0.0f);
    const struct matrix initial = estimator.filter.covariance;
    const float q = (float)EXPECTED_ACCELERATION_VARIANCE;

    estimator_predict(&estimator, 0.5f);

    // Independent closed form at north and dt=0.5 s, with zero initial velocity.
    // Each axis adds q/64 to position, q/16 to cross terms and q/4 to velocity.
    for (unsigned int axis = 0; axis < 2U; ++axis) {
        const float position = matrix_get(&initial, axis, axis);
        const float velocity = matrix_get(&initial, axis + 2U, axis + 2U);
        check_close(matrix_get(&estimator.filter.covariance, axis, axis),
                    position + velocity / 4.0f + q / 64.0f);
        check_close(matrix_get(&estimator.filter.covariance, axis, axis + 2U),
                    velocity / 2.0f + q / 16.0f);
        check_close(matrix_get(&estimator.filter.covariance, axis + 2U, axis),
                    velocity / 2.0f + q / 16.0f);
        check_close(matrix_get(&estimator.filter.covariance, axis + 2U, axis + 2U),
                    velocity + q / 4.0f);
    }
    const struct estimator_output output = estimator_get_output(&estimator);
    assert(output.range_m == 1000.0f && output.azimuth_rad == 0.0f);
    assert(output.range_rate_mps == 0.0f && output.azimuth_rate_radps == 0.0f);
    return 0;
}

static void check_close(float actual, float expected)
{
    assert(isfinite(actual));
    assert(fabsf(actual - expected) <= fmaxf(0.001f, fabsf(expected) * 0.000002f));
}
