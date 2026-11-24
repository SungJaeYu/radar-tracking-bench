#include <assert.h>
#include <math.h>

#include "common/math_constants.h"
#include "tracking/angle_utils.h"
#include "tracking/estimator.h"
#include "tracking/track.h"

int main(void)
{
    struct estimator est;
    estimator_init(&est, 1000.0f, 0.0f);
    struct estimator_output output = estimator_get_output(&est);
    assert(output.range_m == 1000.0f);
    assert(output.range_rate_mps == 0.0f && output.azimuth_rate_radps == 0.0f);

    // At north, the first linearized update has a closed-form Cartesian result.
    estimator_correct(&est, 1030.0f, 0.03f);
    output = estimator_get_output(&est);
    const float expected_x = 1000.0f * 0.00121847f /
                             (0.00121847f + EXPECTED_AZIMUTH_R) * 0.03f;
    const float expected_y = 1000.0f + 25.0f / (25.0f + EXPECTED_RANGE_R) * 30.0f;
    assert(fabsf(output.range_m * sinf(output.azimuth_rad) - expected_x) < 0.001f);
    assert(fabsf(output.range_m * cosf(output.azimuth_rad) - expected_y) < 0.001f);

    // Cartesian CV prediction must follow a straight line, even with angular motion.
    estimator_init(&est, 1000.0f, 0.5f);
    estimator_predict(&est, 0.1f);
    estimator_correct(&est, 1005.0f, 0.52f);
    output = estimator_get_output(&est);
    const float s = sinf(output.azimuth_rad);
    const float c = cosf(output.azimuth_rad);
    const float vx = output.range_rate_mps * s + output.range_m * output.azimuth_rate_radps * c;
    const float vy = output.range_rate_mps * c - output.range_m * output.azimuth_rate_radps * s;
    const float x = output.range_m * s + vx * 0.8f;
    const float y = output.range_m * c + vy * 0.8f;
    estimator_predict(&est, 0.8f);
    output = estimator_get_output(&est);
    assert(fabsf(output.range_m * sinf(output.azimuth_rad) - x) < 0.001f);
    assert(fabsf(output.range_m * cosf(output.azimuth_rad) - y) < 0.001f);

    // Actual track path: prediction copies owned state; lifecycle stays unchanged.
    struct track track;
    track_init(&track);
    track_start(&track, 1000.0f, MATH_PI_F - 0.001f, 100U);
    struct track next = track_predict_next(&track, 200U);
    track_apply_measurement(&next, 1001.0f, -MATH_PI_F + 0.001f);
    assert(track.hit_count == 1U && track.estimate_sensor_ms == 100U);
    output = track_get_estimate(&next);
    assert(fabsf(angle_diff_rad(output.azimuth_rad, MATH_PI_F)) < 0.01f);
    next = track_predict_next(&next, 300U);
    track_apply_measurement(&next, 1002.0f, -MATH_PI_F + 0.002f);
    assert(next.state == TRACK_STATE_CONFIRMED);
    for (unsigned int i = 0; i < 5; ++i) {
        track_apply_miss(&next);
    }
    assert(next.state == TRACK_STATE_LOST);
    track_init(&next);
    track_start(&next, 1.0f, 0.0f, 400U);
    output = track_get_estimate(&next);
    assert(output.range_m == 1.0f && output.range_rate_mps == 0.0f);

    // Independent rate projection oracle, including the otherwise singular origin.
    est.filter.x_m = 600.0f;
    est.filter.y_m = 800.0f;
    est.filter.vx_mps = 20.0f;
    est.filter.vy_mps = -10.0f;
    output = estimator_get_output(&est);
    assert(fabsf(output.range_rate_mps - 4.0f) < 0.00001f);
    assert(fabsf(output.azimuth_rate_radps - 0.022f) < 0.000001f);
    est.filter.x_m = 0.0f;
    est.filter.y_m = 0.0f;
    output = estimator_get_output(&est);
    assert(output.range_m == 0.0f && output.azimuth_rad == 0.0f);
    assert(output.range_rate_mps == 0.0f && output.azimuth_rate_radps == 0.0f);
    return 0;
}
