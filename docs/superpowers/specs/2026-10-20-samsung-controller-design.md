# Samsung Controller — Design

Data: 2026-10-20 · Status: em revisão
Origem: projeto irmão `~/Documents/Projetos/TCL-controller` (sidecar TCL + app SwiftUI em Liquid Glass). Este projeto é **separado** e reaproveita o **contrato HTTP** e uma **cópia do app**.

## 1. Objetivo

Controlar a **Samsung The Frame 32" (QN32LS03CBGXZD, LS03C 2023, Tizen)** pelo Mac com a mesma experiência do app TCL: um sidecar Python novo, limpo, que implementa o mesmo contrato HTTP, e uma cópia do app Swift sem mudança de lógica.

### Critérios de sucesso

1. A cópia do app ("Samsung Controller") abre, sobe o sidecar Samsung (`uv run tcl-sidecar`, porta **8766**) e mostra o estado da Frame — convivendo com o app TCL (porta 8765) na barra de menus.
2. Teclas, volume, abrir apps e desligar funcionam pela API local da TV.
3. **Ligar a TV pelo Mac** funciona (Wake-on-LAN) — diferente da TCL.
4. Entradas HDMI, modo de imagem (e brilho, se a TV expuser) funcionam via SmartThings quando um token estiver configurado; sem token, essas rotas respondem 501 com mensagem clara.
5. Toda resposta respeita exatamente o contrato que o app consome (testes de contrato).
6. Desenvolvido e testado contra uma **TV simulada** (a Frame ainda não está na rede); validação real fica como etapa final quando a TV estiver disponível.

### Fora de escopo (v1)

- Modo Arte (fica para v2, CLI primeiro).
- Qualquer mudança de lógica no app Swift.
- Controlar TCL e Samsung no mesmo app.
- AirPlay (nativo na TV; não precisa de código).

## 2. Projeto

```
Samsung-controller/              (repositório git próprio)
├── docs/
│   ├── CONTRATO-API.md          contrato HTTP app ↔ sidecar (extraído do TCL)
│   └── superpowers/{specs,plans}/
├── sidecar/                     Python 3.12 + uv, pacote samsung_sidecar
└── app/                         cópia do app Swift do TCL-controller (main @ 8e41e85)
```

### 2.1 Cópia do app — únicas alterações permitidas

Copiar `TCL-controller/app` (sem `.build/`, `build/`). Alterar **apenas** valores de configuração/marca:
- Nome exibido "Samsung Controller"; `CFBundleIdentifier` `local.samsung-controller`; nome do `.app` "Samsung Controller.app" (`bundle.sh`).
- Porta **8766**: URL base padrão do cliente e (no sidecar) a lista de hosts permitidos.
- Pasta padrão do sidecar: `~/Documents/Projetos/Samsung-controller/sidecar`.
- Pasta de log: `~/Library/Logs/Samsung-controller/sidecar.log`.
- Padrões do `InputNamesStore`: HDMI 1–4 com nome "HDMI N", símbolo `cable.connector`, nenhuma oculta (o "PS5"/"ARC" eram da TCL).
- Chaves de `UserDefaults`: o app usa o domínio do bundle id, então já ficam separadas.
Testes do app continuam passando (ajustar só valores esperados ligados aos itens acima).

## 3. Contrato HTTP (inalterado)

`docs/CONTRATO-API.md` documenta, a partir do sidecar TCL atual (`TCL-controller/sidecar/src/tcl_sidecar/api.py` e `controller.py`) e dos modelos Swift (`app/Sources/TCLCore/Models.swift`): rotas, corpos, respostas e códigos de erro `{"error","message"}`. Resumo:

| Método | Rota | Resposta |
|---|---|---|
| GET | `/health` | `{ok, tv_host, tv_mac, channels:{remote,adb}, adb_auth}` |
| GET | `/state` | `{power, app, volume, channels, adb_auth}` |
| POST | `/pair/start`, `/pair/finish {"pin"}` | `{ok}` |
| POST | `/key/{name}` | `{ok, channel}` |
| POST | `/app {"link"}` | `{ok}` |
| GET | `/inputs` | `[{port, id, label, connected, active}]` |
| POST | `/input/{port}` | `{ok, active_port}` |
| GET | `/picture[?cached=1]` | `{mode, mode_id, modes:[{id,label}], backlight, cached_at}` |
| POST | `/picture/mode {"mode"}`, `/picture/backlight {"value"}` | `{ok, mode, mode_id}` / `{ok, backlight}` |

