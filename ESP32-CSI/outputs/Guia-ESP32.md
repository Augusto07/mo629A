# Projeto ESP-CSI no ESP32 DEVKITV1

O exemplo csi_recv_router foi compilado com ESP-IDF 5.5.1 e gravado na COM7.
O teste inicial recebeu 2.407 amostras CSI validas em 30 segundos.

O projeto agora fica em `C:\Users\vitor\Documents\MO629A\mo629A\ESP32-CSI`, dentro do repositorio Git `C:\Users\vitor\Documents\MO629A\mo629A`.
A compilacao anterior foi preservada em uma pasta `work/csi-build-esp32-before-move-*`. O proximo build gera os arquivos com os novos caminhos. A placa nao precisa ser regravada apenas porque a pasta mudou.

## Git do projeto

O codigo ESP-CSI em `ESP32-CSI/work/esp-csi` faz parte diretamente do repositorio mo629A. Ele nao e um submodulo: alteracoes nos fontes aparecem no `git status` do repositorio principal e podem ser commitadas normalmente.

A origem e `https://github.com/espressif/esp-csi`, commit `8633d67152db2808f141cc1595970aa9cf406045`. Os arquivos de licenca e os avisos de autoria foram preservados.

Os metadados do repositorio Git original foram preservados localmente em `ESP32-CSI/work/source-git-metadata/esp-csi.git`, uma pasta ignorada pelo Git principal. Eles permitem consultar o historico original e nao precisam ser enviados ao repositorio.

Builds, caches, ferramentas instaladas, coletas CSV e arquivos locais de Wi-Fi continuam fora do versionamento conforme os arquivos .gitignore.

## Pastas

Pasta de trabalho:
`C:\Users\vitor\Documents\MO629A\mo629A\ESP32-CSI`

Repositorio ESP-CSI:
`C:\Users\vitor\Documents\MO629A\mo629A\ESP32-CSI\work\esp-csi`

Projeto compilado:
`C:\Users\vitor\Documents\MO629A\mo629A\ESP32-CSI\work\esp-csi\examples\get-started\csi_recv_router`

Codigo principal para editar:
`C:\Users\vitor\Documents\MO629A\mo629A\ESP32-CSI\work\esp-csi\examples\get-started\csi_recv_router\main\app_main.c`

ESP-IDF:
`C:\Users\vitor\Documents\MO629A\mo629A\ESP32-CSI\work\esp-idf`

Ferramentas e Python isolado:
`C:\Users\vitor\Documents\MO629A\mo629A\ESP32-CSI\work\espressif-tools`

Arquivos gerados pela compilacao:
`C:\Users\vitor\Documents\MO629A\mo629A\ESP32-CSI\work\csi-build-esp32`

## O que mudou

- O exemplo csi_recv_router recebeu um modo de coleta em lotes com POST: o callback copia amostras, e uma tarefa separada pausa a captura, tenta um envio e retoma. A configuracao CSI de radio foi mantida. O modo serial original pode ser restaurado no menuconfig.
- Foram criados sdkconfig.local.defaults e sdkconfig com o alvo esp32, Wi-Fi, CSI habilitado, console em 921600 baud e flash de 4 MB. O projeto ja trazia varias configuracoes de CSI e desempenho; elas foram aproveitadas.
- O gerenciador de dependencias gerou dependencies.lock e managed_components.
- A copia local do ESP-IDF recebeu um ajuste em tools/cmake/toolchain-esp32.cmake: chama os compiladores unificados diretamente, seleciona o perfil ESP32 e informa o caminho do Ninja. Isso evita a falha do intermediario que tentava consultar caminhos curtos no Windows.
- O arquivo work/run_idf.py prepara o ambiente, os caches locais e os caminhos. Use-o por meio do script ESP32.ps1 fornecido.
- Foram criados scripts auxiliares de configuracao/captura, logs e o backup do firmware original.

O Wi-Fi fica na configuracao local e no firmware compilado. Nao publique sdkconfig ou sdkconfig.local.defaults com sua senha.

## Editar, compilar e gravar

1. Abra app_main.c num editor, como VS Code, e salve a alteracao.
2. Feche o Monitor Serial do Arduino IDE antes de gravar ou abrir outro monitor.
3. Abra o PowerShell e execute:

```powershell
cd "C:\Users\vitor\Documents\MO629A\mo629A\ESP32-CSI"
.\outputs\ESP32.ps1 build
```

Se aparecer `Project build complete`, grave:

