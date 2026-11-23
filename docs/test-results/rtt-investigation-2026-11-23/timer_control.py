"""Observe 1 ms host sleeps without UART, Qt, CSV or firmware activity."""
import json
from pathlib import Path
import time

start = time.monotonic()
end = start + 60
events = []
count = 0
maximum = 0
while time.monotonic() < end:
    cpu = time.thread_time()
    before = time.monotonic()
    time.sleep(.001)
    after = time.monotonic()
    cpu_ms = (time.thread_time() - cpu) * 1000
    wall_ms = (after - before) * 1000
    count += 1
    maximum = max(maximum, wall_ms)
    if wall_ms >= 5:
        events.append(dict(start_s=before, wall_ms=wall_ms, thread_cpu_ms=cpu_ms))
result = dict(duration_s=time.monotonic()-start, requested_ms=1, count=count,
              max_wall_ms=maximum, over_5ms=len(events), events=events)
(Path(__file__).parent / 'timer-control.json').write_text(json.dumps(result, indent=2)+'\n')
print(json.dumps({k: v for k, v in result.items() if k != 'events'}, indent=2))
