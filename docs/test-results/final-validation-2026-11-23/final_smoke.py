import dataclasses
import json
import pathlib
import sys
import time
import serial
sys.path.insert(0, '/Users/yuseungjae/Desktop/radar-track-fcc-hil')
from pc_sim.frame_parser import FrameParser
from pc_sim.protocol import build_init_frame, build_measurement_frame, decode_track_payload, TrackState, TrackReportResult
from pc_sim.status_client import request_status

out = pathlib.Path(__file__).resolve().parent / 'final-smoke'
out.mkdir(exist_ok=False)
parser = FrameParser()
reports = []
checks = []
console_text = bytearray()
def check(name, condition):
    checks.append({'name': name, 'passed': bool(condition)})
    if not condition:
        raise AssertionError(name)

with serial.Serial('/dev/cu.usbserial-A5069RR4', 115200, timeout=.02, write_timeout=1) as port, serial.Serial('/dev/cu.usbmodem11203',115200,timeout=.01) as console:
    def receive_report(timeout=2):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            console_text.extend(console.read(console.in_waiting or 1))
            for frame in parser.feed(port.read(128)):
                if frame.frame_type == 7:
                    report = decode_track_payload(frame.payload)
                    reports.append(dataclasses.asdict(report))
                    return report
        raise TimeoutError('TRACK report missing')
    try:
        initial = request_status(port)
        check('initial STATUS: eight zero counters', len(initial)==8 and not any(initial.values()))
        port.write(build_init_frame())
        report = receive_report()
        check('INIT returns EMPTY RESET', report.state == TrackState.EMPTY and report.result == TrackReportResult.RESET and not report.input_present)
        for i in range(20):
            port.write(build_measurement_frame(i*20, 1000, 0))
            report = receive_report()
            check(f'measurement {i}: matching timestamp and estimate', report.input_present and report.estimate_valid and report.input_timestamp_ms == i*20 and abs(report.range_m-1000)<.01 and abs(report.azimuth_rad)<.0001)
            check(f'measurement {i}: state and result', report.state == (TrackState.TENTATIVE if i<2 else TrackState.CONFIRMED) and report.result == (TrackReportResult.STARTED if i==0 else TrackReportResult.UPDATED))
            time.sleep(.02)
        report = receive_report(2)
        check('no-reception timeout returns EMPTY RESET', not report.input_present and report.state == TrackState.EMPTY and report.result == TrackReportResult.RESET)
        port.write(build_measurement_frame(0,1000,0))
        report = receive_report()
        check('measurement restarts after timeout', report.result == TrackReportResult.STARTED and report.state == TrackState.TENTATIVE)
        port.write(build_init_frame())
        report = receive_report()
        check('final INIT leaves EMPTY', report.state == TrackState.EMPTY and report.result == TrackReportResult.RESET)
        final = request_status(port)
        check('final STATUS: eight zero counters', len(final)==8 and not any(final.values()))
        check('PC parser has no CRC or length errors', parser.crc_errors == parser.length_errors == 0)
        console_text.extend(console.read(console.in_waiting or 1))
        text = console_text.decode(errors='replace')
        check('console has no assertion/fatal fault', not any(word in text.lower() for word in ('assertion fail','fatal','mpu fault','hard fault')))
        print(json.dumps({'passed':True,'checks':len(checks),'measurements':21,'track_reports':len(reports),'initial_status':initial,'final_status':final,'evidence':str(out)},indent=2))
    finally:
        (out/'checks.json').write_text(json.dumps(checks,indent=2))
        (out/'reports.json').write_text(json.dumps(reports,indent=2))
        (out/'console.log').write_bytes(console_text)
