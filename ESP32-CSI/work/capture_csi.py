import csv
import json
import pathlib
import time
import serial

root = pathlib.Path(__file__).resolve().parent
output = root.parent / 'outputs'
port = serial.Serial()
port.port = 'COM7'
port.baudrate = 921600
port.timeout = 0.5
port.dtr = False
port.rts = False
port.open()
count = 0
header = 'type,id,mac,rssi,rate,sig_mode,mcs,bandwidth,smoothing,not_sounding,aggregation,stbc,fec_coding,sgi,noise_floor,ampdu_cnt,channel,secondary_channel,local_timestamp,ant,sig_len,rx_format,len,first_word,data'
header_received = False
first_rssi = None
deadline = time.monotonic() + 30
with (root / 'serial-test.log').open('w', encoding='utf-8') as log, (output / 'CSI-captura.csv').open('w', encoding='utf-8', newline='') as data:
    data.write(header + '\n')
    while time.monotonic() < deadline:
        line = port.readline().decode('utf-8', errors='replace').strip()
        if not line:
            continue
        log.write(line + '\n')
        if line.startswith('type,id,mac,'):
            header_received = True
        if line.startswith('CSI_DATA,'):
            data.write(line + '\n')
            count += 1
            if first_rssi is None:
                try:
                    first_rssi = int(next(csv.reader([line]))[3])
                except (ValueError, IndexError):
                    pass
port.close()
print(json.dumps({'csi_samples': count, 'first_rssi_dbm': first_rssi, 'capture_seconds': 30, 'header_received': header_received}))
