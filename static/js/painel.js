
// De quantos em quantos segundos o campo de presença consulta /now
const INTERVALO_AGORA_S = 300;

// De quantos em quantos segundos o gráfico consulta /series
const INTERVALO_SERIES_S = 600;

// Idade máxima da última leitura para valer como "agora", em minutos.
const LEITURA_VALIDA_MIN = 5;

// Horário inicial e final exibidos no gráfico.
const HORA_INI = 7;
const HORA_FIM = 23;

const COR_SIM = '#2E9E6B';

// ----------------------------------------------------------------------
// CONFIGURAÇÃO DA API
// ----------------------------------------------------------------------

const configApi = document.getElementById('config-api');

const API_CONFIGURADA =
  configApi && configApi.dataset.apiEnabled === 'true';

const MODO_DEMO = !API_CONFIGURADA;

const $ = id => document.getElementById(id);

const reduzMovimento =
  window.matchMedia('(prefers-reduced-motion: reduce)').matches;

const dois = n => String(n).padStart(2, '0');

let grafico = null;

// Chave usada para preservar a conexão durante a navegação interna.
const CHAVE_CONEXAO = 'unicampIoT_apiConectada';

// Recupera o estado salvo durante a navegação entre páginas.
let apiConectada =
  !MODO_DEMO &&
  sessionStorage.getItem(CHAVE_CONEXAO) === 'true';

let apiEmConexao = false;

// ----------------------------------------------------------------------
// DATAS
// ----------------------------------------------------------------------

const dataLocalISO = d =>
  d.getFullYear() + '-' +
  dois(d.getMonth() + 1) + '-' +
  dois(d.getDate());

const somarDias = (iso, n) => {
  const p = iso.split('-');

  return dataLocalISO(
    new Date(+p[0], +p[1] - 1, +p[2] + n, 12)
  );
};

const formatarDiaCurto = iso =>
  new Date(iso + 'T12:00:00').toLocaleDateString(
    'pt-BR',
    {
      weekday: 'short',
      day: '2-digit',
      month: '2-digit'
    }
  );

// ----------------------------------------------------------------------
// CONVERSÃO DE UTC PARA HORÁRIO DE BRASÍLIA
// ----------------------------------------------------------------------

const DESLOCAMENTO_BR_MS = -3 * 60 * 60 * 1000;

function emBR(ms) {
  const d = new Date(ms + DESLOCAMENTO_BR_MS);

  return {
    data:
      d.getUTCFullYear() + '-' +
      dois(d.getUTCMonth() + 1) + '-' +
      dois(d.getUTCDate()),

    hora: d.getUTCHours(),
    minuto: d.getUTCMinutes()
  };
}

const agoraBR = () => emBR(Date.now());

const analisarData = ts =>
  Date.parse(String(ts).replace(/(\.\d{3})\d+/, '$1'));

// ----------------------------------------------------------------------
// INTERFACE DE CONEXÃO
// ----------------------------------------------------------------------

function atualizarInterfaceConexao() {
  const controle = $('controle-api');
  const status = $('status-conexao');
  const botao = $('btn-conexao-api');

  if (MODO_DEMO) {
    if (status) {
      status.textContent = 'Modo demonstração';
      status.classList.remove('conectada');
    }

    if (botao) {
      botao.textContent = 'API não configurada';
      botao.disabled = true;
      botao.setAttribute('aria-pressed', 'false');
    }

    return;
  }

  if (controle) {
    controle.classList.toggle('conectada', apiConectada);
  }

  if (status) {
    status.textContent = apiConectada
      ? 'Conectado à API'
      : 'Desconectado da API';

    status.classList.toggle('conectada', apiConectada);
  }

  if (botao) {
    botao.textContent = apiConectada
      ? 'Desconectar da API'
      : 'Conectar à API';

    botao.classList.toggle('desconectar', apiConectada);

    botao.setAttribute(
      'aria-pressed',
      apiConectada ? 'true' : 'false'
    );

    botao.disabled = apiEmConexao;
  }
}

function desconectarAPI() {
  if (MODO_DEMO || !apiConectada) return;

  apiConectada = false;

  sessionStorage.removeItem(CHAVE_CONEXAO);

  atualizarInterfaceConexao();

  $('status').textContent =
    'API desconectada. O gráfico mantém os últimos dados carregados.';
}

