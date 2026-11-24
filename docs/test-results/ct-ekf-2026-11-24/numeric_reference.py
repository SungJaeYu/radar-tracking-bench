"""Independent float64 checks of the production five-state CT filter; no UART."""
import argparse
import ctypes
import json
import math
from pathlib import Path
import subprocess
import sys

import numpy as np

REPO = Path(__file__).resolve().parents[3]
DIM = 5


class Matrix(ctypes.Structure):
    _fields_ = [('rows', ctypes.c_size_t), ('columns', ctypes.c_size_t),
                ('data', ctypes.c_float * (DIM * DIM))]


class Filter(ctypes.Structure):
    _fields_ = [(name, ctypes.c_float) for name in
                ['x_m', 'y_m', 'vx_mps', 'vy_mps', 'turn_rate_radps']] + [('covariance', Matrix)]


def state_array(value):
    return np.array([getattr(value, name) for name, _ in Filter._fields_[:DIM]])


def covariance_array(value):
    return np.array(value.covariance.data).reshape(DIM, DIM).astype(float)


def make_filter(state, covariance):
    value = Filter()
    for (name, _), number in zip(Filter._fields_, state):
        setattr(value, name, float(number))
    value.covariance.rows = value.covariance.columns = DIM
    value.covariance.data[:] = covariance.astype(np.float32).ravel()
    return value


def motion(state, interval):
    """Exact clockwise constant-turn arc, using sinc instead of production series."""
    x, y, vx, vy, omega = state
    angle = omega * interval
    sine, cosine = np.sin(angle), np.cos(angle)
    straight = interval * np.sinc(angle / np.pi)
    cross = interval * angle / 2 * np.sinc(angle / (2 * np.pi)) ** 2
    return np.array([x + straight * vx + cross * vy,
                     y - cross * vx + straight * vy,
                     cosine * vx + sine * vy, -sine * vx + cosine * vy, omega])


def numerical_jacobian(state, interval):
    result = np.empty((DIM, DIM))
    for column in range(DIM):
        step = 1e-5 if column == 4 else max(1e-4, abs(state[column]) * 1e-6)
        offset = np.zeros(DIM)
        offset[column] = step
        result[:, column] = (motion(state + offset, interval) - motion(state - offset, interval)) / (2 * step)
    return result


def predict_reference(state, covariance, interval, acceleration, angular_acceleration):
    jacobian = numerical_jacobian(state, interval)
    noise_map = np.zeros((DIM, 3))
    noise_map[0, 0] = noise_map[1, 1] = interval ** 2 / 2
    noise_map[2, 0] = noise_map[3, 1] = noise_map[4, 2] = interval
    noise = noise_map @ np.diag([acceleration, acceleration, angular_acceleration]) @ noise_map.T
    return motion(state, interval), jacobian @ covariance @ jacobian.T + noise


def correct_reference(state, covariance, measurement, noise):
    radius = np.hypot(*state[:2])
    jacobian = np.zeros((2, DIM))
    jacobian[0, :2] = state[:2] / radius
    jacobian[1, :2] = np.array([state[1], -state[0]]) / radius ** 2
    residual = measurement - [radius, np.arctan2(state[0], state[1])]
    residual[1] = (residual[1] + np.pi) % (2 * np.pi) - np.pi
    cross = covariance @ jacobian.T
    gain = np.linalg.solve(jacobian @ cross + noise, cross.T).T
    attenuation = np.eye(DIM) - gain @ jacobian
    return state + gain @ residual, attenuation @ covariance @ attenuation.T + gain @ noise @ gain.T


def check_covariance(covariance):
    assert np.isfinite(covariance).all()
    scale = max(1.0, np.linalg.norm(covariance, 2))
    assert np.max(abs(covariance - covariance.T)) <= scale * 2e-6
    minimum = float(np.linalg.eigvalsh(covariance).min())
    assert minimum >= -scale * 2e-6, (minimum, scale)
    return minimum


