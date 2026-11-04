# CSI em lotes com uma tentativa de POST

Implementacao para o ESP32 original com ESP-IDF 5.5.1. Em 29/10/2026, a compilacao no PowerShell normal do Windows gerou csi_recv_router.bin com 765440 bytes e passou na verificacao da particao de app (27% livres), com CSI_BATCH_POST_ENABLED=y. A execucao na placa e o POST para um endpoint real ainda precisam ser verificados. Nenhum novo firmware foi gravado durante esta implementacao. O compilador Xtensa ainda apresenta erro de DLL dentro do ambiente do Codex.

## Ciclo atual: captura continua com fila limitada

1. Manter CSI e pings ativos enquanto a placa estiver ligada, sem timer de coleta.
2. Ao completar um lote (padrao: 20 amostras), entrega-lo a tarefa de envio e continuar a captura em outro buffer.
3. Enviar lotes em ordem FIFO, com uma tentativa de POST por lote. O buffer em transmissao fica imutavel.
4. Pausar CSI e pings somente quando todos os buffers estiverem ocupados. Retomar assim que o envio liberar um buffer, tanto em sucesso quanto em falha.

O padrao foi restaurado para 100 pings solicitados por segundo e quatro buffers, incluindo captura e envio. A taxa real de CSI depende do roteador. Um lote parcial aguarda novas amostras; desligar a placa perde os dados ainda em RAM.

Nao ha reenvio, fila persistente, confirmacao de armazenamento no servidor ou gravacao de amostras em flash. Redirects e retentativas de autenticacao estao desabilitados. Respostas HTTP 2xx contam como envio bem-sucedido; qualquer outro resultado descarta o lote. Janelas vazias nao geram POST.

A URL padrao `https://example.invalid/csi` e um stub reconhecido pelo firmware: o lote e descartado sem consulta DNS nem POST. Substitua a URL para ativar a tentativa de envio real.

## Configuracao

No menuconfig, abra **CSI batch POST**:

| Opcao | Padrao | Funcao |
|---|---|---|
| CSI_BATCH_POST_ENABLED | y no ESP32 | Ativa o ciclo em lotes. Desabilitar restaura a saida serial continua original. |
| CSI_POST_URL | https://example.invalid/csi | Destino do POST. |
| CSI_POST_TOKEN | vazio | Token Bearer, sem escrever o prefixo Bearer. Vazio omite autenticacao. |
| CSI_BATCH_MAX_SAMPLES | 20 | Amostras por POST, entre 1 e 400. |
| CSI_BATCH_BUFFER_COUNT | 4 | Buffers de RAM, entre 2 e 8; inclui captura e envio. |
| CSI_BATCH_PING_HZ | 100 | Frequencia solicitada de pings. |
| CSI_POST_TIMEOUT_MS | 1000 | Timeout de I/O por fase; o orcamento do corpo comeca apos a conexao. |
| CSI_BATCH_SERIAL_OUTPUT | n | Tambem imprime as amostras em CSV enquanto a captura esta pausada. |

Para HTTPS, habilite **Component config > mbedTLS > Certificate Bundle** e use um servidor com certificado aceito pelo bundle. A verificacao de certificado nao e desabilitada. HTTP simples pode ser usado em um ambiente local de teste.

O ESP32 envia o token no cabecalho `Authorization: Bearer <token>`. A validacao e responsabilidade do endpoint. Informe somente o valor do token no menuconfig; nao inclua `Bearer ` no campo. O token nao entra no JSON nem nos logs. Quebras de linha no token sao rejeitadas antes do POST. Uma resposta 401 ou 403 descarta o lote sem reenvio.

O valor fica no sdkconfig local e no firmware compilado. Os arquivos sdkconfig e sdkconfig.local.defaults sao ignorados pelo Git. Nao coloque o token em arquivos de exemplo, documentacao ou capturas de tela. Para ativar autenticacao apos esta alteracao e necessario compilar e gravar o firmware novamente; o build Windows confirmado anteriormente ainda nao incluia o campo de token.

Se o compilador acusar CONFIG_CSI_POST_TOKEN nao definido, execute `outputs/ESP32.ps1 reconfigure` a partir de ESP32-CSI. Em seguida abra menuconfig, configure URL/token, salve e compile. O projeto agora acompanha explicitamente main/Kconfig.projbuild como dependencia da configuracao CMake. O teste check_kconfig.py verifica a geracao do define tanto para token vazio quanto para um valor de teste.

**O timeout de POST nao e um limite absoluto para a duracao da pausa.** DNS, conexao, TLS e agendamento podem consumir mais tempo. A conexao usa o timeout de I/O configurado; depois que ela termina, o corpo recebe um novo orcamento de escrita, verificado entre os blocos. A espera pelos cabecalhos da resposta recebe outro timeout de I/O completo. Assim, uma conexao HTTPS lenta nao esgota o prazo do corpo antes do primeiro byte. Continua havendo apenas uma tentativa por lote. A duracao total da pausa aparece no log `pause_ms`.