Erros: `not_paired` 409, `adb_unauthorized` 409, `tv_unreachable` 503, `not_supported` 501, `unknown_key` 404, `tv_not_found` 503, `invalid_pin` 400, `unknown_mode` 400, `invalid_value` 400, `input_not_confirmed` 502, `no_cache` 404, `picture_unreadable` 502, `forbidden` 403, `invalid_request` 422, `internal` 500. Proteção: rejeitar `Origin` e Host fora de `127.0.0.1:8766`/`localhost:8766`.

## 4. Sidecar Samsung

### 4.1 Estrutura

```
sidecar/src/samsung_sidecar/
├── api.py            rotas FastAPI, validação, mapeamento de erros, middleware Origin/Host
├── service.py        TVService: roteamento entre canais, cache, power on/off, redescoberta
├── errors.py         mesma hierarquia/códigos do contrato
├── config.py         Config (tv_host, tv_mac, tv_name, ws_token, st_token, st_device_id) + data_dir()
├── keys.py           nome do contrato → KEY_* Samsung
├── apps.py           link → app id Tizen
├── discovery.py      SSDP (urn:samsung.com:device:RemoteControlReceiver:1) + REST de confirmação
├── channels/
│   ├── local.py      LocalChannel: REST :8001 (info/power) + WebSocket :8002 (TLS, token) via samsungtvws
│   ├── smartthings.py SmartThingsChannel: REST https://api.smartthings.com/v1 via httpx
│   └── wol.py        send_magic_packet(mac)
└── cli.py            CLI de teste (porta 8766)
```
Persistência: `~/Library/Application Support/Samsung-controller/` (`config.json`); `SAMSUNG_CONTROLLER_HOME` sobrescreve para testes. Dependências: `fastapi`, `uvicorn[standard]`, `httpx`, `samsungtvws[async]`; dev: `pytest`, `pytest-asyncio`. Script `tcl-sidecar` **e** `samsung-sidecar` apontam para o mesmo `main()` (porta 8766, `127.0.0.1`).

### 4.2 Mapeamento do contrato

| Rota | Implementação Samsung |
|---|---|
| `/health` | `tv_mac` = MAC salvo (de `wifiMac` do REST `GET http://<ip>:8001/api/v2/`); `channels.remote` = WebSocket conectado; `channels.adb` = SmartThings configurado e respondendo; `adb_auth` = `"pending"` enquanto a TV mostra o pedido "Permitir" do WebSocket |
| `/state` | `power`: REST `device.PowerState` (`"on"`/`"standby"`); REST inacessível → `"standby"`. `app`: `null` (Tizen não expõe o app em primeiro plano pela API local). `volume`: SmartThings `audioVolume` + `audioMute` quando configurado (`{level, max:100, muted}`), senão `null`. Nunca levanta erro |
| `/key/{name}` | WebSocket `send_key`. Mapa: power→`KEY_POWER`*, home→`KEY_HOME`, back→`KEY_RETURN`, up/down/left/right→`KEY_UP/DOWN/LEFT/RIGHT`, ok→`KEY_ENTER`, volume_up/down→`KEY_VOLUP/KEY_VOLDOWN`, mute→`KEY_MUTE`, play_pause→`KEY_PLAY_BACK`, menu→`KEY_MENU`, settings→`KEY_MENU`. `channel` = `"remote"` |
| `power` | Se `power == "standby"` ou TV inacessível: **Wake-on-LAN** para o MAC salvo, depois aguardar REST responder `on` por até 15 s (sondagem 1 s) → `{ok, channel:"wol"}`; senão `tv_unreachable`. Se ligada: *na Frame um toque curto em `KEY_POWER` entra no Modo Arte*; para **desligar** usar pressionar e segurar `KEY_POWER` por 3 s (`hold_key`). Comportamento a confirmar na TV (risco §7) |
| `/app {"link"}` | `apps.py`: `https://www.youtube.com`→`111299001912`, `https://www.netflix.com`→`3201907018807`, `https://www.primevideo.com`→`3201910019365`, `https://www.disneyplus.com`→`3201901017640`, `https://www.globoplay.globo.com`→`3201908019041` (ids a confirmar na TV via `GET /api/v2/applications/<id>`); link desconhecido → abrir no navegador da TV (`open_browser`) |
| `/pair/start` | Abre o WebSocket sem token → TV mostra "Permitir"; aguarda até 30 s; salva o token → `{ok}`; recusado/expirado → `adb_unauthorized` |
| `/pair/finish` | Aceita qualquer PIN (a Samsung não usa PIN) e confirma que há token → `{ok}`; sem token → `not_paired` |
| Pareamento implícito | O primeiro comando sem token abre o WebSocket e dispara o "Permitir"; enquanto pendente, `adb_auth = "pending"` (o app já mostra a faixa "Aceite o pedido… na TV"). `tv_mac` é salvo na descoberta, então o app não entra em "não pareado" |
| `/inputs` | SmartThings `mediaInputSource` (`supportedInputSources`, `inputSource`): portas = fontes `HDMI<n>` → `{port:n, id:"HDMI<n>", label:"HDMI <n>", connected:false, active: inputSource=="HDMI<n>"}`. Sem SmartThings → `not_supported` ("Configure o token SmartThings") |
| `/input/{port}` | SmartThings comando `mediaInputSource.setInputSource("HDMI<port>")`; confirmar lendo `inputSource` por até 5 s → `{ok, active_port}`; senão `input_not_confirmed`; porta fora de `supportedInputSources` → `invalid_value` |
| `/picture` | SmartThings `custom.picturemode` (`supportedPictureModes`, `pictureMode`) → `modes` com `id` = valor SmartThings e `label` = rótulo pt-BR (`PICTURE_LABELS`: Dynamic→"Dinâmico", Standard→"Padrão", Natural→"Natural", Movie→"Filme", FILMMAKER MODE→"Filmmaker"; desconhecido → o próprio valor). `backlight`: capacidade de brilho se presente no dispositivo (descoberta em runtime via `GET /devices/{id}`), senão `0`. Cache como no TCL (`?cached=1`, `no_cache`) |
| `/picture/mode` | `custom.picturemode.setPictureMode(<id>)` para o rótulo pedido (case-insensitive contra `PICTURE_LABELS`); fora da lista → `unknown_mode`; confirma relendo |
| `/picture/backlight` | Se a TV expõe brilho no SmartThings: comando correspondente (0–100, `invalid_value` fora); senão `not_supported` ("Brilho não disponível nesta TV") |

