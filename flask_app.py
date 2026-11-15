import requests

from flask import Flask, render_template, jsonify
from requests.exceptions import RequestException

app = Flask(__name__)

# ----------------------------------------------------------------------
# CONFIGURAÇÕES
# ----------------------------------------------------------------------

try:
    import config

    API_BASE_URL = getattr(config, "API_BASE_URL", "").rstrip("/")
    API_TOKEN = getattr(config, "API_TOKEN", "")

except ImportError:
    API_BASE_URL = ""
    API_TOKEN = ""


# ----------------------------------------------------------------------
# CONSULTA À API DA AWS
# ----------------------------------------------------------------------

def consultar_api(endpoint):
    """
    Consulta a API da AWS utilizando Bearer Token.
    O token permanece exclusivamente no servidor Flask.
    """

    if not API_BASE_URL:
        return jsonify({
            "erro": "Endereço da API não configurado no servidor."
        }), 503

    if not API_TOKEN:
        return jsonify({
            "erro": "Bearer Token não configurado no servidor."
        }), 503

    url = f"{API_BASE_URL}/{endpoint}"

    headers = {
        "Authorization": f"Bearer {API_TOKEN}",
        "Accept": "application/json"
    }

    try:
        response = requests.get(
            url,
            headers=headers,
            timeout=(5, 20)
        )

        response.raise_for_status()

        dados = response.json()

        return jsonify(dados)

    except requests.exceptions.HTTPError as erro:
        status_aws = (
            erro.response.status_code
            if erro.response is not None
            else 502
        )

        app.logger.error(
            "Erro HTTP ao consultar AWS. Endpoint: %s | Status: %s",
            endpoint,
            status_aws
        )

        return jsonify({
            "erro": "A API da AWS rejeitou a requisição.",
            "status": status_aws
        }), 502

    except requests.exceptions.Timeout:
        app.logger.error(
            "Timeout ao consultar AWS. Endpoint: %s",
            endpoint
        )

        return jsonify({
            "erro": "Tempo limite excedido ao consultar a AWS."
        }), 504

    except (RequestException, ValueError):
        app.logger.exception(
            "Erro ao consultar AWS. Endpoint: %s",
            endpoint
        )

        return jsonify({
            "erro": "Não foi possível consultar a API da AWS."
        }), 502


# ----------------------------------------------------------------------
# ROTAS INTERMEDIÁRIAS PARA O FRONTEND
# ----------------------------------------------------------------------

@app.route("/api/now")
def api_now():
    return consultar_api("now")


@app.route("/api/series")
def api_series():
    return consultar_api("series")


# ----------------------------------------------------------------------
# PÁGINAS DO SITE
# ----------------------------------------------------------------------

@app.route("/")
def index():
    api_configurada = bool(API_BASE_URL and API_TOKEN)

    return render_template(
        "painel.html",
        pagina="painel",
        api_configurada=api_configurada
    )


@app.route("/sobre")
def sobre():
    return render_template(
        "sobre.html",
        pagina="sobre"
    )


# ----------------------------------------------------------------------
# EXECUÇÃO LOCAL
# ----------------------------------------------------------------------

if __name__ == "__main__":
    app.run(debug=True)