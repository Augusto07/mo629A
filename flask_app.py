from flask import Flask, render_template

app = Flask(__name__)

# ----------------------------------------------------------------------
# Este servidor só entrega as páginas (HTML, CSS e JavaScript).
# Os dados vêm da API na AWS, consultada diretamente pelo navegador.
#
# O endereço da API fica no arquivo config.py, que NÃO vai para o GitHub.
# Copie config.example.py para config.py e preencha API_BASE_URL.
# Enquanto estiver vazio, o painel mostra dados de demonstração.
# ----------------------------------------------------------------------
try:
    import config
    API_BASE_URL = getattr(config, "API_BASE_URL", "")
except ImportError:
    API_BASE_URL = ""

@app.route("/")
def index():
    return render_template("painel.html", pagina="painel", api_base=API_BASE_URL)

@app.route("/sobre")
def sobre():
    return render_template("sobre.html", pagina="sobre")

# Só roda ao executar "python flask_app.py" no computador (VS Code).
# No PythonAnywhere este bloco é ignorado.
if __name__ == "__main__":
    app.run(debug=True)