def compile_filter(directory, assertions):
    directory.mkdir(parents=True, exist_ok=True)
    library = directory / ('ct.dylib' if sys.platform == 'darwin' else 'ct.so')
    command = ['/usr/bin/clang', '-shared', '-fPIC', '-O0', '-ffp-contract=off', '-std=c11',
               '-Wall', '-Wextra', '-Werror', f'-D__ASSERT_ON={assertions}',
               '-DMATRIX_MAX_ROWS=5', '-DMATRIX_MAX_COLUMNS=5',
               '-I' + str(REPO/'fcc_app/src'), '-I' + str(REPO/'fcc_app/tests/common/include'),
               str(REPO/'fcc_app/src/tracking/estimators/filters/ekf_ct_2d.c'),
               str(REPO/'fcc_app/src/tracking/angle_utils.c'),
               str(REPO/'fcc_app/src/common/matrix.c'), '-lm', '-o', str(library)]
    subprocess.run(command, check=True)
    loaded = ctypes.CDLL(str(library.resolve()))
    loaded.ekf_ct_2d_predict.argtypes = [ctypes.POINTER(Filter)] + [ctypes.c_float] * 3
    loaded.ekf_ct_2d_predict.restype = None
    loaded.ekf_ct_2d_correct.argtypes = [ctypes.POINTER(Filter)] + [ctypes.c_float] * 4
    loaded.ekf_ct_2d_correct.restype = None
    return loaded, command


