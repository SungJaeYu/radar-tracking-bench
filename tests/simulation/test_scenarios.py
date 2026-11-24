"""Validate simulator CLI, wire output, and single-track restrictions."""
import struct
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def invoke(*args):
    command = [sys.executable, '-m', 'pc_sim.cli.run_sim']
    return subprocess.run(command + list(args), cwd=ROOT, capture_output=True, text=True)


def frames(output):
    return [bytes.fromhex(line.split('frame=', 1)[1])
            for line in output.splitlines() if 'frame=' in line]


def test_single_target_cli_emits_current_frames():
    result = invoke('--duration', '0.2', '--dt', '0.1', '--noise', '0',
                    '--azimuth-noise', '0')
    assert result.returncode == 0, result.stderr
    emitted = frames(result.stdout)
    assert len(emitted) == 3
    assert emitted[0] == bytes.fromhex("7e 01 01 00 c8 9d")
    for frame, expected in zip(emitted[1:], [(0, 30000, 0), (100, 29985, 0)]):
        assert frame[:3] == bytes.fromhex('7e 0a 02')
        assert len(frame) == 15
        assert struct.unpack('>IHi', frame[3:-2]) == expected
        import binascii
        assert int.from_bytes(frame[-2:], 'big') == binascii.crc_hqx(frame[1:-2], 0xffff)


def test_multitarget_generation_remains_available_without_board():
    result = invoke('--scenario', 'four_targets', '--duration', '0.1')
    assert result.returncode == 0, result.stderr
    assert len(frames(result.stdout)) == 9
    assert frames(result.stdout)[0] == bytes.fromhex("7e 01 01 00 c8 9d")


def test_segmented_cli_stops_at_scenario_end():
    result = invoke('--scenario', 'straight_turn_straight', '--duration', '100',
                    '--dt', '10', '--noise', '0', '--azimuth-noise', '0')
    assert result.returncode == 0, result.stderr
    emitted = frames(result.stdout)
    assert len(emitted) == 9  # INIT and samples at 0..70 s; scenario ends near 75.49 s.
    values = [struct.unpack('>IHi', frame[3:-2]) for frame in emitted[1:]]
    assert [value[0] for value in values] == list(range(0, 80000, 10000))
    assert values[0] == (0, 1000, 0)
    assert values[1][1] == 2236  # Ten seconds eastbound before the turn.


@pytest.mark.parametrize('extra', [
    ['--scenario', 'two_crossing'], ['--clutter', '1'],
])
def test_serial_rejects_unsupported_multimeasurement_scans(extra):
    result = invoke('--port', 'must-not-be-opened', *extra)
    assert result.returncode == 2
    assert 'single target' in result.stderr


def test_missed_detections_emit_no_measurement():
    result = invoke('--pd', '0', '--duration', '0.2')
    assert result.returncode == 0, result.stderr
    assert frames(result.stdout) == [bytes.fromhex("7e 01 01 00 c8 9d")]


@pytest.mark.parametrize('option,value', [
    ('--dt', '0'), ('--dt', '0.0001'), ('--duration', 'nan'),
    ('--pd', '1.1'), ('--clutter', '-1'), ('--noise', '-1'),
    ('--azimuth-noise', 'inf'), ('--baud', '0'),
])
def test_invalid_scenario_settings(option, value):
    result = invoke(option, value)
    assert result.returncode == 2
    assert 'error:' in result.stderr


def test_uart_scenario_sends_current_frames_and_closes(monkeypatch):
    from unittest.mock import MagicMock
    from pc_sim.cli import run_sim
    serial = MagicMock()
    monkeypatch.setitem(sys.modules, 'serial', serial)
    monkeypatch.setattr(sys, 'argv', ['sim', '--port', 'test', '--duration', '0.2',
                                     '--dt', '0.1', '--noise', '0', '--azimuth-noise', '0'])
    monkeypatch.setattr(run_sim.time, 'sleep', lambda seconds: None)
    run_sim.main()
    connection = serial.Serial.return_value
    sent = [call.args[0] for call in connection.__enter__.return_value.write.call_args_list]
    assert sent == [bytes.fromhex('7e 01 01 00 c8 9d'),
                    bytes.fromhex('7e 0a 02 00 00 00 00 75 30 00 00 00 00 33 7b'),
                    bytes.fromhex('7e 0a 02 00 00 00 64 75 21 00 00 00 00 ef ac')]
    connection.__exit__.assert_called_once()


@pytest.mark.parametrize('option,value,valid', [
    ('--pd', '-0.000001', False), ('--pd', '0', True), ('--pd', '1', True),
    ('--pd', '1.000001', False),
    ('--dt', '0.000999', False), ('--dt', '0.001', True), ('--dt', '0.001001', True),
    ('--duration', '0', False), ('--duration', '0.001', True),
    ('--duration', '4294967.295', True), ('--duration', '4294967.296', False),
    ('--clutter', '-0.000001', False), ('--clutter', '0', True),
    ('--noise', '-0.000001', False), ('--noise', '0', True),
    ('--azimuth-noise', '-0.000001', False), ('--azimuth-noise', '0', True),
    ('--baud', '0', False), ('--baud', '1', True),
])
def test_cli_boundaries_without_executing_long_scenarios(monkeypatch, option, value, valid):
    from pc_sim.cli import run_sim
    calls = []
    monkeypatch.setattr(sys, 'argv', ['sim', option, value])
    monkeypatch.setattr(run_sim, 'run', lambda *args, **kwargs: calls.append(args))
    if valid:
        run_sim.main()
        assert len(calls) == 1
    else:
        with pytest.raises(SystemExit) as error:
            run_sim.main()
        assert error.value.code == 2 and not calls


@pytest.mark.parametrize('option', ['--dt', '--duration', '--pd', '--clutter', '--noise', '--azimuth-noise'])
@pytest.mark.parametrize('value', ['nan', 'inf', '-inf'])
def test_each_simulation_cli_float_rejects_nonfinite(monkeypatch, option, value):
    from pc_sim.cli import run_sim
    monkeypatch.setattr(sys, 'argv', ['sim', f'{option}={value}'])
    monkeypatch.setattr(run_sim, 'run', lambda *a, **k: pytest.fail('Invalid scenario executed'))
    with pytest.raises(SystemExit) as error:
        run_sim.main()
    assert error.value.code == 2
