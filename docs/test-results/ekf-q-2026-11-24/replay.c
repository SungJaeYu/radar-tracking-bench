#include <stdint.h>
#include <string.h>

#include "application/radar_processor.h"

static struct radar_processor processor;

void replay_reset(void)
{
    radar_processor_reset(&processor);
}

int replay_step(const uint8_t *p_payload, float *out_values, uint32_t *out_meta)
{
    struct protocol_frame frame = {.type = FRAME_TYPE_MEAS_REPORT, .payload_length = 10U};
    memcpy(frame.payload, p_payload, frame.payload_length);
    struct radar_process_result result;
    const bool processed = radar_processor_process_measurement(&processor, &frame, 0, &result);
    if (!processed) {
        return 0;
    }
    out_meta[0] = (uint32_t)processor.track.state;
    out_meta[1] = (uint32_t)result.result;
    out_meta[2] = processor.track.estimate_sensor_ms;
    memset(out_values, 0, 4U * sizeof(float));
    if (processor.track.state >= TRACK_STATE_TENTATIVE && processor.track.state <= TRACK_STATE_COASTING) {
        const struct estimator_output estimate = track_get_estimate(&processor.track);
        out_values[0] = estimate.range_m;
        out_values[1] = estimate.azimuth_rad;
        out_values[2] = estimate.range_rate_mps;
        out_values[3] = estimate.azimuth_rate_radps;
    }
    return 1;
}
