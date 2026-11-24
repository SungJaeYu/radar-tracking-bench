import math

import pytest

from pc_sim.simulation import targets


def test_straight_motion():
    target = targets.Target(1, 10, 20, 30, -40)
    target.update(2)
    assert (target.x_m, target.y_m, target.vx_mps, target.vy_mps) == (70, -60, 30, -40)


@pytest.mark.parametrize('direction', [1, -1])
def test_quarter_circle(direction):
    target = targets.Target(1, 10, 20, 100, 0, direction)
    target.update(math.pi / 2)
    assert (target.x_m, target.y_m) == pytest.approx((110, 20 - direction * 100))
    assert (target.vx_mps, target.vy_mps) == pytest.approx((0, -direction * 100), abs=1e-12)


def test_full_circle_and_speed_preservation():
    target = targets.Target(1, 10, 20, 60, 80, 1)
    for _ in range(100):
        target.update(2 * math.pi / 100)
        assert math.hypot(target.vx_mps, target.vy_mps) == pytest.approx(100)
    assert (target.x_m, target.y_m) == pytest.approx((10, 20))
    assert (target.vx_mps, target.vy_mps) == pytest.approx((60, 80))


def test_tiny_turn_retains_lateral_displacement():
    target = targets.Target(1, 0, 0, 100, 0, 1e-10)
    target.update(1)
    assert target.x_m == pytest.approx(100)
    assert target.y_m == pytest.approx(-5e-9, abs=1e-18)


def test_single_turn_scenario():
    assert 'single_turn' in targets.SCENARIOS
    target, = targets.SCENARIOS['single_turn']()
    assert (target.vx_mps, target.vy_mps) == (200, 0)
    assert math.degrees(target.turn_rate_radps) == pytest.approx(1.622, abs=0.001)
    left, = targets.scenario_single_turn(bank_deg=-30, tas_mps=100)
    assert left.turn_rate_radps == pytest.approx(-2 * target.turn_rate_radps)


@pytest.mark.parametrize('kwargs', [
    {'tas_mps': 0}, {'tas_mps': -1}, {'tas_mps': math.inf},
    {'bank_deg': 90}, {'bank_deg': -90}, {'bank_deg': math.nan},
])
def test_invalid_turn_conditions(kwargs):
    with pytest.raises(ValueError):
        targets.scenario_single_turn(**kwargs)


def test_segment_boundary_splits_one_update():
    target = targets.Target(1, 0, 0, 100, 0)
    scenario = targets.SegmentedScenario(target, [
        targets.MotionSegment(0.03, 0),
        targets.MotionSegment(math.pi / 2, 1),
        targets.MotionSegment(1, 0),
    ])
    scenario.update(0.1)
    assert scenario.segment_index == 1
    assert scenario.segment_elapsed_s == pytest.approx(0.07)
    assert (target.x_m, target.y_m) == pytest.approx(
        (3 + 100 * math.sin(0.07), 100 * (math.cos(0.07) - 1)))


def test_segmented_motion_stops_at_end_even_with_oversized_step():
    target = targets.Target(1, 0, 0, 100, 0)
    scenario = targets.SegmentedScenario(target, [
        targets.MotionSegment(1, 0),
        targets.MotionSegment(math.pi / 2, 1),
        targets.MotionSegment(1, 0),
    ])
    scenario.update(100)
    assert scenario.finished
    assert (target.x_m, target.y_m) == pytest.approx((200, -200))
    scenario.update(10)
    assert (target.x_m, target.y_m) == pytest.approx((200, -200))


def test_exact_boundary_sets_next_turn_rate():
    target = targets.Target(1, 0, 0, 100, 0)
    scenario = targets.SegmentedScenario(target, [
        targets.MotionSegment(1, 0), targets.MotionSegment(1, 1),
    ])
    scenario.update(1)
    assert scenario.segment_index == 1
    assert scenario.segment_elapsed_s == 0
    assert target.turn_rate_radps == 1


def test_small_steps_match_one_large_step():
    sampled = targets.SCENARIOS['straight_turn_straight']()
    whole = targets.SCENARIOS['straight_turn_straight']()
    for _ in range(1000):
        sampled.update(sampled.duration_s / 1000)
    whole.update(whole.duration_s)
    assert sampled.finished and whole.finished
    assert (sampled.target.x_m, sampled.target.y_m) == pytest.approx(
        (whole.target.x_m, whole.target.y_m), abs=1e-7)


def test_zero_step_does_not_advance():
    scenario = targets.SCENARIOS['straight_turn_straight']()
    scenario.update(0)
    assert scenario.segment_index == 0
    assert scenario.segment_elapsed_s == 0
    assert (scenario.target.x_m, scenario.target.y_m) == (0, 1000)


def test_straight_turn_straight_factory():
    scenario = targets.SCENARIOS['straight_turn_straight']()
    radius = 200 / scenario.segments[1].turn_rate_radps
    scenario.update(scenario.duration_s)
    assert scenario.finished
    assert (scenario.target.x_m, scenario.target.y_m) == pytest.approx(
        (2000 + radius, 1000 - radius - 2000))
    assert (scenario.target.vx_mps, scenario.target.vy_mps) == pytest.approx(
        (0, -200), abs=1e-10)


@pytest.mark.parametrize('duration,rate', [(0, 0), (-1, 0), (math.inf, 0),
                                         (1, math.nan)])
def test_invalid_motion_segment(duration, rate):
    with pytest.raises(ValueError):
        targets.MotionSegment(duration, rate)


def test_empty_segments_rejected():
    with pytest.raises(ValueError):
        targets.SegmentedScenario(targets.Target(1, 0, 0, 1, 0), [])


@pytest.mark.parametrize('dt', [-1, math.nan, math.inf])
def test_invalid_segment_update_does_not_move(dt):
    scenario = targets.SCENARIOS['straight_turn_straight']()
    with pytest.raises(ValueError):
        scenario.update(dt)
    assert (scenario.target.x_m, scenario.target.y_m) == (0, 1000)