async function conectarAPI() {
  if (MODO_DEMO || apiConectada || apiEmConexao) return;

  apiEmConexao = true;
  atualizarInterfaceConexao();

  if ($('status-conexao')) {
    $('status-conexao').textContent = 'Conectando...';
  }

  $('status').textContent = 'Conectando à API...';

  try {
    const [dadosAgora, dadosSerie] = await Promise.all([
      pedir('/now', true),
      pedir('/series', true)
    ]);

    if (
      !dadosAgora ||
      typeof dadosAgora.timestamp !== 'string' ||
      ![true, false, null].includes(dadosAgora.result)
    ) {
      throw new Error('Resposta inesperada no endpoint /now.');
    }

    if (!Array.isArray(dadosSerie)) {
      throw new Error('Resposta inesperada no endpoint /series.');
    }

    apiConectada = true;

    sessionStorage.setItem(CHAVE_CONEXAO, 'true');

    atualizarInterfaceConexao();

    await Promise.all([
      atualizarAgora(dadosAgora),
      desenharGrafico(dadosSerie)
    ]);

  } catch (e) {
    console.error('Erro ao conectar à API:', e);

    apiConectada = false;

    sessionStorage.removeItem(CHAVE_CONEXAO);

    atualizarInterfaceConexao();

    $('status').textContent =
      'Não foi possível conectar à API. Verifique a conexão e tente novamente.';

    if ($('status-conexao')) {
      $('status-conexao').textContent = 'Falha na conexão';
    }

  } finally {
    apiEmConexao = false;
    atualizarInterfaceConexao();
  }
}

function alternarConexaoAPI() {
  if (apiConectada) {
    desconectarAPI();
  } else {
    conectarAPI();
  }
}

// ----------------------------------------------------------------------
// CAMADA DE DADOS
// ----------------------------------------------------------------------

async function pedir(caminho, permitirDesconectada = false) {
  if (
    !MODO_DEMO &&
    !apiConectada &&
    !permitirDesconectada
  ) {
    throw new Error('API desconectada.');
  }

  const r = await fetch('/api' + caminho, {
    method: 'GET',
    headers: {
      'Accept': 'application/json'
    }
  });

  let dados;

  try {
    dados = await r.json();
  } catch {
    throw new Error('Resposta inválida do servidor.');
  }

  if (!r.ok) {
    throw new Error(
      dados.erro || 'Erro ao consultar o servidor: ' + r.status
    );
  }

  return dados;
}

// ----------------------------------------------------------------------
// ÚLTIMA LEITURA DE PRESENÇA
// ----------------------------------------------------------------------

async function obterAgora(dadosRecebidos = null) {
  if (MODO_DEMO) {
    const a = agoraBR();

    const registros = demoPresencaPorHora(a.data, a.data);

    const ocupada = registros.some(r =>
      r.hora === a.hora &&
      r.minuto <= a.minuto
    );

    return {
      ocupada,
      timestamp: new Date().toISOString()
    };
  }

  const d = dadosRecebidos || await pedir('/now');

  if (
    typeof d.timestamp !== 'string' ||
    ![true, false, null].includes(d.result)
  ) {
    throw new Error('Resposta inesperada da API.');
  }

  return {
    ocupada: d.result === true ? true :
      d.result === false ? false : null,
    timestamp: d.timestamp
  };
}

// ----------------------------------------------------------------------
// REGISTROS DE PRESENÇA DO PERÍODO
// Cada registro verdadeiro será mantido individualmente.
// ----------------------------------------------------------------------

async function obterPresencaPorHora(de, ate, dadosRecebidos = null) {
  if (MODO_DEMO) {
    return demoPresencaPorHora(de, ate);
  }

  const lista = dadosRecebidos || await pedir('/series');

  if (!Array.isArray(lista)) {
    throw new Error('Resposta inesperada da API.');
  }

  const horarios = [];

  lista.forEach(r => {
    if (!r || r.result !== true) return;

    const ms = analisarData(r.timestamp);

    if (isNaN(ms)) return;

    const l = emBR(ms);

    if (l.data < de || l.data > ate) return;

    horarios.push({
      data: l.data,
      hora: l.hora,
      minuto: l.minuto
    });
  });

  return horarios;
}

// ----------------------------------------------------------------------
// DADOS DE DEMONSTRAÇÃO
// ----------------------------------------------------------------------

