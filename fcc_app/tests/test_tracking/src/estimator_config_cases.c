#include <assert.h>
#include <math.h>
#include "tracking/estimator.h"

int main(void)
{
    struct estimator est;
    estimator_init(&est, 1000.0f, 0.0f);
    assert(est.range_filter.measurement_noise_variance == EXPECTED_RANGE_R);
    assert(est.azimuth_filter.measurement_noise_variance == EXPECTED_AZIMUTH_R);
    // Changing R must not silently retune P or Q.
    assert(matrix_get(&est.range_filter.covariance, 0, 0) == 25.0f &&
           matrix_get(&est.range_filter.covariance, 1, 1) == 10000.0f);
    assert(est.range_filter.process_noise_variance == 100.0f);
    assert(matrix_get(&est.azimuth_filter.covariance, 0, 0) == 0.00121847f);
    assert(matrix_get(&est.azimuth_filter.covariance, 1, 1) == 0.03046174f);
    assert(est.azimuth_filter.process_noise_variance == 0.00761544f);
    // Initial zero cross-covariance: scalar Kalman gain has a closed form.
    const float expected_range = 1000.0f + 25.0f / (25.0f + EXPECTED_RANGE_R) * 30.0f;
    const float expected_angle = 0.00121847f / (0.00121847f + EXPECTED_AZIMUTH_R) * 0.03f;
    estimator_correct(&est, 1030.0f, 0.03f);
    assert(fabsf(est.range_filter.estimate - expected_range) < 0.0002f);
    assert(fabsf(est.azimuth_filter.estimate - expected_angle) < 0.000001f);
    return 0;
}
