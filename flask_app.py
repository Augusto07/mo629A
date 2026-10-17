from datetime import datetime, timedelta, timezone
import sqlite3

from flask import Flask, request, jsonify, render_template

app = Flask(__name__)

# ----------------------------------------------------------------------
# CONFIGURAÇÃO: vem do arquivo config.py, que NÃO vai para o GitHub.
# Copie config.example.py para config.py e ajuste os valores.
# ----------------------------------------------------------------------
try:
    from config import DB, API_KEY
except ImportError as erro:
    raise RuntimeError(
        "Arquivo config.py não encontrado. Copie config.example.py para "
        "config.py e preencha DB e API_KEY."
    ) from erro

# Horário de Brasília (UTC-3). O banco guarda em UTC; convertemos ao consultar.
BRT = timezone(timedelta(hours=-3))
OFFSET_SQL = "-3 hours"

def init_db():
    with sqlite3.connect(DB) as con:
        con.execute(
            """CREATE TABLE IF NOT EXISTS entradas (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT DEFAULT CURRENT_TIMESTAMP,
                pessoas INTEGER NOT NULL)"""
        )
        con.execute(
            """CREATE TABLE IF NOT EXISTS sinal (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT DEFAULT CURRENT_TIMESTAMP,
                rssi INTEGER NOT NULL)"""
        )

init_db()

def hoje_br():
    return datetime.now(BRT).date()

ERRO_TS = "campo 'ts' deve estar no formato AAAA-MM-DD HH:MM:SS"

def ts_utc_do_corpo(corpo):
    """Lê o campo opcional 'ts' (horário de Brasília) e devolve em UTC.
    Devolve None se não veio. Levanta ValueError/TypeError se for inválido."""
    texto = corpo.get("ts")
    if not texto:
        return None
    local = datetime.strptime(texto, "%Y-%m-%d %H:%M:%S")
    return (local + timedelta(hours=3)).strftime("%Y-%m-%d %H:%M:%S")

# ----------------------------------------------------------------------
# API: recebe os dados do ESP32
# ----------------------------------------------------------------------
@app.route("/api/dados", methods=["POST"])
def receber():
    if request.headers.get("X-API-Key") != API_KEY:
        return jsonify(erro="não autorizado"), 401
    corpo = request.get_json(silent=True) or {}
    try:
        pessoas = int(corpo.get("pessoas"))
    except (TypeError, ValueError):
        return jsonify(erro="campo 'pessoas' deve ser um número inteiro"), 400

    # Opcional: "ts" no horário de Brasília (AAAA-MM-DD HH:MM:SS), útil para testes.
    # Sem ele, o servidor usa o momento em que recebeu o envio.
    try:
        ts_utc = ts_utc_do_corpo(corpo)
    except (TypeError, ValueError):
        return jsonify(erro=ERRO_TS), 400
    with sqlite3.connect(DB) as con:
        if ts_utc:
            con.execute("INSERT INTO entradas (ts, pessoas) VALUES (?, ?)", (ts_utc, pessoas))
        else:
            con.execute("INSERT INTO entradas (pessoas) VALUES (?)", (pessoas,))
    return jsonify(ok=True)

# Recebe a leitura de sinal Wi-Fi (RSSI, em dBm) enviada periodicamente pelo ESP32
@app.route("/api/sinal", methods=["POST"])
def receber_sinal():
    if request.headers.get("X-API-Key") != API_KEY:
        return jsonify(erro="não autorizado"), 401
    corpo = request.get_json(silent=True) or {}
    try:
        rssi = int(corpo.get("rssi"))
    except (TypeError, ValueError):
        return jsonify(erro="campo 'rssi' deve ser um número inteiro (dBm)"), 400
    if not -120 <= rssi <= 0:
        return jsonify(erro="campo 'rssi' fora do intervalo esperado (-120 a 0 dBm)"), 400
    try:
        ts_utc = ts_utc_do_corpo(corpo)
    except (TypeError, ValueError):
        return jsonify(erro=ERRO_TS), 400
    with sqlite3.connect(DB) as con:
        if ts_utc:
            con.execute("INSERT INTO sinal (ts, rssi) VALUES (?, ?)", (ts_utc, rssi))
        else:
            con.execute("INSERT INTO sinal (rssi) VALUES (?)", (rssi,))
    return jsonify(ok=True)

