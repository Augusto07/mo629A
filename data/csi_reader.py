
import ast
import json
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

# ==================================================
# CONFIGURAÇÕES — EDITE ESTA SEÇÃO
# ==================================================

ARQUIVO = "CSI-captura.csv"

# Canais que serão plotados ao longo do tempo.
# Use None para plotar todos os canais.
# Exemplos: [0, 1, 2, 10, 15]
CANAIS_PLOTAR = [10, 15]

# Pacote utilizado no gráfico de amplitude de todos os canais.
# A numeração começa em zero.
PACOTE_PLOTAR = 0

# ==================================================
# LEITURA E PROCESSAMENTO DOS DADOS
# ==================================================

df = pd.read_csv(ARQUIVO)

def parse_data(valor):
    if isinstance(valor, list):
        return valor
    try:
        return json.loads(valor)
    except (json.JSONDecodeError, TypeError):
        return ast.literal_eval(valor)

def csi_para_complexo(valores):
    valores = np.asarray(valores, dtype=float)
    n = len(valores) // 2

    imaginario = valores[0:2*n:2]
    real = valores[1:2*n:2]

    return real + 1j * imaginario

csi_pacotes = [
    csi_para_complexo(parse_data(valor))
    for valor in df["data"]
]

# Uniformiza o tamanho dos pacotes
n_componentes = min(len(pacote) for pacote in csi_pacotes)

csi = np.vstack([
    pacote[:n_componentes]
    for pacote in csi_pacotes
])

amplitude = np.abs(csi)
fase = np.angle(csi)

numero_pacotes, numero_canais = amplitude.shape

print("Quantidade de pacotes:", numero_pacotes)
print("Quantidade de canais CSI:", numero_canais)

# Validar o índice do pacote selecionado
if not 0 <= PACOTE_PLOTAR < numero_pacotes:
    raise ValueError(
        f"PACOTE_PLOTAR deve estar entre 0 e {numero_pacotes - 1}"
    )

# Validar os canais selecionados
if CANAIS_PLOTAR is None:
    canais_selecionados = list(range(numero_canais))
else:
    canais_selecionados = list(dict.fromkeys(CANAIS_PLOTAR))

    invalidos = [
        canal for canal in canais_selecionados
        if not isinstance(canal, int)
        or canal < 0
        or canal >= numero_canais
    ]

    if invalidos:
        raise ValueError(
            f"Canais inválidos: {invalidos}. "
            f"Use índices entre 0 e {numero_canais - 1}."
        )

# ==================================================
# GRÁFICO 1: TODOS OS CANAIS DE UM PACOTE
# ==================================================

plt.figure(figsize=(12, 4))

plt.plot(
    amplitude[PACOTE_PLOTAR],
    marker=".",
    markersize=3
)

plt.title(f"Amplitude de todos os canais — Pacote {PACOTE_PLOTAR}")
plt.xlabel("Índice do canal CSI")
plt.ylabel("Amplitude")
plt.grid(True, alpha=0.3)
plt.tight_layout()

# ==================================================
# GRÁFICO 2: MAPA DE CALOR
# ==================================================

plt.figure(figsize=(12, 6))

plt.imshow(
    amplitude.T,
    aspect="auto",
    origin="lower",
    interpolation="nearest"
)

plt.title("Evolução da amplitude CSI")
plt.xlabel("Índice do pacote")
plt.ylabel("Índice do canal CSI")
plt.colorbar(label="Amplitude")
plt.tight_layout()

# ==================================================
# GRÁFICO 3: CANAIS SELECIONADOS AO LONGO DO TEMPO
# ==================================================

plt.figure(figsize=(15, 6))

pacotes = np.arange(numero_pacotes)

for canal in canais_selecionados:
    plt.plot(
        pacotes,
        amplitude[:, canal],
        linewidth=0.9,
        label=f"Canal {canal}"
    )

plt.title("Amplitude dos canais selecionados ao longo do tempo")
plt.xlabel("Índice do pacote")
plt.ylabel("Amplitude")
plt.grid(True, alpha=0.3)

if canais_selecionados:
    plt.legend(loc="best", fontsize="small")

plt.tight_layout()
plt.show()
