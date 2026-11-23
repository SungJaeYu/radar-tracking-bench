"""Independent acceptance groups must never infer success from absent evidence."""
from copy import deepcopy
import pytest
from pc_sim.perf_acceptance import evaluate_acceptance, REQUIRED_CHECKS


def evidence():
    last = {name: {'n': 500, 'max_ms': 20, 'over20': 0} for name in
            ('queue_wait', 'processing', 'rx_to_submit', 'rx_byte_wait',
             'tx_queue_wait', 'tx_poll', 'parsed_to_tx_poll')}
    last.update({name: {'n': 500, 'min_ns': 0, 'mean_ns': 10, 'max_ns': 20}
                 for name in ('rx_isr', 'rx_parser', 'estimator_predict', 'estimator_correct')})
    last['tx'] = {'poll_completed': 500, 'encode_failed': 0}
    last['header'] = {'uptime_ms': 10000, 'measurements': 500, 'without_submit': 0,
                      'submit_failed': 0, 'invalid_time': 0, 'rx_capture_lost': 0}
    last.update({'queue ' + name: {'accepted': 500, 'rejected': 0, 'observed_max_used': 1}
                 for name in ('rx', 'tx')})
    snapshots = [{**deepcopy(last), 'cpu': {'uptime_ms': t, 'total_cycles': total, 'busy_cycles': busy,
                          'idle_cycles': total - busy},
                  **{'stack ' + n: {'unused': margin, 'min_unused': margin}
                     for n, margin in [('rx', 256), ('tx', 256), ('main', 256), ('handler', 512)]}}
                 for t, total, busy in [(5000, 100, 40), (10000, 200, 120)]]
    return dict(sent_wire_bytes=500, performance_snapshots=snapshots, run_completed=True, recording_complete=True, duration_s=10,
                load_elapsed_s=10, load_measurements=500, host_skipped_slots=0,
                valid_measurements_total=500, last_performance=last,
                console_complete=True, console_boots=1, console_faults=[],
                performance_summary_count=2,
                recording={'enqueued': 100, 'written': 100}, failure=None,
                restore_failure=None, checks=[{'name': name, 'passed': True, 'category': category}
                    for category, names in REQUIRED_CHECKS.items() for name in names],
                pc_latency_ms={'count': 500, 'p99': 20, 'max': 100})


def test_rtt_only_failure_does_not_fail_board():
    result = evidence()
    result['pc_latency_ms']['max'] = 100.001
    verdict = evaluate_acceptance(result)
    assert verdict['verdicts']['host_rtt']['status'] == 'failed'
    assert verdict['board_qualification']['status'] == 'passed'
    assert verdict['passed']
    assert verdict['requested_profile_passed']
    assert not verdict['full_coverage']


def test_exact_budgets_pass_observed_profile():
    assert evaluate_acceptance(evidence())['passed']


@pytest.mark.parametrize('name', ['rx_byte_wait', 'tx_queue_wait', 'tx_poll', 'parsed_to_tx_poll',
                                 'rx_isr', 'rx_parser', 'estimator_predict', 'estimator_correct'])
@pytest.mark.parametrize('mode', ['missing', 'zero'])
def test_extended_metrics_required(name, mode):
    result = evidence()
    if mode == 'missing':
        del result['last_performance'][name]
    else:
        result['last_performance'][name]['n'] = 0
    assert evaluate_acceptance(result)['verdicts']['board_internal']['status'] == 'inconclusive'
    assert not evaluate_acceptance(result)['passed']


def test_board_failure_with_good_rtt():
    result = evidence()
    result['last_performance']['tx_poll']['max_ms'] = 21
    verdict = evaluate_acceptance(result)
    assert verdict['verdicts']['board_internal']['status'] == 'failed'
    assert verdict['verdicts']['host_rtt']['status'] == 'passed'


@pytest.mark.parametrize('updates', [dict(run_completed=False, failure='abort'),
    dict(recording_complete=False), dict(restore_failure='flash failed'),
    dict(load_measurements=499, host_skipped_slots=1), dict(console_complete=False),
    dict(performance_summary_count=0)])
def test_incomplete_evidence_prevents_qualification(updates):
    result = evidence()
    result.update(updates)
    assert evaluate_acceptance(result)['requested_profile_qualification']['status'] != 'passed'
    assert evaluate_acceptance(result)['passed'] == (updates == dict(load_measurements=499, host_skipped_slots=1))


@pytest.mark.parametrize('metric', ['tx_queue_wait', 'tx_poll', 'parsed_to_tx_poll'])
def test_counts_reconcile(metric):
    result = evidence()
    result['last_performance'][metric]['n'] -= 1
    assert evaluate_acceptance(result)['verdicts']['board_internal']['status'] == 'failed'


@pytest.mark.parametrize('value', [float('nan'), float('inf'), -1, 21])
def test_incoherent_execution_observations(value):
    result = evidence()
    result['last_performance']['rx_isr']['mean_ns'] = value
    assert not evaluate_acceptance(result)['passed']


