"""Write standalone SVG figures for the analysis aggregates."""
from html import escape
import math

PROFILES = ('noiseless', 'weak', 'medium', 'strong')
SERIES = {'kf': ('KF', '#14757b'), 'cv_ekf': ('CV-EKF', '#b04c2d'),
          'ct_ekf': ('CT-EKF', '#6646b0'), 'measured': ('Measured baseline', '#586474')}


class Figure:
    def __init__(self, width, height, title, subtitle):
        self.parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
                      f'viewBox="0 0 {width} {height}" role="img" aria-labelledby="title description">',
                      f'<title id="title">{escape(title)}</title>',
                      f'<desc id="description">{escape(subtitle)}</desc>',
                      '<style>text{font-family:system-ui,sans-serif;fill:#172235}</style>']
        self.rect(0, 0, width, height, '#ffffff')
        self.text(30, 40, title, 24, weight=700)
        self.text(30, 66, subtitle, 13)

    def rect(self, x, y, w, h, color):
        self.parts.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" fill="{color}"/>')

    def text(self, x, y, content, size=13, anchor='start', weight=400):
        self.parts.append(f'<text x="{x}" y="{y}" font-size="{size}" font-weight="{weight}" '
                          f'text-anchor="{anchor}">{escape(str(content))}</text>')

    def save(self, path):
        path.write_text('\n'.join([*self.parts, '</svg>', '']), encoding='utf-8')


def profile_plot(path, groups):
    fig = Figure(980, 515, 'Position error by noise profile',
                 'Pooled Cartesian RMSE over shared valid sensor timestamps from 2.0 s onward.')
    bars = {p: {v: groups['profile', p, v]['position_rmse_m'] for v in SERIES if v != 'measured'}
            for p in PROFILES}
    for p, values in bars.items():
        values['measured'] = groups['profile', p, 'kf']['measured_rmse_m']
    ceiling = max(10, math.ceil(max(x for values in bars.values() for x in values.values()) / 50) * 50)
    for tick in range(6):
        y = 402 - 296 * tick / 5
        fig.rect(86, y, 852, 1, '#dce4eb')
        fig.text(74, y + 4, f'{tick * ceiling / 5:g}', anchor='end')
    fig.text(30, 88, 'RMSE (m)', 12)
    for i, (profile, values) in enumerate(bars.items()):
        for j, (name, value) in enumerate(values.items()):
            x = 102 + i * 210 + j * 47
            height = value / ceiling * 296
            fig.rect(x, 402 - height, 42, height, SERIES[name][1])
            fig.text(x + 21, 393 - height, f'{value:.1f}', 11, 'middle')
        fig.text(193 + i * 210, 427, profile, 14, 'middle', 650)
    for i, (label, color) in enumerate(SERIES.values()):
        x = 108 + i * 206
        fig.rect(x, 465, 14, 14, color)
        fig.text(x + 21, 477, label)
    fig.save(path)


def maneuver_plot(path, groups, maneuvers):
    fig = Figure(1030, 645, 'Position error by maneuver and noise',
                 'Each cell pools both directions. Shading marks the lowest filter RMSE for each maneuver and noise profile.')
    positions = {profile: 210 + index * 200 for index, profile in enumerate(PROFILES)}
    variants = tuple(SERIES)[:3]
    for profile, x in positions.items():
        fig.text(x + 82, 108, profile, 14, 'middle', 700)
        for i, variant in enumerate(variants):
            fig.text(x + 29 + i * 54, 134, SERIES[variant][0], 11, 'middle', 650)
    for i, maneuver in enumerate(maneuvers):
        y = 155 + 43 * i
        fig.rect(27, y, 976, 36, '#f3f6f8' if i % 2 == 0 else '#ffffff')
        label = maneuver.replace('_', ' ').replace('deg', '°/s')
        fig.text(35, y + 23, label, 14)
        for profile, x in positions.items():
            values = [groups['maneuver_profile', f'{maneuver}|{profile}', v]['position_rmse_m']
                      for v in variants]
            for j, value in enumerate(values):
                left = x + 54 * j
                best = value == min(values)
                if best:
                    fig.rect(left + 2, y + 3, 53, 30, '#d2eae5')
                fig.text(left + 29, y + 23, f'{value:.1f}', 12, 'middle', 700 if best else 400)
    fig.text(30, 621, 'Values in metres. Shading uses unrounded values.', 13)
    fig.save(path)


def timing_plot(path, groups):
    fig = Figure(960, 456, 'Board execution time and PC round trip',
                 'Stage means use attributable sample counts. RTT percentiles pool all matched input replies.')
    fig.text(35, 106, 'MCU estimator stage (µs)', 17, weight=700)
    fig.text(505, 106, 'PC UART round trip (ms)', 17, weight=700)
    variants = tuple(SERIES)[:3]
    for j, (x, metrics) in enumerate(((35, ('predict_mean_us_approx', 'correct_mean_us_approx')),
                                     (505, ('rtt_p50_ms', 'rtt_p95_ms')))):
        values = [[groups['all', 'all', v][key] for key in metrics] for v in variants]
        maximum = max(value or 0 for pair in values for value in pair) or 1
        for i, (variant, pair) in enumerate(zip(variants, values)):
            y = 140 + i * 78
            fig.text(x, y + 18, SERIES[variant][0], 13, weight=650)
            for k, value in enumerate(pair):
                bar_y = y + k * 22
                width = (value or 0) / maximum * 242
                fig.rect(x + 82, bar_y, width, 15, SERIES[variant][1] if k == 0 else '#a2adba')
                fig.text(x + 90 + width, bar_y + 12, f'{value:.2f}' if value is not None else 'Unavailable', 12)
        labels = ('Predict', 'Correct') if j == 0 else ('P50 RTT', 'P95 RTT')
        fig.text(x, 382, f'{labels[0]} (upper bar)  ·  {labels[1]} (lower bar)', 13)
    fig.text(35, 428, 'MCU means are estimated from cumulative PERF snapshots. RTT includes host and UART effects.', 13)
    fig.save(path)


def write_plots(output, summary, maneuvers):
    groups = {(row['axis'], row['group'], row['variant']): row for row in summary}
    profile_plot(output / 'position-by-noise.svg', groups)
    maneuver_plot(output / 'position-by-maneuver.svg', groups, maneuvers)
    timing_plot(output / 'timing.svg', groups)
