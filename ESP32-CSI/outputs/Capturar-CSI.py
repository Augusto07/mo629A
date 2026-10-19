"""Salva a saida CSI do ESP32 em um novo CSV, sem reiniciar a placa."""
import argparse
import csv
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import time

import serial

HEADER = 'type,id,mac,rssi,rate,sig_mode,mcs,bandwidth,smoothing,not_sounding,aggregation,stbc,fec_coding,sgi,noise_floor,ampdu_cnt,channel,secondary_channel,local_timestamp,ant,sig_len,rx_format,len,first_word,data'.split(',')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', default='COM7')
    parser.add_argument('--seconds', type=float, default=60, help='0 para coletar ate Ctrl+C')
    args = parser.parse_args()
    if args.seconds < 0:
        parser.error('--seconds deve ser zero ou positivo')
    stamp = datetime.now(timezone(timedelta(hours=-3))).strftime('%Y-%m-%d_%H-%M-%S_%f')
    path = Path(__file__).resolve().parent / f'CSI_{stamp}.csv'
    count = 0
    rejected = 0
    port = serial.Serial()
    port.port = args.port
    port.baudrate = 921600
    port.timeout = 0.5
    port.dtr = False
    port.rts = False
    try:
        port.open()
    except serial.SerialException as exc:
        parser.exit(1, f'Nao foi possivel abrir {args.port}. Feche outros monitores seriais e confira a porta.\n{exc}\n')
    started = time.monotonic()
    last_report = started
    print(f'Gravando: {path}', flush=True)
    print('Para encerrar antes do prazo, pressione Ctrl+C.', flush=True)
    try:
        with path.open('x', encoding='utf-8', newline='') as target:
            writer = csv.writer(target)
            writer.writerow(HEADER)
            try:
                while not args.seconds or time.monotonic() - started < args.seconds:
                    raw = port.readline().decode('utf-8', errors='replace').strip()
                    if raw.startswith('CSI_DATA,'):
                        try:
                            row = next(csv.reader([raw]))
                            if len(row) != len(HEADER) or len(json.loads(row[-1])) != int(row[-3]):
                                raise ValueError('Amostra incompleta')
                        except (ValueError, IndexError, csv.Error, TypeError):
                            rejected += 1
                        else:
                            writer.writerow(row)
                            count += 1
                    if time.monotonic() - last_report >= 5:
                        target.flush()
                        print(f'{time.monotonic() - started:.0f}s | {count} amostras salvas', flush=True)
                        last_report = time.monotonic()
            except KeyboardInterrupt:
                print('\nColeta encerrada pelo usuario.', flush=True)
            except serial.SerialException as exc:
                print(f'\nConexao serial interrompida: {exc}', flush=True)
    finally:
        port.close()
    print(f'Salvas {count} amostras em {time.monotonic() - started:.1f}s. Linhas CSI invalidas ignoradas: {rejected}.', flush=True)
    print(f'CSV: {path}', flush=True)


if __name__ == '__main__':
    main()