```powershell
.\outputs\ESP32.ps1 flash
```

O comando flash tambem compila alteracoes pendentes. Ele substitui o programa da placa.
Se a porta mudar, use `-Port COM8`, por exemplo.

Se a gravacao parar no meio com `The chip stopped responding`, feche os monitores seriais, desconecte/reconecte a placa e tente uma porta USB direta, sem hub. Repita a gravacao completa em velocidade menor:

```powershell
.\outputs\ESP32.ps1 flash -Port COM7 -Baud 57600
```

O padrao continua sendo 115200 baud. A opcao -Baud afeta apenas a gravacao; o monitor e a captura CSV continuam usando 921600 baud. Se a falha persistir, teste outro cabo USB de dados e outra porta USB. Aguarde a conclusao da gravacao e da verificacao antes de iniciar o monitor; uma gravacao parcial nao confirma que o firmware esteja valido.

Para acompanhar no terminal:

```powershell
.\outputs\ESP32.ps1 monitor
```

Saia com Ctrl+]. Como alternativa, use o Monitor Serial do Arduino IDE na COM7 a 921600 baud. Abra somente um monitor por vez.

Se a politica do PowerShell bloquear o script, execute a acao em um processo separado:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\outputs\ESP32.ps1 build
```

Esse comando nao altera a politica permanente do computador. Troque build por flash, monitor ou menuconfig conforme a acao desejada.

A mensagem `skip submodule check on internal CI` e informativa e vem do CMake. O ESP32.ps1 foi corrigido para nao interpretar texto de stderr como falha automatica: build e flash exibem os diagnosticos como texto e retornam o codigo de saida real do processo. A correcao foi testada no Windows PowerShell 5.1 e no PowerShell 7, tanto com sucesso quanto com uma falha simulada. Falhas reais continuam retornando codigo diferente de zero.

Se o compilador nao iniciar e aparecer `WinError 623` ou `Realocacao Invalida da DLL do Sistema`, houve uma falha ao carregar a ferramenta no Windows antes de compilar o codigo. Essa falha foi observada ao executar pelo ambiente do Codex nas pastas antiga e nova. Tente o mesmo comando build num PowerShell aberto normalmente; a compilacao no novo local ainda precisa ser confirmada. Nao e necessario apagar os fontes nem gravar a placa para diagnosticar esse erro.

## Exemplo de alteracao

### Cabecalho C++ bits/error_constants.h nao encontrado

O arquivo faz parte da ferramenta Xtensa instalada. Se ele existir na instalacao mas o compilador nao conseguir encontra-lo, caminhos internos longos no Windows podem ser a causa. O script run_idf.py agora usa a juncao local `work/gcc-toolchain` para chamar a mesma ferramenta por um caminho menor, mantendo a selecao de bibliotecas ESP32 e os arquivos originais.

A juncao e criada automaticamente pelo primeiro build no PowerShell normal e fica fora do Git. Se a criacao falhar por acesso negado, o build encerra sem alterar a instalacao. A configuracao anterior de build e preservada em uma pasta `work/csi-build-esp32-before-reconfigure-*` quando o caminho do compilador muda.

Essa alteracao foi preparada em 29/10/2026. A compilacao completa ainda precisa ser confirmada no PowerShell normal, pois o ambiente de execucao do Codex apresentou erro de DLL ao iniciar o compilador e negou a criacao da juncao.

### Alterar a frequencia de coleta

Em app_main.c, a linha:

```c
#define CONFIG_SEND_FREQUENCY      100
```

controla a frequencia solicitada de pings ao roteador. Alterar 100 para 50 reduz a frequencia solicitada para 50 pings por segundo. A quantidade real de amostras depende das respostas do roteador, do Wi-Fi e da saida serial.

Salve, execute build e depois flash. Essa mudanca e apenas um exemplo; nao foi aplicada ao projeto.

## Alterar Wi-Fi ou outras configuracoes

```powershell
.\outputs\ESP32.ps1 menuconfig
```

No menu Example Connection Configuration, edite o SSID e a senha, salve e saia. Depois execute build e flash.
O arquivo outputs/WiFi.defaults foi usado para a configuracao inicial; edita-lo sozinho nao atualiza o sdkconfig existente.

Nao e necessario repetir set-target esp32 a cada alteracao. Esse passo serve para selecionar ou trocar o modelo de chip e pode regenerar a configuracao.

O Arduino IDE pode ser usado como monitor serial. Este projeto e ESP-IDF/CMake, portanto o botao Upload do Arduino IDE nao compila este projeto diretamente.

## Coletar dados e salvar em CSV

Com o novo modo de POST em lotes, a saida CSI_DATA fica desabilitada por padrao. Para usar a captura CSV abaixo, habilite **CSI batch POST > Also print each captured batch as CSV over serial** no menuconfig e compile/grave. As linhas chegam em rajadas entre as janelas; use local_timestamp para analisar os intervalos reais da coleta. Desabilitar CSI_BATCH_POST_ENABLED restaura a captura serial continua original.

Nao e necessario recompilar nem gravar o ESP32 novamente para iniciar outra coleta. Mantenha a placa conectada por USB e conectada ao Wi-Fi configurado.

1. Feche o Monitor Serial do Arduino IDE ou encerre o monitor do ESP-IDF com Ctrl+]. A porta serial so pode ser usada por um programa por vez.
2. Abra o PowerShell e entre na pasta de trabalho:

```powershell
cd "C:\Users\vitor\Documents\MO629A\mo629A\ESP32-CSI"
```

3. Para coletar durante 60 segundos:

```powershell
.\outputs\Capturar-CSI.ps1 -Segundos 60
```

Troque 60 pela duracao desejada em segundos. Para coletar continuamente ate pressionar Ctrl+C:

```powershell
.\outputs\Capturar-CSI.ps1 -Segundos 0
```

Ctrl+C tambem permite encerrar uma coleta com prazo antes do termino, preservando as amostras ja salvas.

O script usa COM7 a 921600 baud. Se a porta mudar, informe a nova porta:

```powershell
.\outputs\Capturar-CSI.ps1 -Segundos 60 -Porta COM8
```

Cada execucao cria um CSV novo, sem sobrescrever as rodadas anteriores, nesta pasta:

```text
C:\Users\vitor\Documents\MO629A\mo629A\ESP32-CSI\outputs
```

O nome segue o formato `CSI_AAAA-MM-DD_HH-MM-SS_microssegundos.csv`. O terminal informa o caminho e atualiza a quantidade de amostras salvas a cada cinco segundos. Ao encerrar, mostra o total e a quantidade de linhas CSI invalidas ignoradas.

O CSV possui cabecalho e somente linhas CSI_DATA com o numero esperado de campos e de valores CSI. Mensagens de inicializacao e logs do Wi-Fi ficam de fora. A lista de valores CSI e preservada numa unica coluna chamada data.

Se o PowerShell bloquear o script, execute:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\outputs\Capturar-CSI.ps1 -Segundos 60
```

