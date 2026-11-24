"""Persisted inputs must preserve bytes and reject damaged or inconsistent data."""
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest

from pc_sim.simulation.prepared_input import InputSettings, generate_input


@pytest.fixture
def prepared():
    return generate_input(InputSettings(duration_s=.06, pd=.5))


def rewrite(directory, *, row_change=None, metadata_change=None, rehash=False):
    """Change a real dataset; optionally recompute digests to exercise schema checks."""
    path = directory / 'samples.jsonl'
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    if row_change:
        row_change(rows)
        path.write_text(''.join(json.dumps(row) + '\n' for row in rows))
    manifest_path = directory / 'metadata.json'
    manifest = json.loads(manifest_path.read_text())
    if metadata_change:
        metadata_change(manifest)
    if rehash:
        manifest['samples_sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
        canonical = json.dumps(manifest['metadata'], sort_keys=True, separators=(',', ':'),
                               allow_nan=False).encode()
        manifest['metadata_sha256'] = hashlib.sha256(canonical).hexdigest()
    manifest_path.write_text(json.dumps(manifest))


def test_roundtrip_preserves_all_values_and_frames(tmp_path, prepared, monkeypatch):
    from pc_sim.storage.prepared_storage import load_input, save_input
    from pc_sim.simulation import targets

    directory = tmp_path / 'input'
    save_input(directory, prepared)
    # Loading must not invoke a scenario factory or draw fresh random measurements.
    monkeypatch.setattr(targets, 'SCENARIOS', {})
    assert load_input(directory) == prepared
    assert sorted(path.name for path in directory.iterdir()) == ['metadata.json', 'samples.jsonl']


@pytest.mark.parametrize('metadata', [False, True])
def test_changed_data_fails_hash_validation(tmp_path, prepared, metadata):
    from pc_sim.storage.prepared_storage import load_input, save_input

    directory = tmp_path / 'input'
    save_input(directory, prepared)
    if metadata:
        rewrite(directory, metadata_change=lambda data: data['metadata']['settings'].update(seed=5))
    else:
        with (directory / 'samples.jsonl').open('ab') as stream:
            stream.write(b'\n')
    with pytest.raises(ValueError):
        load_input(directory)


@pytest.mark.parametrize('change', [
    lambda rows: rows[0].update(index=1),
    lambda rows: rows[0].update(index=False),
    lambda rows: rows[1].update(timestamp_ms=21),
    lambda rows: rows[0].update(truth_x_m=1000),
    lambda rows: rows[0].update(truth_vx_mps=float('inf')),
    lambda rows: rows[0].update(truth_vx_mps=10**400),
    lambda rows: rows[0].update(frame_hex='7e'),
    lambda rows: rows[0].update(frame_hex='zz'),
    lambda rows: rows[0].update(frame_hex=15),
    lambda rows: rows[0].update(extra=1),
    lambda rows: rows.pop(),
])
def test_rehashed_malformed_samples_still_fail(tmp_path, change):
    from pc_sim.storage.prepared_storage import load_input, save_input

    directory = tmp_path / 'input'
    save_input(directory, generate_input(InputSettings(duration_s=.06)))
    rewrite(directory, row_change=change, rehash=True)
    with pytest.raises(ValueError):
        load_input(directory)


@pytest.mark.parametrize('field,value', [
    ('wire_range_m', 3), ('wire_azimuth_sc', 123), ('measured_range_m', 1),
    ('measured_azimuth_rad', 1), ('frame_hex', '7e0a0200000000753000000000337a'),
])
def test_rehashed_payload_disagreement_fails(tmp_path, field, value):
    from pc_sim.storage.prepared_storage import load_input, save_input

    directory = tmp_path / 'input'
    save_input(directory, generate_input(InputSettings(duration_s=.02,
                                                       range_noise_std_m=0,
                                                       azimuth_noise_std_rad=0)))
    rewrite(directory, row_change=lambda rows: rows[0].update({field: value}), rehash=True)
    with pytest.raises(ValueError):
        load_input(directory)


@pytest.mark.parametrize('change', [
    lambda data: data.update(complete=False),
    lambda data: data['metadata'].update(schema_version=2),
    lambda data: data['metadata'].update(sample_count=1),
    lambda data: data['metadata'].update(effective_duration_s=-1),
    lambda data: data['metadata']['settings'].update(dt_s=0),
    lambda data: data['metadata'].update(source=None),
    lambda data: data['metadata']['initial_target'].update(x_m=10),
])
def test_rehashed_invalid_metadata_fails(tmp_path, prepared, change):
    from pc_sim.storage.prepared_storage import load_input, save_input

    directory = tmp_path / 'input'
    save_input(directory, prepared)
    rewrite(directory, metadata_change=change, rehash=True)
    with pytest.raises(ValueError):
        load_input(directory)


def test_absent_detection_cannot_contain_partial_measurement(tmp_path):
    from pc_sim.storage.prepared_storage import load_input, save_input

    directory = tmp_path / 'input'
    save_input(directory, generate_input(InputSettings(duration_s=.02, pd=0)))
    rewrite(directory, row_change=lambda rows: rows[0].update(wire_range_m=1000), rehash=True)
    with pytest.raises(ValueError):
        load_input(directory)


def test_existing_directory_is_never_overwritten(tmp_path, prepared):
    from pc_sim.storage.prepared_storage import save_input

    directory = tmp_path / 'input'
    save_input(directory, prepared)
    before = {path.name: path.read_bytes() for path in directory.iterdir()}
    with pytest.raises(FileExistsError):
        save_input(directory, prepared)
    assert before == {path.name: path.read_bytes() for path in directory.iterdir()}


def test_save_failure_does_not_publish_complete_manifest(tmp_path, prepared, monkeypatch):
    from pc_sim.storage.prepared_storage import load_input, save_input

    directory = tmp_path / 'input'
    original = Path.open

    def fail_manifest(path, *args, **kwargs):
        if path.name == 'metadata.json' and args and 'x' in args[0]:
            raise OSError('disk full')
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, 'open', fail_manifest)
    with pytest.raises(OSError, match='disk full'):
        save_input(directory, prepared)
    assert (directory / 'samples.jsonl').exists()
    with pytest.raises((OSError, ValueError)):
        load_input(directory)


