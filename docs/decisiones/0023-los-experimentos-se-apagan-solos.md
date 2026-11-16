# 0023 — Los experimentos se encienden con su verbo y se apagan solos

*Fecha: 16-nov-2026 — Estado: aceptada y aplicada — Ámbito: CÓMO se mira y se estropea el tráfico
de un lab desde el bastión (`capture:` e `impairment:`)*

## El problema

containerlab da `capture` (mirar el tráfico de un enlace) y `netem` (estropearlo). En Proxmox,
tocar `tc` en el **nodo** violaría el ADR 0001 (sólo API al hipervisor), así que la única
herramienta del motor es el **bastión**, que ya está dentro del lab. Faltaba la primitiva.

## La decisión

**1. Son EXPERIMENTOS, no estado del mundo.** Un lab no «es» capturado: se captura un rato. Por
eso no van en la convergencia: tienen **bloque propio** en la declaración (`capture:`,
`impairment:`) y **verbo propio** (`./lab capture`, `./lab impair`). `apply` no los toca.

**2. Se miden DONDE EL BASTIÓN PISA.** El bastión no lleva una pata en cada bridge del lab: su
dotación es su bridge de gestión **más los que declara en `bridges:`**. Declarar una captura en
un bridge donde no tiene pata se puede (es texto), pero no se puede montar: el motor lo rechaza
al montarlo y **el validador también lo caza al LEER la declaración** (`interfaz_del_bastion`).
Medir DENTRO de una zona pide darle antes al bastión una pata ahí: es una decisión de topología.

**3. El impairment es ACOTADO por diseño**: se aplica, se espera lo declarado y **se retira en el
mismo comando**. Un `netem` huérfano es peor que un lab sin impairment, así que no puede quedar
uno sin dueño ni aunque el motor falle en medio.

**4. Vocabulario cerrado y corto**: `capture: {bridge, filtro, segundos}` (un `tcpdump` con su
filtro) e `impairment: {bridge, retardo, perdida, jitter, segundos}` (traducido a `netem`).

## La trampa: el impairment NO hace lo que parece

El ADR da por hecho que bastaría con «una pata en el bridge» para estropear el tráfico que lo
cruza. **Y no basta**: en un bridge de Linux cada invitado tiene su propia interfaz, y `netem` se
pone en la del bastión, así que **estropea el tráfico del bastión** — el suyo — y no el de dos
invitados que hablen entre ellos. No es el `netem` de containerlab: es «y si el LAB se comunicara
mal». Para estropear el tráfico de otros habría que tocar `tc` en el nodo, que es exactamente lo
que prohíbe el ADR 0001.

La parte que sí vale de los dos: son acotados, así que un experimento no deja el lab roto, y
`capture` funciona de verdad (el `tcpdump` pone la interfaz en **modo promiscuo** y el bridge le
entrega también el tráfico que no va dirigido a él).

## Qué NO se toca

- **El nodo**: ni una operación de `tc` fuera del invitado (ADR 0001).
- **La convergencia**: `apply` no captura ni estropea nada. Si el lab no declara estos bloques, no
  existen.
- **Los diarios** (ADR 0014): la captura va a la evidencia del verbo, no al diario del interior.

## Cómo se comprueba

- **`test/test_interior.py`**: la traducción a `netem`, que el impairment lleve el `del` **y** el
  `sleep` en el mismo comando (acotado), y que `captura_de` diga que no hay bastión en vez de
  devolver un comando a medias.
- **`test/test_declaracion.py`**: un `bridge` que no es del lab, y otro que es del lab pero donde
  el bastión **no tiene pata** (los dos, con su motivo).
- **El ciclo real** (informe §6.4): `./lab capture` rc=0 en el 08 y `./lab impair` rc=0 en el 06,
  sin dejar nada puesto; y la captura mal declarada, rechazada por el motor con el motivo exacto.

## VER

- [deployment_engine/filter_plugins/interior.py](../../deployment_engine/filter_plugins/interior.py)
  (`captura_de`, `impairment_de`, `interfaz_del_bastion`)
- [deployment_engine/playbooks/capture.yml](../../deployment_engine/playbooks/capture.yml) y
  [impair.yml](../../deployment_engine/playbooks/impair.yml)
- [docs/decisiones/0001-solo-api-de-proxmox.md](0001-solo-api-de-proxmox.md) (por qué no se toca
  el nodo)
- [docs/informe-estado-del-arte-2026-11.md](../informe-estado-del-arte-2026-11.md) (§6.4, medido)
