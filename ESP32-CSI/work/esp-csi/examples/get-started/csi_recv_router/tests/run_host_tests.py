"""Build and execute the actual batch C code against simulated ESP-IDF drivers.

Usage: python run_host_tests.py path/to/zig.exe
The test compiler is only for host tests, not ESP32 firmware.
"""
import csv
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

here = Path(__file__).resolve().parent
compiler = Path(sys.argv[1]).resolve()
headers = [
    'sdkconfig.h', 'esp_err.h', 'esp_wifi.h', 'ping/ping_sock.h',
    'esp_heap_caps.h', 'esp_http_client.h', 'esp_log.h', 'esp_mac.h',
    'esp_random.h', 'esp_timer.h', 'esp_crt_bundle.h',
    'freertos/FreeRTOS.h', 'freertos/task.h', 'freertos/semphr.h',
]
test_root = here.parents[4] / 'host-tools/test-runs'
test_root.mkdir(parents=True, exist_ok=True)
with tempfile.TemporaryDirectory(prefix='csi-host-', dir=test_root) as temp:
    work = Path(temp)
    assert work.resolve().parent == test_root.resolve()
    os.environ['ZIG_GLOBAL_CACHE_DIR'] = str(compiler.parent.parent / 'cache')
    for header in headers:
        path = work / header
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('#include "host_stubs.h"\n', encoding='utf-8')
    for serial in (0, 1):
        binary = work / f'test-{serial}.exe'
        result = work / f'result-{serial}.jsonl'
        subprocess.run([
            str(compiler), 'cc', '-target', 'x86_64-windows-gnu', '-std=c11',
            '-Wall', '-Wextra', '-Werror', '-Wformat=2', '-O0',
            f'-DCONFIG_CSI_BATCH_SERIAL_OUTPUT={serial}', '-I', str(work),
            '-I', str(here), str(here / 'test_batch.c'),
            str(here.parent / 'main/csi_batch_json.c'), '-o', str(binary),
        ], check=True)
        completed = subprocess.run([str(binary), str(result)], text=True, capture_output=True, check=True)
        records = [json.loads(line) for line in result.read_text().splitlines()]
        assert len(records) == 3
        for batch, expected_count in zip(records, (20, 20, 20)):
            assert set(batch) == {'schema_version', 'device_id', 'session_id', 'batch_id', 'samples'}
            assert len(batch['samples']) == expected_count
            for sample in batch['samples']:
                assert set(sample) == {'seq', 'timestamp_us', 'ap_mac', 'rssi_dbm',
                                       'noise_floor_dbm', 'channel', 'bandwidth_mhz', 'sig_mode',
                                       'first_word_invalid', 'csi_raw'}
            assert all(len(s['csi_raw']) == 128 for s in batch['samples'])
            assert all(s['first_word_invalid'] is True for s in batch['samples'])
            assert all(s['bandwidth_mhz'] == 20 for s in batch['samples'])
            assert all(s['sig_mode'] == 1 for s in batch['samples'])
        assert records[0]['device_id'] == 'dev"\\\n'
        assert records[0]['samples'][0]['timestamp_us'] == 5000000000
        assert records[0]['samples'][0]['csi_raw'][0] == -128
        assert records[0]['samples'][1]['csi_raw'][0] == 127
        if serial:
            lines = [line for line in completed.stdout.splitlines() if line.startswith('CSI_DATA,')]
            assert len(lines) == 2100
            for row in csv.reader(lines):
                assert len(row) == 25 and len(json.loads(row[-1])) == int(row[-3]) == 128
        print(completed.stderr.strip())
print('All host tests passed: continuous capture, FIFO saturation/pause/resume, CSV, partial writes and failed-batch release.')