def test_requested_load_separate_from_observed_board():
    result = evidence()
    result.update(host_skipped_slots=1, load_measurements=499)
    verdict = evaluate_acceptance(result)
    assert verdict['board_qualification']['status'] == 'passed'
    assert verdict['verdicts']['requested_load']['status'] == 'inconclusive'
    assert verdict['passed']
    assert not verdict['requested_profile_passed']


@pytest.mark.parametrize('mode', ['missing', 'zero', 'nonmonotone', 'incoherent', 'over80'])
def test_cpu_observations_are_required(mode):
    result = evidence()
    cpu = result['performance_snapshots'][-1]['cpu']
    if mode == 'missing':
        del result['performance_snapshots'][-1]['cpu']
    elif mode == 'zero':
        cpu.update(total_cycles=0, busy_cycles=0, idle_cycles=0)
    elif mode == 'nonmonotone':
        cpu.update(total_cycles=50, busy_cycles=20, idle_cycles=30)
    elif mode == 'incoherent':
        cpu['busy_cycles'] += 1
    else:
        cpu.update(total_cycles=200, busy_cycles=121, idle_cycles=79)
    assert not evaluate_acceptance(result)['passed']


@pytest.mark.parametrize('name,limit', [('rx', 256), ('tx', 256), ('main', 256), ('handler', 512)])
def test_sampled_stack_margin(name, limit):
    result = evidence()
    result['performance_snapshots'][-1]['stack ' + name]['min_unused'] = limit - 1
    assert evaluate_acceptance(result)['verdicts']['board_internal']['status'] == 'failed'


def test_all_independent_failures_are_collected():
    result = evidence()
    result['pc_latency_ms'].update(p99=21, max=101)
    result['last_performance']['tx_poll']['max_ms'] = 21
    result['recording']['written'] = 99
    result['restore_failure'] = 'restore failed'
    result['checks'].append({'name': 'missing delivery', 'passed': False, 'category': 'delivery'})
    verdict = evaluate_acceptance(result)
    assert all(verdict['verdicts'][k]['status'] != 'passed'
               for k in ('board_internal', 'host_rtt', 'delivery', 'evidence'))
    assert len(verdict['verdicts']['host_rtt']['reasons']) == 2
    assert len(verdict['verdicts']['evidence']['reasons']) == 2


@pytest.mark.parametrize('key', ['p99', 'max', 'count'])
@pytest.mark.parametrize('value', [None, float('nan'), float('inf')])
def test_missing_rtt_never_passes(key, value):
    result = evidence()
    result['pc_latency_ms'][key] = value
    assert evaluate_acceptance(result)['verdicts']['host_rtt']['status'] == 'inconclusive'


def test_abort_never_yields_passed_unassessed_groups():
    result = evidence()
    result.update(run_completed=False, failure='catastrophic receive error')
    verdict = evaluate_acceptance(result)
    assert all(g['status'] != 'passed' for g in verdict['verdicts'].values())


def test_missing_main_stack_is_inconclusive():
    result = evidence()
    del result['performance_snapshots'][0]['stack main']
    assert evaluate_acceptance(result)['verdicts']['board_internal']['status'] == 'inconclusive'


@pytest.mark.parametrize('metric', ['rx_byte_wait', 'rx_parser'])
def test_rx_byte_samples_reconcile_to_successfully_sent_wire_bytes(metric):
    result = evidence()
    result['last_performance'][metric]['n'] -= 1
    verdict = evaluate_acceptance(result)
    assert verdict['verdicts']['board_internal']['status'] == 'failed'


def test_missing_sent_byte_count_is_inconclusive():
    result = evidence()
    del result['sent_wire_bytes']
    verdict = evaluate_acceptance(result)
    assert verdict['verdicts']['board_internal']['status'] == 'inconclusive'
    assert not verdict['passed']


@pytest.mark.parametrize('metric', ['rx_isr', 'rx_byte_wait', 'queue rx', 'header', 'cpu', 'stack main'])
def test_missing_early_extended_fields_prevents_evidence_pass(metric):
    result = evidence()
    del result['performance_snapshots'][0][metric]
    verdict = evaluate_acceptance(result)
    assert verdict['verdicts']['evidence']['status'] == 'inconclusive'
    assert not verdict['passed']


def test_idle_zero_samples_do_not_invalidate_complete_extended_snapshot():
    result = evidence()
    for metric in ('queue_wait', 'processing', 'rx_to_submit', 'rx_byte_wait',
                   'tx_queue_wait', 'tx_poll', 'parsed_to_tx_poll', 'rx_isr',
                   'rx_parser', 'estimator_predict', 'estimator_correct'):
        result['performance_snapshots'][0][metric] = {'n': 0}
    assert evaluate_acceptance(result)['passed']


def test_missing_required_delivery_guard_is_inconclusive():
    result = evidence()
    result['checks'] = [check for check in result['checks'] if check['name'] != 'all measurements matched once']
    verdict = evaluate_acceptance(result)
    assert verdict['verdicts']['delivery']['status'] == 'inconclusive'
    assert not verdict['passed']


