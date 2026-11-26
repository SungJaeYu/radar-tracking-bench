"""The unified entrypoint dispatches real commands and preserves failures."""
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]


def invoke(*args, without_packages=False):
    command = [sys.executable]
    if without_packages:
        command.append('-S')
    return subprocess.run(command + ['-m', 'pc_sim', *args], cwd=ROOT,
                          capture_output=True, text=True)


@pytest.mark.parametrize('args', [(), ('--help',), ('gui', '--help')])
def test_help_does_not_require_optional_packages(args):
    result = invoke(*args, without_packages=True)
    assert result.returncode == 0, result.stderr
    assert 'usage:' in result.stdout


@pytest.mark.parametrize('command', [
    'simulate', 'evaluate', 'noise-sweep', 'spike-sweep', 'input', 'status',
    'send-frame', 'send-radar',
])
def test_command_help_is_forwarded(command):
    result = invoke(command, '--help')
    assert result.returncode == 0, result.stderr
    assert f'pc_sim {command}' in result.stdout


def test_input_generation_and_verification_without_optional_packages(tmp_path):
    directory = str(tmp_path / 'input')
    result = invoke('input', 'generate', directory, '--duration', '.04', without_packages=True)
    assert result.returncode == 0, result.stderr
    assert 'samples=2' in result.stdout
    verified = invoke('input', 'verify', directory, without_packages=True)
    assert verified.returncode == 0, verified.stderr
    assert 'samples=2' in verified.stdout


def test_simulation_arguments_reach_existing_sender():
    result = invoke('simulate', '--duration', '.1', '--dt', '.1', '--noise', '0',
                    '--azimuth-noise', '0')
    assert result.returncode == 0, result.stderr
    assert '7e 0a 02 00 00 00 00 75 30 00 00 00 00 33 7b' in result.stdout


@pytest.mark.parametrize('command', ['noise-sweep', 'spike-sweep'])
def test_sweep_dry_runs(command):
    result = invoke(command, '--dry-run')
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip()


@pytest.mark.parametrize('args', [('missing',), ('simulate', '--unknown'), ('gui', '--unknown')])
def test_invalid_commands_and_arguments_fail(args):
    result = invoke(*args)
    assert result.returncode == 2
    assert 'error:' in result.stderr


def test_status_failure_is_returned_to_shell(tmp_path):
    result = invoke('status', '--port', str(tmp_path / 'nonexistent-uart'))
    assert result.returncode == 1
    assert 'STATUS request failed' in result.stderr


def test_in_process_dispatch_restores_arguments(tmp_path):
    from pc_sim.__main__ import main

    original = sys.argv
    assert main(['input', 'generate', str(tmp_path / 'input'), '--duration', '.02']) == 0
    assert sys.argv is original
    with pytest.raises(SystemExit):
        main(['input', '--unknown'])
    assert sys.argv is original
