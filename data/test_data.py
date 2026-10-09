import csv
import time
import serial
from datetime import datetime

# Altere COM3 para a porta do seu ESP8266
PORTA = "COM3"
BAUD_RATE = 115200
ARQUIVO = "rssi.csv"

with serial.Serial(PORTA, BAUD_RATE, timeout=2) as esp:
    # O ESP8266 pode reiniciar ao abrir a porta serial.
    time.sleep(2)
    esp.reset_input_buffer()

    with open(ARQUIVO, "a", newline="", encoding="utf-8") as arquivo:
        escritor = csv.writer(arquivo)

        # Cria o cabeçalho apenas se o arquivo estiver vazio.
        if arquivo.tell() == 0:
            escritor.writerow([
                "data_hora",
                "tempo_ms",
                "rssi_dbm"
            ])

        print(f"Salvando dados em {ARQUIVO}")
        print("Pressione Ctrl+C para encerrar.")

        try:
            while True:
                linha = esp.readline().decode(
                    "utf-8", errors="ignore"
                ).strip()

                if not linha or linha == "tempo_ms,rssi_dbm":
                    continue

                partes = linha.split(",")

                if len(partes) != 2:
                    continue

                try:
                    tempo_ms = int(partes[0])
                    rssi_dbm = int(partes[1])
                except ValueError:
                    continue

                data_hora = datetime.now().astimezone().isoformat(
                    timespec="seconds"
                )

                escritor.writerow([
                    data_hora,
                    tempo_ms,
                    rssi_dbm
                ])

                # Garante que as leituras sejam gravadas no disco.
                arquivo.flush()

                print(data_hora, rssi_dbm, "dBm")

        except KeyboardInterrupt:
            print(f"\nColeta encerrada. Arquivo: {ARQUIVO}")