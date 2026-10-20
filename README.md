# Samsung Controller

Controle da Samsung The Frame 32" (QN32LS03CBGXZD, Tizen) pela barra de menus do Mac.

- `app/`: app SwiftUI (cópia do app TCL, só com mudanças de configuração; ver [`app/README.md`](app/README.md)).
- `sidecar/`: serviço Python (porta 8766), implementado (v1); instalação, primeiro uso e limitações em
  [`sidecar/README.md`](sidecar/README.md).
- [`docs/CONTRATO-API.md`](docs/CONTRATO-API.md): contrato HTTP entre app e sidecar.
- `docs/superpowers/specs/`: design.