const GRADE_DEMO = {
  1: [[8, 12], [14, 18]],
  2: [[10, 12], [14, 17]],
  3: [[8, 12], [14, 18]],
  4: [[10, 12], [14, 17]],
  5: [[8, 10]]
};

function demoPresencaPorHora(de, ate) {
  const registros = [];
  const agora = agoraBR();

  for (
    let dia = de;
    dia <= ate;
    dia = somarDias(dia, 1)
  ) {
    const grade =
      GRADE_DEMO[new Date(dia + 'T12:00:00').getDay()] || [];

    grade.forEach(intervalo => {
      const inicio = intervalo[0] * 60;
      const fim = intervalo[1] * 60;

      for (let minutos = inicio; minutos < fim; minutos += 10) {
        const hora = Math.floor(minutos / 60);
        const minuto = minutos % 60;

        if (
          dia === agora.data &&
          (hora > agora.hora ||
            (hora === agora.hora && minuto > agora.minuto))
        ) {
          continue;
        }

        registros.push({
          data: dia,
          hora,
          minuto
        });
      }
    });
  }

  return registros;
}

// ----------------------------------------------------------------------
// CARDS DE INDICADORES
// ----------------------------------------------------------------------

function atualizarCards(registros, hoje, pontos) {

  // --------------------------------------------------
  // REGISTROS DE HOJE
  // Conta diretamente os pontos de hoje exibidos no gráfico.
  // --------------------------------------------------

  const registrosHoje = pontos.filter(
    ponto => ponto.data === hoje
  ).length;

  $('card-registros-hoje').textContent = registrosHoje;

  $('card-registros-hoje-detalhe').textContent =
    registrosHoje === 1
      ? '1 ponto exibido no gráfico hoje'
      : 'Pontos exibidos no gráfico hoje';

  // --------------------------------------------------
  // MAIOR ATIVIDADE DE HOJE
  // --------------------------------------------------

  const registrosHojeLista = registros.filter(
    r =>
      r.data === hoje &&
      Number.isInteger(r.hora) &&
      r.hora >= HORA_INI &&
      r.hora <= HORA_FIM
  );

  const quantidadePorHora = {};

  registrosHojeLista.forEach(r => {
    quantidadePorHora[r.hora] =
      (quantidadePorHora[r.hora] || 0) + 1;
  });

  let maiorHora = null;
  let maiorQuantidade = 0;

  for (let hora = HORA_INI; hora <= HORA_FIM; hora++) {
    const quantidade = quantidadePorHora[hora] || 0;

    if (quantidade > maiorQuantidade) {
      maiorQuantidade = quantidade;
      maiorHora = hora;
    }
  }

  if (maiorHora !== null) {
    $('card-horario-pico').textContent =
      dois(maiorHora) + 'h';

    $('card-horario-pico-detalhe').textContent =
      maiorQuantidade === 1
        ? '1 registro hoje'
        : maiorQuantidade + ' registros hoje';
  } else {
    $('card-horario-pico').textContent = '—';

    $('card-horario-pico-detalhe').textContent =
      'Sem registros hoje';
  }

  // --------------------------------------------------
  // TOTAL NO PERÍODO
  // --------------------------------------------------

  const totalPeriodo = registros.length;

  $('card-total-periodo').textContent = totalPeriodo;

  $('card-total-periodo-detalhe').textContent =
    totalPeriodo === 1
      ? '1 registro com presença'
      : 'Registros com presença no período';
}

// ----------------------------------------------------------------------
// INDICADOR: PRESENÇA ATUAL
// Agora atualizado somente no card, sem o indicador duplicado no topo.
// ----------------------------------------------------------------------

function definirPresenca(ocupada) {
  const valor =
    ocupada === true ? 'Sim' :
      ocupada === false ? 'Não' : '—';

  const classe =
    ocupada === true ? 'positivo' :
      ocupada === false ? 'negativo' : '';

  const cardValor = $('card-presenca-valor');

  if (cardValor) {
    cardValor.textContent = valor;

    cardValor.classList.remove(
      'positivo',
      'negativo'
    );

    if (classe) {
      cardValor.classList.add(classe);
    }
  }
}

function descreverLeitura(ms) {
  const l = emBR(ms);
  const hora = dois(l.hora) + ':' + dois(l.minuto);

  return l.data === agoraBR().data
    ? 'às ' + hora
    : 'em ' + l.data.slice(8) + '/' +
    l.data.slice(5, 7) + ' às ' + hora;
}

