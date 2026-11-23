"""Check performance bench evidence parsing without serial I/O or flashing."""
import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / 'fcc_app/tests/test_perf_monitor/board_check.py'
spec = importlib.util.spec_from_file_location('perf_board_check', SCRIPT)
board_check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(board_check)


def summary(uptime=5000, omit=None, execution=True, modern=True):
    # Deliberately fixed text, independent of the firmware's formatting implementation.
    lines = [f'PERF uptime_ms={uptime} measurements=3 without_submit=0 submit_failed=0 invalid_time=0']
    lines += [f'PERF {name}: n=3 total_ms=2 p50_bin=1 p95_bin=1 p99_bin=1 max_ms=1 over20=0'
              for name in ('queue_wait', 'processing', 'rx_to_submit')]
    if execution:
        lines += ['PERF estimator_predict: n=3 min_ns=100 mean_ns=200 max_ns=300',
                  'PERF estimator_correct: n=0 no samples']
    lines += [f'PERF queue {name}: accepted=4 rejected=0 observed_max_used=1' for name in ('rx', 'tx')]
    lines += ['PERF tx: poll_completed=4 encode_failed=0']
    lines += [f'PERF stack {name}: unused=700 min_unused=680' for name in ('rx', 'handler', 'tx')]
    if modern:
        lines = [line.replace('PERF uptime_ms=', 'PERF summary: uptime_ms=')
                 .replace(' over20=', ' over_budget_count=')
                 .replace(' unused=', ' unused_bytes=').replace(' min_unused=', ' min_unused_bytes=')
                 .replace('n=0 no samples', 'n=0 status=no_samples') for line in lines]
    return ''.join('\x1b[0m<inf> radar_perf: ' + line + '\x1b[0m\r\n'
                   for line in lines if omit is None or not line.startswith(omit))


@pytest.mark.parametrize('bytewise', [False, True])
@pytest.mark.parametrize('execution', [False, True])
@pytest.mark.parametrize('modern', [False, True])
def test_perf_console_handles_serial_chunks(bytewise, execution, modern):
    parser = board_check.PerfConsole()
    text = summary(execution=execution, modern=modern)
    for chunk in text if bytewise else [text]:
        parser.feed(chunk)
    assert len(parser.snapshots) == 1
    assert parser.snapshots[0]['header']['uptime_ms'] == 5000
    assert parser.snapshots[0]['stack tx']['min_unused'] == 680
    if execution:
        assert parser.snapshots[0]['estimator_predict']['mean_ns'] == 200
        assert parser.snapshots[0]['estimator_correct'] == {'n': 0}


def test_perf_console_discards_incomplete_summary_before_next_header():
    parser = board_check.PerfConsole()
    parser.feed(summary(5000, omit='PERF processing:'))
    assert not parser.snapshots
    parser.feed(summary(10000))
    assert len(parser.snapshots) == 1
    assert parser.snapshots[0]['header']['uptime_ms'] == 10000


@pytest.mark.parametrize('error_fields', ['unavailable=-134', 'status=unavailable error=-134'])
def test_perf_console_keeps_stack_query_errors_visible(error_fields):
    parser = board_check.PerfConsole()
    parser.feed(summary().replace('PERF stack tx: unused_bytes=700 min_unused_bytes=680',
                                  f'PERF stack tx: {error_fields}'))
    assert parser.snapshots[0]['stack tx'] == {'unavailable': -134}


@pytest.mark.parametrize('message', ['ASSERTION FAIL', '***** MPU FAULT *****', '--- 5 messages dropped ---'])
def test_perf_console_flags_invalid_evidence(message):
    parser = board_check.PerfConsole()
    parser.feed(message + '\n')
    assert parser.faults == [message]


def test_perf_console_counts_boots_and_percentile_rank():
    parser = board_check.PerfConsole()
    parser.feed('FCC ready: USART6 RX/TX initialized\n' * 2)
    assert parser.boots == 2
    assert board_check.percentile([], .5) is None
    assert board_check.percentile(list(range(1, 101)), .5) == 50
    assert board_check.percentile(list(range(1, 101)), .99) == 99


def test_rtt_summary_keeps_host_gap_informational():
    result = board_check.timing_summary([6., 7., 35.], [0., .02, .157], 1., 5)
    assert result['host_max_send_gap_ms'] == pytest.approx(137.)
    assert result['actual_measurement_hz'] == 3
    assert result['host_pacing_is_acceptance_gate'] is False
    assert result['host_pacing_is_requested_profile_gate'] is True
    assert result['host_rtt_is_acceptance_gate'] is False
    assert result['pc_latency_ms'] == {'count': 3, 'p50': 7., 'p95': 35., 'p99': 35., 'max': 35.}
    assert [ok for _, ok in board_check.rtt_budget_checks(result)] == [False, True]
    assert [ok for _, ok in board_check.rtt_budget_checks(result, 35., 35.)] == [True, True]
    assert [ok for _, ok in board_check.rtt_budget_checks(result, 34., 34.)] == [False, False]


