"""Prepare single-target sensor inputs before any UART or replay clock starts."""
from dataclasses import asdict, dataclass
import hashlib
import math
from pathlib import Path
import random
import struct
import subprocess

from pc_sim.transport.protocol import build_measurement_frame_from_radians
from pc_sim.simulation.targets import RadarSensorModel, SCENARIOS, SegmentedScenario

MAX_SAMPLES = 180_000
SINGLE_TARGET_SCENARIOS = ('single_approach', 'single_turn', 'straight_turn_straight')


@dataclass(frozen=True)
class InputSettings:
    scenario: str = 'single_approach'
    dt_s: float = .02
    duration_s: float = 1.0
    pd: float = 1.0
    range_noise_std_m: float = 10.0
    azimuth_noise_std_rad: float = .01
    seed: int = 42

    def validate(self) -> None:
        """Reject invalid settings without allocating samples or opening files."""
        values = (self.dt_s, self.duration_s, self.pd,
                  self.range_noise_std_m, self.azimuth_noise_std_rad)
        try:
            valid_numbers = all(type(value) in (int, float) and math.isfinite(value)
                                for value in values)
        except OverflowError:
            valid_numbers = False
        if not valid_numbers:
            raise ValueError('Settings must be finite numbers')
        if self.scenario not in SINGLE_TARGET_SCENARIOS:
            raise ValueError('A supported single-target scenario is required')
        if self.dt_s < .001 or not 0 < self.duration_s <= 0xffffffff / 1000:
            raise ValueError('dt_s must be >= 0.001; duration must fit the uint32 ms clock')
        if not 0 <= self.pd <= 1 or min(self.range_noise_std_m,
                                      self.azimuth_noise_std_rad) < 0:
            raise ValueError('pd must be 0..1 and noise must be nonnegative')
        if type(self.seed) is not int:
            raise ValueError('seed must be an integer')


@dataclass(frozen=True, slots=True)
class PreparedSample:
    index: int
    timestamp_ms: int
    truth_x_m: float
    truth_y_m: float
    truth_vx_mps: float
    truth_vy_mps: float
    truth_range_m: float
    truth_azimuth_rad: float
    measured_range_m: float | None
    measured_azimuth_rad: float | None
    wire_range_m: int | None
    wire_azimuth_sc: int | None
    frame: bytes | None


@dataclass(frozen=True)
class PreparedInput:
    metadata: dict
    samples: tuple[PreparedSample, ...]


def sample_count(duration_s: float, dt_s: float) -> int:
    """Count the same exclusive-end grid used by run_sim, including float boundaries."""
    count = math.ceil(duration_s / dt_s)
    if count > 0 and (count - 1) * dt_s >= duration_s:
        count -= 1
    if count * dt_s < duration_s:
        count += 1
    if not 1 <= count <= MAX_SAMPLES:
        raise ValueError(f'Input must contain 1..{MAX_SAMPLES} samples')
    return count


def _source_identity() -> dict:
    directory = Path(__file__).resolve().parent
    files = {'prepared_input.py': directory / 'prepared_input.py',
             'targets.py': directory / 'targets.py',
             'protocol.py': directory.parent / 'transport' / 'protocol.py'}
    source = {'git_commit': None, 'git_dirty': None,
              'files_sha256': {name: hashlib.sha256(path.read_bytes()).hexdigest()
                               for name, path in files.items()}}
    try:
        commit = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=directory,
                                capture_output=True, text=True, check=True, timeout=5)
        status = subprocess.run(['git', 'status', '--porcelain'], cwd=directory,
                                capture_output=True, text=True, check=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return source
    source.update(git_commit=commit.stdout.strip(), git_dirty=bool(status.stdout.strip()))
    return source


def generate_input(settings: InputSettings) -> PreparedInput:
    """Generate all samples; invalid wire measurements abort instead of being dropped.

    Coordinates are east/north metres, azimuth clockwise from north in radians.
    The existing sensor clips noisy range at zero; a detected zero then fails wire
    encoding. No detection (probability or sensor range) retains truth with no frame.
    """
    settings.validate()
    scenario = SCENARIOS[settings.scenario]()
    segmented = isinstance(scenario, SegmentedScenario)
    target = scenario.target if segmented else scenario[0]
    duration_s = min(settings.duration_s, scenario.duration_s) if segmented else settings.duration_s
    count = sample_count(duration_s, settings.dt_s)
    sensor = RadarSensorModel(pd=settings.pd, clutter_rate=0,
                              sigma_range_m=settings.range_noise_std_m,
                              sigma_azimuth_rad=settings.azimuth_noise_std_rad)
    metadata = {
        'schema_version': 1, 'settings': asdict(settings),
        'effective_duration_s': duration_s, 'sample_count': count,
        'initial_target': asdict(target),
        'segments': [asdict(segment) for segment in scenario.segments] if segmented else [],
        'sensor': asdict(sensor), 'source': _source_identity(),
    }
    rng = random.Random(settings.seed)
    samples = []
    for index in range(count):
        timestamp_ms = round(index * settings.dt_s * 1000)
        measurements = sensor.measure([target], timestamp_ms, rng)
        measured_range = measured_angle = wire_range = wire_angle = frame = None
        if measurements:
            measurement, = measurements
            measured_range = measurement.range_m
            measured_angle = measurement.azimuth_rad
            try:
                frame = build_measurement_frame_from_radians(
                    timestamp_ms, measured_range, measured_angle)
            except ValueError as error:
                raise ValueError(f'Cannot encode sample {index} at {timestamp_ms} ms: {error}') from error
            _, wire_range, wire_angle = struct.unpack('>IHi', frame[3:-2])
        samples.append(PreparedSample(
            index, timestamp_ms, target.x_m, target.y_m, target.vx_mps, target.vy_mps,
            target.range_m, target.azimuth_rad, measured_range, measured_angle,
            wire_range, wire_angle, frame))
        if segmented:
            scenario.update(min(settings.dt_s, duration_s - index * settings.dt_s))
        else:
            target.update(settings.dt_s)
    return PreparedInput(metadata, tuple(samples))