Os logs `POST completed` e `POST failed` incluem `body_sent`, `connect_ms` e `elapsed_ms`, sem exibir URL ou token. Em uma falha, `stage` identifica a etapa:

- `headers`: configuracao dos cabecalhos falhou.
- `connect`: nao foi possivel abrir a conexao/requisicao.
- `write`: o corpo nao foi completamente transmitido, inclusive se o orcamento acabou.
- `early_response`: o envio do corpo falhou, mas foi possivel ler um status que o servidor enviou antecipadamente, por exemplo uma rejeicao de autenticacao. Nao ha uma nova requisicao; a leitura adicional tem timeout de I/O de ate 200 ms. Um lote incompleto nunca e marcado como sucesso, mesmo se esse status for 2xx.
- `response`: o corpo foi transmitido, mas nao foi obtido um status HTTP valido a tempo.
- `http_status`: chegou uma resposta que nao e 2xx; consulte HTTP, por exemplo 401/403 para autenticacao e 413 para tamanho do corpo.

`body_sent=N/N` indica que a API de escrita aceitou todo o corpo; nao garante armazenamento ou processamento pelo servidor. `HTTP=0` nao e um status enviado pelo servidor.

## Memoria e serial

As amostras sao copiadas dentro do callback para buffers pre-alocados em RAM. O callback nao faz POST, alocacao dinamica nem impressao serial. Um limite de 128 bytes CSI por amostra corresponde ao LLTF habilitado no exemplo atual; comprimentos maiores ou nulos sao descartados e contabilizados, sem truncar a amostra.

O JSON e calculado em uma primeira passagem e enviado em blocos na segunda passagem. Nao ha uma segunda copia completa do lote em formato JSON. A alocacao e `sizeof(csi_batch_sample_t) * CSI_BATCH_MAX_SAMPLES * CSI_BATCH_BUFFER_COUNT`; o tamanho aparece no log inicial (14080 bytes nos testes de host, com os padroes). As tarefas de envio e controle usam stacks de 8192 e 3072 bytes; HTTP/TLS tambem usam RAM. Uma falha de alocacao impede o inicio.

Por padrao o monitor serial exibe os resumos de lote, nao as linhas CSI_DATA. Para continuar usando Capturar-CSI.ps1, habilite CSI_BATCH_SERIAL_OUTPUT, compile e grave novamente. O CSV conserva as 25 colunas originais e o timestamp bruto do driver. A impressao ocorre na tarefa de envio e pode encher a fila; use local_timestamp para medir os intervalos de aquisicao, nao o horario de chegada pela USB.

## Contrato JSON

Um POST tem Content-Type application/json e este formato (array abreviado):

```json
{
  "schema_version": 1,
  "device_id": "e4:65:b8:a1:48:74",
  "session_id": "1ef9a29bce614297a4584aba89ec6090",
  "batch_id": 0,
  "samples": [
    {
      "seq": 0,
      "timestamp_us": 1001234,
      "ap_mac": "9a:d7:42:16:37:54",
      "rssi_dbm": -57,
      "noise_floor_dbm": -97,
      "channel": 11,
      "bandwidth_mhz": 20,
      "sig_mode": 1,
      "first_word_invalid": true,
      "csi_raw": [83, -80, 4, 0, -13, 35]
    }
  ]
}
```

O campo `sig_mode` preserva o modo PHY real de cada amostra, necessario para verificar compatibilidade com o modelo treinado. O endpoint e o adaptador devem preservar esse campo; dados antigos sem ele ficam sem classificacao quando o modelo exige um modo especifico. `bandwidth_mhz` continua em MHz (20/40); o adaptador converte para o codigo ESP (0/1). No envio real, csi_raw contem todos os valores capturados (normalmente 128); acima ele esta abreviado. Os valores brutos sao inteiros com sinal, em pares imaginario/real. Quando first_word_invalid for true, o backend deve desconsiderar os primeiros quatro valores durante a analise; eles sao preservados no transporte.

- device_id e o MAC da interface Wi-Fi do ESP32; ap_mac e o BSSID de origem da amostra.
- session_id muda a cada inicializacao do firmware; batch_id identifica a janela dentro dessa sessao.
- timestamp_us e o instante em microssegundos desde o boot, medido com esp_timer no callback. Nao e data UTC.
- O CSV opcional preserva o contador de 32 bits do driver em local_timestamp; ele pode dar a volta. Esse campo nao e enviado adicionalmente no JSON.
- dropped conta amostras invalidas e respostas em transito rejeitadas ao lotar a fila. Nao estima eventos enquanto CSI esta desabilitado.
- discarded no resumo serial conta os lotes descartados, incluindo os descartados pelo stub.
- queue mostra lotes prontos/em envio apos liberar o lote atual; captured, sent_samples e discarded_samples mostram totais de amostras. pauses e pause_ms mostram quantidade e duracao acumulada das pausas por RAM cheia; upload_ms mede o processamento do lote.
- ping_tx e ping_rx mostram contadores da sessao de pings ativa (reiniciam apos uma pausa); wifi=1 indica associacao Wi-Fi. Associacao Wi-Fi nao garante acesso a Internet.

