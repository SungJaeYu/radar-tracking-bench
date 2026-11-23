"""Print scenario frames or send them over UART using the STM32 CRC-16 protocol."""
import argparse
from contextlib import nullcontext
import math
import random
import time

if __package__:
    from .protocol import build_init_frame, build_measurement_frame_from_radians
    from .targets import RadarSensorModel, SCENARIOS, SegmentedScenario
else:
    from protocol import build_init_frame, build_measurement_frame_from_radians
    from targets import RadarSensorModel, SCENARIOS, SegmentedScenario


def run(ser, scenario_name, dt, duration, pd, clutter_rate, seed,
        noise=10.0, azimuth_noise=0.01):
    scenario = SCENARIOS[scenario_name]()
    if isinstance(scenario, SegmentedScenario):
        targets = [scenario.target]
        duration = min(duration, scenario.duration_s)
    else:
        targets = scenario
    sensor = RadarSensorModel(pd=pd, clutter_rate=clutter_rate,
                              sigma_range_m=noise, sigma_azimuth_rad=azimuth_noise)
    rng = random.Random(seed)
    # Send INIT once at sequence start, regardless of missed detections.
    init_frame = build_init_frame()
    if ser is not None:
        ser.write(init_frame)
        ser.flush()
    print(f"INIT frame={init_frame.hex(' ')}")

    step = 0
    start = time.monotonic()
    while step * dt < duration:
        # Measure the initial position at t=0, then advance before the next sample.
        timestamp_ms = round(step * dt * 1000)
        measurements = sensor.measure(targets, timestamp_ms, rng)
        print(f"step={step} t={timestamp_ms} ms measurements={len(measurements)}")
        for meas in measurements:
            try:
                frame = build_measurement_frame_from_radians(
                    meas.timestamp_ms, meas.range_m, meas.azimuth_rad)
            except ValueError as error:
                # Report unrepresentable measurements rather than silently clipping them.
                print(f"measurement skipped: {error}")
                continue
            if ser is not None:
                ser.write(frame)
                ser.flush()
            print(f"range={meas.range_m:.2f} azimuth_rad={meas.azimuth_rad:.6f} "
                  f"frame={frame.hex(' ')}")
        step += 1
        if isinstance(scenario, SegmentedScenario):
            scenario.update(min(dt, duration - (step - 1) * dt))
        else:
            for target in targets:
                target.update(dt)
        # Advance time even on missed detections; output-only mode does not wait.
        if ser is not None and step * dt < duration:
            time.sleep(max(0.0, start + step * dt - time.monotonic()))


def main():
    parser = argparse.ArgumentParser(description="현재 STM32용 레이더 시나리오 송신기")
    parser.add_argument('--port', help='생략하면 UART 없이 프레임만 출력')
    parser.add_argument('--baud', type=int, default=115200)
    parser.add_argument('--scenario', choices=list(SCENARIOS), default='single_approach')
    parser.add_argument('--dt', type=float, default=0.05)
    parser.add_argument('--duration', type=float, default=60.0)
    parser.add_argument('--pd', type=float, default=1.0)
    parser.add_argument('--clutter', type=float, default=0.0)
    parser.add_argument('--noise', type=float, default=10.0, help='거리 잡음 표준편차(m)')
    parser.add_argument('--azimuth-noise', type=float, default=0.01,
                        help='방위각 잡음 표준편차(rad)')
    parser.add_argument('--seed', type=int, default=42)
    args = parser.parse_args()
    values = (args.dt, args.duration, args.pd, args.clutter, args.noise, args.azimuth_noise)
    if not all(math.isfinite(value) for value in values):
        parser.error('simulation settings must be finite')
    if args.dt < 0.001 or args.duration <= 0 or args.duration * 1000 > 0xFFFFFFFF:
        parser.error('dt must be >= 0.001 s; duration must fit a uint32 millisecond clock')
    if not 0 <= args.pd <= 1 or min(args.clutter, args.noise, args.azimuth_noise) < 0:
        parser.error('pd must be 0..1; clutter and noise must be nonnegative')
    if args.baud <= 0:
        parser.error('baud must be positive')
    # Firmware has one track and does not associate multiple measurements per scan.
    if args.port:
        scenario = SCENARIOS[args.scenario]()
        target_count = 1 if isinstance(scenario, SegmentedScenario) else len(scenario)
        if target_count != 1 or args.clutter != 0:
            parser.error('firmware requires a single target and zero clutter; omit --port for preview')
    connection = nullcontext(None)
    if args.port:
        import serial
        connection = serial.Serial(args.port, args.baud, write_timeout=2)
    with connection as ser:
        try:
            run(ser, args.scenario, args.dt, args.duration, args.pd, args.clutter,
                args.seed, args.noise, args.azimuth_noise)
        except KeyboardInterrupt:
            print('\n시뮬레이션 중단')


if __name__ == '__main__':
    main()