Esse comando nao altera a politica permanente do computador. Tambem aceita `-Segundos 0` e `-Porta COM8`.

Se nenhuma amostra for salva, confira a porta, feche os outros monitores seriais e verifique se o ESP32 esta conectado ao Wi-Fi configurado. Depois que a captura terminar, a porta e liberada e voce pode abrir o monitor novamente.

## Coleta em lotes e envio POST

No PowerShell, entre em `C:\Users\vitor\Documents\MO629A\mo629A\ESP32-CSI` e execute:

```powershell
.\outputs\ESP32.ps1 menuconfig
```

Abra **CSI batch POST**. Os novos padroes sao 20 amostras por POST, quatro buffers de RAM, 100 pings solicitados por segundo (frequencia anterior restaurada) e timeout de I/O de 1000 ms. Nao existe timer de coleta. CSI e pings continuam durante os envios; pausam somente quando todos os buffers estao ocupados e retomam quando um envio libera memoria. Cada lote tem uma tentativa, tanto em sucesso quanto em falha. Nao ha reenvio nem persistencia em flash; lotes parciais aguardam novas amostras.

Execute reconfigure e confira `CSI_BATCH_MAX_SAMPLES=20`, `CSI_BATCH_BUFFER_COUNT=4` e `CSI_BATCH_PING_HZ=100` no menuconfig: um sdkconfig existente pode conservar valores anteriores. O antigo `CSI_BATCH_WINDOW_MS` foi removido. Preserve URL/token e configuracoes de Wi-Fi.

A URL `https://example.invalid/csi` e um stub: o firmware descarta cada lote sem acessar a rede. Substitua a URL para testar o endpoint real. Para HTTPS, habilite o Certificate Bundle do mbedTLS e use um certificado confiavel. O backend recebe JSON com identificacao da placa/sessao/lote, timestamps, metadados e valores CSI brutos.