def test_empty_rtt_cannot_pass_an_explicit_budget():
    result = board_check.timing_summary([], [], 10., 0)
    assert result['pc_latency_ms']['max'] is None
    assert [ok for _, ok in board_check.rtt_budget_checks(result, 10., 20.)] == [False, False]


def test_default_rtt_budgets_include_boundaries_and_reject_excess():
    def verdict(values):
        result = board_check.timing_summary(values, [0., .137], 1., 0)
        return [ok for _, ok in board_check.rtt_budget_checks(result)]
    assert verdict([20.] * 99 + [100.]) == [True, True]
    assert verdict([20.001] * 99 + [100.]) == [False, True]
    assert verdict([20.] * 99 + [100.001]) == [True, False]


def test_extended_perf_fields_and_main_stack_are_retained():
    parser = board_check.PerfConsole()
    additions = ''.join(f'PERF {name}: n=3 max_ms=20 over_budget_count=0\n'
                        for name in ('rx_byte_wait', 'tx_queue_wait', 'tx_poll', 'parsed_to_tx_poll'))
    additions += ''.join(f'PERF {name}: n=3 min_ns=10 mean_ns=20 max_ns=30\n'
                         for name in ('rx_isr', 'rx_parser'))
    additions += 'PERF cpu: uptime_ms=5000 total_cycles=100 busy_cycles=40 idle_cycles=60\n'
    additions += 'PERF stack main: unused_bytes=512 min_unused_bytes=256\n'
    parser.feed(summary().replace('PERF stack tx:', additions + 'PERF stack tx:'))
    last = parser.snapshots[-1]
    assert last['parsed_to_tx_poll']['over20'] == 0
    assert last['rx_isr']['max_ns'] == 30
    assert last['cpu']['total_cycles'] == 100
    assert last['stack main']['min_unused'] == 256
    assert parser.incomplete_summaries == 0


def test_incomplete_summary_is_counted_even_when_later_snapshot_is_complete():
    parser = board_check.PerfConsole()
    parser.feed(summary(5000, omit='PERF processing:') + summary(10000))
    assert parser.incomplete_summaries == 1
    assert len(parser.snapshots) == 1


def test_host_gap_jitter_preserved_explicitly():
    result = board_check.timing_summary([1, 2, 3], [0, .02, .05], .06, 0)
    assert result['host_send_gap_ms']['max'] == pytest.approx(30)
    assert result['host_absolute_period_error_ms']['max'] == pytest.approx(10)


@pytest.mark.parametrize('restore_fails', [False, True])
@pytest.mark.parametrize('host_interrupted', [False, True])
def test_runner_abort_still_restores_and_writes_inconclusive_verdicts(tmp_path, monkeypatch,
                                                                  restore_fails, host_interrupted):
    """Exercise run's actual exception/finally path without serial or flashing."""
    import argparse
    import json

    for name, config in [('build_perf', 'CONFIG_RADAR_PERF_MONITOR=y'), ('build', '')]:
        path = tmp_path / name / 'zephyr'
        path.mkdir(parents=True)
        (path / '.config').write_text(config + '\nCONFIG_RADAR_MEASUREMENT_TIMEOUT_MS=1000\n')
        (path / 'zephyr.hex').write_text('fake')
        (path / 'zephyr.elf').write_text('fake')
    (tmp_path / 'pc_sim').mkdir()
    for name in ('async_recording.py', 'perf_acceptance.py'):
        (tmp_path / 'pc_sim' / name).write_text('fake source')
    monkeypatch.setattr(board_check, 'ROOT', tmp_path)
    monkeypatch.setattr(board_check.subprocess, 'check_output', lambda *a, **k: 'fake-commit')
    flashes = []

    def flash(command, **kwargs):
        flashes.append(command)
        if restore_fails:
            raise RuntimeError('restore failed')

    class FakeSerial:
        def __init__(self, port, *a, **k):
            if port == 'console':
                if host_interrupted:
                    board_check.check_input_continuity(0, 0., 20, 1.16, 1000)
                raise RuntimeError('console unavailable')

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    monkeypatch.setattr(board_check.subprocess, 'run', flash)
    monkeypatch.setattr(board_check.serial, 'Serial', FakeSerial)
    monkeypatch.setattr(board_check, 'request_status', lambda data: {'errors': 0})
    monkeypatch.setattr(board_check.time, 'sleep', lambda duration: None)
    args = argparse.Namespace(output=tmp_path / 'new-evidence', duration=10, smoke=False,
                              pc_rtt_p99_ms=20, pc_rtt_max_ms=100, git='git', west='west',
                              data_port='data', console_port='console', workspace=tmp_path)
    assert board_check.run(args) == 1
    assert len(flashes) == 1 and str(tmp_path / 'build') in flashes[0]
    result = json.loads((args.output / 'results.json').read_text())
    assert not result['passed'] and not result['run_completed']
    if host_interrupted:
        assert result['failure'] is None
        assert result['host_input_interruption']['host_gap_ms'] == pytest.approx(1160)
        assert result['verdicts']['board_internal']['status'] == 'inconclusive'
    else:
        assert 'console unavailable' in result['failure']
        assert result['host_input_interruption'] is None
    assert bool(result['restore_failure']) == restore_fails
    assert all(v['status'] != 'passed' for v in result['verdicts'].values())


