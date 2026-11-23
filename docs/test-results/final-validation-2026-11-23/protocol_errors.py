"""Exercise CRC, length and partial-frame recovery on the normal board image."""
import json
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT))
import serial
from pc_sim.protocol import build_init_frame, build_measurement_frame, decode_track_payload
from pc_sim.frame_parser import FrameParser
from pc_sim.status_client import request_status

out=Path(__file__).resolve().parent/'protocol-errors'
out.mkdir(exist_ok=False)
checks=[]
statuses=[]
wire=[]


def check(name,condition):
    checks.append(dict(name=name,passed=bool(condition)))
    if not condition:
        raise AssertionError(name)


class RecordedSerial(serial.Serial):
    def write(self,data):
        count=super().write(data)
        wire.append(dict(direction='tx',hex=data[:count].hex(),time=time.monotonic()))
        return count

    def read(self,size=1):
        data=super().read(size)
        if data:
            wire.append(dict(direction='rx',hex=data.hex(),time=time.monotonic()))
        return data


failure=None
try:
    with RecordedSerial('/dev/cu.usbserial-A5069RR4',115200,timeout=.02,write_timeout=1) as port:
        def status():
            value=request_status(port)
            statuses.append(value)
            return value
        baseline=status()
        check('initial eight counters zero',len(baseline)==8 and not any(baseline.values()))
        corrupt=bytearray(build_measurement_frame(0,1000,0));corrupt[-1]^=1
        port.write(corrupt);time.sleep(.1)
        crc=status()
        check('CRC counter increments once',crc==dict(baseline,crc_errors=1))
        port.write(b'\x7e\x00\x7e\x21');time.sleep(.1)
        length=status()
        check('invalid lengths count twice',length==dict(crc,length_errors=2))
        port.write(build_measurement_frame(0,1000,0)[:7]);time.sleep(1.3)
        partial=status()
        check('partial frame timeout counts once',partial==dict(length,frame_timeouts=1))
        port.write(build_init_frame());time.sleep(.1)
        check('INIT preserves diagnostics',status()==partial)
        decoder=FrameParser()
        port.write(build_measurement_frame(0,1000,0))
        deadline=time.monotonic()+.5
        reports=[]
        while time.monotonic()<deadline:
            for frame in decoder.feed(port.read(64)):
                if frame.frame_type==7:
                    reports.append(decode_track_payload(frame.payload))
        check('valid measurement recovers',any(r.input_present and r.estimate_valid and r.result==0 and abs(r.range_m-1000)<.01 for r in reports))
        check('response CRC/LEN clean',decoder.crc_errors==decoder.length_errors==0)
        check('recovery preserves counters',status()==partial)
except Exception as error:
    failure=repr(error)
finally:
    result=dict(passed=failure is None,checks=checks,status=statuses,failure=failure)
    (out/'results.json').write_text(json.dumps(result,indent=2)+'\n')
    (out/'wire.json').write_text(json.dumps(wire,indent=2)+'\n')
    print(json.dumps(result,indent=2))
raise SystemExit(1 if failure else 0)