Nesse mesmo menu, edite **Bearer token (value only, without Bearer prefix)** para configurar o token. Digite apenas seu valor, sem o prefixo Bearer. Cada POST tera o cabecalho `Authorization: Bearer <token>`; se o campo ficar vazio, esse cabecalho sera omitido. O endpoint precisa validar o token. Nao e necessario enviar o segredo no chat: ele fica no sdkconfig local, ignorado pelo Git, e no firmware compilado. Apos mudar URL ou token, salve, compile e grave novamente. O suporte ao token foi adicionado depois do primeiro build confirmado e precisa ser recompilado.

Se aparecer `CONFIG_CSI_POST_TOKEN undeclared`, a configuracao gerada ainda e anterior a esse campo. Execute `reconfigure`, depois `menuconfig` para preencher URL/token, salve e execute `build`:

```powershell
.\outputs\ESP32.ps1 reconfigure
.\outputs\ESP32.ps1 menuconfig
.\outputs\ESP32.ps1 build
```

O CMake tambem foi configurado para acompanhar alteracoes no arquivo main/Kconfig.projbuild e regenerar a configuracao. Nao e necessario apagar sdkconfig nem repetir set-target para resolver esse erro.

O timeout de 1000 ms nao limita a duracao total do envio: DNS e TLS podem demorar mais. O monitor serial mostra queue, captured, sent_samples, discarded_samples, dropped, pauses, pause_ms, upload_ms e free_heap. pause_ms e a duracao acumulada de pausas por fila cheia. Se o envio for mais lento que a coleta, essas pausas geram lacunas reais.

O timeout agora e aplicado por fase: a conexao HTTPS nao consome o orcamento reservado para escrever o corpo, e a resposta recebe um novo timeout de I/O. O log POST failed informa stage (headers/connect/write/response/http_status), body_sent, connect_ms e elapsed_ms. Use essa linha para diagnosticar HTTP=0. POST completed indica que houve resposta HTTP 2xx. Essa correcao requer nova compilacao e gravacao; os resumos antigos sem stage nao permitem identificar precisamente a falha.

O JSON foi alinhado ao contrato do endpoint: schema_version, device_id, session_id, batch_id e samples. Cada amostra contem seq, timestamp_us, ap_mac, rssi_dbm, noise_floor_dbm, channel, bandwidth_mhz, first_word_invalid e csi_raw. Contadores de diagnostico ficam apenas na serial.

No diagnostico anterior, um sdkconfig local usou 20 amostras, timeout de 5000 ms e pings a 20 Hz. Esses valores sao historicos; o padrao atual foi restaurado para 100 Hz. Uma resposta antecipada apos falha de escrita continua aparecendo como stage=early_response.

Para analisar os pequenos lotes em conjunto, use `modeling_and_analysis/csi_collection_inference.ipynb`. Edite `WINDOW_PROFILES` para escolher duracao, passo, minimo de pacotes e limite de lacunas, incluindo bordas. O perfil local inicial usa 1 segundo / passo de 0.2 segundo / 12 pacotes / lacuna maxima de 0.25 segundo; o perfil original de treinamento e comparado no mesmo notebook. As previsoes com novos parametros sao exploratorias ate validacao ou novo treinamento. Nenhum arquivo Lambda ou recurso AWS foi alterado.

Depois de salvar a configuracao:

```powershell
.\outputs\ESP32.ps1 build
.\outputs\ESP32.ps1 flash
.\outputs\ESP32.ps1 monitor
```

Detalhes do protocolo, limites e testes estao em `C:\Users\vitor\Documents\MO629A\mo629A\ESP32-CSI\work\esp-csi\examples\get-started\csi_recv_router\BATCH_POST.md`.

Em 29/10/2026, o build no PowerShell normal do Windows gerou o firmware com o modo de lotes habilitado: 765440 bytes e 27% livres na particao de app. A compilacao esta confirmada; a execucao na placa e o POST para um endpoint real ainda nao foram testados. Nenhum novo firmware foi gravado nesta etapa. O compilador continua apresentando erro de DLL quando iniciado dentro do ambiente do Codex.

## Backup e arquivos de captura

ESP32-firmware-original.bin: copia dos 4 MB da flash antes da gravacao.
CSI-captura.csv: captura inicial de 30 segundos.
CSI_*.csv: novas rodadas feitas com Capturar-CSI.ps1.
Mantenha work e outputs juntas dentro de ESP32-CSI. Os scripts usam caminhos relativos a essa pasta. Ao mover o projeto, o primeiro build preserva a compilacao antiga e gera outra com os novos caminhos.
