import os

# No computador (VS Code): o banco fica numa pasta ao lado do código.
DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dados.db")

# No PythonAnywhere, use o caminho absoluto do seu usuário:
# DB = "/home/SEU-USUARIO/dados.db"

# Chave que o ESP32 envia no header X-API-Key.
API_KEY = "troque-por-uma-chave-secreta"