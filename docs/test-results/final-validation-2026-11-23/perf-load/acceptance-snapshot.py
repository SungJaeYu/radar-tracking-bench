"""Strict, independent verdicts for the extended observed PERF profile.

Execution timings describe observations only: no WCET limit has been specified.
"""
import math

ACCEPTANCE_REVISION = '2026-11-23-board-only-v2'

LATENCIES = ('queue_wait', 'processing', 'rx_to_submit', 'rx_byte_wait',
             'tx_queue_wait', 'tx_poll', 'parsed_to_tx_poll')
EXECUTIONS = ('rx_isr', 'rx_parser', 'estimator_predict', 'estimator_correct')
STACK_MARGINS = {'rx': 256, 'tx': 256, 'handler': 512, 'main': 256}
STACK_ALLOCATED = {'rx': 1024, 'tx': 1024, 'handler': 2048, 'main': 1024}
REQUIRED_CHECKS = {
    'delivery': ('all measurements matched once', 'all STATUS requests answered',
                 'one post-load timeout report', 'initial STATUS zero',
                 'INIT reset report received', 'RX accepted frame count',
                 'TX queued and polling counts match received frames'),
    'evidence': ('idle performance summary', 'single firmware boot',
                 'performance summaries remain continuous', 'restored normal STATUS zero'),
    'board_internal': ('idle timing has no samples', 'idle stack queries available',
                       'measurement count reconciles', 'no submit failures or invalid times',
                       'invalid measurement is counted without submission',
                       'processing successful sample count', 'rx_to_submit successful sample count',
                       'queue wait count includes invalid input', '20ms board latency budget',
                       'no queue rejection', 'no TX encoder failures',
                       'all sampled stacks have headroom'),
}
GAPS = ['physical RX arrival to ISR entry is unmeasured',
        'physical TX last stop bit is unmeasured',
        'true WCET and execution-time acceptance limits are unestablished',
        'physical CPU utilization and accurate ISR attribution are unmeasured',
        'hardware fault campaigns are not performed',
        'sampled stack headroom is not a stack safety certification']


def finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def combine(groups):
    status = ('failed' if any(g['status'] == 'failed' for g in groups) else
              'inconclusive' if any(g['status'] == 'inconclusive' for g in groups) else 'passed')
    return {'status': status, 'reasons': [r for g in groups for r in g['reasons']]}


