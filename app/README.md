# Samsung Controller (app de barra de menu)

App nativo para macOS 26+ (Liquid Glass) que controla a TV Samsung pela barra de menu, conversando com o
sidecar Python (`../sidecar`) em `http://127.0.0.1:8766`. Se o sidecar não estiver
rodando, o app o inicia com `uv run tcl-sidecar` e o encerra ao sair (só quando foi ele
quem iniciou).

## Requisitos

- macOS 26 ou mais recente (a interface usa Liquid Glass; o app não abre em versões anteriores)
- Xcode 26+ instalado (o toolchain é usado via `DEVELOPER_DIR`, sem `xcode-select`)
- [`uv`](https://docs.astral.sh/uv/) (`brew install uv`) e o sidecar já pareado com a TV

## Compilar e testar

```sh
cd app
export DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer
swift build
swift test
```

## Gerar e abrir o .app

```sh
./scripts/bundle.sh                 # funciona de qualquer pasta
open "build/Samsung Controller.app"
```

O bundle é assinado ad hoc e não aparece no Dock (`LSUIElement`).

## Uso

- Clique no ícone da TV na barra de menu. O menu segue o estilo da Central de Controle:
  cabeçalho `TV · ● <estado> · <entrada ativa>`, módulos de vidro **Controles** (power,
  início, voltar), **Entrada**, **Imagem** e **Apps** (atalhos), barra de **volume**
  (−, +, sem som) e rodapé com Ajustes e Sair.
- **Entrada**: mostra a entrada ativa com o nome amigável (ex.: HDMI 1) ou "Apps" quando a
  TV está num app. Clique para expandir a lista das portas HDMI visíveis (ponto verde =
  aparelho conectado) e clique numa porta para trocar.
- **Imagem**: mostra o último modo conhecido. Ao expandir, lê o modo e o brilho da TV
  ("Lendo da TV…" — a TV abre e fecha o próprio menu de imagem); os modos aparecem como
  botões (o atual destacado) e o brilho (0–100) é enviado ao soltar o controle deslizante.
- Só um módulo fica expandido por vez.
- Com o menu aberto: setas = D-pad, Enter = OK, Esc = recolhe o módulo expandido ou, se
  nenhum estiver aberto, voltar.
- **Ligar**: no v1 o app não liga a TV a partir da espera (em "Em espera" os controles ficam
  desabilitados). Ligue pelo controle físico ou pela rede com `uv run samsung key power` (Wake-on-LAN),
  na pasta do sidecar.
- **Ajustes**: pareamento (a Samsung não usa PIN: aceite "Permitir" na TV e digite quaisquer 6
  letras ou números no campo de PIN ou apenas feche os Ajustes), **Entradas** (nome, símbolo e "Ocultar" de cada porta;
  padrão "HDMI N" com símbolo de cabo, nenhuma oculta), atalhos (adicionar/remover/reordenar) e
  pasta do sidecar (padrão `~/Documents/Projetos/Samsung-controller/sidecar`).
- Log do sidecar: `~/Library/Logs/Samsung-controller/sidecar.log` (botão **Abrir log**).

## Origem e diferenças em relação ao TCL

Cópia de `TCL-controller/app` (main @ 8e41e85) sem mudança de lógica. Os nomes dos módulos Swift
(`TCLCore`, `TCLController`, `TCLControllerApp`) foram **mantidos de propósito**: renomeá-los seria
uma mudança de código além da configuração. Só mudaram estes valores:

- `scripts/bundle.sh`: nome "Samsung Controller" (`CFBundleName`), `.app` "Samsung Controller.app",
  `CFBundleIdentifier` `local.samsung-controller` (o executável continua `TCLController`).
- `Sources/TCLCore/SidecarClient.swift`: URL base padrão `http://127.0.0.1:8766` (antes 8765).
- `Sources/TCLCore/SidecarProcess.swift`: log em `~/Library/Logs/Samsung-controller/sidecar.log`.
- `Sources/TCLController/TCLControllerApp.swift`: pasta padrão do sidecar `~/Documents/Projetos/Samsung-controller/sidecar`.
- `Sources/TCLCore/InputNames.swift`: padrão de todas as portas = "HDMI N", `cable.connector`, visível (antes PS5/ARC oculta).
- `Tests/TCLCoreTests/InputNamesTests.swift`: valores esperados ajustados.
- Este README (textos de marca, porta e caminhos).

Permanece (lógica, não configuração): a comparação com o pacote Android `com.tcl.tv` em
`TVStore.swift`/`MenuView.swift`, que o app usa como sentinela de "a TV está numa entrada" (decisão R4:
o sidecar Samsung devolve `app = "com.tcl.tv"` quando o SmartThings informa uma entrada HDMI ativa, e
`null` nos demais casos), e o comando `uv run tcl-sidecar` (o sidecar Samsung expõe também o script
`tcl-sidecar`). Também é herdado o texto "ligue pelo controle físico" do estado "Em espera".

O histórico de validação abaixo é da TV TCL e fica apenas como referência.

## Validação (2026-10-16, TV real)

| Item | Resultado |
|---|---|
| Ícone na barra, cabeçalho "TV 192.168.2.133" | ✅ |
| TV em standby → "Em espera", controles desabilitados | ✅ |
| TV ligada pelo controle físico → "● Ligada · <app>" | ✅ |
| Home, Voltar, Volume −/+ | ✅ (volume controla a soundbar via HDMI-CEC/ARC) |
| Setas / Enter / Esc como D-pad, repetição controlada | ✅ |
| Atalho YouTube | ✅ |
| Power desliga a TV, menu volta a "Em espera" | ✅ |
| Sair com sidecar externo → sidecar continua rodando | ✅ |
| Sem sidecar → app sobe o próprio em ~10 s (log em ~/Library/Logs/TCL-controller/) | ✅ |
| Sair com sidecar do app → `uv` e Python encerrados, porta 8765 livre | ✅ |
| Ajustes › Atalhos (adicionar/validar link) | ⏳ a validar depois |
| Pareamento por PIN na UI (incl. PIN incorreto) | ⏳ a validar depois |
| Fase 'não pareado' | ⏳ a validar depois |
| Sidecar parado + Tentar de novo | ⏳ a validar depois |
| Faixa de aviso do ADB | ⏳ a validar depois |

## Validação Fase 4 (2026-10-18, TV real)

| Item | Resultado |
|---|---|
| Painel em Liquid Glass (Controles, Entrada, Imagem, Apps, volume) e cabeçalho com "🎮 PS5" | ✅ |
| Entrada: expandir com animação, HDMI 3 ↔ PS5, TV acompanha | ✅ |
| Imagem: "Lendo da TV…", modos listados, menu da TV abre e fecha sozinho, Padrão → Jogo → Padrão | ✅ |
| Brilho: 100 → 60 → 100, um envio por soltura | ✅ |
| Esc recolhe o bloco expandido | ✅ |
| Ajustes › Entradas: renomear HDMI 3 e ver no bloco Entrada | ✅ |
