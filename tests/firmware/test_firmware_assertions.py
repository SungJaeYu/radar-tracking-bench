"""Run invalid internal calls in child processes so assertions cannot kill pytest."""

from pathlib import Path
import shutil
import signal
import subprocess

import pytest


@pytest.fixture(scope="module")
def assertion_probe(tmp_path_factory):
    root = Path(__file__).resolve().parents[2]
    src = root / "fcc_app/src"
    compiler = Path("/Applications/Xcode.app/Contents/Developer/Toolchains/XcodeDefault.xctoolchain/usr/bin/clang")
    if not compiler.exists():
        found = shutil.which("cc")
        if not found:
            pytest.skip("A host C compiler is required")
        compiler = Path(found)
    folder = tmp_path_factory.mktemp("firmware-assertions")
    probe = folder / "probe.c"
    probe.write_text('''
#include <math.h>
#include <stddef.h>
#include <stdlib.h>
#include "common/ring_buffer.h"
#include "protocol/frame_parser.h"
#include "tracking/estimators/filters/kf_cv_1d.h"
#include "tracking/angle_utils.h"
int main(int argc, char **argv) {
    if (argc == 4) {
        struct kf_cv_1d_filter filter;
        float value = strtof(argv[3], NULL);
        int field = atoi(argv[2]);
        if (argv[1][0] == 's') {
            struct matrix initial = {.rows = KF_CV_1D_STATE_DIM,
                .columns = KF_CV_1D_STATE_DIM, .data = {1, 0, 0, 1}};
            if (field == 0) initial.rows = (size_t)value;
            else initial.columns = (size_t)value;
            kf_cv_1d_init(&filter, 0, 0, &initial, 0, 1);
        } else if (argv[1][0] == 'a') {
            float args[] = {0, 0, 1, 0, 0, 1, 0, 1};
            if (field < 0 || field >= 8) return 2;
            args[field] = value;
            kf_cv_1d_init(&filter, args[0], args[1],
            &(const struct matrix){.rows = KF_CV_1D_STATE_DIM, .columns = KF_CV_1D_STATE_DIM, .data = {args[2], args[3], args[4], args[5]}},
            args[6], args[7]);
        } else {
            kf_cv_1d_init(&filter, 0, 0,
            &(const struct matrix){.rows = KF_CV_1D_STATE_DIM, .columns = KF_CV_1D_STATE_DIM, .data = {1, 0, 0, 1}},
            0, 1);
            if (argv[1][0] == 'd') kf_cv_1d_predict(&filter, value);
            if (argv[1][0] == 'c') kf_cv_1d_correct(&filter, value);
            if (argv[1][0] == 'w') kf_cv_1d_correct_angle(&filter, value);
        }
        return 0;
    }
    if (argc != 2) return 2;
    if (argv[1][0] == 'n') wrap_angle_rad(NAN);
    if (argv[1][0] == 'i') wrap_angle_rad(INFINITY);
    if (argv[1][0] == 'm') wrap_angle_rad(-INFINITY);
    if (argv[1][0] == 'r') ring_init(NULL);
    if (argv[1][0] == 'z') {
        struct kf_cv_1d_filter filter;
        kf_cv_1d_init(&filter, 0, 0, NULL, 0, 1);
    }
    if (argv[1][0] == 'p') {
        struct frame_parser parser;
        frame_parser_init(&parser);
        parser.state = 99;
        frame_parser_feed(&parser, 0);
    }
    if (argv[1][0] == 'k') {
        struct kf_cv_1d_filter filter;
        kf_cv_1d_init(&filter, 0, 0,
            &(const struct matrix){.rows = KF_CV_1D_STATE_DIM, .columns = KF_CV_1D_STATE_DIM, .data = {1, 0, 0, 1}},
            INFINITY, 1);
    }
    return 0;
}
''')
    executable = folder / "probe"
    sdk = Path("/Applications/Xcode.app/Contents/Developer/Platforms/MacOSX.platform/Developer/SDKs/MacOSX.sdk")
    sdk_flags = ["-isysroot", str(sdk)] if sdk.exists() else []
    sources = ["common/ring_buffer.c", "protocol/frame_parser.c",
               "protocol/protocol_frame.c", "common/crc16.c",
               "tracking/estimators/filters/kf_cv_1d.c", "tracking/angle_utils.c"]
    subprocess.run([str(compiler), *sdk_flags, "-std=c11", "-DNDEBUG",
                    "-Wall", "-Wextra", "-Werror", "-I", str(src),
                    "-I", str(root / "fcc_app/tests/common/include"), str(probe),
                    *(str(src / name) for name in sources), "-lm", "-o", str(executable)],
                   check=True)
    return executable


@pytest.mark.parametrize("mode,message", [
    ("ring", "Ring buffer pointer is NULL"),
    ("parser", "Invalid parser state: 99"),
    ("kalman", "Process noise must be finite and nonnegative"),
    ("zero_covariance_pointer", "Initial covariance pointer is NULL"),
    ("nan", "Angle value must be finite"),
    ("infinity", "Angle value must be finite"),
    ("minus_infinity", "Angle value must be finite"),
])
def test_internal_contract_asserts_even_with_ndebug(assertion_probe, mode, message):
    result = subprocess.run([str(assertion_probe), mode], capture_output=True, text=True, timeout=5)
    assert result.returncode == -signal.SIGABRT
    assert message in result.stderr


@pytest.mark.parametrize('field', range(8))
@pytest.mark.parametrize('value', ['nan', 'inf', '-inf'])
def test_kalman_init_each_nonfinite_argument(assertion_probe, field, value):
    result = subprocess.run([str(assertion_probe), 'args', str(field), value],
                            capture_output=True, text=True, timeout=5)
    assert result.returncode == -signal.SIGABRT
    assert 'must be finite' in result.stderr


@pytest.mark.parametrize('field,value,valid', [
    (2, '-0.000001', False), (2, '0', True),
    (5, '-0.000001', False), (5, '0', True),
    (6, '-0.000001', False), (6, '0', True),
    (7, '-0.000001', False), (7, '0', False), (7, '0.000001', True),
])
def test_kalman_variance_zero_boundaries(assertion_probe, field, value, valid):
    result = subprocess.run([str(assertion_probe), 'args', str(field), value],
                            capture_output=True, text=True, timeout=5)
    assert result.returncode == (0 if valid else -signal.SIGABRT)


@pytest.mark.parametrize('mode', ['dt', 'correct', 'wrap_correct'])
@pytest.mark.parametrize('value', ['nan', 'inf', '-inf'])
def test_kalman_update_nonfinite_arguments(assertion_probe, mode, value):
    result = subprocess.run([str(assertion_probe), mode, '0', value],
                            capture_output=True, text=True, timeout=5)
    assert result.returncode == -signal.SIGABRT


@pytest.mark.parametrize('value,valid', [('-0.000001', False), ('0', True), ('0.000001', True)])
def test_kalman_prediction_interval_zero_boundary(assertion_probe, value, valid):
    result = subprocess.run([str(assertion_probe), 'dt', '0', value],
                            capture_output=True, text=True, timeout=5)
    assert result.returncode == (0 if valid else -signal.SIGABRT)


@pytest.mark.parametrize('field', [0, 1])
@pytest.mark.parametrize('size', [0, 1, 3, 4])
def test_kf_covariance_requires_two_by_two(assertion_probe, field, size):
    result = subprocess.run([str(assertion_probe), 'shape', str(field), str(size)],
                            capture_output=True, text=True, timeout=5)
    assert result.returncode == -signal.SIGABRT
    assert 'Initial covariance must be 2x2' in result.stderr
