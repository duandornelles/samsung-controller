# Contrato HTTP app ↔ sidecar

Extraído (sem modificar) do projeto irmão TCL-controller @ 8e41e85:
`sidecar/src/tcl_sidecar/{api,controller,errors}.py`, `sidecar/README.md`,
`app/Sources/TCLCore/{Models,SidecarClient,ErrorMessages}.swift` e `app/Tests/TCLCoreTests/Fixtures/*.json`.
O sidecar Samsung implementa exatamente este contrato, com a porta **8766** no lugar de 8765.

## 1. Convenções gerais

- Base: `http://127.0.0.1:8766`, corpo JSON (`Content-Type: application/json` nos POST com corpo).
- Chaves do JSON em `snake_case`; o app decodifica com `convertFromSnakeCase`. Qualquer chave ausente ou de tipo
  diferente nas respostas abaixo faz o app tratar a resposta como `invalidResponse` ("Erro inesperado").
- Erro: sempre `{"error": "<codigo>", "message": "<texto pt-BR>"}` com o status HTTP da tabela da seção 4.
  O app mostra `message` para códigos sem texto próprio. Corpo de erro que não seja esse JSON vira `http_<status>`.
- Sucesso é qualquer status 2xx. O app só lê campos específicos de algumas respostas (indicado em cada rota);
  as demais chaves devem existir por contrato.
- Rotas inexistentes (404 padrão do FastAPI `{"detail":"Not Found"}`) e 405 não fazem parte do contrato.

## 2. Host e Origin (proteção local)

Middleware executado antes de qualquer rota:

- Rejeitar com `403 {"error":"forbidden","message":"Origem não permitida"}` se a requisição tiver **qualquer**
  cabeçalho `Origin`, **ou** se `Host` não for exatamente `127.0.0.1:8766` ou `localhost:8766`.
- O app (URLSession) e a CLI (httpx) não enviam `Origin`; o `Host` sai como `127.0.0.1:8766` (a URL base padrão
  do `SidecarClient`). Bind do servidor: `127.0.0.1:8766`.
- Objetivo: bloquear CSRF de páginas web e DNS rebinding.

## 3. Rotas

