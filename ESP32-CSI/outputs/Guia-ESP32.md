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

- O codigo-fonte rastreado do ESP-CSI permanece igual ao repositorio original.
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

Se o compilador nao iniciar e aparecer `WinError 623` ou `Realocacao Invalida da DLL do Sistema`, houve uma falha ao carregar a ferramenta no Windows antes de compilar o codigo. Essa falha foi observada ao executar pelo ambiente do Codex nas pastas antiga e nova. Tente o mesmo comando build num PowerShell aberto normalmente; a compilacao no novo local ainda precisa ser confirmada. Nao e necessario apagar os fontes nem gravar a placa para diagnosticar esse erro.

## Exemplo de alteracao

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

## Backup e arquivos de captura

ESP32-firmware-original.bin: copia dos 4 MB da flash antes da gravacao.
CSI-captura.csv: captura inicial de 30 segundos.
CSI_*.csv: novas rodadas feitas com Capturar-CSI.ps1.
Mantenha work e outputs juntas dentro de ESP32-CSI. Os scripts usam caminhos relativos a essa pasta. Ao mover o projeto, o primeiro build preserva a compilacao antiga e gera outra com os novos caminhos.
