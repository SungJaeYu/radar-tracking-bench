"""Validated JSONL input storage; integrity checks never replace stored wire bytes."""
from dataclasses import asdict, fields
import hashlib
import json
import math
from pathlib import Path
import struct

from pc_sim.simulation.prepared_input import InputSettings, PreparedInput, PreparedSample, sample_count
from pc_sim.transport.protocol import build_measurement_frame_from_radians

MAX_METADATA_BYTES = 65_536
MAX_SAMPLE_BYTES = 4_096
METADATA_KEYS = {'schema_version', 'settings', 'effective_duration_s', 'sample_count',
                 'initial_target', 'segments', 'sensor', 'source'}
SAMPLE_KEYS = {field.name for field in fields(PreparedSample)} - {'frame'} | {'frame_hex'}


def _json_bytes(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')


def _mapping(value: object, keys: set[str]) -> None:
    if not isinstance(value, dict) or set(value) != keys:
        raise ValueError('Unexpected or missing input fields')


def _finite(value: object) -> bool:
    try:
        return type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        return False


def _digest(value: object) -> bool:
    return (isinstance(value, str) and len(value) == 64
            and all(char in '0123456789abcdef' for char in value))


def _validate_metadata(metadata: dict) -> InputSettings:
    _mapping(metadata, METADATA_KEYS)
    if type(metadata['schema_version']) is not int or metadata['schema_version'] != 1:
        raise ValueError('Unsupported input schema version')
    _mapping(metadata['settings'], {field.name for field in fields(InputSettings)})
    settings = InputSettings(**metadata['settings'])
    settings.validate()
    duration = metadata['effective_duration_s']
    if not _finite(duration) or not 0 < duration <= settings.duration_s:
        raise ValueError('Invalid effective duration')
    count = metadata['sample_count']
    if type(count) is not int or count != sample_count(duration, settings.dt_s):
        raise ValueError('Sample count does not match sensor grid')
    initial = metadata['initial_target']
    _mapping(initial, {'target_id', 'x_m', 'y_m', 'vx_mps', 'vy_mps', 'turn_rate_radps'})
    if type(initial['target_id']) is not int or not all(_finite(value) for value in initial.values()):
        raise ValueError('Invalid initial target')
    segments = metadata['segments']
    if not isinstance(segments, list) or len(segments) > 1000:
        raise ValueError('Invalid motion segments')
    for segment in segments:
        _mapping(segment, {'duration_s', 'turn_rate_radps'})
        if not all(_finite(value) for value in segment.values()) or segment['duration_s'] <= 0:
            raise ValueError('Invalid motion segment')
    if bool(segments) != (settings.scenario == 'straight_turn_straight'):
        raise ValueError('Scenario and segments disagree')
    expected_duration = (min(settings.duration_s, math.fsum(s['duration_s'] for s in segments))
                         if segments else settings.duration_s)
    if duration != expected_duration:
        raise ValueError('Effective duration and segments disagree')
    sensor = metadata['sensor']
    _mapping(sensor, {'sigma_range_m', 'sigma_azimuth_rad', 'sigma_doppler_mps', 'pd',
                      'clutter_rate', 'max_range_m'})
    if not all(_finite(value) and value >= 0 for value in sensor.values()):
        raise ValueError('Invalid sensor configuration')
    if (sensor['pd'] != settings.pd or sensor['clutter_rate'] != 0
            or sensor['sigma_range_m'] != settings.range_noise_std_m
            or sensor['sigma_azimuth_rad'] != settings.azimuth_noise_std_rad
            or sensor['max_range_m'] <= 0):
        raise ValueError('Sensor and settings disagree')
    source = metadata['source']
    _mapping(source, {'git_commit', 'git_dirty', 'files_sha256'})
    commit = source['git_commit']
    if commit is not None and (not isinstance(commit, str) or len(commit) not in (40, 64)
                               or any(char not in '0123456789abcdef' for char in commit)):
        raise ValueError('Invalid source revision')
    if source['git_dirty'] is not None and type(source['git_dirty']) is not bool:
        raise ValueError('Invalid source status')
    _mapping(source['files_sha256'], {'prepared_input.py', 'targets.py', 'protocol.py'})
    if not all(_digest(value) for value in source['files_sha256'].values()):
        raise ValueError('Invalid source hashes')
    return settings


def _validate_sample(sample: PreparedSample, index: int, settings: InputSettings,
                     metadata: dict) -> None:
    if type(sample.index) is not int or sample.index != index:
        raise ValueError('Sample order mismatch')
    if (type(sample.timestamp_ms) is not int
            or sample.timestamp_ms != round(index * settings.dt_s * 1000)
            or not 0 <= sample.timestamp_ms <= 0xffffffff):
        raise ValueError('Sensor timestamp mismatch')
    truth = (sample.truth_x_m, sample.truth_y_m, sample.truth_vx_mps, sample.truth_vy_mps,
             sample.truth_range_m, sample.truth_azimuth_rad)
    if not all(_finite(value) for value in truth):
        raise ValueError('Truth must be finite')
    if not math.isclose(sample.truth_range_m, math.hypot(sample.truth_x_m, sample.truth_y_m),
                        rel_tol=1e-12, abs_tol=1e-9):
        raise ValueError('Truth range disagrees with coordinates')
    if not math.isclose(sample.truth_azimuth_rad, math.atan2(sample.truth_x_m, sample.truth_y_m),
                        rel_tol=0, abs_tol=1e-12):
        raise ValueError('Truth azimuth disagrees with coordinates')
    if index == 0:
        initial = metadata['initial_target']
        if truth[:4] != tuple(initial[key] for key in ('x_m', 'y_m', 'vx_mps', 'vy_mps')):
            raise ValueError('First sample disagrees with initial target')
    measured = (sample.measured_range_m, sample.measured_azimuth_rad,
                sample.wire_range_m, sample.wire_azimuth_sc)
    if sample.frame is None:
        if any(value is not None for value in measured):
            raise ValueError('Absent detection has measurement fields')
        if settings.pd == 1 and sample.truth_range_m <= metadata['sensor']['max_range_m']:
            raise ValueError('Unexpected missing detection')
        return
    if (settings.pd == 0 or sample.truth_range_m > metadata['sensor']['max_range_m']
            or type(sample.frame) is not bytes or len(sample.frame) != 15
            or not all(_finite(value) for value in measured[:2])
            or any(type(value) is not int for value in measured[2:])):
        raise ValueError('Invalid detected measurement')
    expected = build_measurement_frame_from_radians(
        sample.timestamp_ms, sample.measured_range_m, sample.measured_azimuth_rad)
    if sample.frame != expected:
        raise ValueError('Frame header, payload or CRC disagrees with measurement')
    _, wire_range, wire_angle = struct.unpack('>IHi', sample.frame[3:-2])
    if (wire_range, wire_angle) != measured[2:]:
        raise ValueError('Decoded wire values disagree with frame')


def save_input(directory: str | Path, prepared: PreparedInput) -> None:
    """Write a new directory; publish the completion manifest only after samples close.

    On failure, leave partial files for inspection. They are not reusable inputs.
    SHA256 detects accidental changes, not an attacker who rewrites both data and hashes.
    """
    settings = _validate_metadata(prepared.metadata)
    if len(prepared.samples) != prepared.metadata['sample_count']:
        raise ValueError('Sample count mismatch')
    for index, sample in enumerate(prepared.samples):
        _validate_sample(sample, index, settings, prepared.metadata)
    metadata_bytes = _json_bytes(prepared.metadata)
    if len(metadata_bytes) > MAX_METADATA_BYTES - 1024:
        raise ValueError('Metadata is too large')
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    digest = hashlib.sha256()
    with (directory / 'samples.jsonl').open('xb') as stream:
        for sample in prepared.samples:
            row = asdict(sample)
            frame = row.pop('frame')
            row['frame_hex'] = frame.hex() if frame is not None else None
            line = _json_bytes(row) + b'\n'
            if len(line) > MAX_SAMPLE_BYTES:
                raise ValueError('Sample is too large')
            stream.write(line)
            digest.update(line)
    manifest = {'complete': True, 'metadata': prepared.metadata,
                'metadata_sha256': hashlib.sha256(metadata_bytes).hexdigest(),
                'samples_sha256': digest.hexdigest()}
    with (directory / 'metadata.json').open('xb') as stream:
        stream.write(_json_bytes(manifest) + b'\n')


def _read_json(raw: bytes) -> object:
    def reject_duplicates(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('Duplicate JSON field')
            result[key] = value
        return result

    try:
        return json.loads(raw, object_pairs_hook=reject_duplicates)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ValueError('Invalid input JSON') from error


def load_input(directory: str | Path) -> PreparedInput:
    """Validate bounded files and return the original frames, never regenerated input.

    Current generator source hashes need not match the recorded hashes: the saved
    sequence is the replay authority. Validation encodes only to check consistency.
    """
    directory = Path(directory)
    with (directory / 'metadata.json').open('rb') as stream:
        raw = stream.read(MAX_METADATA_BYTES + 1)
    if len(raw) > MAX_METADATA_BYTES:
        raise ValueError('Metadata is too large')
    manifest = _read_json(raw)
    _mapping(manifest, {'complete', 'metadata', 'metadata_sha256', 'samples_sha256'})
    if manifest['complete'] is not True:
        raise ValueError('Input save is incomplete')
    if not all(_digest(manifest[key]) for key in ('metadata_sha256', 'samples_sha256')):
        raise ValueError('Invalid dataset hashes')
    metadata = manifest['metadata']
    if hashlib.sha256(_json_bytes(metadata)).hexdigest() != manifest['metadata_sha256']:
        raise ValueError('Metadata hash mismatch')
    settings = _validate_metadata(metadata)
    samples = []
    digest = hashlib.sha256()
    with (directory / 'samples.jsonl').open('rb') as stream:
        for index in range(metadata['sample_count']):
            line = stream.readline(MAX_SAMPLE_BYTES + 1)
            if not line or len(line) > MAX_SAMPLE_BYTES:
                raise ValueError('Missing or oversized sample')
            digest.update(line)
            row = _read_json(line)
            _mapping(row, SAMPLE_KEYS)
            frame_hex = row.pop('frame_hex')
            if frame_hex is not None and (not isinstance(frame_hex, str) or len(frame_hex) != 30):
                raise ValueError('Invalid frame hex')
            row['frame'] = bytes.fromhex(frame_hex) if frame_hex is not None else None
            sample = PreparedSample(**row)
            _validate_sample(sample, index, settings, metadata)
            samples.append(sample)
        if stream.read(1):
            raise ValueError('Unexpected trailing sample data')
    if digest.hexdigest() != manifest['samples_sha256']:
        raise ValueError('Samples hash mismatch')
    return PreparedInput(metadata, tuple(samples))
