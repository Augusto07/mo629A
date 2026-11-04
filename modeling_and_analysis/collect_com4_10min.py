"""Collect CSI for 10 minutes on COM4, with progress and a JSON summary.

Uses capture_csi.py without deliberately resetting or flashing the board.
CSV, status and summary files are saved beside one another in captures/.
"""
import argparse
import csv
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
from pathlib import Path
import threading
import time

import capture_csi


LOCAL_TIMEZONE = timezone(timedelta(hours=-3))


def summarize_capture(output):
    """Summarize driver timestamps, recovering signed/unsigned uint32 wraps."""
    count = resets = invalid_timestamps = gaps_over_2s = 0
    previous = None
    span = 0.0
    longest_gap = None
    lengths = set()
    if output.exists():
        with output.open(newline='', encoding='utf-8') as stream:
            for row in csv.DictReader(stream):
                count += 1
                lengths.add(int(row['len']))
                try:
                    stamp = int(row['local_timestamp']) % 2**32
                except (KeyError, ValueError, TypeError):
                    invalid_timestamps += 1
                    previous = None
                    continue
                if previous is not None:
                    delta = stamp-previous
                    if delta < -(2**31):
                        delta += 2**32
                    if delta < 0:
                        resets += 1
                    else:
                        gap = delta/1e6
                        span += gap
                        longest_gap = gap if longest_gap is None else max(longest_gap, gap)
                        gaps_over_2s += gap > 2
                previous = stamp
    observed_span = span if not resets and not invalid_timestamps and count else None
    return dict(records=count, csi_lengths=sorted(lengths), clock_resets=resets,
                invalid_timestamps=invalid_timestamps, acquisition_span_s=observed_span,
                mean_packet_rate_hz=(count-1)/observed_span if observed_span else None,
                longest_gap_s=longest_gap, gaps_over_2s=gaps_over_2s,
                sha256=hashlib.sha256(output.read_bytes()).hexdigest() if output.exists() else None)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', default='COM4')
    parser.add_argument('--baud', type=int, default=921600)
    parser.add_argument('--seconds', type=float, default=600)
    parser.add_argument('--delay', type=float, default=0,
                        help='Seconds to wait before opening the serial port')
    parser.add_argument('--presence', choices=('unknown', 'empty', 'occupied'), default='unknown',
                        help='User-declared recording context; not inferred from CSI')
    parser.add_argument('--wait', type=float, default=30,
                        help='Maximum wait for the first valid CSI packet')
    parser.add_argument('--output', type=Path, help='Optional new CSV path')
    args = parser.parse_args(argv)
    if any(not math.isfinite(value) or value <= 0 for value in (args.seconds, args.wait)):
        parser.error('--seconds and --wait must be finite and positive')
    if args.baud <= 0:
        parser.error('--baud must be positive')
    if not math.isfinite(args.delay) or args.delay < 0:
        parser.error('--delay must be finite and nonnegative')
    scheduled_at = datetime.now(LOCAL_TIMEZONE)
    deadline = time.monotonic()+args.delay
    while time.monotonic() < deadline:
        remaining = deadline-time.monotonic()
        print(json.dumps(dict(state='waiting', port=args.port, delay_remaining_s=round(remaining, 1),
                              recording_context=args.presence,
                              capture_start_at=(scheduled_at+timedelta(seconds=args.delay)).isoformat())), flush=True)
        time.sleep(min(30, remaining))
    started_at = datetime.now(LOCAL_TIMEZONE)
    stamp = started_at.strftime('%Y%m%d_%H%M%S_%f')
    output = (args.output or Path(__file__).parent/'captures'/
              f'csi_{args.port.lower()}_{stamp}_{args.seconds:g}s.csv').resolve()
    if output.exists():
        parser.error(f'Output already exists: {output}')
    output.parent.mkdir(parents=True, exist_ok=True)
    status_path = output.with_suffix('.status.json')
    stop = threading.Event()
    start = time.monotonic()
    context = dict(port=args.port, baud=args.baud, requested_capture_seconds=args.seconds,
                   csv=str(output), started_at=started_at.isoformat(),
                   scheduled_at=scheduled_at.isoformat(), delay_seconds=args.delay,
                   recording_context=args.presence, context_source='user' if args.presence != 'unknown' else None)

    def report(status):
        status_path.write_text(json.dumps(status, indent=2), encoding='utf-8')
        print(json.dumps(status), flush=True)

    def progress():
        while not stop.wait(30):
            count = max(0, output.read_bytes().count(b'\n')-1) if output.exists() else 0
            report(dict(context, state='collecting', elapsed_wall_s=round(time.monotonic()-start, 1),
                        flushed_records=count))

    report(dict(context, state='starting'))
    thread = threading.Thread(target=progress, daemon=True)
    thread.start()
    try:
        code = capture_csi.main(['--port', args.port, '--baud', str(args.baud),
                                 '--seconds', str(args.seconds), '--wait', str(args.wait),
                                 '--output', str(output)])
    finally:
        stop.set()
        thread.join()
    summary = dict(context, state='finished' if code == 0 else 'failed', exit_code=code,
                   elapsed_wall_s=round(time.monotonic()-start, 3),
                   finished_at=datetime.now(LOCAL_TIMEZONE).isoformat(),
                   firmware_flashed=False, **summarize_capture(output))
    output.with_suffix('.summary.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
    report(summary)
    return code


if __name__ == '__main__':
    raise SystemExit(main())
