# Unicamp IoT

Sistema de IoT que conta quantas pessoas entram na sala de aula do Instituto de Computação da Unicamp, usando um ESP32. Os dados são enviados a um servidor web e mostrados em gráficos.

Projeto de mestrado em desenvolvimento.

## Como rodar

```bash
pip install -r requirements.txt
copy config.example.py config.py     # Windows (Linux e macOS: cp)
python flask_app.py
```

Abra http://127.0.0.1:5000 no navegador.

O `config.py` guarda o endereço da API na AWS (`API_BASE_URL`) e não vai para o GitHub. Enquanto esse endereço estiver vazio, o painel mostra dados de demonstração.