def evaluate_acceptance(result, snapshots=None):
    groups = {name: {'status': 'passed', 'reasons': []} for name in
              ('board_internal', 'delivery', 'evidence', 'host_rtt', 'requested_load')}

    def mark(group, reason, status='inconclusive'):
        value = groups[group]
        if value['status'] != 'failed':
            value['status'] = status
        value['reasons'].append(reason)

    if not result.get('run_completed'):
        for group in groups:
            mark(group, 'run aborted or final assessment incomplete')
    for check in result.get('checks', []):
        if not check['passed']:
            mark(check.get('category', 'evidence'), check['name'], 'failed')
    present_checks = {(check.get('category'), check.get('name'))
                      for check in result.get('checks', [])}
    for category, names in REQUIRED_CHECKS.items():
        for name in names:
            if (category, name) not in present_checks:
                mark(category, 'required guard absent: ' + name)
    last = result.get('last_performance', {})
    for name in LATENCIES + EXECUTIONS:
        metric = last.get(name, {})
        if not finite(metric.get('n')) or metric['n'] <= 0:
            mark('board_internal', name + ': positive sample count missing')
            continue
        if name in LATENCIES:
            if not all(finite(metric.get(k)) for k in ('max_ms', 'over20')):
                mark('board_internal', name + ': latency fields missing')
            elif metric['max_ms'] < 0 or metric['max_ms'] > 20 or metric['over20'] != 0:
                mark('board_internal', name + ': 20ms budget or coherent observations violated', 'failed')
        else:
            fields = [metric.get(k) for k in ('min_ns', 'mean_ns', 'max_ns')]
            if not all(finite(v) for v in fields):
                mark('board_internal', name + ': finite execution observations missing')
            elif not 0 <= fields[0] <= fields[1] <= fields[2]:
                mark('board_internal', name + ': incoherent execution observations', 'failed')
    for name, expected in [('rx_byte_wait', result.get('sent_wire_bytes')),
                           ('rx_parser', result.get('sent_wire_bytes')),
                           ('tx_queue_wait', last.get('tx', {}).get('poll_completed')),
                           ('tx_poll', last.get('tx', {}).get('poll_completed')),
                           ('parsed_to_tx_poll', result.get('valid_measurements_total'))]:
        n = last.get(name, {}).get('n')
        if not finite(expected) or expected <= 0:
            mark('board_internal', name + ': reconciliation count missing')
        elif finite(n) and n > 0 and n != expected:
            mark('board_internal', name + ': sample count does not reconcile' if result.get('run_completed') else name + ': partial snapshot cannot reconcile final traffic',
                 'failed' if result.get('run_completed') else 'inconclusive')
    snapshots = result.get('performance_snapshots', []) if snapshots is None else snapshots
    cpu_windows = []
    previous = None
    if len(snapshots) < 2:
        mark('board_internal', 'CPU and sampled stack snapshots insufficient')
    required_fields = {
        'header': ('uptime_ms', 'measurements', 'without_submit', 'submit_failed', 'invalid_time', 'rx_capture_lost'),
        'queue rx': ('accepted', 'rejected', 'observed_max_used'),
        'queue tx': ('accepted', 'rejected', 'observed_max_used'),
        'tx': ('poll_completed', 'encode_failed'),
        'cpu': ('uptime_ms', 'total_cycles', 'busy_cycles', 'idle_cycles'),
        **{'stack ' + name: ('unused', 'min_unused') for name in STACK_MARGINS},
    }
    for index, snapshot in enumerate(snapshots):
        for name, fields in required_fields.items():
            metric = snapshot.get(name, {})
            if not all(finite(metric.get(key)) for key in fields):
                mark('evidence', f'snapshot {index}: {name} fields incomplete')
        for name in LATENCIES + EXECUTIONS:
            metric = snapshot.get(name, {})
            count = metric.get('n')
            if not finite(count) or count < 0:
                mark('evidence', f'snapshot {index}: {name} sample count absent/invalid')
            elif count > 0:
                fields = ('max_ms', 'over20') if name in LATENCIES else ('min_ns', 'mean_ns', 'max_ns')
                if not all(finite(metric.get(key)) for key in fields):
                    mark('evidence', f'snapshot {index}: {name} sampled fields incomplete')
        if snapshot.get('header', {}).get('rx_capture_lost', 0) != 0:
            mark('board_internal', 'RX timing capture lost or timer service gap exceeded', 'failed')
        # Earlier observations remain evidence even if later counters reset.
        for name in LATENCIES:
            metric = snapshot.get(name, {})
            if (finite(metric.get('max_ms')) and (metric['max_ms'] < 0 or metric['max_ms'] > 20) or
                    finite(metric.get('over20')) and metric['over20'] != 0):
                mark('board_internal', f'snapshot {index}: {name} latency violation', 'failed')
        for name, keys in (('header', ('submit_failed', 'invalid_time')),
                           ('queue rx', ('rejected',)), ('queue tx', ('rejected',)),
                           ('tx', ('encode_failed',))):
            for key in keys:
                value = snapshot.get(name, {}).get(key)
                if finite(value) and value != 0:
                    mark('board_internal', f'snapshot {index}: {name}/{key} error observed', 'failed')
        for name, margin in STACK_MARGINS.items():
            stack = snapshot.get('stack ' + name, {})
            unused, minimum = stack.get('unused'), stack.get('min_unused')
            if not finite(unused) or not finite(minimum):
                mark('board_internal', name + ': sampled stack headroom missing')
            elif not margin <= minimum <= unused <= STACK_ALLOCATED[name]:
                mark('board_internal', name + ': sampled 25% stack reserve or coherent bounds violated', 'failed')
        cpu = snapshot.get('cpu', {})
        keys = ('uptime_ms', 'total_cycles', 'busy_cycles', 'idle_cycles')
        if not all(finite(cpu.get(k)) for k in keys):
            mark('board_internal', 'CPU scheduler counters missing')
            previous = None
            continue
        if (cpu['total_cycles'] <= 0 or min(cpu[k] for k in keys) < 0 or
                cpu['busy_cycles'] + cpu['idle_cycles'] != cpu['total_cycles']):
            mark('board_internal', 'CPU scheduler counters incoherent', 'failed')
            previous = None
            continue
        if previous is not None:
            delta = {k: cpu[k] - previous[k] for k in keys}
            if (delta['total_cycles'] <= 0 or not 0 < delta['uptime_ms'] < 6000 or
                    delta['busy_cycles'] < 0 or delta['idle_cycles'] < 0):
                mark('board_internal', 'CPU scheduler interval counters not monotone/continuous', 'failed')
            else:
                percent = 100 * delta['busy_cycles'] / delta['total_cycles']
                cpu_windows.append({'uptime_ms': cpu['uptime_ms'],
                                    'interval_ms': delta['uptime_ms'], 'non_idle_percent': percent})
                if percent > 80:
                    mark('board_internal', 'CPU scheduler non-idle exceeds 80% interval policy', 'failed')
        previous = cpu
    if not cpu_windows:
        mark('board_internal', 'no coherent CPU scheduler interval observed')
    recording = result.get('recording', {})
    if (not result.get('recording_complete') or not recording.get('enqueued') or
            recording.get('enqueued') != recording.get('written')):
        mark('evidence', 'recording did not finish and drain completely')
    if result.get('failure'):
        mark('evidence', 'run failure: ' + result['failure'])
    if result.get('restore_failure'):
        mark('evidence', 'normal firmware restoration failed: ' + result['restore_failure'], 'failed')
    if not result.get('console_complete') or result.get('performance_summary_count', 0) < 2:
        mark('evidence', 'console/performance summaries incomplete')
    if result.get('console_boots') != 1 or result.get('console_faults'):
        mark('evidence', 'console boot/fault evidence invalid', 'failed')
    duration, elapsed = result.get('duration_s'), result.get('load_elapsed_s')
    if not finite(duration) or duration <= 0 or not finite(elapsed) or elapsed < duration:
        mark('requested_load', 'full requested load duration not observed')
    elif (result.get('load_measurements') != math.ceil(duration * 50) or
          result.get('host_skipped_slots') != 0):
        mark('requested_load', 'requested 50Hz scheduled slots not fully delivered')
    rtt = result.get('pc_latency_ms', {})
    if not finite(rtt.get('count')) or rtt['count'] <= 0:
        mark('host_rtt', 'RTT samples missing')
    for key, limit in [('p99', 20), ('max', 100)]:
        value = rtt.get(key)
        if not finite(value):
            mark('host_rtt', key + ': finite RTT observation missing')
        elif value < 0 or value > limit:
            mark('host_rtt', f'PC RTT {key} exceeds {limit}ms or is invalid', 'failed')
    board = combine([groups[k] for k in ('board_internal', 'delivery', 'evidence')])
    requested = combine([board, groups['requested_load']])
    return dict(verdicts=groups, board_qualification=board,
                requested_profile_qualification=requested,
                passed=board['status'] == 'passed',
                passed_scope='observed_board_delivery_evidence',
                requested_profile_passed=requested['status'] == 'passed',
                acceptance_revision=ACCEPTANCE_REVISION,
                full_coverage=False, coverage_gaps=GAPS,
                cpu_scheduler_windows=cpu_windows,
                cpu_scheduler_scope='non-idle runtime accounting; not physical CPU/ISR utilization or WCET',
                cpu_scheduler_non_idle_limit_percent=80,
                sampled_stack_minimum_bytes=STACK_MARGINS,
                execution_timing_scope='observed min/mean/max only; no execution WCET limits',
                stack_scope='sampled 25% reserve only; no stack safety certification')