def test_invalid_in_memory_sequence_is_not_persisted(tmp_path, prepared):
    from pc_sim.storage.prepared_storage import save_input

    invalid = replace(prepared, samples=(replace(prepared.samples[0], timestamp_ms=1),))
    with pytest.raises(ValueError):
        save_input(tmp_path / 'input', invalid)
    assert not (tmp_path / 'input').exists()


def test_oversized_line_is_rejected(tmp_path, prepared):
    from pc_sim.storage.prepared_storage import load_input, save_input

    directory = tmp_path / 'input'
    save_input(directory, prepared)
    (directory / 'samples.jsonl').write_bytes(b' ' * 100_000)
    with pytest.raises(ValueError):
        load_input(directory)


def test_cli_generate_verify_and_corruption(tmp_path):
    command = [sys.executable, '-m', 'pc_sim.cli.prepare_input']
    directory = tmp_path / 'cli'
    result = subprocess.run(command + ['generate', str(directory), '--scenario', 'single_turn',
                                      '--duration', '.06'], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert 'samples=3' in result.stdout
    verified = subprocess.run(command + ['verify', str(directory)], capture_output=True, text=True)
    assert verified.returncode == 0, verified.stderr
    assert 'samples=3' in verified.stdout
    (directory / 'samples.jsonl').write_text('broken')
    broken = subprocess.run(command + ['verify', str(directory)], capture_output=True, text=True)
    assert broken.returncode != 0 and 'Traceback' not in broken.stderr