Timeouts de cliente: o que o app usa (`SidecarClient`, `timeoutInterval` por requisição). Estouro vira
`SidecarError.timeout` ("A TV demorou para responder"); conexão recusada vira `notRunning` ("Sidecar não está
respondendo"). Erros possíveis abaixo omitem `forbidden` (403, qualquer rota) e `internal` (500, qualquer rota).
`invalid_request` (422) vale para qualquer rota com corpo/parâmetro inválido.

### GET /health
Timeout do app: 5 s. Resposta 200:
```json
{"ok":true,"tv_host":"192.168.2.133","tv_mac":"38:c8:04:d3:73:d8","channels":{"remote":false,"adb":false},"adb_auth":null}
```
Tipos: `ok` bool; `tv_host`, `tv_mac`, `adb_auth` string ou `null`; `channels.remote`/`channels.adb` bool.
`adb_auth` é `"pending"` ou `null`. Não levanta erro.

### GET /state
Timeout: 5 s. Nunca levanta erro. Resposta 200 (TV ligada):
```json
{"power":"on","app":"com.google.android.youtube.tv","volume":{"level":13,"max":100,"muted":false},"channels":{"remote":true,"adb":true},"adb_auth":null}
```
TV em espera:
```json
{"power":"standby","app":null,"volume":null,"channels":{"remote":false,"adb":false},"adb_auth":null}
```
Tipos: `power` `"on"`/`"standby"`/`null` (`null` = TV ainda não descoberta); `app` string ou `null`;
`volume` objeto `{level:int, max:int, muted:bool}` ou `null`; `channels` como em `/health`; `adb_auth` string ou `null`.

**Sentinela `app == "com.tcl.tv"`** (decisão R4): o app depende desse valor para saber que "a TV está mostrando uma
fonte de entrada (HDMI)". O sidecar Samsung devolve exatamente `"com.tcl.tv"` quando o SmartThings informa uma
entrada `HDMIn` como fonte ativa; sem SmartThings, em espera ou fora de HDMI, `app` é `null`. Não é um id de app real.

### POST /pair/start
Sem corpo. Timeout: 30 s. Resposta 200: `{"ok":true}`.
Erros: `tv_not_found` (503), `tv_unreachable` (503), `not_supported` (501), `adb_unauthorized` (409).

### POST /pair/finish
Corpo: `{"pin":"<string>"}`. Timeout: 30 s. Resposta 200: `{"ok":true}`.
No Samsung o PIN não existe: **qualquer PIN é aceito** (o valor é ignorado) e basta já haver token salvo pelo
`/pair/start` (senão `not_paired`). O corpo continua obrigatório pelo contrato.
Erros: `invalid_pin` (400), `not_paired` (409), `tv_unreachable` (503), `invalid_request` (422, sem `pin`).

### POST /key/{name}
Sem corpo. Timeout: 30 s. Nomes válidos: `power, home, back, up, down, left, right, ok, volume_up, volume_down,
mute, play_pause, menu, settings`. Resposta 200: `{"ok":true,"channel":"remote"}` (o app lê só `channel`;
no TCL é `"remote"` ou `"adb"`; no Samsung é `"remote"`, ou `"wol"` no `power` que liga a TV pela rede (Wake-on-LAN)).
Erros: `unknown_key` (404), `not_paired` (409), `adb_unauthorized` (409), `tv_unreachable` (503), `tv_not_found` (503).

### POST /app
Corpo: `{"link":"<url>"}` (ex.: `https://www.youtube.com`). Timeout: 30 s. Resposta 200: `{"ok":true}`.
Erros: `not_paired` (409), `tv_unreachable` (503), `tv_not_found` (503), `invalid_request` (422).

### GET /inputs
Timeout: 10 s. Resposta 200: lista (vazia se a TV ainda é desconhecida). Exemplo real (TCL):
```json
[{"port":1,"id":"com.tcl.tvinput/.passthroughinput.TvPassThroughService/HW1413744128","label":"HDMI 1","connected":false,"active":false},{"port":2,"id":"com.tcl.tvinput/.passthroughinput.TvPassThroughService/HW1413744384","label":"HDMI 2","connected":true,"active":false},{"port":3,"id":"com.tcl.tvinput/.passthroughinput.TvPassThroughService/HW1413744640","label":"HDMI 3","connected":false,"active":false},{"port":4,"id":"com.tcl.tvinput/.passthroughinput.TvPassThroughService/HDMI100004","label":"HDMI 4","connected":false,"active":true}]
```
Item: `port` int, `id` string, `label` string, `connected` bool, `active` bool. Poll somente leitura: não faz
redescoberta. Erros: `tv_unreachable` (503), `adb_unauthorized` (409), `not_supported` (501, Samsung sem SmartThings).

### POST /input/{port}
`port` inteiro na URL (número da porta HDMI); não inteiro → `invalid_request` (422). Sem corpo. Timeout: 10 s.
Resposta 200: `{"ok":true,"active_port":3}` (o app ignora o corpo). A troca é confirmada antes de responder.
Erros: `invalid_value` (400, porta inexistente), `input_not_confirmed` (502), `tv_unreachable` (503),
`adb_unauthorized` (409), `not_supported` (501).

### GET /picture[?cached=1]
Timeout: 20 s. Com `?cached=1` devolve a última leitura sem tocar na TV (`no_cache` 404 se não houver). Resposta 200:
```json
{"mode":"Padrão","mode_id":"EN_TCL_HDR10_STANDARD","modes":[{"id":"EN_TCL_HDR10_BRIGHT","label":"Dinâmico"},{"id":"EN_TCL_HDR10_STANDARD","label":"Padrão"},{"id":"EN_TCL_HDR10_ECO","label":"Esporte"},{"id":"EN_TCL_HDR10_SOFT","label":"Filme"},{"id":"EN_TCL_HDR10_GAME","label":"Jogo"},{"id":"EN_TCL_HDR10_PC","label":"PC"}],"backlight":100,"cached_at":"2026-10-17T16:49:52.687681+00:00"}
```
Tipos: `mode` string (rótulo), `mode_id` string, `modes` lista de `{id:string,label:string}`, `backlight` **int**
(não nulo), `cached_at` string ISO-8601 (todos obrigatórios para o app).
Erros: `no_cache` (404), `picture_unreadable` (502), `tv_unreachable` (503), `adb_unauthorized` (409), `not_supported` (501).

### POST /picture/mode
Corpo: `{"mode":"<rótulo>"}` (casamento case-insensitive contra `modes[].label`). Timeout: 20 s.
Resposta 200: `{"ok":true,"mode":"Jogo","mode_id":"EN_TCL_HDR10_GAME"}` (o app lê só `mode`).
Erros: `unknown_mode` (400), `picture_unreadable` (502, inclusive "a TV não confirmou"), `tv_unreachable` (503),
`not_supported` (501), `invalid_request` (422).

### POST /picture/backlight
Corpo: `{"value":<int 0..100>}`. Timeout: 20 s. Resposta 200: `{"ok":true,"backlight":60}` (o app lê só `backlight`).
Erros: `invalid_value` (400, fora de 0–100), `picture_unreadable` (502), `tv_unreachable` (503),
`not_supported` (501), `invalid_request` (422, não inteiro).

## 4. Tabela de erros

| Código | HTTP | Significado / texto no app |
|---|---|---|
| `not_paired` | 409 | "Pareamento necessário" |
| `adb_unauthorized` | 409 | "Aceite o pedido de depuração na TV" |
| `tv_unreachable` | 503 | "TV inacessível" |
| `tv_not_found` | 503 | usa `message` do sidecar |
| `not_supported` | 501 | usa `message` do sidecar |
| `unknown_key` | 404 | usa `message` |
| `invalid_pin` | 400 | "PIN incorreto — tente de novo ou peça um novo PIN" |
| `unknown_mode` | 400 | "Modo indisponível nesta entrada" |
| `invalid_value` | 400 | usa `message` |
| `input_not_confirmed` | 502 | "A TV não confirmou a troca de entrada" |
| `no_cache` | 404 | usa `message` |
| `picture_unreadable` | 502 | `message` do sidecar (ou "Não foi possível ler a imagem da TV" se vazia) |
| `forbidden` | 403 | Host/Origin não permitido (`"Origem não permitida"`) |
| `invalid_request` | 422 | `"Requisição inválida: <campo>: <detalhe>; ..."` (validação do corpo/parâmetros) |
| `internal` | 500 | `"Erro interno no sidecar"` (exceção não tratada; detalhe só no log) |

Erros do cliente (sem resposta HTTP): `notRunning` ("Sidecar não está respondendo"), `timeout`
("A TV demorou para responder"), `invalidResponse` ("Erro inesperado").

## 5. Comportamento relevante para o app

- O app faz poll de `/state` e `/inputs` enquanto o menu está aberto; `/picture?cached=1` mostra o último modo.
- Trocar de entrada invalida o cache de imagem (`/picture?cached=1` passa a dar `no_cache` até nova leitura).
- Com a TV em espera, `/state` responde 200 com `power:"standby"` (nunca erro).
- Ligar a partir da espera (decisão R8): no v1 o app desabilita os controles em "Em espera" e não envia
  `POST /key/power` (o texto "ligue pelo controle físico" é herdado do app TCL). O sidecar liga pela rede
  (Wake-on-LAN, `channel:"wol"`) quando recebe `power` com a TV em espera, ex.: `uv run samsung key power`.
  A operação de energia tem prazo total de ~20 s e pedidos simultâneos são atendidos um por vez.
- Redescoberta: no máximo uma por comando quando há `tv_unreachable`, exceto em `/inputs` (somente leitura).
