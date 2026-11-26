"""
Target motion and radar sensor models.

Cartesian target coordinates: x east, y north; units m and m/s.
Radar output: polar range_m, azimuth_rad, elevation_rad, and doppler_mps.
"""

import math
import random
from dataclasses import dataclass
from functools import partial
from typing import List

STANDARD_GRAVITY_MPS2 = 9.80665
SEGMENT_TIME_TOLERANCE_S = 1e-9  # Boundary roundoff tolerance, far below the 1 ms sensor clock.


@dataclass
class Measurement:
    """Sensor quantities; elevation and Doppler remain PC-only and are not sent on wire."""
    timestamp_ms: int
    range_m: float
    azimuth_rad: float
    elevation_rad: float
    doppler_mps: float


# Positive nodes/weights of eight-point Gauss-Legendre quadrature.
# Used only for varying speed/rate; the legacy exact constant-turn path is retained.
_MOTION_QUADRATURE = (
    (.1834346424956498, .3626837833783620),
    (.5255324099163290, .3137066458778873),
    (.7966664774136267, .2223810344533745),
    (.9602898564975363, .1012285362903763),
)

# Target motion: clockwise turns with optional along-track/angular acceleration.

@dataclass
class Target:
    """Planar truth motion; accelerations remain constant during each update."""
    target_id: int
    x_m:       float   # East position
    y_m:       float   # North position
    vx_mps:    float   # East velocity
    vy_mps:    float   # North velocity
    turn_rate_radps: float = 0.0 # Turn rate [rad/s], clockwise positive

    acceleration_mps2: float = 0.0  # Along velocity direction, not a fixed Cartesian axis
    angular_acceleration_radps2: float = 0.0  # Clockwise turn-rate derivative

    def update(self, dt: float) -> None:
        if not math.isfinite(dt) or dt < 0:
            raise ValueError('dt must be finite and nonnegative')
        if self.acceleration_mps2 != 0 or self.angular_acceleration_radps2 != 0:
            self._update_accelerated(dt)
            return
        turn_angle_rad = self.turn_rate_radps * dt

        cos_a = math.cos(turn_angle_rad)
        sin_a = math.sin(turn_angle_rad)

        old_vx = self.vx_mps
        old_vy = self.vy_mps

        # Integrate the arc with a constant turn rate over this time step.
        if self.turn_rate_radps == 0.0:
            self.x_m += old_vx * dt
            self.y_m += old_vy * dt
        else:
            a = sin_a / self.turn_rate_radps
            # Equivalent to (1 - cos(theta)) / omega, stable near zero.
            b = 2.0 * math.sin(turn_angle_rad / 2.0) ** 2 / self.turn_rate_radps
            self.x_m += old_vx * a + old_vy * b
            self.y_m += -old_vx * b + old_vy * a

        self.vx_mps = old_vx * cos_a + old_vy * sin_a
        self.vy_mps = -old_vx * sin_a + old_vy * cos_a

    def _update_accelerated(self, dt: float) -> None:
        values = (self.x_m, self.y_m, self.vx_mps, self.vy_mps, self.turn_rate_radps,
                  self.acceleration_mps2, self.angular_acceleration_radps2)
        if not all(math.isfinite(value) for value in values):
            raise ValueError('Motion state must be finite')
        speed = math.hypot(self.vx_mps, self.vy_mps)
        end_speed = speed + self.acceleration_mps2 * dt
        end_rate = self.turn_rate_radps + self.angular_acceleration_radps2 * dt
        if not math.isfinite(end_speed) or not math.isfinite(end_rate) or end_speed < 0:
            raise ValueError('Motion must retain finite nonnegative speed and finite turn rate')
        if dt == 0:
            return
        if speed == 0:
            raise ValueError('Accelerated motion requires an initial velocity direction')
        direction_x, direction_y = self.vx_mps / speed, self.vy_mps / speed
        angle = self.turn_rate_radps * dt + .5 * self.angular_acceleration_radps2 * dt * dt
        if not math.isfinite(angle):
            raise ValueError('Motion angle must be finite')
        # Bound time and phase per integration panel, independently of sensor dt.
        panels = max(1, math.ceil(dt),
                     math.ceil(max(abs(self.turn_rate_radps), abs(end_rate)) * dt / .25))
        width = dt / panels
        dx = dy = 0.0
        for panel in range(panels):
            midpoint = (panel + .5) * width
            for node, weight in _MOTION_QUADRATURE:
                for sign in (-1, 1):
                    t = midpoint + sign * node * width / 2
                    phase = self.turn_rate_radps * t + .5 * self.angular_acceleration_radps2 * t * t
                    cosine, sine = math.cos(phase), math.sin(phase)
                    distance_weight = (speed + self.acceleration_mps2 * t) * weight * width / 2
                    dx += distance_weight * (direction_x * cosine + direction_y * sine)
                    dy += distance_weight * (-direction_x * sine + direction_y * cosine)
        cosine, sine = math.cos(angle), math.sin(angle)
        next_state = (self.x_m + dx, self.y_m + dy,
                      end_speed * (direction_x * cosine + direction_y * sine),
                      end_speed * (-direction_x * sine + direction_y * cosine))
        if not all(math.isfinite(value) for value in next_state):
            raise ValueError('Motion integration produced a nonfinite state')
        self.x_m, self.y_m, self.vx_mps, self.vy_mps = next_state
        self.turn_rate_radps = end_rate

    @property
    def range_m(self) -> float:
        return math.hypot(self.x_m, self.y_m)

    @property
    def azimuth_rad(self) -> float:
        """Clockwise azimuth from radar boresight (+y), computed as atan2(x, y)."""
        return math.atan2(self.x_m, self.y_m)

    @property
    def elevation_rad(self) -> float:
        """Elevation above the horizontal plane; zero for this same-altitude 2D model."""
        return 0.0

    def radial_velocity_mps(self) -> float:
        """Line-of-sight velocity for Doppler; positive means receding."""
        r = self.range_m
        if r < 1e-6:
            return 0.0
        return (self.x_m * self.vx_mps + self.y_m * self.vy_mps) / r


