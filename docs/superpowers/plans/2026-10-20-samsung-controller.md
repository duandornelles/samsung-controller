# Samsung Controller Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Sidecar Python para a Samsung The Frame que implementa o contrato HTTP do app, mais uma cópia do app Swift reconfigurada (porta 8766), num repositório separado.

**Architecture:** `samsung_sidecar` em camadas — canais isolados (`local` = REST/WebSocket da TV via `samsungtvws`, `smartthings` = REST de nuvem via `httpx`, `wol` = pacote mágico), um `TVService` que roteia, e `api.py` que só traduz HTTP ↔ serviço segundo `docs/CONTRATO-API.md`. Tudo testado com canais falsos (a TV não está disponível).

**Tech Stack:** Python 3.12 · uv · FastAPI · httpx · samsungtvws[async] · pytest/pytest-asyncio · Swift 6 (cópia do app)

**Spec:** `docs/superpowers/specs/2026-10-20-samsung-controller-design.md`

## Global Constraints

- Repositório: `~/Documents/Projetos/Samsung-controller` (git próprio). Fonte do contrato e do app: `~/Documents/Projetos/TCL-controller` @ `main` (8e41e85) — **somente leitura**, nunca modificar.
- Porta **8766**, bind só `127.0.0.1`; rejeitar `Origin` e Host fora de `127.0.0.1:8766`/`localhost:8766` (403 `forbidden`).
- Contrato idêntico ao do TCL (rotas, chaves JSON, códigos/HTTP de erro), formato `{"error","message"}`, mensagens pt-BR.
- Persistência `~/Library/Application Support/Samsung-controller/config.json` (`SAMSUNG_CONTROLLER_HOME` para testes). Nunca logar tokens.
- Scripts `tcl-sidecar` e `samsung-sidecar` → mesmo `samsung_sidecar.api:main`.
- Nenhum teste toca rede real (TV, SmartThings, broadcast).
- App copiado: só as alterações de configuração da spec §2.1; `export DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer` em todo comando Swift; nunca `xcode-select`; 0 warnings.
- Sidecar: `uv run pytest -q -W error` limpo. Commits terminam com `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. **TV em standby e usuário aperta power no app** → Wake-on-LAN + espera, não `tv_unreachable` imediato. → teste em Task 5.
2. **Primeiro comando sem token (TV mostrando "Permitir")** → `adb_auth: "pending"` no `/state`/`/health` em tempo limitado, sem travar a requisição além do timeout. → testes em Tasks 3 e 5.
3. **SmartThings não configurado ou token inválido** → `/inputs` e `/picture` respondem 501 com mensagem clara; `/state` continua funcionando (volume `null`). → testes em Tasks 4 e 5.
4. **Resposta fora do contrato** (chave faltando/tipo errado) quebraria o app silenciosamente → teste de contrato contra os JSONs do app. → Task 6.
5. **Desligar a Frame com toque curto só entra no Modo Arte** → usar segurar 3 s (`hold`). → teste em Task 5.

---

## File Structure

```
Samsung-controller/
├── docs/CONTRATO-API.md
├── app/                                  (cópia reconfigurada)
└── sidecar/
    ├── pyproject.toml
    ├── src/samsung_sidecar/{__init__,errors,config,keys,apps}.py
    ├── src/samsung_sidecar/channels/{__init__,wol,local,smartthings}.py
    ├── src/samsung_sidecar/{discovery,service,api,cli}.py
    └── tests/ (fakes.py, conftest.py, fixtures/contract/*.json, test_*.py)
```

Comandos do sidecar a partir de `sidecar/`.

---

### Task 1: Contrato documentado e cópia do app

**Files:** Create `docs/CONTRATO-API.md`, `app/**` (cópia), `README.md` (raiz).

- [ ] **Step 1: Contrato** — escrever `docs/CONTRATO-API.md` lendo (sem modificar) `TCL-controller/sidecar/src/tcl_sidecar/{api,controller,errors}.py`, `TCL-controller/sidecar/README.md` e `TCL-controller/app/Sources/TCLCore/Models.swift`: para cada rota da spec §3 — método, caminho, corpo, resposta de sucesso (com exemplo JSON real tirado de `TCL-controller/app/Tests/TCLCoreTests/Fixtures/*.json` quando houver), erros possíveis; tabela de erros (código, HTTP); regras de Host/Origin; timeouts que o app usa.
- [ ] **Step 2: Copiar o app** — `rsync -a --exclude .build --exclude build ~/Documents/Projetos/TCL-controller/app/ app/`.
- [ ] **Step 3: Reconfigurar (spec §2.1)** — somente: nome "Samsung Controller" e `CFBundleIdentifier` `local.samsung-controller` e `.app` "Samsung Controller.app" em `scripts/bundle.sh`; porta 8766 na URL base padrão do `SidecarClient`; pasta padrão do sidecar `~/Documents/Projetos/Samsung-controller/sidecar`; log `~/Library/Logs/Samsung-controller/sidecar.log`; padrões do `InputNamesStore` = "HDMI N"/`cable.connector`/visível para todas as portas; textos que digam "TCL" na UI → "Samsung"/"TV". Registrar no `app/README.md` a lista exata do que mudou em relação ao TCL. Ajustar apenas os testes que verificam esses valores.
- [ ] **Step 4: Verificar** — `cd app && swift build` (0 warnings) e `swift test` (todos verdes); `./scripts/bundle.sh` gera `build/Samsung Controller.app`; `plutil -p` mostra o bundle id novo. `grep -rn "8765\|TCL-controller" app/Sources` → nenhuma ocorrência.
- [ ] **Step 5: Commit** — `feat: contrato da API e cópia do app reconfigurada (porta 8766)`

---

### Task 2: Sidecar — base (erros, config, teclas, apps, WOL)

**Files:** Create `sidecar/pyproject.toml`, `src/samsung_sidecar/{__init__,errors,config,keys,apps}.py`, `src/samsung_sidecar/channels/{__init__,wol}.py`, `tests/{conftest,test_errors,test_config,test_keys,test_apps,test_wol}.py`.

**Interfaces:**
- Produces:
  - `errors.TVError(Exception)` com `code`, `http_status`; subclasses com os códigos/HTTP da tabela de erros da spec §3 (`NotPaired`, `AdbUnauthorized`, `TVUnreachable`, `NotSupported`, `UnknownKey`, `TVNotFound`, `InvalidPin`, `UnknownMode`, `InvalidValue`, `InputNotConfirmed`, `NoCache`, `PictureUnreadable`).
  - `config.Config` dataclass: `tv_host: str|None`, `tv_mac: str|None`, `tv_name: str|None`, `ws_token: str|None`, `st_token: str|None`, `st_device_id: str|None`; `data_dir() -> Path`, `load_config() -> Config` (arquivo corrompido/chaves desconhecidas → ignora chaves desconhecidas; JSON inválido → `Config()`), `save_config(cfg) -> None` (atômico, permissão `0o600`).
  - `keys.KEYS: dict[str,str]` e `keys.samsung_key(name) -> str` (`UnknownKey`): mapa exato da spec §4.2.
  - `apps.APP_IDS: dict[str,str]` (links → ids da spec §4.2, comparação ignorando barra final e `www.`); `apps.app_for(link) -> str | None`.
  - `channels.wol.magic_packet(mac: str) -> bytes` (6×`0xFF` + MAC×16 = 102 bytes; aceita `:` ou `-`; `ValueError` se inválido); `async send_magic_packet(mac, broadcast="255.255.255.255", ports=(9, 7), sender=None) -> None` (`sender` injetável para testes).
- `pyproject.toml`: `uv init --lib --name samsung-sidecar --python 3.12 --vcs none`; deps `fastapi`, `uvicorn[standard]`, `httpx`, `samsungtvws[async]`; dev `pytest`, `pytest-asyncio`; `asyncio_mode = "auto"`; scripts `tcl-sidecar` e `samsung-sidecar` → `samsung_sidecar.api:main`, `samsung` → `samsung_sidecar.cli:main` (módulos criados nas Tasks 6).

- [ ] **Step 1: Testes que falham**

```python
def test_error_codes(): assert (UnknownMode("x").code, UnknownMode("x").http_status) == ("unknown_mode", 400)
def test_config_roundtrip_and_perms(tmp_path, monkeypatch): ...  # save/load; stat mode == 0o600
def test_config_tolerates_garbage(tmp_path, monkeypatch): ...    # '{"x":1,"tv_host":"1.2.3.4"}' → tv_host ok; "{" → Config()
def test_keys_map(): assert samsung_key("back") == "KEY_RETURN" and samsung_key("ok") == "KEY_ENTER" and samsung_key("power") == "KEY_POWER"
def test_unknown_key(): with pytest.raises(UnknownKey): samsung_key("explodir")
def test_app_ids(): assert app_for("https://www.youtube.com") == "111299001912" and app_for("youtube.com/") == "111299001912" and app_for("https://x.org") is None
def test_magic_packet(): pkt = magic_packet("AA:BB:CC:DD:EE:FF"); assert len(pkt) == 102 and pkt[:6] == b"\xff"*6 and pkt[6:12] == bytes.fromhex("aabbccddeeff")
def test_magic_packet_invalid(): with pytest.raises(ValueError): magic_packet("zz")
async def test_send_magic_packet_uses_sender(): ...  # sender recebe (packet, ("255.255.255.255", 9)) e porta 7
```

- [ ] **Step 2: Rodar e ver falhar** — `uv run pytest -q -W error`.
- [ ] **Step 3: Implementar.**
- [ ] **Step 4: Verde.**
- [ ] **Step 5: Commit** — `feat(sidecar): base (erros, config, teclas, apps, wake-on-lan)`

---

### Task 3: Canal local (REST + WebSocket)

**Files:** Create `src/samsung_sidecar/channels/local.py`, `tests/{fakes.py,test_local.py}`.

**Interfaces:**
- Consumes: `errors`, `config`.
- Produces: `class LocalChannel`:
  - `__init__(self, host: str, token: str | None, on_token: Callable[[str], None], rest_factory=..., ws_factory=..., connect_timeout_s: float = 4.0, pairing_timeout_s: float = 30.0)`
  - `async device_info() -> dict` — REST `GET http://<host>:8001/api/v2/` → dict da chave `device`; inacessível → `TVUnreachable`.
  - `async power_state() -> Literal["on","standby"] | None` — de `device_info()["PowerState"]`; inacessível → `None` (não levanta).
  - `async mac() -> str | None` — `wifiMac` em minúsculas.
  - `async key(samsung_key: str) -> None`, `async hold(samsung_key: str, seconds: float) -> None`
  - `async run_app(app_id: str) -> None`, `async open_browser(url: str) -> None`
  - `pairing_pending: bool` (propriedade: True enquanto aguarda "Permitir"), `connected: bool`
  - `async set_host(host: str) -> None`, `async close() -> None`
- Regras: WebSocket `wss://<host>:8002/api/v2/channels/samsung.remote.control?name=<base64("Samsung Controller")>&token=<token>` via `samsungtvws` async (verificar no pacote instalado os nomes reais: `SamsungTVWSAsyncRemote`, `SendRemoteKey.click/press/release`, `ChannelEmitCommand.launch_app`/`rest_app_run`, browser; ajustar e anotar no relatório). Conexão preguiçosa sob `asyncio.Lock`; sem token: conectar dispara o "Permitir" — `pairing_pending=True` até receber token (chama `on_token(token)`) ou `pairing_timeout_s` (→ `AdbUnauthorized("Aceite o pedido de conexão na TV")`, `pairing_pending=False`); conexão recusada/timeout TCP → `TVUnreachable`; `ms.channel.unauthorized` → `AdbUnauthorized`. Fábricas injetáveis para testes.

- [ ] **Step 1: Testes que falham** (fakes de REST e WebSocket em `tests/fakes.py`)

```python
async def test_power_state_on_and_standby(): ...            # PowerState "on"/"standby"; REST erro → None
async def test_mac_lowercase(): ...                          # wifiMac "AA:BB:..." → "aa:bb:..."
async def test_key_sends_click(): ...                        # KEY_HOME enviado
async def test_hold_press_wait_release(): ...                # press KEY_POWER, espera 3 s (sleep falso), release
async def test_first_connect_without_token_saves_token(): ... # on_token("abc"); pairing_pending volta a False
async def test_pairing_pending_visible_while_waiting(): ...   # durante a espera pairing_pending True (Review Focus 2)
async def test_pairing_timeout_unauthorized(): ...            # nunca chega token → AdbUnauthorized em < 1 s com timeout 0.2
async def test_unreachable(): ...                             # conexão recusada → TVUnreachable
async def test_concurrent_keys_single_connection(): ...       # gather de 5 keys → 1 conexão
async def test_run_app_and_browser(): ...
```

- [ ] **Step 2: Ver falhar.** · **Step 3: Implementar.** · **Step 4: Verde.**
- [ ] **Step 5: Commit** — `feat(sidecar): canal local da TV (REST + WebSocket)`

---

### Task 4: Canal SmartThings

**Files:** Create `src/samsung_sidecar/channels/smartthings.py`, `tests/test_smartthings.py`, `tests/fixtures/smartthings_status.json`, `tests/fixtures/smartthings_device.json` (exemplos no formato da API, com `mediaInputSource`, `custom.picturemode`, `audioVolume`, `audioMute`, `switch`).

**Interfaces:**
- Produces:
  - `PICTURE_LABELS: dict[str,str]` (spec §4.2) e `picture_label(value) -> str` (desconhecido → o próprio valor).
  - `class SmartThingsChannel`: `__init__(self, token: str, device_id: str, transport: httpx.AsyncBaseTransport | None = None, base_url="https://api.smartthings.com/v1", timeout_s=10.0)`
    - `async status() -> dict`; `async command(capability: str, command: str, args: list) -> None`
    - `async input_sources() -> tuple[list[str], str | None]` (suportadas, atual)
    - `async set_input(source: str) -> None`
    - `async picture_modes() -> tuple[list[str], str | None]`; `async set_picture_mode(mode: str) -> None`
    - `async volume() -> dict | None` → `{level, max: 100, muted}`
    - `async backlight() -> int | None` e `async set_backlight(v: int) -> None` — via capacidade de brilho se presente em `GET /devices/{id}` (procurar capacidade cujo id contenha `brightness` ou `backlight`); ausente → `None` / `NotSupported("Brilho não disponível nesta TV")`
    - `@staticmethod async list_devices(token, transport=None) -> list[dict]`
  - 401 → `NotSupported("Token SmartThings inválido")`; rede/timeout → `TVUnreachable("SmartThings inacessível")`; header `Authorization: Bearer <token>` (nunca logado).

- [ ] **Step 1: Testes que falham** (`httpx.MockTransport`)

```python
async def test_input_sources(): ...      # (["digitalTv","HDMI1","HDMI2"], "HDMI1")
async def test_set_input_command_body(): ...  # {"commands":[{"component":"main","capability":"mediaInputSource","command":"setInputSource","arguments":["HDMI2"]}]}
async def test_picture_modes_and_labels(): ...  # picture_label("Standard") == "Padrão"; picture_label("X") == "X"
async def test_volume(): ...             # {"level": 12, "max": 100, "muted": False}
async def test_backlight_absent(): ...   # sem capacidade → backlight() None; set_backlight → NotSupported
async def test_unauthorized(): ...       # 401 → NotSupported (Review Focus 3)
async def test_auth_header_and_no_token_in_errors(): ...
```

- [ ] **Step 2–4:** ver falhar → implementar → verde.
- [ ] **Step 5: Commit** — `feat(sidecar): canal SmartThings`

---

### Task 5: Descoberta e TVService

**Files:** Create `src/samsung_sidecar/{discovery,service}.py`, `tests/{test_discovery,test_service}.py`.

**Interfaces:**
- Consumes: Tasks 2–4.
- Produces:
  - `discovery.TVCandidate(host: str, name: str)`; `async discover(timeout=3.0, ssdp=..., probe=...) -> list[TVCandidate]` (SSDP `M-SEARCH` por `urn:samsung.com:device:RemoteControlReceiver:1`; confirma cada IP com REST `:8001/api/v2/`); `async find_tv(mac: str | None, get_mac: Callable[[str], Awaitable[str|None]], discover=discover) -> tuple[TVCandidate, str]` (casa por MAC; `None` → primeiro; nenhum → `TVNotFound`).
  - `class TVService` (métodos e retornos **idênticos** ao `TVController` do TCL, para o `api.py` espelhar o contrato): `send_key(name) -> str`, `launch_app(link) -> None`, `state() -> dict`, `health() -> dict`, `start_pairing()`, `finish_pairing(pin)`, `inputs() -> list[dict]`, `set_input(port:int) -> dict`, `picture(cached=False) -> dict`, `set_picture_mode(label) -> dict`, `set_backlight(value:int) -> dict`, `warmup()`, `close()`. Construtor: `(config, local_factory, st_factory, wol=send_magic_packet, finder=find_tv, save=save_config, sleep=asyncio.sleep, now=...)`.
- Regras (spec §4.2): `power` → se `power_state()` ≠ `"on"`: WOL para `config.tv_mac` (sem MAC → `TVUnreachable`), sondar `power_state()` a cada 1 s por até 15 s → `"wol"`; senão `hold("KEY_POWER", 3.0)` → `"remote"`. Demais teclas → `key` → `"remote"`. `launch_app`: `app_for(link)` → `run_app`, senão `open_browser`. `state()` nunca levanta; `adb_auth = "pending"` se `local.pairing_pending`. `health.tv_mac` = MAC salvo. Sem `st_token`/`st_device_id` → `inputs`/`set_input`/`picture*` levantam `NotSupported("Configure o token SmartThings (samsung smartthings <token>)")`. `set_input` confirma por até 5 s (sondagem 1 s). Cache de imagem como no TCL, invalidado após `set_input`. `start_pairing` = conectar sem token aguardando o "Permitir"; `finish_pairing` aceita qualquer PIN se houver token, senão `NotPaired`. Primeiro uso sem `tv_host`: descobrir e salvar host/MAC/nome. Redescoberta uma vez em `TVUnreachable` (exceto `state`/`inputs`), igual ao TCL.

- [ ] **Step 1: Testes que falham** (fakes de canais)

```python
async def test_power_from_standby_uses_wol_and_waits(): ...   # wol(mac) chamado; standby,standby,on → "wol" (Review Focus 1)
async def test_power_wol_timeout_unreachable(): ...           # nunca on em 15 s → TVUnreachable
async def test_power_when_on_holds_3s(): ...                  # hold("KEY_POWER", 3.0) → "remote" (Review Focus 5)
async def test_keys_map_to_local(): ...                       # "back" → key("KEY_RETURN")
async def test_launch_known_and_unknown_link(): ...
async def test_state_pending_pairing(): ...                   # adb_auth "pending" (Review Focus 2)
async def test_state_volume_from_smartthings_or_none(): ...   # sem ST → volume None, sem erro (Review Focus 3)
async def test_inputs_without_smartthings_501(): ...          # NotSupported
async def test_inputs_mapping(): ...                          # HDMI1/HDMI2 → [{port:1,id:"HDMI1",label:"HDMI 1",connected:False,active:True}, ...]
async def test_set_input_confirm_and_invalid(): ...
async def test_picture_and_cache_invalidation(): ...          # labels pt-BR; após set_input → cached → NoCache
async def test_set_picture_mode_unknown(): ...                # UnknownMode, nenhum comando
async def test_backlight_not_supported(): ...
async def test_first_use_discovers_and_saves(): ...
async def test_discover_matches_mac(): ...                     # discovery: find_tv casa pelo MAC
```

- [ ] **Step 2–4:** ver falhar → implementar → verde.
- [ ] **Step 5: Commit** — `feat(sidecar): descoberta e serviço da TV`

---

### Task 6: API, CLI e testes de contrato

**Files:** Create `src/samsung_sidecar/{api,cli}.py`, `tests/{test_api,test_contract,test_cli}.py`, `tests/fixtures/contract/*.json` (cópias de `TCL-controller/app/Tests/TCLCoreTests/Fixtures/*.json` e de respostas documentadas em `docs/CONTRATO-API.md`), `sidecar/README.md`.

**Interfaces:**
- Consumes: `TVService` (Task 5).
- Produces: `create_app(service, allowed_hosts={"127.0.0.1:8766","localhost:8766"}) -> FastAPI`, `build_service() -> TVService`, `main()` (`uvicorn.run(..., host="127.0.0.1", port=8766)`); rotas e handlers exatamente como no contrato (inclui catch-all 500 `internal`, 422 `invalid_request`, middleware 403 `forbidden`, lifespan com `warmup()` em background e `close()` no fim). CLI `samsung` (httpx → `http://127.0.0.1:8766`): `health`, `state`, `pair`, `key <nome>`, `app <link>`, `inputs`, `input <porta>`, `picture`, `mode <rótulo>`, `smartthings <token>` (lista dispositivos com `SmartThingsChannel.list_devices`, escolhe o que tiver "Frame" ou "TV" no nome; se vários, pergunta pelo índice; salva `st_token` e `st_device_id` no config — direto no arquivo, sem passar pelo HTTP).
- Teste de contrato: para cada rota de sucesso, a resposta (service falso) tem **o mesmo conjunto de chaves e tipos** do fixture correspondente (recursivo); para cada erro, `{"error","message"}` com o código/HTTP do contrato.

- [ ] **Step 1: Testes que falham** — `test_contract.py` (health, state, inputs, picture, key, set_input, pictures sets, cada código de erro), `test_api.py` (Origin → 403, Host errado → 403, 8766 ok, 422 shape, 500 shape), `test_cli.py` (MockTransport; `smartthings` grava config com token e device id escolhido).
- [ ] **Step 2–4:** ver falhar → implementar → verde; `uv run python -c "from samsung_sidecar.api import create_app, build_service; create_app(build_service()); print('ok')"` com `SAMSUNG_CONTROLLER_HOME=$(mktemp -d)`.
- [ ] **Step 5: README do sidecar** (pt-BR: instalar, `uv run samsung-sidecar`, primeiro uso — "Permitir" na TV, configurar SmartThings, CLI, limitações/riscos da spec §7).
- [ ] **Step 6: Commit** — `feat(sidecar): API, CLI e testes de contrato`

---

### Task 7: Validação real (quando a Frame estiver na rede)

- [ ] Controlador + usuário: descoberta, "Permitir", teclas, abrir apps, desligar (segurar) e ligar (WOL), token SmartThings, entradas, modos de imagem, brilho; ajustar ids de apps/rótulos/timings conforme a TV; registrar em `docs/descobertas/`.
