
# SmartClass

**Conectando tecnologia e presença em sala de aula.**

O **SmartClass** é um projeto desenvolvido no Instituto de Computação da Universidade Estadual de Campinas (UNICAMP), que utiliza tecnologias de Internet das Coisas (IoT) e informações do sinal Wi-Fi para acompanhar a presença de pessoas em uma sala de aula.

A solução utiliza um dispositivo ESP32 para coletar informações de CSI (*Channel State Information*) do sinal Wi-Fi e enviá-las a um servidor. Os dados são disponibilizados por meio de uma API e apresentados em um painel web, permitindo acompanhar os registros de presença ao longo do tempo.

## Visão geral

O projeto é composto por três partes principais:

- **Coleta de dados:** o ESP32 realiza medições de CSI relacionadas ao sinal Wi-Fi do ambiente.
- **Infraestrutura e disponibilização dos dados:** a AWS é utilizada para disponibilizar a API e armazenar os dados coletados.
- **Visualização:** uma aplicação web desenvolvida com Python e Flask consulta a API e apresenta as informações em um painel interativo.

## Arquitetura

```text
ESP32
  |
  | Coleta de informações CSI
  v
Infraestrutura AWS
  |
  | API e armazenamento de dados
  v
Aplicação Web (Python + Flask)
  |
  | Consulta e organização dos dados
  v
Painel SmartClass
  |
  v
Visualização de presença
```

## Funcionalidades

O painel web disponibiliza indicadores e gráficos para facilitar a visualização dos dados:

- **Presença atual:** apresenta a situação indicada pela leitura mais recente recebida.
- **Registros hoje:** exibe a quantidade de registros de presença do dia atual.
- **Maior atividade:** identifica o horário com maior quantidade de registros de presença no dia.
- **Total no período:** apresenta o total de registros positivos no intervalo selecionado.
- **Gráfico de presença:** organiza os registros por dia e horário, permitindo observar padrões ao longo do tempo.
- **Seleção de período:** permite visualizar os dados dos últimos 7 ou 15 dias.
- **Atualização automática:** realiza consultas periódicas à API para atualizar os indicadores e o gráfico.

## Tecnologias utilizadas

| Tecnologia | Aplicação |
|---|---|
| ESP32 | Coleta de informações CSI do sinal Wi-Fi |
| AWS | Infraestrutura em nuvem, API e armazenamento de dados |
| Python | Desenvolvimento do servidor |
| Flask | Framework utilizado na aplicação web |
| JavaScript | Interatividade e atualização dos dados no painel |
| Chart.js | Construção dos gráficos |
| HTML5 e CSS3 | Estrutura e estilização da interface |
| PythonAnywhere | Hospedagem da aplicação web |

## Comunicação com a API

A aplicação Flask atua como intermediária entre o navegador e a API disponibilizada na infraestrutura AWS.

O painel utiliza duas rotas internas para consultar os dados:

| Rota | Descrição |
|---|---|
| `/api/now` | Obtém a leitura mais recente |
| `/api/series` | Obtém o histórico de registros para construção do gráfico |

As credenciais de acesso à API são mantidas na configuração do servidor, evitando sua exposição diretamente no código JavaScript executado pelo navegador.

## Hospedagem

A aplicação web é hospedada na plataforma **PythonAnywhere**, que permite executar aplicações Python utilizando Flask.

A hospedagem disponibiliza o painel por meio de um endereço web, enquanto a infraestrutura AWS permanece responsável pelos serviços de API e armazenamento de dados.

## Execução local

Para executar a aplicação em ambiente local, siga os passos abaixo.

### 1. Clone o repositório

```bash
git clone URL_DO_REPOSITORIO
cd NOME_DO_REPOSITORIO
```

### 2. Crie um ambiente virtual

```bash
python -m venv venv
```

### 3. Ative o ambiente virtual

Windows:

```bash
venv\Scripts\activate
```

Linux/macOS:

```bash
source venv/bin/activate
```

### 4. Instale as dependências

Caso o repositório contenha um arquivo `requirements.txt`:

```bash
pip install -r requirements.txt
```

### 5. Configure as variáveis de ambiente

Configure no ambiente de execução as credenciais necessárias para a comunicação com a API:

- `API_BASE_URL`: endereço-base da API.
- `API_TOKEN`: token de autenticação.

**Importante:** não compartilhe essas credenciais publicamente nem as envie para o repositório.

### 6. Execute a aplicação

Utilize o comando de inicialização configurado no projeto Flask.

## Objetivo

O SmartClass busca integrar tecnologias de IoT, comunicação sem fio e desenvolvimento web para transformar informações coletadas do ambiente em dados visualizáveis, facilitando o acompanhamento dos registros de presença em salas de aula.

---

Desenvolvido no **Instituto de Computação — UNICAMP**.
