import pandas as pd
import matplotlib.pyplot as plt

# Carrega os dados
df = pd.read_csv("rssi.csv")

# Converte a data/hora para datetime
df["data_hora"] = pd.to_datetime(df["data_hora"])

# Plota o RSSI ao longo do tempo
plt.figure(figsize=(12, 5))
plt.plot(df["data_hora"], df["rssi_dbm"], linewidth=1)

plt.title("RSSI do ESP8266 ao longo do tempo")
plt.xlabel("Horário")
plt.ylabel("RSSI (dBm)")
plt.grid(True)
plt.xticks(rotation=45)
plt.tight_layout()

plt.show()