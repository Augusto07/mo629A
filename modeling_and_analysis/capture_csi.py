"""Capture a timed window of router CSI to CSV (requires pyserial)."""

import argparse
import csv
from datetime import datetime
import json
from pathlib import Path
import sys
import time

import serial


ESP32_HEADER = (
    "type,id,mac,rssi,rate,sig_mode,mcs,bandwidth,smoothing,not_sounding,"
    "aggregation,stbc,fec_coding,sgi,noise_floor,ampdu_cnt,channel,"
    "secondary_channel,local_timestamp,ant,sig_len,rx_format,len,first_word,data"
).split(",")
NEW_CHIP_HEADER = (
    "type,seq,mac,rssi,rate,noise_floor,fft_gain,agc_gain,channel,"
    "local_timestamp,sig_len,rx_format,len,first_word,data"
).split(",")


def parse_record(line):
    """Reject logs and incomplete/corrupt CSI records."""
    if not line.startswith(b"CSI_DATA,"):
        return None
    try:
        row = next(csv.reader([line.decode("ascii")], strict=True))
        if len(row) not in (len(ESP32_HEADER), len(NEW_CHIP_HEADER)):
            return None
        samples = json.loads(row[-1])
        if not isinstance(samples, list) or len(samples) != int(row[-3]):
            return None
        if not all(type(value) is int for value in samples):
            return None
        return row
    except (UnicodeError, ValueError, csv.Error, StopIteration):
        return None


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", default="COM4")
    parser.add_argument("--baud", type=int, default=921600)
    parser.add_argument("--seconds", type=float, default=120)
    parser.add_argument("--wait", type=float, default=60,
                        help="Maximum seconds to wait for the first CSI record")
    parser.add_argument("--output", type=Path,
                        default=Path(__file__).parent / "captures" /
                        (datetime.now().strftime("csi_%Y%m%d_%H%M%S") + ".csv"))
    args = parser.parse_args(argv)
    if args.seconds <= 0 or args.wait <= 0:
        parser.error("--seconds and --wait must be positive")

    count = 0
    skipped = 0
    started = None
    output = args.output.resolve()
    try:
        # Preserve the running firmware; do not deliberately reset the board.
        with serial.Serial() as port:
            port.port = args.port
            port.baudrate = args.baud
            port.timeout = 0.1
            port.dtr = False
            port.rts = False
            port.open()
            port.reset_input_buffer()
            output.parent.mkdir(parents=True, exist_ok=True)
            with output.open("x", newline="", encoding="utf-8") as stream:
                writer = csv.writer(stream)
                print(f"Waiting for CSI on {args.port} at {args.baud} baud...", flush=True)
                wait_until = time.monotonic() + args.wait
                pending = b""
                columns = None
                try:
                    while True:
                        now = time.monotonic()
                        if started is None and now >= wait_until:
                            print("No CSI received. Check Wi-Fi and close other serial monitors.",
                                  file=sys.stderr)
                            return 1
                        if started is not None and now - started >= args.seconds:
                            break
                        pending += port.read(min(max(port.in_waiting, 1), 4096))
                        while b"\n" in pending:
                            line, pending = pending.split(b"\n", 1)
                            now = time.monotonic()
                            if started is not None and now - started >= args.seconds:
                                break
                            row = parse_record(line.rstrip(b"\r"))
                            if row is None:
                                if line.startswith(b"CSI_DATA,"):
                                    skipped += 1
                                continue
                            if started is None:
                                started = now
                                columns = len(row)
                                writer.writerow(ESP32_HEADER if columns == len(ESP32_HEADER)
                                                else NEW_CHIP_HEADER)
                                print(f"Capturing {args.seconds:g} seconds to {output}", flush=True)
                            if len(row) != columns:
                                skipped += 1
                                continue
                            writer.writerow(row)
                            count += 1
                            if count % 100 == 0:
                                stream.flush()
                        if len(pending) > 16384:
                            pending = b""
                            skipped += 1
                except KeyboardInterrupt:
                    print("\nCapture interrupted; saving collected records.", flush=True)
                finally:
                    print(f"Saved {count} records; skipped {skipped} malformed records.\n{output}",
                          flush=True)
    except (serial.SerialException, OSError) as error:
        print(f"Capture failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