def test_runtime_failure_is_recorded_before_abort():
    checks = []
    with pytest.raises(AssertionError, match='CRC'):
        board_check.runtime_failure(checks, 'board CRC error', 'delivery')
    assert checks == [{'name': 'board CRC error', 'passed': False, 'category': 'delivery'}]


@pytest.mark.parametrize('sent_s,sensor_ms,interrupted', [
    (.999, 999, False), (1., 1000, True),
    (.02, 1000, False), (.02, 1001, True),
])
def test_load_input_continuity_boundaries(sent_s, sensor_ms, interrupted):
    args = (0, 0., sensor_ms, sent_s, 1000)
    if interrupted:
        with pytest.raises(board_check.HostInputInterrupted):
            board_check.check_input_continuity(*args)
    else:
        board_check.check_input_continuity(*args)


def test_load_input_guard_uses_configured_receive_timeout():
    with pytest.raises(board_check.HostInputInterrupted) as error:
        board_check.check_input_continuity(0, 0., 20, .5, 500)
    assert error.value.details['receive_timeout_ms'] == 500
    board_check.check_input_continuity(0, 0., 20, .5, 1000)


def test_captured_host_gap_is_detected_before_the_false_board_rejection():
    # Actual pre-write timestamps from final-validation-2026-11-23.
    with pytest.raises(board_check.HostInputInterrupted) as error:
        board_check.check_input_continuity(1537180, 596549.987482458,
                                           1537200, 596551.147064708, 1000)
    assert error.value.details['host_gap_ms'] == pytest.approx(1159.582250)
    assert error.value.details['sensor_interval_ms'] == 20
    # The next send's sensor gap is independently inconsistent with steady load.
    with pytest.raises(board_check.HostInputInterrupted) as error:
        board_check.check_input_continuity(1537200, 596551.147064708,
                                           1538340, 596551.179224791, 1000)
    assert error.value.details['sensor_interval_ms'] == 1140


def test_first_input_and_normal_sensor_wrap_do_not_interrupt_load():
    board_check.check_input_continuity(None, None, 0, 500., 1000)
    board_check.check_input_continuity(0xfffffff0, 500., 4, 500.02, 1000)


def test_input_guard_does_not_exempt_backward_timestamps():
    # Backward/duplicate input still reaches the existing strict response checks.
    board_check.check_input_continuity(20, 0., 0, .02, 1000)
    board_check.check_input_continuity(20, 0., 20, .02, 1000)


def test_sensor_interval_limit_matches_firmware_contract():
    source = SCRIPT.parents[3] / 'fcc_app/src/application/radar_processor.c'
    assert f'#define TRACK_MAX_PREDICTION_INTERVAL_MS {board_check.MAX_SENSOR_INTERVAL_MS}U' in source.read_text()


@pytest.mark.parametrize('io_finished_s,expected_sleeps', [
    (.020, []), (.021, []), (.0195, [.0005]), (.005, [.001]),
])
def test_pump_does_not_sleep_after_io_reaches_deadline(io_finished_s, expected_sleeps):
    """Exercise the real nested pump when receive work consumes its time budget."""
    from types import CellType, CodeType, FunctionType, SimpleNamespace
    from unittest.mock import Mock

    clock = SimpleNamespace(now=0., sleeps=[])
    clock.monotonic = lambda: clock.now

    def sleep(seconds):
        clock.sleeps.append(seconds)
        clock.now = .020

    def read(size):
        clock.now = io_finished_s
        return b''

    clock.sleep = sleep
    console = Mock(in_waiting=0)
    console.read.return_value = b''
    data = Mock(in_waiting=0)
    data.read.side_effect = read
    decoder = Mock(crc_errors=0, length_errors=0)
    decoder.feed.return_value = []
    environment = dict(console=console, data=data, decoder=decoder, recorder=Mock(),
                       sequence=None, received_measurements=0, checks=[], reports=[],
                       statuses=[], sent_at={}, latencies=[],
                       snapshot_parser=SimpleNamespace(faults=[], boots=1))
    # Bind the actual fixture code to test doubles without opening ports or flashing.
    code = next(value for value in board_check.run.__code__.co_consts
                if isinstance(value, CodeType) and value.co_name == 'pump_until')
    pump = FunctionType(code, {**board_check.__dict__, 'time': clock},
                        closure=tuple(CellType(environment[name]) for name in code.co_freevars))
    pump(.020)
    assert clock.sleeps == pytest.approx(expected_sleeps)
    data.read.assert_called_once_with(0)
    decoder.feed.assert_called_once_with(b'')