@dataclass(frozen=True)
class MotionSegment:
    """Set starting turn rate and constant accelerations for a timed segment."""

    duration_s: float
    turn_rate_radps: float
    acceleration_mps2: float = 0.0
    angular_acceleration_radps2: float = 0.0

    def __post_init__(self) -> None:
        if not math.isfinite(self.duration_s) or self.duration_s <= 0:
            raise ValueError('duration_s must be finite and positive')
        if not all(math.isfinite(value) for value in (self.turn_rate_radps, self.acceleration_mps2,
                                                       self.angular_acceleration_radps2)):
            raise ValueError('Segment rates and accelerations must be finite')


class SegmentedScenario:
    """Own one target's motion schedule; discard time beyond the final segment.

    Each update splits at segment boundaries. Measurements remain the caller's
    responsibility, so internal motion steps do not add sensor samples.
    """

    def __init__(self, target: Target, segments: list[MotionSegment]) -> None:
        if not segments:
            raise ValueError('segments must not be empty')
        self.target = target
        self.segments = tuple(segments)
        self.segment_index = 0
        self.segment_elapsed_s = 0.0
        self._start_segment()

    def _start_segment(self) -> None:
        segment = self.segments[self.segment_index]
        self.target.turn_rate_radps = segment.turn_rate_radps
        self.target.acceleration_mps2 = segment.acceleration_mps2
        self.target.angular_acceleration_radps2 = segment.angular_acceleration_radps2

    @property
    def duration_s(self) -> float:
        return math.fsum(segment.duration_s for segment in self.segments)

    @property
    def finished(self) -> bool:
        return self.segment_index == len(self.segments)

    def update(self, dt: float) -> None:
        """Advance by up to dt seconds; zero or post-completion updates do nothing."""
        if not math.isfinite(dt) or dt < 0:
            raise ValueError('dt must be finite and nonnegative')

        remaining_s = dt
        while remaining_s > 0 and not self.finished:
            segment = self.segments[self.segment_index]
            segment_remaining_s = segment.duration_s - self.segment_elapsed_s
            interval_s = min(remaining_s, segment_remaining_s)
            self.target.update(interval_s)
            remaining_s -= interval_s

            at_boundary = math.isclose(interval_s, segment_remaining_s, rel_tol=0.0,
                                       abs_tol=SEGMENT_TIME_TOLERANCE_S)
            if at_boundary:
                self.segment_index += 1
                self.segment_elapsed_s = 0.0
                if not self.finished:
                    self._start_segment()
            else:
                self.segment_elapsed_s += interval_s


