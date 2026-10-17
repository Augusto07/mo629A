// De quantos em quantos minutos o painel se atualiza sozinho
  const INTERVALO_MIN = 5;

  const COR_DIA = '#B3122E';
  const COR_DIA_SUAVE = 'rgba(179, 18, 46, 0.5)';
  const COR_HORA = '#1F5C7A';
  const COR_SINAL = '#2F7D5B';
  const LACUNA_MIN = 15;   // sem leituras por mais que isso: a linha do sinal é interrompida
  const reduzMovimento = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  const formatarDia = iso => { const p = iso.split('-'); return p[2] + '/' + p[1]; };
  const formatarDiaLongo = iso =>
    new Date(iso + 'T12:00:00').toLocaleDateString('pt-BR',
      { weekday: 'long', day: '2-digit', month: '2-digit', year: 'numeric' });

  function opcoes(extra) {
    return Object.assign({
      responsive: true,
      maintainAspectRatio: false,
      animation: reduzMovimento ? false : { duration: 400 },
      interaction: { mode: 'index', intersect: false },
      scales: {
        y: { beginAtZero: true, ticks: { precision: 0 }, grid: { color: '#E3E8ED' } },
        x: {
          grid: { display: false },
          ticks: { maxRotation: 0, autoSkip: true, autoSkipPadding: 8 }
        }
      }
    }, extra);
  }

  let diasAtuais = [];

  const graficoDia = new Chart(document.getElementById('graf-dia'), {
    type: 'bar',
    data: { labels: [], datasets: [{ label: 'Entradas', data: [], backgroundColor: [], borderRadius: 4 }] },
    options: opcoes({
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            title: itens => diasAtuais[itens[0].dataIndex]
              ? formatarDiaLongo(diasAtuais[itens[0].dataIndex].data) : ''
          }
        }
      }
    })
  });

  const graficoHora = new Chart(document.getElementById('graf-hora'), {
    type: 'bar',
    data: { labels: [], datasets: [{ label: 'Entradas', data: [], backgroundColor: COR_HORA, borderRadius: 4 }] },
    options: opcoes({
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            title: itens => {
              const h = itens[0].dataIndex;
              return h + 'h às ' + (h + 1) + 'h';
            }
          }
        }
      }
    })
  });

  const horaDecimal = hms => { const p = hms.split(':'); return +p[0] + p[1] / 60 + p[2] / 3600; };
  const formatarHora = v => {
    let h = Math.floor(v), m = Math.round((v - h) * 60);
    if (m === 60) { h += 1; m = 0; }
    return String(h).padStart(2, '0') + ':' + String(m).padStart(2, '0');
  };

  const graficoSinal = new Chart(document.getElementById('graf-sinal'), {
    type: 'line',
    data: {
      datasets: [{
        label: 'Sinal (dBm)', data: [], parsing: false,
        borderColor: COR_SINAL, backgroundColor: COR_SINAL,
        borderWidth: 2, pointRadius: 3, pointHoverRadius: 6, tension: 0, spanGaps: false
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
            label: item => item.parsed.y + ' dBm'
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
          suggestedMin: -90, suggestedMax: -30,
          title: { display: true, text: 'dBm' },
          grid: { color: '#E3E8ED' }
        }
      }
    }
  });

  async function carregarDias() {
    const n = document.getElementById('periodo').value;
    const r = await fetch('/api/diario?dias=' + n);
    if (!r.ok) throw new Error('diario');
    const d = await r.json();

    diasAtuais = d.dias;
    graficoDia.data.labels = d.dias.map(x => formatarDia(x.data));
    graficoDia.data.datasets[0].data = d.dias.map(x => x.total);
    graficoDia.data.datasets[0].backgroundColor =
      d.dias.map(x => x.data === d.hoje ? COR_DIA : COR_DIA_SUAVE);
    graficoDia.update();

    document.getElementById('hoje-total').textContent = d.dias[d.dias.length - 1].total;

    ['dia', 'dia-sinal'].forEach(id => {
      const campo = document.getElementById(id);
      campo.max = d.hoje;
      if (!campo.value) campo.value = d.hoje;
    });
  }

  async function carregarHoras() {
    const dia = document.getElementById('dia').value;
    if (!dia) return;
    const r = await fetch('/api/por-hora?data=' + dia);
    if (!r.ok) throw new Error('hora');
    const d = await r.json();

    graficoHora.data.labels = d.horas.map(x => x.hora + 'h');
    graficoHora.data.datasets[0].data = d.horas.map(x => x.total);
    graficoHora.update();

    document.getElementById('vazio-hora').hidden = d.total > 0;
  }

  // Ajusta o eixo do tempo: "ajustar" dá zoom no período com dados; "dia" mostra 0h a 24h
  let horasSinal = [];
  function ajustarEscalaSinal() {
    const x = graficoSinal.options.scales.x;
    const diaInteiro = document.getElementById('escala-sinal').value === 'dia';
    let ini = 0, fim = 24, passo = 4;
    if (!diaInteiro && horasSinal.length) {
      ini = Math.max(0, Math.min(...horasSinal) - 0.25);
      fim = Math.min(24, Math.max(...horasSinal) + 0.25);
      if (fim - ini < 1) {                       // evita um zoom exagerado com poucas leituras
        const centro = (ini + fim) / 2;
        ini = Math.max(0, centro - 0.5);
        fim = Math.min(24, centro + 0.5);
      }
      passo = [0.25, 0.5, 1, 2, 4].find(p => (fim - ini) / p <= 8) || 4;
      ini = Math.max(0, Math.floor(ini / passo) * passo);
      fim = Math.min(24, Math.ceil(fim / passo) * passo);
    }
    x.min = ini;
    x.max = fim;
    x.ticks.stepSize = passo;
  }

  async function carregarSinal() {
    const dia = document.getElementById('dia-sinal').value;
    if (!dia) return;
    const r = await fetch('/api/sinal?data=' + dia);
    if (!r.ok) throw new Error('sinal');
    const d = await r.json();

    // Se ficar muito tempo sem leitura (ESP32 offline), interrompe a linha
    const pontos = [];
    let anterior = null;
    d.leituras.forEach(l => {
      const x = horaDecimal(l.hora);
      if (anterior !== null && (x - anterior) * 60 > LACUNA_MIN) pontos.push({ x: (anterior + x) / 2, y: null });
      pontos.push({ x: x, y: l.rssi });
      anterior = x;
    });
    graficoSinal.data.datasets[0].data = pontos;
    horasSinal = d.leituras.map(l => horaDecimal(l.hora));
    ajustarEscalaSinal();
    graficoSinal.update();

    const vazio = d.leituras.length === 0;
    document.getElementById('vazio-sinal').hidden = !vazio;
    const resumo = document.getElementById('resumo-sinal');
    if (vazio) { resumo.textContent = ''; return; }
    const valores = d.leituras.map(l => l.rssi);
    const media = Math.round(valores.reduce((a, b) => a + b, 0) / valores.length);
    resumo.textContent = d.leituras.length + ' leituras. Média ' + media + ' dBm, pior ' +
      Math.min(...valores) + ' dBm. Última leitura às ' +
      d.leituras[d.leituras.length - 1].hora.slice(0, 5) + '.';
  }

  async function atualizar() {
    const status = document.getElementById('status');
    try {
      await carregarDias();
      await carregarHoras();
      await carregarSinal();
      const agora = new Date().toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' });
      status.className = 'rodape';
      status.textContent = 'Atualizado às ' + agora + '. A página se atualiza sozinha a cada ' + INTERVALO_MIN + ' minutos.';
    } catch (e) {
      status.className = 'rodape erro';
      status.textContent = 'Não foi possível carregar os dados. Atualize a página para tentar de novo.';
    }
  }

  // Ao mudar um filtro, recarrega só o gráfico dele (menos requisições ao servidor)
  async function soEste(carregar) {
    try {
      await carregar();
    } catch (e) {
      const status = document.getElementById('status');
      status.className = 'rodape erro';
      status.textContent = 'Não foi possível carregar os dados. Atualize a página para tentar de novo.';
    }
  }
  document.getElementById('periodo').addEventListener('change', () => soEste(carregarDias));
  document.getElementById('dia').addEventListener('change', () => soEste(carregarHoras));
  document.getElementById('dia-sinal').addEventListener('change', () => soEste(carregarSinal));
  document.getElementById('escala-sinal').addEventListener('change', () => {
    ajustarEscalaSinal();       // só muda a escala, sem nova requisição ao servidor
    graficoSinal.update();
  });
  setInterval(() => { if (!document.hidden) atualizar(); }, INTERVALO_MIN * 60 * 1000);
  atualizar();