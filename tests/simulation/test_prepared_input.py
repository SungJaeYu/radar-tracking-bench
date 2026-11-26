"""Prepared inputs preserve existing sensor draws, motion and wire bytes."""
from contextlib import redirect_stdout
from dataclasses import replace
import io
import math

import pytest


def test_straight_truth_and_literal_wire_frames():
    from pc_sim.simulation.prepared_input import InputSettings, generate_input

    data = generate_input(InputSettings(duration_s=.2, dt_s=.1,
                                       range_noise_std_m=0, azimuth_noise_std_rad=0))
    assert [sample.timestamp_ms for sample in data.samples] == [0, 100]
    assert [sample.truth_y_m for sample in data.samples] == [30000, 29985]
    assert [sample.frame.hex() for sample in data.samples] == [
        '7e0a0200000000753000000000337b', '7e0a0200000064752100000000efac']
    assert all(sample.truth_vy_mps == -150 for sample in data.samples)
    assert data.metadata['source']['files_sha256']['targets.py']


@pytest.mark.parametrize('scenario,duration,dt', [
    ('single_approach', 1, .02), ('single_turn', 2, .02),
    ('straight_turn_straight', 100, .1),
])
def test_seeded_frames_match_existing_sender(scenario, duration, dt):
    from pc_sim.simulation.prepared_input import InputSettings, generate_input
    from pc_sim.cli.run_sim import run

    settings = InputSettings(scenario=scenario, duration_s=duration, dt_s=dt, pd=.8)
    data = generate_input(settings)
    output = io.StringIO()
    with redirect_stdout(output):
        run(None, scenario, dt, duration, .8, 0, 42, 10, .01)
    expected = [bytes.fromhex(line.split('frame=')[1])
                for line in output.getvalue().splitlines() if 'frame=' in line][1:]
    assert [sample.frame for sample in data.samples if sample.frame is not None] == expected
    assert data.samples == generate_input(settings).samples
    assert data.samples != generate_input(replace(settings, seed=43)).samples
    if scenario == 'straight_turn_straight':
        assert data.metadata['effective_duration_s'] < duration
        assert data.samples[-1].timestamp_ms == 75400


def test_misses_keep_truth_and_sensor_grid():
    from pc_sim.simulation.prepared_input import InputSettings, generate_input

    data = generate_input(InputSettings(duration_s=.06, pd=0))
    assert [sample.timestamp_ms for sample in data.samples] == [0, 20, 40]
    assert [sample.truth_y_m for sample in data.samples] == [30000, 29997, 29994]
    assert all(sample.frame is None and sample.measured_range_m is None
               and sample.wire_range_m is None for sample in data.samples)


@pytest.mark.parametrize('changes', [
    {'dt_s': 0}, {'dt_s': .0009}, {'duration_s': 0}, {'duration_s': math.inf},
    {'pd': 1.1}, {'pd': math.nan}, {'range_noise_std_m': -1},
    {'azimuth_noise_std_rad': math.inf}, {'seed': True}, {'seed': 1.5},
    {'scenario': 'four_targets'}, {'scenario': 'missing'},
    {'duration_s': 4294967.296}, {'duration_s': 3600.02},
    {'range_noise_std_m': 10**400},
])
def test_invalid_or_excessive_requests_fail_before_generation(changes):
    from pc_sim.simulation.prepared_input import InputSettings, generate_input

    with pytest.raises(ValueError):
        generate_input(InputSettings(**changes))


def test_unrepresentable_measurement_fails_instead_of_skipping():
    from pc_sim.simulation.prepared_input import InputSettings, generate_input

    with pytest.raises(ValueError, match='sample 1'):
        generate_input(InputSettings(duration_s=201, dt_s=200,
                                     range_noise_std_m=0, azimuth_noise_std_rad=0))


def test_fractional_duration_uses_same_exclusive_end_as_sender():
    from pc_sim.simulation.prepared_input import InputSettings, generate_input

    data = generate_input(InputSettings(duration_s=.07, dt_s=.01))
    assert [sample.timestamp_ms for sample in data.samples] == [0, 10, 20, 30, 40, 50, 60]
