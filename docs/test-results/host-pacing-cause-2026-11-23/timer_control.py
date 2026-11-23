"""Exercise the same 20ms skip rule with sleep only, without UART or recorder."""
import argparse
import json
from pathlib import Path
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--duration', type=int, default=60)
    args = parser.parse_args()
    events, samples = [], []
    index = skipped = 0
    start = time.monotonic()
    end, next_send = start + args.duration, start
    while time.monotonic() < end:
        deadline = min(next_send, end)
        while time.monotonic() < deadline:
            requested = min(.001, max(0, deadline - time.monotonic()))
            cpu = time.thread_time_ns()
            before = time.monotonic()
            time.sleep(requested)
            after = time.monotonic()
            used_cpu_ms = (time.thread_time_ns() - cpu) / 1e6
            if after - before >= .002:
                events.append(dict(start_s=before, end_s=after, requested_ms=requested * 1000,
                                   wall_ms=(after - before) * 1000, thread_cpu_ms=used_cpu_ms))
        now = time.monotonic()
        if now >= end:
            break
        missed = int(max(0, now - next_send) / .02)
        skipped += missed
        index += missed
        samples.append(dict(sensor_ms=index * 20, monotonic_s=now, skipped_before=missed))
        index += 1
        next_send = start + index * .02
    result = dict(kind='host-only timing control, no UART, no parser, no recording worker',
                  duration_s=args.duration, elapsed_s=time.monotonic() - start,
                  sample_slots=len(samples), skipped_slots=skipped,
                  long_sleeps=events, samples=samples)
    args.output.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({k:v for k,v in result.items() if k not in ('samples','long_sleeps')}, indent=2))


if __name__ == '__main__':
    main()
