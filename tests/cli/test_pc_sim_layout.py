"""Role-based module commands work without compatibility entrypoints."""
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize('module', [
    'cli.run_sim', 'cli.radar_sender', 'cli.frame_sender', 'cli.status_client',
    'cli.prepare_input', 'evaluation.evaluate', 'evaluation.noise_sweep',
    'evaluation.spike_sweep',
])
def test_module_command_help(module):
    result = subprocess.run([sys.executable, '-m', f'pc_sim.{module}', '--help'], cwd=ROOT,
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert 'usage:' in result.stdout
    assert not result.stderr


def test_offline_generation_has_no_qt_or_serial_dependency(tmp_path):
    result = subprocess.run([
        sys.executable, '-S', '-m', 'pc_sim.cli.prepare_input', 'generate', str(tmp_path / 'input'),
        '--duration', '.02', '--noise', '0', '--azimuth-noise', '0',
    ], cwd=ROOT, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert 'samples=1' in result.stdout


def test_status_failure_exit_code_is_preserved(tmp_path):
    missing_port = str(tmp_path / 'nonexistent-uart')
    result = subprocess.run([sys.executable, '-m', 'pc_sim.cli.status_client',
                             '--port', missing_port], cwd=ROOT, capture_output=True, text=True)
    assert result.returncode == 1, result.stderr
    assert 'STATUS request failed' in result.stderr
