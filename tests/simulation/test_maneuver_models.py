"""Analytic limits, independent quadrature, segment transitions and wire regression."""
from dataclasses import asdict
import hashlib
import json
import math

import pytest
from pc_sim.simulation.targets import Target, MotionSegment, SegmentedScenario, SCENARIOS
from pc_sim.simulation.prepared_input import InputSettings, generate_input
from pc_sim.storage.prepared_storage import save_input, load_input


def test_straight_acceleration():
    target = Target(1, 0, 1000, 200, 0, acceleration_mps2=5)
    target.update(20)
    assert target.x_m == pytest.approx(5000, abs=1e-8)
    assert target.vx_mps == pytest.approx(300)
    assert target.y_m == pytest.approx(1000)


def test_angular_acceleration_against_independent_midpoint():
    target = Target(1, 0, 1000, 200, 0, angular_acceleration_radps2=.01)
    target.update(10)
    n = 50000
    times = [(i + .5) * 10/n for i in range(n)]
    x = math.fsum(200 * math.cos(.005*t*t) for t in times)*10/n
    y = 1000 - math.fsum(200 * math.sin(.005*t*t) for t in times)*10/n
    assert target.x_m == pytest.approx(x, abs=1e-6)
    assert target.y_m == pytest.approx(y, abs=1e-6)
    assert target.turn_rate_radps == pytest.approx(.1)
    assert target.vx_mps == pytest.approx(200*math.cos(.5))


def test_variable_motion_partition_invariance():
    large = Target(1, 0, 1000, 100, 100, .02, 2, -.004)
    small = Target(**asdict(large))
    large.update(10)
    for _ in range(100):
        small.update(.1)
    for key in ['x_m','y_m','vx_mps','vy_mps','turn_rate_radps']:
        assert getattr(large,key) == pytest.approx(getattr(small,key), abs=1e-7)


def test_invalid_motion_preserves_state():
    target = Target(1, 0, 1000, 10, 0, acceleration_mps2=-2)
    before = asdict(target)
    with pytest.raises(ValueError):
        target.update(6)
    assert asdict(target) == before
    for dt in [-1, math.nan, math.inf]:
        with pytest.raises(ValueError):
            target.update(dt)
        assert asdict(target) == before


def test_acceleration_resets_at_segment_boundary():
    scenario = SegmentedScenario(Target(1,0,1000,200,0),
        [MotionSegment(2,0,5), MotionSegment(3,0)])
    scenario.update(5)
    assert scenario.target.x_m == pytest.approx(1040)
    assert scenario.target.vx_mps == pytest.approx(210)
    assert scenario.finished


@pytest.mark.parametrize('name,duration', [('straight_100',60),('straight_200',60),('straight_300',60),
    ('turn_1deg',110),('turn_2deg',65),('turn_4deg',42.5),('s_turn',100),
    ('accel_decel_2',70),('accel_decel_5',70),('turn_rate_ramp',50)])
@pytest.mark.parametrize('prefix',['','outbound_'])
def test_presets_and_storage_roundtrip(name,duration,prefix,tmp_path):
    name = prefix + name
    scenario = SCENARIOS[name]()
    assert scenario.duration_s == pytest.approx(duration)
    prepared = generate_input(InputSettings(scenario=name,duration_s=120,dt_s=.1))
    assert len(prepared.samples) == round(duration*10)
    assert all(s.frame is not None for s in prepared.samples)
    assert prepared.metadata['schema_version'] == 2
    save_input(tmp_path/'input',prepared)
    assert load_input(tmp_path/'input') == prepared
    scenario.update(duration)
    speed = math.hypot(scenario.target.vx_mps,scenario.target.vy_mps)
    assert speed == pytest.approx(100 if 'straight_100' in name else 300 if 'straight_300' in name else 200)
    if 's_turn' in name:
        assert scenario.target.vx_mps == pytest.approx(0 if prefix else 200,abs=1e-8)
    if 'turn_rate_ramp' in name:
        assert scenario.target.turn_rate_radps == 0


@pytest.mark.parametrize('name,digest', [
    ('single_approach','539d1064eadde6766cc791e5602a681ba66405450459d1b9390f3f50f54918ed'),
    ('single_turn','b01717528911aa8c34cf84b67c9ec4e163adccef6736aae637c887f9743c1c8a'),
    ('straight_turn_straight','ebeeb99fe73b8af282d12b677a58f32e0a851ee3e8f9d1dd9c502effb441913e'),
])
def test_legacy_samples_are_byte_identical(name,digest):
    # Captured from d6f92bc before adding accelerations; includes truth, noise and wire.
    prepared = generate_input(InputSettings(scenario=name,duration_s=80,dt_s=.1))
    rows = [{**asdict(s),'frame':s.frame.hex() if s.frame else None} for s in prepared.samples]
    assert hashlib.sha256(json.dumps(rows,sort_keys=True).encode()).hexdigest() == digest
    assert prepared.metadata['schema_version'] == 1
    assert 'acceleration_mps2' not in prepared.metadata['initial_target']


@pytest.mark.parametrize('kwargs', [{'acceleration_mps2':math.nan},
                                  {'angular_acceleration_radps2':math.inf}])
def test_invalid_segment_accelerations(kwargs):
    with pytest.raises(ValueError):
        MotionSegment(1,0,**kwargs)


def test_ramp_heading_integral():
    scenario = SCENARIOS['turn_rate_ramp']()
    scenario.update(scenario.duration_s)
    # Triangle20deg + rectangle40deg + triangle20deg = clockwise80deg.
    assert scenario.target.vx_mps == pytest.approx(200*math.cos(math.radians(80)),abs=1e-8)
    assert scenario.target.vy_mps == pytest.approx(-200*math.sin(math.radians(80)),abs=1e-8)


def test_new_schema_rejects_missing_acceleration_fields(tmp_path):
    from copy import deepcopy
    from pc_sim.simulation.prepared_input import PreparedInput
    prepared = generate_input(InputSettings(scenario='turn_rate_ramp',duration_s=1))
    metadata = deepcopy(prepared.metadata)
    del metadata['segments'][1]['angular_acceleration_radps2']
    with pytest.raises(ValueError):
        save_input(tmp_path/'invalid',PreparedInput(metadata,prepared.samples))


def test_new_scenario_cannot_discard_motion_metadata(tmp_path):
    from copy import deepcopy
    from pc_sim.simulation.prepared_input import PreparedInput
    prepared = generate_input(InputSettings(scenario='turn_rate_ramp',duration_s=1))
    metadata = deepcopy(prepared.metadata)
    metadata['schema_version'] = 1
    for item in [metadata['initial_target'],*metadata['segments']]:
        del item['acceleration_mps2']
        del item['angular_acceleration_radps2']
    with pytest.raises(ValueError,match='schema version 2'):
        save_input(tmp_path/'invalid',PreparedInput(metadata,prepared.samples))