## Migracao e analise local

Execute reconfigure e menuconfig. Confira `CSI_BATCH_PING_HZ=100`, `CSI_BATCH_MAX_SAMPLES=20` e `CSI_BATCH_BUFFER_COUNT=4`; o antigo `CSI_BATCH_WINDOW_MS` foi removido. Valores de um sdkconfig existente podem prevalecer sobre os novos padroes. Preserve URL, token, Wi-Fi e timeout adequados ao endpoint. Compile e grave para ativar o novo comportamento.

O modulo local `modeling_and_analysis/collection_pipeline.py` e o notebook `csi_collection_inference.ipynb` juntam lotes pelos timestamps de aquisicao. Duracao, passo, minimo de pacotes e limite de lacunas sao configuraveis. O perfil local inicial usa janela de 1 segundo, passo de 0.2 segundo, minimo de 12 pacotes e lacuna maxima de 0.25 segundo, incluindo bordas. O perfil de treinamento continua disponivel para comparacao. Pausas e envios perdidos ficam desconhecidos quando excedem o limite escolhido. Resultados com parametros diferentes do treinamento sao exploratorios. Lambda, recursos AWS, coeficientes e treinamento do GMM nao foram alterados.

## Historico: configuracao local de diagnostico

Apos o log com body_sent=3320/122606 e as janelas vazias, uma configuracao local anterior usou 20 amostras por lote, CSI_POST_TIMEOUT_MS=5000 e CSI_BATCH_PING_HZ=20. Esses valores descrevem o diagnostico anterior, nao os novos padroes.

Execute reconfigure, build e flash para ativar os ajustes. Depois compare o status HTTP, body_sent, ping_tx, ping_rx e wifi. Se houver pings enviados sem respostas, isso aponta para o caminho ate o gateway; se houver respostas de ping mas nenhuma amostra, a captura CSI precisa de investigacao separada. Esses indicadores nao identificam sozinhos a causa de uma falha de rede.

O backend deve tolerar lacunas entre janelas e ausencia de lotes. Nenhum comportamento de entrega garantida e prometido.

## Validacao

Os testes em tests/ compilam o codigo real com drivers simulados. Cobrem captura durante escrita HTTP parcial, imutabilidade do lote em envio, FIFO, lotacao, pausa/retomada, ausencia do timer, operacao repetida, tamanho invalido, descarte apos uma tentativa, timeout, status nao-2xx, stub e compatibilidade do CSV.

Com um compilador Zig disponivel, execute no PowerShell:

```powershell
.\work\espressif-tools\python_env\idf5.5_py3.12_env\Scripts\python.exe .\work\esp-csi\examples\get-started\csi_recv_router\tests\run_host_tests.py .\work\host-tools\zig-x86_64-windows-0.14.1\zig.exe
```

Os testes de host nao substituem build, medicao de heap/stack e verificacao do POST na placa. O compilador de teste e local e ignorado pelo Git. Nao e uma dependencia do firmware.

O teste Python `tests/check_kconfig.py` verifica os novos padroes, limites de tamanho/quantidade de buffers, remocao do timer e modo POST desabilitado. Os testes de host passaram com CSV habilitado e desabilitado.

O build completo passou para ESP32 com ESP-IDF 6.1. O componente `esp_csi_gain_ctrl` foi limitado aos alvos que usam controle de ganho; o ESP32 original nao depende dessa biblioteca, evitando a referencia ao binario inexistente `6.1/esp32/libesp_csi_gain_ctrl.a`. O firmware de teste tem 956160 bytes, cabendo na particao de app de 1 MB com 9% livres.

Na COM4 foi identificado um ESP32-D0WD-V3 revisao 3.1 com flash de 4 MB; Secure Boot e criptografia de flash estao desabilitados. Leituras curtas de flash passaram, incluindo a tabela de particoes. As copias maiores falharam com corrupcao serial ou travamento, tanto com esptool 5.6 quanto 4.13 e com o loader ROM sem stub. Como nao houve backup completo da regiao a alterar, nenhum firmware foi gravado e nenhum eFuse foi alterado. A placa foi reiniciada no programa original. Os testes de captura/upload na placa ainda dependem de uma conexao serial estavel; consulte `outputs/COM4-test-report.md`.

O teste `tests/check_powershell.py` passou no Windows PowerShell 5.1 e no PowerShell 7: verifica que diagnosticos em stderr nao interrompem o wrapper e que codigos de falha reais continuam sendo propagados. Usa um runner simulado e nao grava a placa.
