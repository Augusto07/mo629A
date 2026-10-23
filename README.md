# Unicamp IoT

Sistema de IoT que conta quantas pessoas entram na sala de aula do Instituto de Computação da Unicamp, usando um ESP32. O ESP32 envia os dados pela internet para um servidor web, que os guarda em um banco de dados e os mostra em um painel com gráficos.

Este é um projeto de mestrado em desenvolvimento.

## O que o painel mostra

- **Entradas hoje:** o total de pessoas que entraram na sala no dia atual.
- **Entradas por dia:** o total de cada dia, nos últimos 7, 14 ou 30 dias.
- **Entradas por hora:** como as entradas se distribuem ao longo de um dia escolhido.
- **Sinal Wi-Fi do ESP32:** a força do sinal (RSSI, em dBm) ao longo do dia. Se o ESP32 ficar mais de 15 minutos sem enviar leituras, a linha do gráfico é interrompida, o que mostra quando ele esteve fora do ar.
- **Página "Sobre o projeto":** uma explicação resumida do sistema.

O painel funciona em computadores e em celulares. Todos os horários seguem o horário de Brasília.

## Como funciona

```
ESP32 --(POST com JSON)--> servidor Flask --> banco SQLite --> painel com gráficos
```

1. O ESP32 detecta uma entrada na sala.
2. Ele envia o registro, pela internet, para a API do servidor.
3. O servidor guarda o registro, com data e hora, no banco de dados.
4. O painel consulta a API e desenha os gráficos.

Além das entradas, o ESP32 envia periodicamente a leitura do sinal Wi-Fi, para acompanhar a qualidade da conexão.

## Tecnologias

- ESP32, para a coleta dos dados
- Python e Flask, para o servidor e a API
- SQLite, para o banco de dados
- HTML, CSS e JavaScript, com Chart.js, para o painel
- PythonAnywhere, para a hospedagem

## Como rodar no computador

Requisito: Python 3 instalado.

1. Instale as dependências:
   ```bash
   pip install -r requirements.txt
   ```
2. Crie o seu arquivo de configuração a partir do modelo:
   ```bash
   copy config.example.py config.py     # Windows
   cp config.example.py config.py       # Linux e macOS
   ```
3. (Opcional) Abra o `config.py` e troque a `API_KEY` por uma chave sua.
4. Inicie o servidor:
   ```bash
   python flask_app.py
   ```
5. Abra http://127.0.0.1:5000 no navegador.

O servidor reinicia sozinho quando você salva um arquivo. Para desligá-lo, use `Ctrl+C`.

O banco local (`dados.db`) é criado automaticamente na pasta do projeto, começa vazio e é independente do banco do servidor em produção. Para ver os gráficos com dados, envie registros pela API, como descrito abaixo.

O painel carrega o Chart.js e as fontes por CDN, então precisa de conexão com a internet.

## Configuração

O arquivo `config.py` define duas coisas e **não deve ser enviado ao GitHub** (o `.gitignore` já o ignora):

| Variável | Para que serve |
|---|---|
| `DB` | Caminho do arquivo do banco de dados |
| `API_KEY` | Chave que o ESP32 envia no header `X-API-Key` |

No computador, o modelo usa um `dados.db` na pasta do projeto. No servidor, `DB` deve ser o caminho absoluto, por exemplo `/home/SEU-USUARIO/dados.db`. A mesma `API_KEY` precisa estar no servidor e no código do ESP32.

## API

### Envio de dados

Exige o header `X-API-Key` com a chave do `config.py`.

| Método e caminho | Corpo | Para que serve |
|---|---|---|
| `POST /api/dados` | `{"pessoas": 1}` | Registra quantas pessoas entraram |
| `POST /api/sinal` | `{"rssi": -62}` | Registra uma leitura de sinal Wi-Fi, em dBm (de -120 a 0) |

Exemplo de requisição:

```
POST /api/dados
Content-Type: application/json
X-API-Key: SUA-CHAVE

{"pessoas": 1}
```

O campo `pessoas` é a quantidade de pessoas que entraram naquele envio (normalmente 1). O servidor soma esses valores por dia e por hora.

O campo opcional `ts` (por exemplo, `"2026-10-17 08:15:00"`, no horário de Brasília) permite informar a data e a hora do registro, o que é útil em testes. Sem ele, vale o momento em que o servidor recebe o envio.

Respostas: `200` com `{"ok": true}` quando grava, `401` se a chave estiver ausente ou errada, e `400` se algum campo for inválido (a mensagem explica o motivo).

### Consulta de dados

Não exigem chave.

| Caminho | Devolve |
|---|---|
| `GET /api/diario?dias=30` | Total de entradas por dia (de 1 a 90 dias) |
| `GET /api/por-hora?data=AAAA-MM-DD` | Entradas nas 24 horas de um dia |
| `GET /api/sinal?data=AAAA-MM-DD` | Leituras de sinal Wi-Fi de um dia |
| `GET /api/historico` | Registros brutos das entradas, com horário em UTC |

## Banco de dados

SQLite, com duas tabelas:

| Tabela | Colunas |
|---|---|
| `entradas` | `id`, `ts`, `pessoas` |
| `sinal` | `id`, `ts`, `rssi` |

Os horários ficam guardados em UTC e são convertidos para o horário de Brasília (UTC-3) nas consultas. As tabelas são criadas automaticamente na primeira execução.

## Publicação no PythonAnywhere

1. Coloque o código na pasta do site (por exemplo, `~/mysite`), clonando este repositório.
2. Crie lá o `config.py`, com o caminho absoluto do banco e a chave da API.
3. Na aba **Web**, clique em **Reload**.

Para atualizar depois de enviar mudanças ao GitHub, rode `git pull` na pasta do site e clique em **Reload**. Se só os arquivos de `templates/` e `static/` mudarem, o Reload não é necessário, mas vale forçar a atualização do navegador (`Ctrl+F5`).

## Limitações e observações

- **Horário do registro:** sem o campo `ts`, o horário gravado é o da chegada do envio, e não o da entrada da pessoa. Se o ESP32 ficar offline e enviar tudo de uma vez ao reconectar, essas entradas ficam com o horário da reconexão.
- **Consultas públicas:** só os envios exigem a chave. Quem souber o endereço do site consegue ler os dados pelas rotas de consulta.
- **Plano gratuito do PythonAnywhere:** o site precisa ser renovado uma vez por mês, pelo botão da aba **Web**, e a cota de CPU é de 100 segundos por dia. Passar da cota deixa o site mais lento, mas não o derruba.
- **Sinal Wi-Fi:** o RSSI mede a qualidade da conexão entre o ESP32 e o roteador, e não até o servidor.