# Radar sensor model

@dataclass
class RadarSensorModel:
    """
    Generate noisy measurements with missed detections and clutter.

    Parameters:
        sigma_range_m      Range standard deviation (m).
        sigma_azimuth_rad  Azimuth standard deviation (rad).
        sigma_doppler_mps  Doppler standard deviation (m/s).
        pd                 Detection probability (0.0 to 1.0).
        clutter_rate       Mean false detections per scan (Poisson).
        max_range_m        Targets beyond this range are not detected.
    """
    sigma_range_m:     float = 10.0
    sigma_azimuth_rad: float = 0.01
    sigma_doppler_mps: float = 0.5
    pd:                float = 0.9
    clutter_rate:      float = 0.5
    max_range_m:       float = 30_000.0

    def measure(self,
                targets: List[Target],
                timestamp_ms: int,
                rng: random.Random = random.Random()
                ) -> list:
        """
        Return Measurement objects in shuffled order.
        Association algorithms must not rely on target-list ordering.
        """
        measurements = []

        for tgt in targets:
            if tgt.range_m > self.max_range_m:
                continue
            if rng.random() > self.pd:
                continue  # Missed detection

            r   = tgt.range_m        + rng.gauss(0, self.sigma_range_m)
            az  = tgt.azimuth_rad    + rng.gauss(0, self.sigma_azimuth_rad)
            el  = tgt.elevation_rad  # No elevation noise in the 2D scenario.
            dop = tgt.radial_velocity_mps() + rng.gauss(0, self.sigma_doppler_mps)

            measurements.append(Measurement(
                timestamp_ms=timestamp_ms,
                range_m=max(0.0, r),
                azimuth_rad=az,
                elevation_rad=el,
                doppler_mps=dop,
            ))

        # Inject a Poisson-distributed number of clutter detections.
        n_clutter = _poisson(self.clutter_rate, rng)
        for _ in range(n_clutter):
            r   = rng.uniform(0, self.max_range_m)
            az  = rng.uniform(-math.pi, math.pi)
            dop = rng.gauss(0, self.sigma_doppler_mps * 3)
            measurements.append(Measurement(
                timestamp_ms=timestamp_ms,
                range_m=r,
                azimuth_rad=az,
                elevation_rad=0.0,
                doppler_mps=dop,
            ))

        rng.shuffle(measurements)
        return measurements


def _poisson(lam: float, rng: random.Random) -> int:
    """Sample Poisson(lambda) using the Knuth algorithm."""
    if lam <= 0:
        return 0
    L = math.exp(-lam)
    k, p = 0, 1.0
    while p > L:
        k += 1
        p *= rng.random()
    return k - 1


# Predefined scenarios

def scenario_two_crossing() -> List[Target]:
    """Two targets crossing in front of the radar."""
    return [
        Target(target_id=1, x_m=-5000, y_m=20000, vx_mps= 50, vy_mps=-80),
        Target(target_id=2, x_m= 5000, y_m=20000, vx_mps=-50, vy_mps=-80),
    ]

def scenario_single_approach() -> List[Target]:
    """One target approaching along the radar boresight."""
    return [
        Target(target_id=1, x_m=0, y_m=30000, vx_mps=0, vy_mps=-150),
    ]

def scenario_four_targets() -> List[Target]:
    """Four-target input load scenario; no multi-target firmware tracking is implied."""
    return [
        Target(target_id=1, x_m=-8000, y_m=25000, vx_mps= 40, vy_mps=-60),
        Target(target_id=2, x_m= 8000, y_m=25000, vx_mps=-40, vy_mps=-60),
        Target(target_id=3, x_m=    0, y_m=15000, vx_mps= 20, vy_mps=-100),
        Target(target_id=4, x_m= 3000, y_m=10000, vx_mps=-30, vy_mps=-120),
    ]

