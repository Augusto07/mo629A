// Quantos minutos entre uma atualização automática e a próxima
const INTERVALO_MIN = 1;

// Faixa do eixo do tempo na escala "fixa", em horas (de 0 a 24).
// Leituras fora dessa faixa nunca são escondidas: a faixa se amplia para incluí-las.
const FAIXA_FIXA = { ini: 6, fim: 22 };

const COR_LINHA = '#1F5C7A';
const COR_AREA = 'rgba(31, 92, 122, 0.12)';

// Endereço da API na AWS (vem do config.py, pelo atributo data-api-base do painel.html).
// Vazio = modo demonstração, com dados fictícios.
const configApi = document.getElementById('config-api');
const API_BASE = String((configApi && configApi.dataset.apiBase) || '').replace(/\/+$/, '');
const MODO_DEMO = API_BASE === '';

const $ = id => document.getElementById(id);
const reduzMovimento = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
const dois = n => String(n).padStart(2, '0');
const dataLocalISO = d => d.getFullYear() + '-' + dois(d.getMonth() + 1) + '-' + dois(d.getDate());
const horaDecimal = hms => { const p = hms.split(':'); return +p[0] + p[1] / 60 + (p[2] || 0) / 3600; };
const formatarHora = v => {
  let h = Math.floor(v), m = Math.round((v - h) * 60);
  if (m === 60) { h += 1; m = 0; }
  return dois(h) + ':' + dois(m);
};

/* ====================================================================
   CAMADA DE DADOS
   É o único trecho que conhece a API. Quando a API da AWS estiver pronta,
   só estas duas funções precisam mudar. O restante do painel não depende
   do formato das respostas.

   Formato PROVISÓRIO esperado (ajustar quando a API existir):
     GET {API_BASE}/presenca
         -> { "ocupada": true }    (ou { "pessoas": 12 }, e então ocupada = pessoas > 0)
     GET {API_BASE}/contagem?data=AAAA-MM-DD
         -> { "leituras": [ { "hora": "08:05:00", "pessoas": 3 }, ... ] }
   ==================================================================== */

async function pedir(caminho) {
  const r = await fetch(API_BASE + caminho);
  if (!r.ok) throw new Error('API respondeu ' + r.status);
  return r.json();
}

async function obterPresenca() {
  if (MODO_DEMO) {
    const hoje = demoContagem(dataLocalISO(new Date()));
    return { ocupada: hoje.length > 0 && hoje[hoje.length - 1].pessoas > 0 };
  }
  const d = await pedir('/presenca');
  return { ocupada: typeof d.ocupada === 'boolean' ? d.ocupada : Number(d.pessoas) > 0 };
}

async function obterContagem(dia) {
  if (MODO_DEMO) return demoContagem(dia);
  const d = await pedir('/contagem?data=' + encodeURIComponent(dia));
  return d.leituras;
}

/* --------------------------------------------------------------------
   Dados fictícios do modo demonstração (nada disso é usado com a API real)
   -------------------------------------------------------------------- */
const AULAS = [[8, 10, 30], [10, 12, 24], [14, 16, 34], [16, 18, 20]];   // início, fim, pessoas

function semente(texto) {
  let h = 2166136261;
  for (const c of texto) { h ^= c.charCodeAt(0); h = Math.imul(h, 16777619); }
  return h >>> 0;
}
function aleatorio(s) {
  return () => { s = (Math.imul(s, 1664525) + 1013904223) >>> 0; return s / 4294967296; };
}

function demoContagem(dia) {
  const rnd = aleatorio(semente(dia));
  const agora = new Date();
  const limite = dia === dataLocalISO(agora) ? agora.getHours() + agora.getMinutes() / 60 : 24;
  const leituras = [];
  for (let min = 7 * 60; min <= 19 * 60; min += 5) {
    const h = min / 60;
    if (h > limite) break;
    const aula = AULAS.find(a => h >= a[0] && h < a[1]);
    const pessoas = aula ? Math.max(0, Math.round(aula[2] + (rnd() - 0.5) * 6)) : 0;
    leituras.push({ hora: formatarHora(h) + ':00', pessoas: pessoas });
  }
  return leituras;
}

/* ====================================================================
   INTERFACE
   ==================================================================== */

// Campo "há pessoas na sala?": true = Sim, false = Não, null = indisponível
function definirPresenca(ocupada) {
  $('presenca-ponto').className = 'ponto' + (ocupada === true ? ' sim' : ocupada === false ? ' nao' : '');
  $('presenca-valor').textContent = ocupada === true ? 'Sim' : ocupada === false ? 'Não' : '—';
}

