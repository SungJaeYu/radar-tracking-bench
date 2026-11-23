"""Export reproducible figures and tables from the dated, immutable board captures."""
import csv
import hashlib
import html
import json
import math
import os
from pathlib import Path

os.environ.setdefault('MPLCONFIGDIR', '/private/tmp/radar-report-matplotlib')
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'docs/analysis/2026-11-23'
LOAD = ROOT / 'docs/test-results/host-input-retest-2026-11-23/perf-load'
TURN = ROOT / 'docs/test-results/final-validation-2026-11-23/turn'
COLORS = ['#007f78', '#2975b7', '#d57b18', '#8561b5', '#b24f67', '#537d42', '#475569']
LATENCIES = {
    'rx_byte_wait': 'RX byte residence', 'queue_wait': 'Handler queue',
    'processing': 'Handler processing', 'rx_to_submit': 'Parsed → TX submit',
    'tx_queue_wait': 'TX queue', 'tx_poll': 'TX polling',
    'parsed_to_tx_poll': 'Parsed → TX polling',
}


def read_csv(path: Path) -> list[dict]:
    """Read source values without rewriting their capture files."""
    with path.open(newline='') as stream:
        return list(csv.DictReader(stream))


def write_csv(name: str, rows: list[dict]) -> None:
    with (OUT / name).open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def percentile(values: np.ndarray, fraction: float) -> float:
    """Use the runner's nearest-rank convention, not interpolated quantiles."""
    ordered = np.sort(values)
    return float(ordered[max(0, math.ceil(len(ordered) * fraction) - 1)])


def save_figure(fig, name: str, note: str) -> None:
    fig.text(.06, .018, note, fontsize=9, color='#526274')
    fig.savefig(OUT / f'{name}.png', dpi=160, facecolor='white')
    fig.savefig(OUT / f'{name}.svg', facecolor='white')
    plt.close(fig)