# ----------------------------------------------------------------------
# API: dados para os gráficos
# ----------------------------------------------------------------------
@app.route("/api/diario")
def diario():
    try:
        n = int(request.args.get("dias", 30))
    except ValueError:
        n = 30
    n = max(1, min(n, 90))

    hoje = hoje_br()
    inicio = hoje - timedelta(days=n - 1)

    with sqlite3.connect(DB) as con:
        linhas = con.execute(
            """SELECT strftime('%Y-%m-%d', ts, ?) AS dia, SUM(pessoas)
               FROM entradas
               WHERE strftime('%Y-%m-%d', ts, ?) >= ?
               GROUP BY dia""",
            (OFFSET_SQL, OFFSET_SQL, inicio.isoformat()),
        ).fetchall()
    totais = {dia: total for dia, total in linhas}

    dias = []
    for i in range(n):
        d = (inicio + timedelta(days=i)).isoformat()
        dias.append({"data": d, "total": totais.get(d, 0)})
    return jsonify(hoje=hoje.isoformat(), dias=dias)

@app.route("/api/por-hora")
def por_hora():
    texto = request.args.get("data", hoje_br().isoformat())
    try:
        dia = datetime.strptime(texto, "%Y-%m-%d").date()
    except ValueError:
        return jsonify(erro="data inválida, use AAAA-MM-DD"), 400

    with sqlite3.connect(DB) as con:
        linhas = con.execute(
            """SELECT CAST(strftime('%H', ts, ?) AS INTEGER) AS hora, SUM(pessoas)
               FROM entradas
               WHERE strftime('%Y-%m-%d', ts, ?) = ?
               GROUP BY hora""",
            (OFFSET_SQL, OFFSET_SQL, dia.isoformat()),
        ).fetchall()
    totais = {hora: total for hora, total in linhas}

    horas = [{"hora": h, "total": totais.get(h, 0)} for h in range(24)]
    return jsonify(data=dia.isoformat(), horas=horas, total=sum(totais.values()))

@app.route("/api/sinal")
def sinal():
    texto = request.args.get("data", hoje_br().isoformat())
    try:
        dia = datetime.strptime(texto, "%Y-%m-%d").date()
    except ValueError:
        return jsonify(erro="data inválida, use AAAA-MM-DD"), 400

    with sqlite3.connect(DB) as con:
        linhas = con.execute(
            """SELECT strftime('%H:%M:%S', ts, ?) AS hora, rssi
               FROM sinal
               WHERE strftime('%Y-%m-%d', ts, ?) = ?
               ORDER BY ts""",
            (OFFSET_SQL, OFFSET_SQL, dia.isoformat()),
        ).fetchall()
    return jsonify(data=dia.isoformat(), leituras=[{"hora": h, "rssi": r} for h, r in linhas])

# Útil para conferir os registros brutos
@app.route("/api/historico")
def historico():
    with sqlite3.connect(DB) as con:
        linhas = con.execute("SELECT ts, pessoas FROM entradas ORDER BY ts").fetchall()
    return jsonify([{"ts": ts, "pessoas": p} for ts, p in linhas])

# ----------------------------------------------------------------------
# Páginas (o HTML fica em templates/, o CSS e o JS em static/)
# ----------------------------------------------------------------------
@app.route("/")
def index():
    return render_template("painel.html", pagina="painel")

@app.route("/sobre")
def sobre():
    return render_template("sobre.html", pagina="sobre")

# Só roda ao executar "python flask_app.py" no computador (VS Code).
# No PythonAnywhere este bloco é ignorado.
if __name__ == "__main__":
    app.run(debug=True)