### 4.3 SmartThings

- Token pessoal (PAT) criado pelo usuário em `https://account.smartthings.com/tokens` com escopos de leitura/execução de dispositivos. Configurado pela CLI: `samsung smartthings <token>` → lista dispositivos (`GET /v1/devices`), escolhe o de `deviceTypeName`/`name` contendo "Frame"/"TV" (ou pergunta se houver mais de um) e salva `st_device_id`.
- Status: `GET /v1/devices/{id}/status`; comandos: `POST /v1/devices/{id}/commands` `{"commands":[{"component":"main","capability":…,"command":…,"arguments":[…]}]}`. Timeout 10 s. HTTP 401 → `not_supported` ("Token SmartThings inválido").
- Nunca logar o token.

### 4.4 Erros, redescoberta e concorrência

- `tv_unreachable` para REST/WebSocket inacessíveis (timeout de conexão 4 s); redescoberta uma vez por comando (SSDP, casar pelo MAC salvo), igual ao TCL.
- Um `asyncio.Lock` por canal; WebSocket reaproveitado entre comandos e recriado ao cair.
- Mensagens de erro em pt-BR.

## 5. Testes

- **Contrato**: para cada rota, a resposta do sidecar (com canais simulados) é validada contra os JSONs de exemplo do app (`app/Tests/TCLCoreTests/Fixtures/*.json`) — mesmas chaves e tipos.
- Unidades por camada com fakes: `LocalChannel` (REST/WebSocket falsos: power state, token pendente/negado, hold_key), `SmartThingsChannel` (httpx `MockTransport`: status, comandos, 401), `wol` (pacote de 102 bytes, broadcast), `service` (power on via WOL + espera, power off por hold, pareamento implícito → `adb_auth`, sem SmartThings → 501, redescoberta), `api` (todas as rotas e códigos, middleware 8766).
- App copiado: `swift test` verde após as alterações de configuração.
- **Validação real (etapa final, quando a Frame estiver na rede)**: descoberta, "Permitir", teclas, desligar/ligar, apps, SmartThings (entradas, imagem, brilho), comportamento do `KEY_POWER` na Frame.

## 6. Plano de entrega

1. Projeto + contrato documentado + cópia do app com alterações de configuração.
2. Canais (local, SmartThings, WOL) com fakes.
3. Service + API + CLI com testes de contrato.
4. Validação real quando a TV estiver disponível.

## 7. Riscos

- **KEY_POWER na Frame**: toque curto alterna Modo Arte; desligar exige segurar — validar; se `hold_key` não desligar, usar SmartThings `switch.off`.
- **Wake-on-LAN** depende de "Ligar com dispositivo móvel / rede" ativo na TV e de a Frame manter Wi-Fi em standby (Modo Arte/standby) — validar.
- **Brilho** pode não existir no SmartThings para este modelo → 501 documentado.
- App ids Tizen podem variar por região — confirmar na TV.
- Sem a TV, tudo é validado contra simulação; diferenças reais viram ajustes na etapa 4.
