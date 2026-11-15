import os

"""
Configurações do projeto Unicamp IoT.

O token não deve ser compartilhado ou enviado ao GitHub.
"""

API_BASE_URL = os.getenv(
    "API_BASE_URL",
    "https://j8wv601b6h.execute-api.us-east-2.amazonaws.com/model-result"
)

API_TOKEN = os.getenv("API_TOKEN", "")