async function atualizarAgora(dadosRecebidos = null) {
  if (!MODO_DEMO && !apiConectada && !dadosRecebidos) return;

  try {
    const ultimo = await obterAgora(dadosRecebidos);
    const ms = analisarData(ultimo.timestamp);

    if (isNaN(ms)) {
      throw new Error('Horário inválido.');
    }

    const antiga =
      LEITURA_VALIDA_MIN > 0 &&
      Date.now() - ms > LEITURA_VALIDA_MIN * 60000;

    definirPresenca(antiga ? null : ultimo.ocupada);

    const detalhe =
      (antiga ? 'Sem leitura recente. ' : '') +
      'Última leitura ' + descreverLeitura(ms) + '.';

    if ($('card-presenca-detalhe')) {
      $('card-presenca-detalhe').textContent = detalhe;
    }

  } catch (e) {
    console.error('Erro ao atualizar presença:', e);

    definirPresenca(null);

    if ($('card-presenca-detalhe')) {
      $('card-presenca-detalhe').textContent =
        'Não foi possível obter a leitura mais recente.';
    }
  }
}

// ----------------------------------------------------------------------
// PREPARAÇÃO DOS PONTOS DO GRÁFICO
// ----------------------------------------------------------------------

function criarPontos(registros, dias) {
  const indiceDias = new Map(
    dias.map((dia, indice) => [dia, indice])
  );

  return registros
    .filter(r =>
      indiceDias.has(r.data) &&
      r.hora >= HORA_INI &&
      r.hora <= HORA_FIM
    )
    .map(r => ({
      x: r.hora * 60 + r.minuto,
      y: indiceDias.get(r.data),
      data: r.data,
      hora: r.hora,
      minuto: r.minuto
    }));
}

// ----------------------------------------------------------------------
// GRÁFICO: LINHA DO TEMPO DE PRESENÇA
// ----------------------------------------------------------------------

function criarGrafico(dias, pontos) {
  const ctx = $('graf-presenca').getContext('2d');

  if (grafico) {
    grafico.destroy();
  }

  grafico = new Chart(ctx, {
    type: 'scatter',

    data: {
      datasets: [{
        label: 'Presença registrada',
        data: pontos,

        backgroundColor: COR_SIM,
        borderColor: COR_SIM,

        pointRadius: 3.5,
        pointHoverRadius: 6,
        pointHitRadius: 8,
        pointBorderWidth: 0
      }]
    },

    options: {
      responsive: true,
      maintainAspectRatio: false,

      layout: {
        padding: {
          top: 12,
          bottom: 12,
          left: 8,
          right: 8
        }
      },

      animation: {
        duration: reduzMovimento ? 0 : 350
      },

      interaction: {
        mode: 'nearest',
        intersect: true
      },

      plugins: {
        legend: {
          display: false
        },

        tooltip: {
          callbacks: {
            title(context) {
              const ponto = context[0].raw;

              return formatarDiaCurto(ponto.data);
            },

            label(context) {
              const ponto = context.raw;

              return 'Presença registrada às ' +
                dois(ponto.hora) + ':' +
                dois(ponto.minuto);
            }
          }
        }
      },

      scales: {
        // EIXO HORIZONTAL: HORÁRIOS
        x: {
          type: 'linear',

          min: (HORA_INI - 1) * 60,
          max: (HORA_FIM + 1) * 60,

          position: 'top',

          ticks: {
            stepSize: 60,
            autoSkip: false,
            maxRotation: 0,
            minRotation: 0,

            callback(value) {
              const hora = value / 60;

              if (hora < HORA_INI || hora > HORA_FIM) {
                return '';
              }

              // Em telas pequenas, exibe horários de 4 em 4 horas.
              if (
                window.innerWidth <= 600 &&
                hora !== HORA_INI &&
                hora !== HORA_FIM &&
                (hora - HORA_INI) % 4 !== 0
              ) {
                return '';
              }

              return dois(hora) + 'h';
            },

            color: '#344054',

            font: {
              size: 12
            }
          },

          grid: {
            color: 'rgba(148, 163, 184, 0.30)',
            borderDash: [4, 4],
            drawTicks: true
          },

          border: {
            color: '#98A2B3'
          }
        },

        // EIXO VERTICAL: DIAS
        y: {
          type: 'linear',

          min: -0.5,
          max: dias.length - 0.5,

          reverse: true,

          afterBuildTicks(axis) {
            axis.ticks = dias.map((dia, indice) => ({
              value: indice
            }));
          },

          ticks: {
            autoSkip: false,

            callback(value) {
              const indice = Math.round(Number(value));
              const dia = dias[indice];

              return dia ? formatarDiaCurto(dia) : '';
            },

            color: '#344054',

            font: {
              size: 12
            }
          },

          grid: {
            color: 'rgba(148, 163, 184, 0.16)',
            drawTicks: false
          },

          border: {
            color: '#98A2B3'
          }
        }
      }
    }
  });
}