def table(rows: list[dict]) -> str:
    headers = ''.join(f'<th>{html.escape(str(k))}</th>' for k in rows[0])
    body = ''.join('<tr>' + ''.join(f'<td>{html.escape(format(v, ".3f") if isinstance(v, float) else str(v))}</td>' for v in r.values()) + '</tr>' for r in rows)
    return f'<div class="table-wrap"><table><thead><tr>{headers}</tr></thead><tbody>{body}</tbody></table></div>'


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    plt.rcParams.update({'font.family': 'DejaVu Sans', 'font.size': 11,
                         'axes.spines.top': False, 'axes.spines.right': False,
                         'axes.labelcolor': '#344456', 'text.color': '#172a3b',
                         'axes.titleweight': 'bold', 'axes.grid': True,
                         'grid.alpha': .16, 'svg.fonttype': 'none'})
    result = json.loads((LOAD / 'results.json').read_text())
    snapshots = json.loads((LOAD / 'performance.json').read_text())
    samples = read_csv(LOAD / 'session/samples.csv')
    reports = read_csv(LOAD / 'session/reports.csv')
    statuses = read_csv(LOAD / 'session/status.csv')
    sent = {int(row['timestamp_ms']): row for row in samples}
    inputs = [r for r in reports if int(r['flags']) & 1]
    assert len(sent) == len(samples) == len(inputs) == result['valid_measurements_total']
    assert {int(r['input_timestamp_ms']) for r in inputs} == set(sent)
    assert len({int(r['input_timestamp_ms']) for r in inputs}) == len(inputs)
    tx = np.array([float(sent[int(r['input_timestamp_ms'])]['tx_monotonic_s']) for r in inputs])
    rx = np.array([float(r['rx_monotonic_s']) for r in inputs])
    rtt = (rx - tx) * 1000
    elapsed = tx - tx[0]
    gaps = np.diff(tx) * 1000
    assert np.all(rtt >= 0) and np.all(np.diff(tx) > 0)
    slow_events = []
    for index in np.flatnonzero(rtt > 100):
        first = max(0, int(np.searchsorted(tx, tx[index], side='right')) - 1)
        stop = min(len(gaps), int(np.searchsorted(tx, rx[index], side='left')))
        overlap = (gaps[first:stop] > 100) & (tx[first + 1:stop + 1] > tx[index]) & (tx[first:stop] < rx[index])
        slow_events.append({'sensor_ms': int(inputs[index]['input_timestamp_ms']),
                            'host_elapsed_s': float(elapsed[index]), 'rtt_ms': float(rtt[index]),
                            'overlaps_send_gap_above_100ms': bool(overlap.any())})
    if slow_events:
        write_csv('slow-rtt-events.csv', slow_events)
    for key, fraction in [('p50', .5), ('p95', .95), ('p99', .99)]:
        assert math.isclose(percentile(rtt, fraction), result['pc_latency_ms'][key], abs_tol=1e-6)
    assert math.isclose(float(rtt.max()), result['pc_latency_ms']['max'], abs_tol=1e-6)
    expected_slots = round(result['duration_s'] * 50)
    sensor_ms = np.array([int(r['timestamp_ms']) for r in samples])
    assert np.all(sensor_ms % 20 == 0)
    slots = sensor_ms // 20
    assert len(set(slots)) == len(slots) and slots.min() >= 0 and slots.max() < expected_slots
    missing = np.setdiff1d(np.arange(expected_slots), slots)
    assert len(missing) == result['host_skipped_slots']
    assert all(int(v) == 0 for row in statuses for k, v in row.items() if k != 'rx_monotonic_s')

    last = result['last_performance']
    latency_rows = []
    for key, label in LATENCIES.items():
        metric = last[key]
        latency_rows.append({'stage': label, 'samples': metric['n'],
                             'mean_ms': round(metric['total_ms'] / metric['n'], 6),
                             'p50_bin_ms': metric['p50_bin'], 'p95_bin_ms': metric['p95_bin'],
                             'p99_bin_ms': metric['p99_bin'], 'max_ms': metric['max_ms'],
                             'over_20ms': metric['over20']})
    write_csv('latency-summary.csv', latency_rows)
    fig, ax = plt.subplots(figsize=(12, 6.8))
    fig.subplots_adjust(left=.23, right=.94, top=.73, bottom=.12)
    fig.suptitle('STM32 · 30-minute observed load', x=.06, y=.96, ha='left', fontsize=23)
    fig.text(.06, .82, '89,057 / 89,057\nMeasurements matched', fontsize=13, weight='bold')
    fig.text(.39, .82, '0\nCRC / queue / RX errors', fontsize=13, weight='bold')
    fig.text(.72, .82, 'PASS\nBoard + delivery + evidence', fontsize=13, weight='bold', color=COLORS[0])
    y = np.arange(len(latency_rows))
    ax.barh(y, [r['max_ms'] for r in latency_rows], color=COLORS, alpha=.88, height=.6)
    ax.scatter([r['p99_bin_ms'] for r in latency_rows], y, marker='D', color='#172a3b', s=35, label='Reported p99 bin', zorder=3)
    for i, row in enumerate(latency_rows):
        ax.text(row['max_ms'] + .25, i, f"{row['max_ms']} ms", va='center', fontsize=11)
    ax.axvline(20, color='#bb4c4c', ls='--', label='20 ms board limit')
    ax.set(yticks=y, yticklabels=[r['stage'] for r in latency_rows], xlabel='Observed latency (ms)', xlim=(0, 23))
    ax.invert_yaxis()
    ax.legend(loc='lower right', frameon=True, facecolor='white', edgecolor='none', framealpha=.95)
    save_figure(fig, '01-board-latency', 'Source: 2026-11-23 PERF retest. Maxima are cumulative observations; bins are integer ms. Requested 50 Hz profile: INCONCLUSIVE.')

    resource_rows = []
    for previous, current in zip(snapshots, snapshots[1:]):
        row = {'board_uptime_s': current['header']['uptime_ms'] / 1000}
        for key in ('processing', 'rx_to_submit', 'parsed_to_tx_poll'):
            count = current[key]['n'] - previous[key]['n']
            row[key + '_interval_mean_ms'] = ((current[key]['total_ms'] - previous[key]['total_ms']) / count if count else math.nan)
        for name in ('rx', 'handler', 'tx', 'main'):
            row[name + '_min_unused_bytes'] = current['stack ' + name]['min_unused']
        resource_rows.append(row)
    write_csv('board-intervals.csv', resource_rows)
    cpu = result['cpu_scheduler_windows']
    write_csv('cpu-windows.csv', cpu)
    fig, axes = plt.subplots(3, 1, figsize=(12, 9), sharex=True)
    fig.subplots_adjust(left=.1, right=.96, top=.89, bottom=.1, hspace=.4)
    fig.suptitle('Board time and resource headroom', x=.06, ha='left', fontsize=22)
    minutes = np.array([r['board_uptime_s'] for r in resource_rows]) / 60
    for key, color in zip(('processing', 'rx_to_submit', 'parsed_to_tx_poll'), COLORS):
        axes[0].plot(minutes, [r[key + '_interval_mean_ms'] for r in resource_rows], label=LATENCIES[key], color=color)
    axes[0].set(ylabel='Interval mean (ms)', ylim=(0, 4.8), title='Means from cumulative count / total deltas; not interval maxima')
    axes[0].legend(ncol=3, fontsize=9, loc='upper right', frameon=False)
    axes[1].plot([r['uptime_ms'] / 60000 for r in cpu], [r['non_idle_percent'] for r in cpu], color=COLORS[0])
    axes[1].axhline(80, ls='--', color='#bb4c4c', label='80% limit')
    axes[1].set(ylabel='Non-idle (%)', ylim=(0, 100), title='Scheduler accounting · peak %.2f%%' % max(r['non_idle_percent'] for r in cpu))
    axes[1].legend(frameon=False, loc='upper right')
    for name, color in zip(('rx', 'handler', 'tx', 'main'), COLORS):
        size = 2048 if name == 'handler' else 1024
        axes[2].plot(minutes, [r[name + '_min_unused_bytes'] / size * 100 for r in resource_rows], label=name, color=color)
    axes[2].axhline(25, ls='--', color='#bb4c4c', label='25% minimum')
    axes[2].set(xlabel='Board uptime (min)', ylabel='Minimum free (%)', ylim=(0, 100), title='Cumulative sampled stack minima')
    axes[2].legend(ncol=5, frameon=False, loc='upper right', fontsize=10)
    save_figure(fig, '02-board-resources', 'Source: same 30-minute run. Board uptime is independent of host time. Scheduler non-idle is not physical CPU/ISR utilization.')

    windows = []
    for start in range(0, 1800, 5):
        mask = (elapsed >= start) & (elapsed < start + 5)
        gap_mask = (elapsed[1:] >= start) & (elapsed[1:] < start + 5)
        if mask.any():
            windows.append({'start_s': start, 'samples': int(mask.sum()),
                            'rtt_p99_ms': percentile(rtt[mask], .99), 'rtt_max_ms': float(rtt[mask].max()),
                            'send_gap_max_ms': float(gaps[gap_mask].max()) if gap_mask.any() else 0})
    write_csv('host-five-second-windows.csv', windows)
    fig, axes = plt.subplots(2, 1, figsize=(12, 8))
    fig.subplots_adjust(left=.1, right=.96, top=.87, bottom=.11, hspace=.48)
    fig.suptitle('Host timing · kept separate from STM32 acceptance', x=.06, ha='left', fontsize=20)
    for key, color, label in [('rtt_max_ms', COLORS[1], 'RTT max / 5 s'), ('rtt_p99_ms', COLORS[0], 'RTT p99 / 5 s'),
                              ('send_gap_max_ms', COLORS[2], 'Send gap max / 5 s')]:
        axes[0].plot([w['start_s'] / 60 for w in windows], [w[key] for w in windows], color=color, label=label, linewidth=1.2)
    axes[0].axhline(100, color='#bb4c4c', ls='--', label='100 ms RTT diagnostic')
    axes[0].set(xlabel='Host elapsed time (min)', ylabel='Time (ms)', title='Temporal envelopes; coincidence does not establish a cause')
    axes[0].legend(ncol=2, frameon=False, fontsize=9, loc='upper right')
    ordered = np.sort(rtt)
    axes[1].plot(ordered, np.arange(1, len(ordered) + 1) / len(ordered) * 100, color=COLORS[1])
    for value, label, color in [(percentile(rtt, .99), 'p99 %.2f ms' % percentile(rtt, .99), COLORS[0]),
                                (rtt.max(), 'max %.2f ms' % rtt.max(), COLORS[2])]:
        axes[1].axvline(value, ls='--', color=color, label=label)
    axes[1].set(xscale='log', xlabel='PC write → response read (ms, log scale)', ylabel='Cumulative share (%)', ylim=(0, 103), title='Empirical RTT distribution from all 89,057 matched reports')
    axes[1].legend(frameon=False, loc='lower right')
    save_figure(fig, '03-host-timing', 'RTT includes USB/UART/host scheduling. No subtraction from board latency, no inferred physical wire timestamp, no board fail from RTT alone.')

    missing_per_minute = np.bincount(missing // 3000, minlength=30)
    coverage = [{'minute': i + 1, 'scheduled': 3000, 'sent': int(3000 - n), 'not_sent': int(n)} for i, n in enumerate(missing_per_minute)]
    write_csv('input-coverage.csv', coverage)
    fig, axes = plt.subplots(2, 1, figsize=(12, 7.5))
    fig.subplots_adjust(left=.1, right=.96, top=.86, bottom=.12, hspace=.55)
    fig.suptitle('Input coverage · 943 scheduled slots were not sent', x=.06, ha='left', fontsize=21)
    axes[0].bar(np.arange(1, 31), missing_per_minute, color=COLORS[2])
    axes[0].set(xlabel='Scheduled sensor-time minute', ylabel='Unsent slots', title='Missing source slots, not lost board responses', xlim=(.4, 30.6))
    axes[1].plot([w['start_s'] / 60 for w in windows], [w['send_gap_max_ms'] for w in windows], color=COLORS[2])
    axes[1].axhline(1000, color='#bb4c4c', ls='--', label='1,000 ms host-gap interruption guard')
    axes[1].axhline(20, color=COLORS[0], ls=':', label='20 ms requested period')
    axes[1].set(xlabel='Host elapsed time (min)', ylabel='Send gap (ms)', ylim=(0, 1100), title='Actual pre-write gaps · maximum %.2f ms' % gaps.max())
    axes[1].legend(frameon=True, facecolor='white', edgecolor='none', framealpha=.95, loc='upper right', fontsize=9)
    save_figure(fig, '04-input-coverage', '90,000 scheduled = 89,057 sent + 943 unsent. All sent measurements matched. Slot completeness does not prove physically exact periodic input.')

    turn = read_csv(TURN / 'aligned.csv')
    turn_result = json.loads((TURN / 'results.json').read_text())
    times = np.array([int(r['timestamp_ms']) / 1000 for r in turn])
    errors = np.array([float(r['position_error_m']) for r in turn])
    valid = times >= 2
    assert len(turn) == turn_result['sent'] and math.isclose(float(np.sqrt(np.mean(errors[valid] ** 2))), turn_result['metrics']['all']['position_m']['rmse'], abs_tol=1e-10)
    turn_rows = []
    for segment, label in [(None, 'all after 2 s'), (0, 'straight before'), (1, 'turn'), (2, 'straight after')]:
        mask = valid & (np.array([int(r['segment']) for r in turn]) == segment) if segment is not None else valid
        turn_rows.append({'segment': label, 'samples': int(mask.sum()), 'position_rmse_m': float(np.sqrt(np.mean(errors[mask] ** 2))), 'max_position_error_m': float(errors[mask].max())})
    write_csv('turn-error-summary.csv', turn_rows)
    fig = plt.figure(figsize=(13, 7.7))
    gs = fig.add_gridspec(2, 2, left=.08, right=.92, top=.84, bottom=.12, hspace=.45, wspace=.35)
    trajectory = fig.add_subplot(gs[:, 0])
    error_ax = fig.add_subplot(gs[0, 1])
    range_ax = fig.add_subplot(gs[1, 1])
    fig.suptitle('Separate turn test · trajectory and estimation error', x=.06, ha='left', fontsize=21)
    fig.text(.06, .885, '755 measurements · 10 Hz · no injected noise · accuracy observed, no pass threshold', fontsize=11)
    trajectory.plot([float(r['truth_x_m']) / 1000 for r in turn], [float(r['truth_y_m']) / 1000 for r in turn], color=COLORS[0], linewidth=3, label='Synthetic truth')
    trajectory.plot([float(r['estimate_x_m']) / 1000 for r in turn], [float(r['estimate_y_m']) / 1000 for r in turn], color=COLORS[1], ls='--', linewidth=1.2, label='Recorded board estimate')
    trajectory.scatter([0], [1], color=COLORS[2], s=45, label='Start', zorder=3)
    trajectory.set(xlabel='East (km)', ylabel='North (km)', title='Straight → turn → straight', aspect='equal')
    trajectory.legend(fontsize=9, frameon=False, loc='lower left')
    error_ax.plot(times, errors, color=COLORS[1])
    error_ax.set(ylabel='Position error (m)', title='RMSE: all %.2f m / turn %.2f m' % (turn_rows[0]['position_rmse_m'], turn_rows[2]['position_rmse_m']))
    range_ax.plot(times, [float(r['range_error_m']) for r in turn], color=COLORS[0], label='Range error (m)')
    angle_ax = range_ax.twinx()
    angle_ax.plot(times, [float(r['azimuth_error_deg']) for r in turn], color=COLORS[2], label='Azimuth error (deg)', alpha=.8)
    range_ax.set(xlabel='Sensor time (s)', ylabel='Range error (m)')
    angle_ax.set_ylabel('Azimuth error (deg)', color=COLORS[2])
    for ax in (error_ax, range_ax):
        ax.axvspan(0, 2, color='#b1bac4', alpha=.3)
        ax.axvspan(10, 65.486818564, color=COLORS[0], alpha=.08)
        ax.set_xlim(0, 76)
    save_figure(fig, '05-turn-tracking', 'Source: separate final-validation turn capture. Gray: 0–2 s excluded from summary; pale green: turn. Position error is relative to synthetic truth.')

    summary = {'source_run': str(LOAD.relative_to(ROOT)), 'board_qualification': result['board_qualification']['status'],
               'requested_profile_qualification': result['requested_profile_qualification']['status'],
               'duration_s': result['load_elapsed_s'], 'matched_measurements': len(inputs), 'missing_responses': len(samples) - len(inputs),
               'unsent_slots': len(missing), 'actual_hz': result['actual_measurement_hz'],
               'rtt_p99_ms': percentile(rtt, .99), 'rtt_max_ms': float(rtt.max()),
               'host_gap_max_ms': float(gaps.max()), 'cpu_peak_percent': max(r['non_idle_percent'] for r in cpu),
               'latencies': latency_rows, 'turn': turn_rows, 'percentile_method': 'nearest rank',
               'board_latency_distribution_available': False}
    summary['observations'] = {
        'unsent_percent': len(missing) / expected_slots * 100,
        'unsent_in_first_12_sensor_minutes': int(missing_per_minute[:12].sum()),
        'rtt_above_100ms_count': len(slow_events),
        'slow_rtt_overlapping_send_gap_above_100ms': sum(r['overlaps_send_gap_above_100ms'] for r in slow_events),
        'straight_before_share_of_post_warmup_squared_error_percent':
            turn_rows[1]['samples'] * turn_rows[1]['position_rmse_m'] ** 2 /
            (turn_rows[0]['samples'] * turn_rows[0]['position_rmse_m'] ** 2) * 100,
    }
    (OUT / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    source_paths = [LOAD / f for f in ('results.json', 'performance.json', 'metadata.json', 'session/samples.csv', 'session/reports.csv', 'session/status.csv')]
    source_paths += [TURN / f for f in ('aligned.csv', 'results.json', 'metadata.json')]
    provenance = {'inputs_sha256': {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in source_paths},
                  'tool_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                  'checks': ['unique input/reply timestamp bijection', 'RTT count and nearest-rank percentiles match original',
                             'scheduled = sent + unsent', 'all recorded STATUS counters zero', 'turn RMSE matches original'],
                  'libraries': {'matplotlib': matplotlib.__version__, 'numpy': np.__version__}}
    (OUT / 'analysis-provenance.json').write_text(json.dumps(provenance, indent=2) + '\n')
    sections = [
        ('01-board-latency', '보드 지연과 판정', '최댓값과 기록된 p99 구간을20ms 기준과 비교했다. 이 그림은 개별 보드 지연의 원시 분포가 아니다.'),
        ('02-board-resources', '시간에 따른 보드 자원', '누적 카운터의 차분으로 구간 평균을 계산했다. 스택은 누적 최소 여유이며, CPU는 스케줄러 비유휴 관측값이다.'),
        ('03-host-timing', '호스트 지연', '89,057개 입력과 응답을 센서 시각으로 연결한 뒤 동일한 PC monotonic 시계의 read−write를 계산했다. 최대659ms는 보드 지연으로 해석하지 않는다.'),
        ('04-input-coverage', '요청 부하가 미확정인 이유', '943개는 보드가 잃어버린 응답이 아니라 PC가 송신하지 않은 예정 슬롯이다. 실제 송신한89,057개는 모두 대응했다. 정확한 물리 주기까지 증명한 것은 아니다.'),
        ('05-turn-tracking', '별도 선회 시험', '다른 실행의10Hz·무잡음 선회 기록이다. 최초2초를 제외한 위치 RMSE는4.513m, 선회 구간은1.396m였다. 합격 한계가 정해진 정확도 시험은 아니다.'),
    ]
    observations = summary['observations']
    findings = [
        f'예정 입력의 {observations["unsent_percent"]:.2f}%가 미송신이었다. 누락943개 중 {observations["unsent_in_first_12_sensor_minutes"]}개는 첫12분의 예정 슬롯에 집중됐다.',
        f'RTT가100ms를 넘은 {len(slow_events)}건 중 {observations["slow_rtt_overlapping_send_gap_above_100ms"]}건은100ms 초과 송신 공백과 시간 구간이 겹쳤다. 이는 호스트 경로 지연과 부합하지만 특정 앱이나 스케줄러가 원인이라는 인과 증명은 아니다.',
        f'선회 시험에서는2–10초 초기 직선 구간이 warm-up 이후 전체 제곱 위치오차의 {observations["straight_before_share_of_post_warmup_squared_error_percent"]:.1f}%를 차지했다. 전체 RMSE만 보면 이후 구간의 오차를 구분하기 어렵다.',
    ]
    body = '<section><h2>데이터에서 보이는 점</h2><ul>' + ''.join(f'<li>{text}</li>' for text in findings) + '</ul><p><a href="slow-rtt-events.csv">RTT100ms 초과 사건표</a></p></section>'
    body += ''.join(f'<section id="{name}"><h2>{title}</h2><p>{text}</p><img src="{name}.png" alt="{title}" loading="lazy"><p class="download"><a href="{name}.svg">SVG</a> · <a href="{name}.png">PNG</a></p></section>' for name, title, text in sections)
    verdict_rows = [{'분류': '관측 부하의 보드·전송·증거', '판정': '통과', '근거': '30분 / 측정 89,057개 모두 대응'},
                    {'분류': '요청한50Hz 전체 입력', '판정': '미확정', '근거': '90,000 예정 슬롯 중943개 미송신'},
                    {'분류': '호스트 RTT', '판정': '진단 한도 초과', '근거': 'p99 11.279ms / 최대659.311ms; 보드 gate 제외'}]
    video = '<section id="video"><h2>GUI 무음 시연 · 저장 기록 재생</h2><p>별도 GUI 세션(2026-11-23 05:13:57 UTC)의139개 측정과140개 TRACK을 기존 화면에 재현한다. 최신30분 성능 시험이나 새 실보드 실행 영상이 아니다. 제품 GUI에 재생 기능을 추가한 것도 아니다.</p><video controls preload="metadata" poster="video-poster.png" src="gui-recorded-replay.mp4"></video><p><a href="gui-recorded-replay.mp4">MP4 다운로드</a> · <a href="video-provenance.json">영상 출처·재생 정보</a></p></section>'
    css = 'body{margin:0;background:#f3f5f7;color:#203347;font:16px/1.7 system-ui,sans-serif}main{max-width:1180px;margin:auto;padding:44px 24px}h1{font-size:38px;line-height:1.25}h2{font-size:25px;margin:0 0 10px}.eyebrow{color:#087c73;font-weight:700;letter-spacing:2px}.lead{font-size:19px;max-width:900px}section{background:white;border:1px solid #dde4e9;border-radius:12px;padding:26px;margin:26px 0}img,video{width:100%;height:auto;display:block}video{background:#101820;border-radius:8px}a{color:#086f85}nav{display:flex;gap:18px;flex-wrap:wrap}.table-wrap{overflow:auto}table{border-collapse:collapse;width:100%;font-size:14px}th,td{padding:12px;text-align:left;border-bottom:1px solid #dce4ea}th{background:#edf3f6}.download{margin:8px 0 0;font-size:13px}.note{color:#58697a}footer{font-size:13px;color:#58697a}@media(max-width:650px){main{padding:25px 12px}h1{font-size:29px}section{padding:16px}}@media print{body{background:white}section{break-inside:avoid}video,nav{display:none}main{padding:0}}'
    report = f'<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Radar Lab · 실보드 분석</title><style>{css}</style><main><p class="eyebrow">RADAR LAB / EVIDENCE REVIEW</p><h1>실보드 성능과 호스트 영향</h1><p class="lead">30분 관측 부하의 보드 처리는 통과했다. 요청50Hz 전체 입력은 미확정이다. 둘을 구분해 원본 기록을 분석했다.</p><nav><a href="#video">GUI 동영상</a><a href="#01-board-latency">보드 지연</a><a href="#03-host-timing">호스트 영향</a><a href="#05-turn-tracking">선회 추적</a></nav><section><h2>결과를 읽는 기준</h2>{table(verdict_rows)}<p class="note">2026-11-23 · STM32F746G-DISCO · 성능 판정/원본 기록 변경 없음. 이전 CRC2건의 원인을 이번 결과로 확정하지 않는다.</p></section>{video}{body}<section><h2>수치 표와 재현 자료</h2>{table(latency_rows)}<p>보드 지연 값의 단위는ms이며 p50/p95/p99는 정수ms 히스토그램 구간이다.</p>{table(turn_rows)}<p><a href="latency-summary.csv">지연 CSV</a> · <a href="board-intervals.csv">보드 구간 CSV</a> · <a href="cpu-windows.csv">CPU CSV</a> · <a href="host-five-second-windows.csv">호스트 구간 CSV</a> · <a href="input-coverage.csv">입력 누락 CSV</a> · <a href="turn-error-summary.csv">선회 CSV</a></p><p><a href="summary.json">분석 요약 JSON</a> · <a href="analysis-provenance.json">출처 해시·검증</a> · <a href="../../test-results/host-input-retest-2026-11-23/README.md">원본 실보드 보고서</a></p></section><footer>시간축: host elapsed / board uptime / sensor time을 구분했다. 개별 ISR 지연, 물리 UART 경계, WCET, 시스템 전체 스택 안전성은 이 자료의 검증 범위가 아니다.</footer></main></html>'
    (OUT / 'index.html').write_text(report + '\n')
    lines = ['# 실보드 결과 분석과 GUI 동영상', '', '[전체 HTML 보고서](index.html) · [무음 GUI 영상](gui-recorded-replay.mp4)', '',
             '최신30분 관측 부하에서89,057개 입력 모두 대응·보드 오류0. 요청50Hz 전체는943개 미송신 슬롯으로 미확정이다.', '',
             '영상은 이전 GUI 실보드 세션의 기록 재생이며 최신30분 시험이나 새 보드 실행이 아니다.', '',
             '## 데이터에서 보이는 점', '', *['- ' + text for text in findings], '']
    for name, title, text in sections:
        lines.extend([f'## {title}', '', text, '', f'![{title}]({name}.png)', ''])
    lines.extend(['## 재현', '', '추가 의존성은 Matplotlib와 imageio-ffmpeg이며 기존 Zephyr 환경을 변경하지 않고 임시 폴더에 설치했다.', '',
                  '```sh', 'PYTHONPATH=/private/tmp/radar-report-deps /Users/yuseungjae/zephyrproject/.venv/bin/python tools/docs/analyze_board_results.py',
                  'PYTHONPATH=/private/tmp/radar-report-deps /Users/yuseungjae/zephyrproject/.venv/bin/python tools/docs/render_gui_video.py', '```', '',
                  '[출처 해시와 수치 대조](analysis-provenance.json) · [영상 정보](video-provenance.json) · [분석 JSON](summary.json)', '',
                  '원시 자료, 펌웨어, 시험 판정은 변경하지 않았다. v1.1.0 완료 상태도 변경하지 않았다.', ''])
    (OUT / 'README.md').write_text('\n'.join(lines))
    print(json.dumps({k: v for k, v in summary.items() if k not in ('latencies', 'turn')}, indent=2))


if __name__ == '__main__':
    main()
