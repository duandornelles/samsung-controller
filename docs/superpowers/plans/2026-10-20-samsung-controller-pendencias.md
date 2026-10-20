# Samsung Controller v1 — pendências adiadas (revisões)

Itens menores aceitos para depois e itens a validar na TV (Task 7). Origem: plano `2026-10-20-samsung-controller.md`.

- Task 1: minor (deferred): contract /state lacks com.tcl.tv sentinel note (→ Task 6 per R4); /pair/start adb_unauthorized TCL-unreachable; ?cached bool parsing; §5 polling claim unchecked; README keeps TCL validation history
- Task 2: minor (deferred): load_config no type check on values; pyproject description placeholder; app links with paths fall to browser (by spec); WOL rejects bare 12-hex MAC
- Task 3: minor (deferred): stale token → TVUnreachable instead of AdbUnauthorized (validate on TV); pairing_pending up to 4 s when TV off; incoming WS messages never drained (keepalive drop → reconnect); DEEP_LINK app launch unverified; aiohttp not declared; on_token before _remote assignment; _send_locked retries on any Exception
- Task 4: minor (deferred): __context__ still holds httpx exc with Authorization header (suppressed in tracebacks); new AsyncClient per call + extra GET /status before commands; resp.json ValueError uncaught; setter name guessed; list_devices duplicates kwargs; sentinel typing; missing tests 404/422/non-JSON/timeout/403
- Task 3: minor (deferred): conn.close() in open() except not shielded; second cancel during hold shield; import ordering
- Task 5: minor (deferred): adb true before first ST call; WOL with unknown MAC triggers rediscovery but no WOL retry; wifiMac won't wake Ethernet-connected Frame (validate); _st_call marks ST down on any NotSupported except brightness
- Task 6: minor (deferred): error codes injected only on /inputs; lifespan warmup not asserted; CLI catches only ConnectError and not EOFError; dead monkeypatch in test_pair and /pair/finish body unasserted; unused shape() helper
- Task 6: minor (deferred): /picture schema requires non-empty modes (stricter than Swift); unused imports in test_service.py
- Final: parked — start_pairing/_run rediscovery passes an invalid saved MAC to find_tv → TVNotFound (fix: pass None when !valid_mac) — Ruling: real but only reachable with a hand-edited/pre-fix config (sidecar no longer saves invalid MACs); no second fix wave allowed; surfaced to user
- Final: parked — valid_mac/magic_packet TypeError on non-string MAC (hand-edited config) → 500 — Ruling: same edge case; deferred
- Final: parked — microsecond write races in _persist vs CLI — Ruling: negligible; deferred
- Final: parked — queued second power press can take ~40 s (deadline starts after lock) — Ruling: acceptable (R10); app shows timeout but action completes