def test_known_delivery_failure_survives_abort():
    result = evidence()
    result['run_completed'] = False
    result['failure'] = 'board CRC error'
    result['checks'].append({'name': 'board CRC error', 'passed': False, 'category': 'delivery'})
    verdict = evaluate_acceptance(result)
    assert verdict['verdicts']['delivery']['status'] == 'failed'
    assert verdict['verdicts']['board_internal']['status'] == 'inconclusive'
    assert verdict['board_qualification']['status'] == 'failed'
    assert not verdict['passed']


def test_aborted_snapshot_does_not_fail_for_undrained_traffic_counts():
    result = evidence()
    result['run_completed'] = False
    result['sent_wire_bytes'] = 510
    result['valid_measurements_total'] = 510
    verdict = evaluate_acceptance(result)
    assert verdict['verdicts']['board_internal']['status'] == 'inconclusive'
    result['last_performance']['tx_poll']['max_ms'] = 21
    assert evaluate_acceptance(result)['verdicts']['board_internal']['status'] == 'failed'


def test_isr_capture_loss_cannot_pass():
    result = evidence()
    result['performance_snapshots'][0]['header']['rx_capture_lost'] = 1
    assert evaluate_acceptance(result)['verdicts']['board_internal']['status'] == 'failed'

def test_missing_capture_loss_counter_is_inconclusive():
    result = evidence()
    del result['performance_snapshots'][0]['header']['rx_capture_lost']
    assert evaluate_acceptance(result)['verdicts']['evidence']['status'] == 'inconclusive'


@pytest.mark.parametrize('metric', ['rx_byte_wait', 'tx_poll', 'parsed_to_tx_poll'])
def test_earlier_latency_violation_cannot_be_hidden_by_final_summary(metric):
    result = evidence()
    result['performance_snapshots'][0][metric]['max_ms'] = 21
    assert evaluate_acceptance(result)['verdicts']['board_internal']['status'] == 'failed'

@pytest.mark.parametrize('metric,field', [('header','invalid_time'), ('queue rx','rejected'), ('tx','encode_failed')])
def test_earlier_error_cannot_be_hidden_by_final_summary(metric, field):
    result = evidence()
    result['performance_snapshots'][0][metric][field] = 1
    assert evaluate_acceptance(result)['verdicts']['board_internal']['status'] == 'failed'

def test_negative_rtt_diagnostic_cannot_fail_board():
    result = evidence()
    result['pc_latency_ms']['max'] = -1
    verdict = evaluate_acceptance(result)
    assert verdict['verdicts']['host_rtt']['status'] == 'failed'
    assert verdict['passed']

def test_failed_profile_does_not_mislabel_observed_board():
    result = evidence()
    result.update(host_skipped_slots=5,load_measurements=495)
    result['pc_latency_ms']['max'] = 300
    verdict = evaluate_acceptance(result)
    assert verdict['passed'] and not verdict['requested_profile_passed']
    assert verdict['passed_scope'] == 'observed_board_delivery_evidence'


@pytest.mark.parametrize('run_completed', [False, True])
def test_host_input_interruption_is_inconclusive_not_board_failure(run_completed):
    result = evidence()
    result.update(run_completed=run_completed,
                  host_input_interruption={'host_gap_ms': 1159.582, 'sensor_interval_ms': 20})
    verdict = evaluate_acceptance(result)
    assert verdict['verdicts']['board_internal']['status'] == 'inconclusive'
    assert verdict['verdicts']['requested_load']['status'] == 'inconclusive'
    assert verdict['board_qualification']['status'] == 'inconclusive'
    assert not verdict['passed'] and not verdict['requested_profile_passed']
    assert any('host input' in reason for reason in verdict['verdicts']['requested_load']['reasons'])


@pytest.mark.parametrize('failure', ['latency', 'crc', 'queue', 'cpu', 'stack', 'capture', 'restore'])
def test_host_input_interruption_does_not_hide_real_failures(failure):
    result = evidence()
    result.update(run_completed=False, host_input_interruption={'host_gap_ms': 1159.582})
    if failure == 'latency':
        result['performance_snapshots'][0]['tx_poll']['max_ms'] = 21
    elif failure == 'crc':
        result['checks'].append({'name': 'board CRC error', 'passed': False, 'category': 'delivery'})
    elif failure == 'queue':
        result['performance_snapshots'][0]['queue rx']['rejected'] = 1
    elif failure == 'cpu':
        result['performance_snapshots'][-1]['cpu'].update(busy_cycles=121, idle_cycles=79)
    elif failure == 'stack':
        result['performance_snapshots'][0]['stack main']['min_unused'] = 255
    elif failure == 'capture':
        result['performance_snapshots'][0]['header']['rx_capture_lost'] = 1
    else:
        result['restore_failure'] = 'restore failed'
    verdict = evaluate_acceptance(result)
    assert verdict['board_qualification']['status'] == 'failed'
    assert not verdict['passed']
