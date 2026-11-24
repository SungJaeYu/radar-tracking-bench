"""Render recorded board events in the existing GUI; never open a serial port."""
import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

os.environ['QT_QPA_PLATFORM'] = 'offscreen'
os.environ['QT_SCALE_FACTOR'] = '1'
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import imageio_ffmpeg
from PIL import Image, ImageDraw, ImageFont
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication
import pc_sim.ui.gui as gui
from pc_sim.simulation.gui_model import Sample
from pc_sim.transport.protocol import TrackReport, TrackReportFlag, TrackReportResult, TrackState

OUT = ROOT / 'docs/analysis/2026-11-23'
SOURCE = ROOT / 'docs/test-results/release-v1.1.0-2026-11-23/gui/session/20261123-141357-7bc50801'
WIDTH, HEIGHT, FPS, DURATION_S = 1600, 1000, 15, 40
PREVIEWS = (0, 5, 10, 16, 22, 26, 34)
BACKGROUND, TEAL, TEXT, MUTED = '#101820', '#3ce0b1', '#dce8ef', '#9db3c2'


def rows(filename: str) -> list[dict]:
    with (SOURCE / filename).open(newline='') as stream:
        return list(csv.DictReader(stream))


def font(size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype('/System/Library/Fonts/Supplemental/Arial.ttf', size)


def title_card(ending: bool) -> Image.Image:
    frame = Image.new('RGB', (WIDTH, HEIGHT), BACKGROUND)
    draw = ImageDraw.Draw(frame)
    draw.line((100, 180, 1500, 180), fill='#365064', width=2)
    draw.text((100, 115), 'RADAR LAB  /  RECORDED BOARD SESSION', font=font(25), fill=TEAL)
    draw.text((100, 245), 'Traceable inputs. Visible estimates.' if ending else 'From measurement to track.', font=font(62), fill=TEXT)
    draw.text((100, 355), '139 measurements  /  140 TRACK reports  /  one recorded STATUS query', font=font(29), fill=TEXT)
    draw.text((100, 425), 'Synthetic approaching target  |  Recorded STM32F746G-DISCO responses', font=font(26), fill=MUTED)
    draw.text((100, 510), 'Recorded data replay — no serial connection or new board run.', font=font(26), fill=TEAL)
    draw.text((100, 565), 'Source: 2026-11-23 05:13:57 UTC  ·  ~15 seconds at 1x', font=font(24), fill=MUTED)
    if ending:
        draw.text((100, 665), 'The separate 30-minute performance analysis is in the accompanying report.', font=font(25), fill=TEXT)
        draw.text((100, 715), 'This clip demonstrates the GUI; it does not qualify the requested 50 Hz load.', font=font(24), fill=MUTED)
    else:
        draw.text((100, 665), 'Settings → TRACK → STATUS', font=font(32), fill=TEXT)
        draw.text((100, 725), 'English interface  ·  Silent documentation clip  ·  Paused views are labeled', font=font(24), fill=MUTED)
    draw.line((100, 840, 1500, 840), fill='#365064', width=2)
    return frame


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--preview-only', action='store_true')
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    preview_dir = OUT / 'video-frames'
    preview_dir.mkdir(exist_ok=True)
    samples, reports, statuses = rows('samples.csv'), rows('reports.csv'), rows('status.csv')
    metadata = json.loads((SOURCE / 'metadata.json').read_text())
    assert metadata['mode'] == 'board' and len(samples) == 139 and len(reports) == 140
    assert all(int(row[k]) == 0 for row in statuses for k in row if k != 'rx_monotonic_s')
    events = ([(float(r['tx_monotonic_s']), 'sample', r) for r in samples]
              + [(float(r['rx_monotonic_s']), 'report', r) for r in reports]
              + [(float(r['rx_monotonic_s']), 'status', r) for r in statuses])
    events.sort(key=lambda item: item[0])
    start_s, end_s = events[0][0], events[-1][0]
    playback_clock = [start_s]
    original_clock = gui.time
    gui.time = SimpleNamespace(monotonic=lambda: playback_clock[0])
    app = QApplication.instance() or QApplication([])
    window = gui.MainWindow()
    window.resize(WIDTH, 900)
    window.plot_timer.stop()
    window.mode.setCurrentIndex(1)
    window.mode.setItemText(1, 'Recorded board session · replay')
    window.connected = True
    window.connection_label.setText('Recorded replay · no UART open')
    for combo in (window.data_port, window.console_port):
        combo.clear()
        combo.addItem('Not opened · recorded CSV')
    for key, value in metadata['settings'].items():
        if key in window.inputs:
            window.inputs[key].setValue(value)
    window.record_label.setText('Recorded session: 20261123-141357')
    window.console_text.setPlainText('Console is not replayed in this clip.\nThe TX/run tab displays recorded sample bytes.\n')
    window.event_text.setPlainText('Recorded CSV playback; no UART is open.\n')
    window.log_tabs.setCurrentIndex(1)
    window.content_split.setSizes([890, 300])
    window.plots_split.setSizes([410, 320])
    window.map_plot.setXRange(140, 330, padding=0)
    window.map_plot.setYRange(780, 1020, padding=0)
    window.map_plot.setTitle('Target position · replay zoom')
    window.range_plot.setXRange(0, 15, padding=.02)
    window.range_plot.setYRange(820, 1015, padding=.02)
    window.range_plot.plotItem.legend.setOffset((10, -10))
    for control in (window.mode, window.connect_button, window.refresh_button,
                    window.start_button, window.stop_button, window.record_button):
        control.setEnabled(False)
    window.show()
    app.processEvents()
    cursor = 0
    encoder = None
    log = None
    counts = {'sample': 0, 'report': 0, 'status': 0}
    try:
        if not args.preview_only:
            log = (OUT / 'video-encode.log').open('w')
            encoder = subprocess.Popen([imageio_ffmpeg.get_ffmpeg_exe(), '-y', '-v', 'warning',
                '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', f'{WIDTH}x{HEIGHT}', '-r', str(FPS),
                '-i', '-', '-an', '-c:v', 'libx264', '-preset', 'fast', '-crf', '20',
                '-threads', '2', '-pix_fmt', 'yuv420p', '-movflags', '+faststart',
                str(OUT / 'gui-recorded-replay.mp4')], stdin=subprocess.PIPE, stderr=log)
        indices = [int(t * FPS) for t in PREVIEWS] if args.preview_only else range(DURATION_S * FPS)
        for frame_index in indices:
            video_s = frame_index / FPS
            if video_s < 3:
                frame = title_card(False)
            elif video_s >= 28:
                frame = title_card(True)
            else:
                source_s = min(video_s - 3, end_s - start_s)
                playback_clock[0] = start_s + source_s
                while cursor < len(events) and events[cursor][0] <= playback_clock[0]:
                    timestamp, kind, row = events[cursor]
                    if kind == 'sample':
                        window.on_sample(Sample(int(row['timestamp_ms']), float(row['truth_range_m']),
                            int(row['measured_range_m']), float(row['measured_azimuth_rad']), bytes.fromhex(row['frame_hex'])))
                    elif kind == 'report':
                        report = TrackReport(**{key: int(row[key]) for key in ('report_sequence', 'input_timestamp_ms', 'estimate_timestamp_ms')},
                            **{key: float(row[key]) for key in ('range_m', 'azimuth_rad', 'range_rate_mps', 'azimuth_rate_radps')},
                            state=TrackState(int(row['state'])), result=TrackReportResult(int(row['result'])), flags=TrackReportFlag(int(row['flags'])))
                        window.on_track_received(report, timestamp)
                    else:
                        window.on_status_received({k: int(v) for k, v in row.items() if k != 'rx_monotonic_s'})
                        window.status_updated.setText(f'Recorded query: t={timestamp - start_s:.2f} s')
                        window.status_button.setEnabled(False)
                    counts[kind] += 1
                    cursor += 1
                tab = 1 if source_s < 4 else 3
                if 11 <= source_s < 13 or video_s >= 24:
                    tab = 2
                window.control_tabs.setCurrentIndex(tab)
                window.draw_samples()
                window.metrics.setText(window.metrics.text().replace('UART write', 'Recorded TX'))
                window.event_text.setPlainText(window.event_text.toPlainText().replace('UART write', 'Recorded TX'))
                window.event_text.verticalScrollBar().setValue(window.event_text.verticalScrollBar().maximum())
                label = f'Recorded TRACK · {counts["report"]} reports · no live connection'
                window.board_note.setText(label)
                window.track_message.setText(label)
                window.statusBar().showMessage('Recorded replay — no live UART transmission')
                app.processEvents()
                qimage = window.grab().toImage().convertToFormat(QImage.Format.Format_RGB888)
                gui_image = Image.frombytes('RGB', (qimage.width(), qimage.height()), bytes(qimage.bits()), 'raw', 'RGB', qimage.bytesPerLine(), 1)
                assert gui_image.size == (WIDTH, 900)
                frame = Image.new('RGB', (WIDTH, HEIGHT), BACKGROUND)
                frame.paste(gui_image, (0, 100))
                draw = ImageDraw.Draw(frame)
                paused = video_s - 3 >= end_s - start_s
                draw.text((22, 14), 'RECORDED BOARD REPLAY  /  ' + ('PAUSED VIEW' if paused else '1x PLAYBACK'), font=font(25), fill=TEAL)
                draw.text((22, 57), 'Source: 2026-11-23 05:13:57 UTC  ·  Existing GUI rendered from CSV  ·  Not a new board run', font=font(18), fill=MUTED)
                draw.text((1570, 14), f't = {source_s:05.2f} s', font=font(25), fill=TEXT, anchor='ra')
            if frame_index in [t * FPS for t in PREVIEWS]:
                frame.save(preview_dir / f'{int(video_s):02d}s.png')
                if video_s == 10:
                    frame.save(OUT / 'video-poster.png')
            if encoder is not None:
                encoder.stdin.write(frame.tobytes())
        assert cursor == len(events) and window.worker is None
        if encoder is not None:
            encoder.stdin.close()
            if encoder.wait(timeout=60):
                raise RuntimeError('Video encoder failed; see video-encode.log')
        provenance = {'kind': 'rendered replay of recorded board CSV, not a live screen capture',
                      'source_session': str(SOURCE.relative_to(ROOT)), 'source_started_utc': metadata['started_utc'],
                      'source_duration_s': end_s - start_s, 'source_events_rendered': counts,
                      'fps': FPS, 'duration_s': DURATION_S, 'frames': DURATION_S * FPS,
                      'size': [WIDTH, HEIGHT], 'audio': False, 'preview_only': args.preview_only,
                      'chapters': {'0-3': 'source introduction', '3-19': 'recorded events at 1x; then paused',
                                   '19-24': 'paused TRACK', '24-28': 'paused STATUS', '28-40': 'scope and source'},
                      'input_sha256': {str((SOURCE / name).relative_to(ROOT)): hashlib.sha256((SOURCE / name).read_bytes()).hexdigest()
                                       for name in ('metadata.json', 'samples.csv', 'reports.csv', 'status.csv')},
                      'gui_source_sha256': hashlib.sha256((ROOT / 'pc_sim/ui/gui.py').read_bytes()).hexdigest(),
                      'renderer_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
        (OUT / 'video-provenance.json').write_text(json.dumps(provenance, indent=2) + '\n')
        print(json.dumps({k: v for k, v in provenance.items() if 'sha256' not in k}, indent=2))
    finally:
        if encoder is not None and encoder.poll() is None:
            encoder.stdin.close()
            encoder.wait(timeout=60)
        if log is not None:
            log.close()
        window.close()
        gui.time = original_clock


if __name__ == '__main__':
    main()