const grafico = new Chart($('graf-contagem'), {
  type: 'line',
  data: {
    datasets: [{
      label: 'Pessoas', data: [], parsing: false,
      borderColor: COR_LINHA, backgroundColor: COR_AREA, fill: true,
      borderWidth: 2, pointRadius: 3, pointHoverRadius: 6, tension: 0
    }]
  },
  options: {
    responsive: true,
    maintainAspectRatio: false,
    animation: reduzMovimento ? false : { duration: 400 },
    interaction: { mode: 'nearest', axis: 'x', intersect: false },
    plugins: {
      legend: { display: false },
      tooltip: {
        callbacks: {
          title: itens => formatarHora(itens[0].parsed.x),
          label: item => item.parsed.y + (item.parsed.y === 1 ? ' pessoa' : ' pessoas')
        }
      }
    },
    scales: {
      x: {
        type: 'linear', min: 0, max: 24,
        ticks: { stepSize: 4, callback: v => formatarHora(v) },
        grid: { display: false }
      },
      y: {
        beginAtZero: true, suggestedMax: 5,
        ticks: { precision: 0 },
        title: { display: true, text: 'Pessoas' },
        grid: { color: '#E3E8ED' }
      }
    }
  }
});

// Eixo do tempo. Duas escalas, escolhidas no seletor:
//   "dados": dá zoom no período que tem leituras (sem leituras, mostra o dia inteiro)
//   "fixa":  usa sempre a faixa FAIXA_FIXA (ampliada se houver leituras fora dela)
let horasAtuais = [];

function ajustarEscala() {
  const x = grafico.options.scales.x;
  const horas = horasAtuais;
  let ini = 0, fim = 24;
  if ($('escala').value === 'fixa') {
    ini = FAIXA_FIXA.ini;
    fim = FAIXA_FIXA.fim;
    if (horas.length) {
      ini = Math.min(ini, Math.floor(Math.min(...horas)));
      fim = Math.max(fim, Math.ceil(Math.max(...horas)));
    }
  } else if (horas.length) {
    ini = Math.max(0, Math.min(...horas) - 0.25);
    fim = Math.min(24, Math.max(...horas) + 0.25);
    if (fim - ini < 1) {
      const centro = (ini + fim) / 2;
      ini = Math.max(0, centro - 0.5);
      fim = Math.min(24, centro + 0.5);
    }
  }
  const passo = [0.25, 0.5, 1, 2, 4].find(p => (fim - ini) / p <= 8) || 4;
  x.min = Math.max(0, Math.floor(ini / passo) * passo);
  x.max = Math.min(24, Math.ceil(fim / passo) * passo);
  x.ticks.stepSize = passo;
}

async function carregarContagem() {
  const dia = $('dia').value;
  if (!dia) return;
  const leituras = (await obterContagem(dia)).slice().sort((a, b) => a.hora.localeCompare(b.hora));

  const horas = leituras.map(l => horaDecimal(l.hora));
  grafico.data.datasets[0].data = leituras.map((l, i) => ({ x: horas[i], y: l.pessoas }));
  horasAtuais = horas;
  ajustarEscala();
  grafico.update();

  $('vazio').hidden = leituras.length > 0;
  if (!leituras.length) { $('resumo').textContent = ''; return; }
  let pico = leituras[0];
  leituras.forEach(l => { if (l.pessoas > pico.pessoas) pico = l; });
  $('resumo').textContent = leituras.length + ' leituras. Máximo de ' + pico.pessoas +
    (pico.pessoas === 1 ? ' pessoa' : ' pessoas') + ' às ' + pico.hora.slice(0, 5) + '.';
}

function mostrarStatus(ok) {
  const status = $('status');
  if (ok) {
    const agora = new Date().toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' });
    status.className = 'rodape';
    status.textContent = (MODO_DEMO ? 'Modo demonstração. ' : '') + 'Atualizado às ' + agora +
      '. A página se atualiza sozinha a cada ' + INTERVALO_MIN + (INTERVALO_MIN === 1 ? ' minuto.' : ' minutos.');
  } else {
    status.className = 'rodape erro';
    status.textContent = 'Não foi possível carregar os dados. Atualize a página para tentar de novo.';
  }
}

async function atualizar() {
  const [presenca, contagem] = await Promise.allSettled([obterPresenca(), carregarContagem()]);
  definirPresenca(presenca.status === 'fulfilled' ? presenca.value.ocupada : null);
  mostrarStatus(presenca.status === 'fulfilled' && contagem.status === 'fulfilled');
}

// Início
$('opcao-fixa').textContent = 'Faixa fixa (' + dois(FAIXA_FIXA.ini) + 'h às ' + dois(FAIXA_FIXA.fim) + 'h)';
$('aviso-demo').hidden = !MODO_DEMO;
const hoje = dataLocalISO(new Date());
$('dia').max = hoje;
$('dia').value = hoje;

// Trocar a escala só redesenha o eixo, sem nova consulta à API
$('escala').addEventListener('change', () => { ajustarEscala(); grafico.update(); });
$('dia').addEventListener('change', async () => {
  try { await carregarContagem(); mostrarStatus(true); } catch (e) { mostrarStatus(false); }
});
setInterval(() => { if (!document.hidden) atualizar(); }, INTERVALO_MIN * 60 * 1000);
atualizar();