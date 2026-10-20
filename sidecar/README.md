# Sidecar Samsung

Serviço local (FastAPI, `127.0.0.1:8766`) que controla uma TV Samsung (testado para a The Frame) e expõe o
contrato descrito em [`docs/CONTRATO-API.md`](../docs/CONTRATO-API.md) para o app macOS.

Canais: local (REST `:8001` + WebSocket `:8002`) para teclas e apps, SmartThings (nuvem) para entrada HDMI,
modo de imagem, brilho e volume, e Wake-on-LAN para ligar.

## Instalar

```sh
cd sidecar
uv sync
```

Requer Python 3.12+ e [uv](https://docs.astral.sh/uv/).

## Rodar

```sh
uv run samsung-sidecar
```

Dados em `~/Library/Application Support/Samsung-controller/` (ou `$SAMSUNG_CONTROLLER_HOME`): `config.json`
(permissão 0600) guarda IP, MAC, token do WebSocket e credenciais SmartThings.

## Primeiro uso

1. TV ligada na mesma rede. O sidecar a descobre sozinho (SSDP) na primeira chamada.
2. Pareamento: `uv run samsung pair` e **aceite "Permitir"** na tela da TV (você tem ~30 s). O token fica salvo.
3. SmartThings (entrada, imagem, volume): crie um Personal Access Token em
   <https://account.smartthings.com/tokens> com permissão de dispositivos e rode
   `uv run samsung smartthings <token>`. O comando lista seus dispositivos, escolhe o que tiver "Frame" ou "TV"
   no nome (pergunta o índice se houver vários) e grava `st_token`/`st_device_id` direto no config. O token não é impresso.

## CLI de teste

Fala com o sidecar em execução (`SAMSUNG_SIDECAR_URL` muda a URL):

```sh
uv run samsung health | state | pair | inputs | picture
uv run samsung key <nome>        # power, home, back, up, down, left, right, ok, volume_up, ...
uv run samsung app <link>        # ex.: https://www.youtube.com
uv run samsung input <porta>     # porta HDMI
uv run samsung mode <rótulo>     # ex.: Filme
uv run samsung smartthings <token>
```

## Testes

```sh
uv run pytest -q -W error
```

Sem rede real: canais falsos, `MockTransport` e `TestClient`. `tests/test_contract.py` compara chaves e tipos de
cada resposta com os fixtures do app em `tests/fixtures/contract/`.

## Limitações e riscos

- Sem o SmartThings configurado, `/inputs`, `/input`, `/picture*` respondem `not_supported` (501) e o app só tem teclas/apps.
- `power` com a TV ligada segura `KEY_POWER` por 3 s (toque curto na Frame entra no Modo Arte). Ligar usa
  Wake-on-LAN e exige o MAC salvo; em Wi-Fi a TV em espera profunda pode não acordar.
- O estado "entrada ativa" vem da nuvem SmartThings: depende de internet e tem latência; `connected` das entradas é sempre `false`.
- `/pair/finish` aceita qualquer PIN (a Samsung não usa PIN).
- O token SmartThings fica em texto no `config.json` (0600); revogue-o no portal se o Mac for comprometido.
- A API só aceita `Host` `127.0.0.1:8766`/`localhost:8766` e rejeita qualquer `Origin` (proteção CSRF/DNS rebinding); não exponha a porta.
- A dependência `samsungtvws` está fixada em 3.0.x porque o canal local copia internos da biblioteca.