def scenario_single_turn(bank_deg: float = 30.0, tas_mps: float = 200.0) -> List[Target]:
    """Constant-altitude coordinated turn, with no wind and constant TAS.

    Start eastbound. Positive bank means a clockwise (right) turn.
    Bank and TAS are scenario inputs, converted to the Target motion state.
    """
    if not math.isfinite(tas_mps) or tas_mps <= 0:
        raise ValueError('tas_mps must be finite and positive')
    if not math.isfinite(bank_deg) or not -90.0 < bank_deg < 90.0:
        raise ValueError('bank_deg must be finite and between -90 and 90 degrees')
    turn_rate_radps = STANDARD_GRAVITY_MPS2 * math.tan(math.radians(bank_deg)) / tas_mps
    return [
        Target(target_id=1, x_m=0, y_m=1000, vx_mps=tas_mps, vy_mps=0,
               turn_rate_radps=turn_rate_radps),
    ]


def scenario_straight_turn_straight() -> SegmentedScenario:
    """Fly east for 10 s, turn right by 90 degrees, then fly south for 10 s.

    Reuse the constant-turn scenario's bank/TAS assumptions and initial state.
    Turn-rate transitions are instantaneous, not aircraft roll dynamics.
    """
    target, = scenario_single_turn()
    turn_rate_radps = target.turn_rate_radps
    turn_duration_s = math.radians(90.0) / abs(turn_rate_radps)
    return SegmentedScenario(target, [
        MotionSegment(10.0, 0.0),
        MotionSegment(turn_duration_s, turn_rate_radps),
        MotionSegment(10.0, 0.0),
    ])


SCENARIOS = {
    "two_crossing":    scenario_two_crossing,
    "single_approach": scenario_single_approach,
    "four_targets":    scenario_four_targets,
    "single_turn":     scenario_single_turn,
    "straight_turn_straight": scenario_straight_turn_straight,
}


# Fixed, reviewable presets for the expanded comparison; units remain SI internally.
MANEUVER_NAMES = ('straight_100', 'straight_200', 'straight_300',
                  'turn_1deg', 'turn_2deg', 'turn_4deg', 's_turn',
                  'accel_decel_2', 'accel_decel_5', 'turn_rate_ramp')


def scenario_maneuver(name: str, outbound: bool = False) -> SegmentedScenario:
    """Build one approved truth schedule; outbound changes only initial heading."""
    speed = 200.0
    if name in ('straight_100', 'straight_200', 'straight_300'):
        speed = float(name.split('_')[1])
        segments = [MotionSegment(60, 0)]
    elif name in ('turn_1deg', 'turn_2deg', 'turn_4deg'):
        rate_deg = float(name.split('_')[1].removesuffix('deg'))
        segments = [MotionSegment(10, 0), MotionSegment(90/rate_deg, math.radians(rate_deg)),
                    MotionSegment(10, 0)]
    elif name == 's_turn':
        rate = math.radians(2)
        segments = [MotionSegment(10, 0), MotionSegment(20, rate), MotionSegment(40, -rate),
                    MotionSegment(20, rate), MotionSegment(10, 0)]
    elif name in ('accel_decel_2', 'accel_decel_5'):
        acceleration = float(name.rsplit('_', 1)[1])
        segments = [MotionSegment(10, 0), MotionSegment(20, 0, acceleration),
                    MotionSegment(10, 0), MotionSegment(20, 0, -acceleration), MotionSegment(10, 0)]
    elif name == 'turn_rate_ramp':
        rate = math.radians(4)
        segments = [MotionSegment(10, 0), MotionSegment(10, 0, angular_acceleration_radps2=rate/10),
                    MotionSegment(10, rate), MotionSegment(10, rate, angular_acceleration_radps2=-rate/10),
                    MotionSegment(10, 0)]
    else:
        raise ValueError('Unknown maneuver preset: ' + name)
    target = Target(1, 0, 1000, 0 if outbound else speed, speed if outbound else 0)
    return SegmentedScenario(target, segments)


MANEUVER_SCENARIOS = {
    prefix + name: partial(scenario_maneuver, name, outbound=bool(prefix))
    for prefix in ('', 'outbound_') for name in MANEUVER_NAMES
}
SCENARIOS.update(MANEUVER_SCENARIOS)