// ----------------------------------------------------------------------
// ATUALIZAÇÃO DO GRÁFICO
// ----------------------------------------------------------------------

async function desenharGrafico(dadosRecebidos = null) {
  if (!MODO_DEMO && !apiConectada && !dadosRecebidos) return;

  const periodo = Number($('periodo').value);

  const hoje = agoraBR().data;
  const de = somarDias(hoje, -(periodo - 1));

  $('status').textContent = 'Carregando dados...';

  try {
    const registros = await obterPresencaPorHora(
      de,
      hoje,
      dadosRecebidos
    );

    const dias = Array.from(
      { length: periodo },
      (_, i) => somarDias(de, i)
    );

    const pontos = criarPontos(registros, dias);

    criarGrafico(dias, pontos);

    // Atualiza os quatro cards usando os dados do gráfico.
    atualizarCards(registros, hoje, pontos);

    $('vazio').hidden = pontos.length > 0;

    $('resumo').textContent =
      'Cada ponto representa um registro de presença. ' +
      'Passe o cursor sobre um ponto para consultar a data e o horário.';

    $('status').textContent = MODO_DEMO
      ? 'Exibindo dados fictícios para demonstração.'
      : 'Dados atualizados em ' +
      dois(agoraBR().hora) + ':' +
      dois(agoraBR().minuto) + '.';

  } catch (e) {
    console.error('Erro ao desenhar gráfico:', e);

    $('status').textContent =
      'Não foi possível carregar os dados do gráfico.';

    $('vazio').hidden = true;
    $('resumo').textContent = '';
  }
}

// ----------------------------------------------------------------------
// EVENTOS E INICIALIZAÇÃO
// ----------------------------------------------------------------------

// Alterar o período só consulta a API se estiver conectado.
$('periodo').addEventListener('change', () => {
  if (MODO_DEMO || apiConectada) {
    desenharGrafico();
  } else {
    $('status').textContent =
      'Conecte-se à API para carregar os dados do período selecionado.';
  }
});

// Evento do botão conectar/desconectar.
if ($('btn-conexao-api')) {
  $('btn-conexao-api').addEventListener(
    'click',
    alternarConexaoAPI
  );
}

async function iniciarPainel() {
  if (MODO_DEMO) {
    $('aviso-demo').hidden = false;

    apiConectada = false;
    atualizarInterfaceConexao();

    // Demonstração funciona automaticamente.
    await Promise.all([
      atualizarAgora(),
      desenharGrafico()
    ]);

  } else {
    atualizarInterfaceConexao();

    if (apiConectada) {
      // A conexão foi preservada durante a navegação interna.
      definirPresenca(null);

      $('status').textContent =
        'Conexão restaurada. Atualizando os dados...';

      // Atualiza os dados ao retornar ao painel.
      await Promise.all([
        atualizarAgora(),
        desenharGrafico()
      ]);

    } else {
      // A API começa desconectada.
      definirPresenca(null);

      $('card-presenca-detalhe').textContent =
        'Aguardando conexão com a API';

      $('status').textContent =
        'API desconectada. Clique em "Conectar à API" para carregar os dados.';
    }
  }

  // Atualiza o card Presença atual a cada 5 minutos.
  setInterval(() => {
    if (MODO_DEMO || apiConectada) {
      atualizarAgora();
    }
  }, INTERVALO_AGORA_S * 1000);

  // Atualiza o gráfico e os cards a cada 10 minutos.
  setInterval(() => {
    if (MODO_DEMO || apiConectada) {
      desenharGrafico();
    }
  }, INTERVALO_SERIES_S * 1000);
}

iniciarPainel();