def run_checks(library):
    rng = np.random.default_rng(721)
    transform = rng.normal(size=(DIM, DIM))
    scale = np.diag([5, 7, 10, 12, .1])
    covariance = scale @ (transform @ transform.T + np.eye(DIM)) @ scale
    prediction_error = covariance_error = correction_error = 0.0
    count = 0
    minimum_eigenvalue = math.inf
    for turn in [0, -1e-10, 1e-10, -1e-4, 1e-4, -.5, .5, -1.2, 1.2]:
        for interval in [0, .001, .1, 1, 2]:
            value = make_filter([5000, 7000, 130, 170, turn], covariance)
            state, prior = state_array(value), covariance_array(value)
            dt, acceleration, angular = [ctypes.c_float(v).value for v in [interval, 100, .0001]]
            expected_state, expected_covariance = predict_reference(state, prior, dt, acceleration, angular)
            library.ekf_ct_2d_predict(ctypes.byref(value), dt, acceleration, angular)
            actual_state, actual_covariance = state_array(value), covariance_array(value)
            np.testing.assert_allclose(actual_state, expected_state, rtol=2e-6, atol=.002)
            np.testing.assert_allclose(actual_covariance, expected_covariance, rtol=3e-5, atol=.003)
            prediction_error = max(prediction_error, float(np.max(abs(actual_state - expected_state))))
            covariance_error = max(covariance_error, float(np.max(abs(actual_covariance - expected_covariance))))
            minimum_eigenvalue = min(minimum_eigenvalue, check_covariance(actual_covariance))
            count += 1
    # Adjacent binary32 values straddle each branch boundary with dt=1 exactly.
    # Compare both values and their boundary jumps with the independent double model.
    threshold_state_jump = threshold_covariance_jump = 0.0
    for sign in [-1, 1]:
        boundary = np.float32(sign * .05)
        turns = [np.nextafter(boundary, np.float32(0)), boundary,
                 np.nextafter(boundary, np.float32(sign * np.inf))]
        previous = None
        for turn in turns:
            value = make_filter([5000, 7000, 130, 170, turn], covariance)
            state, prior = state_array(value), covariance_array(value)
            angular = ctypes.c_float(.0001).value
            expected_state, expected_covariance = predict_reference(state, prior, 1, 100, angular)
            library.ekf_ct_2d_predict(ctypes.byref(value), 1, 100, angular)
            actual_state, actual_covariance = state_array(value), covariance_array(value)
            np.testing.assert_allclose(actual_state, expected_state, rtol=2e-6, atol=.002)
            np.testing.assert_allclose(actual_covariance, expected_covariance, rtol=3e-5, atol=.003)
            minimum_eigenvalue = min(minimum_eigenvalue, check_covariance(actual_covariance))
            prediction_error = max(prediction_error, float(np.max(abs(actual_state - expected_state))))
            covariance_error = max(covariance_error, float(np.max(abs(actual_covariance - expected_covariance))))
            if previous is not None:
                previous_state, previous_covariance, previous_expected_state, previous_expected_covariance = previous
                state_jump = actual_state - previous_state
                covariance_jump = actual_covariance - previous_covariance
                np.testing.assert_allclose(state_jump, expected_state - previous_expected_state,
                                           rtol=0, atol=.002)
                np.testing.assert_allclose(covariance_jump, expected_covariance - previous_expected_covariance,
                                           rtol=0, atol=.003)
                threshold_state_jump = max(threshold_state_jump, float(np.max(abs(state_jump))))
                threshold_covariance_jump = max(threshold_covariance_jump, float(np.max(abs(covariance_jump))))
            previous = actual_state, actual_covariance, expected_state, expected_covariance
            count += 1
    # Correlated SPD prior tests all five gain rows, including turn-rate correction.
    for state in [[5000, 7000, 130, 170, .03], [.01, -1000, 30, 10, -.1], [-.01, -1000, 30, 10, .1]]:
        value = make_filter(state, covariance)
        state, prior = state_array(value), covariance_array(value)
        angle = math.atan2(state[0], state[1]) + .02
        angle = (angle + math.pi) % (2 * math.pi) - math.pi
        measurement = np.array([ctypes.c_float(np.hypot(*state[:2]) + 15).value,
                                ctypes.c_float(angle).value])
        variances = [ctypes.c_float(v).value for v in [25, .00121847]]
        expected_state, expected_covariance = correct_reference(state, prior, measurement, np.diag(variances))
        library.ekf_ct_2d_correct(ctypes.byref(value), *measurement, *variances)
        np.testing.assert_allclose(state_array(value), expected_state, rtol=3e-5, atol=.003)
        np.testing.assert_allclose(covariance_array(value), expected_covariance, rtol=3e-5, atol=.003)
        correction_error = max(correction_error, float(np.max(abs(state_array(value) - expected_state))))
        minimum_eigenvalue = min(minimum_eigenvalue, check_covariance(covariance_array(value)))
        count += 1
    # Long repeated prediction/correction checks finite values and full eigenvalues.
    value = make_filter([0, 1000, 0, 200, .03], np.diag([25, 25, 10000, 10000, .01]))
    truth = state_array(value)
    for index in range(10000):
        truth = motion(truth, .1)
        library.ekf_ct_2d_predict(ctypes.byref(value), .1, 100, .0001)
        radius = np.hypot(*truth[:2]) + 5 * math.sin(index * .3)
        angle = math.atan2(truth[0], truth[1]) + .002 * math.cos(index * .2)
        library.ekf_ct_2d_correct(ctypes.byref(value), radius, angle, 25, .00121847)
        assert np.isfinite(state_array(value)).all()
        minimum_eigenvalue = min(minimum_eigenvalue, check_covariance(covariance_array(value)))
    return dict(prediction_cases=51,series_threshold_cases=6,correction_cases=3,long_run_steps=10000,
                max_series_threshold_state_component_jump=threshold_state_jump,
                max_series_threshold_covariance_entry_jump=threshold_covariance_jump,
                max_prediction_state_component_error=prediction_error,
                max_prediction_covariance_entry_error=covariance_error,
                max_correction_state_component_error=correction_error,
                minimum_observed_covariance_eigenvalue=minimum_eigenvalue,
                tolerance_note='Component errors mix state units; assertions apply per-entry tolerances. Eigenvalue tolerance is relative to matrix norm.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    results = []
    for assertions in [0, 2]:
        library, command = compile_filter(args.build/str(assertions), assertions)
        results.append(dict(assertions=assertions,command=command,**run_checks(library)))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(results, indent=2)+'\n')
    print(json.dumps(results, indent=2))


if __name__ == '__main__':
    main()
