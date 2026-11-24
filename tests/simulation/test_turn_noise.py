"""Noisy maneuver input preserves truth and can be reused byte for byte."""
from dataclasses import replace
import math

from pc_sim.simulation.prepared_input import InputSettings, generate_input
from pc_sim.storage.prepared_storage import load_input, save_input


def test_turn_noise_preserves_complete_truth_and_saved_frames(tmp_path):
    settings = InputSettings(scenario='straight_turn_straight', duration_s=80, dt_s=.1,
                             range_noise_std_m=0, azimuth_noise_std_rad=0, seed=42)
    baseline = generate_input(settings)
    noisy_settings = replace(settings, range_noise_std_m=10, azimuth_noise_std_rad=.01)
    noisy = generate_input(noisy_settings)
    repeated = generate_input(noisy_settings)
    assert noisy.samples == repeated.samples
    assert len(noisy.samples) == len(baseline.samples)
    assert noisy.samples[-1].timestamp_ms > 75000
    assert len(noisy.metadata['segments']) == 3
    for truth, measured in zip(baseline.samples, noisy.samples):
        assert (truth.timestamp_ms, truth.truth_x_m, truth.truth_y_m,
                truth.truth_vx_mps, truth.truth_vy_mps) == (
                    measured.timestamp_ms, measured.truth_x_m, measured.truth_y_m,
                    measured.truth_vx_mps, measured.truth_vy_mps)
        assert truth.measured_range_m == truth.truth_range_m
        assert math.isclose(truth.measured_azimuth_rad, truth.truth_azimuth_rad, abs_tol=1e-12)
    assert all(s.frame is not None for s in noisy.samples)
    assert any(a.frame != b.frame for a, b in zip(baseline.samples, noisy.samples))
    assert any(s.measured_range_m != s.truth_range_m for s in noisy.samples)
    assert any(s.measured_azimuth_rad != s.truth_azimuth_rad for s in noisy.samples)
    folder = tmp_path / 'noisy-turn'
    save_input(folder, noisy)
    saved = load_input(folder)
    assert saved.samples == noisy.samples
    assert saved.metadata['settings']['range_noise_std_m'] == 10
    assert saved.metadata['settings']['azimuth_noise_std_rad'] == .01
