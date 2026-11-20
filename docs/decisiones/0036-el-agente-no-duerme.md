# 0036 · El agente no duerme: la espera es del motor, el fin del verbo es el trigger

- **Fecha:** 20-nov-2026
- **Estado:** aceptada
- **Contexto:** el agente que orquesta el repo (Hermes, y también Codex, Claude Code
  o Cursor) lanzaba el ciclo de un lab y, como el ciclo tarda más que el tope de la
  herramienta que lo lanza (420 s), se inventaba la espera por fuera:
  `sleep 400; grep -c "PLAY RECAP" /tmp/ciclo04r.log`. En una sola sesión fueron
  cuatro ciclos seguidos con `sleep 360–420` entre medias: unos 25 minutos de reloj
  en pausas ciegas. El motor, en cambio, no tiene ni un `sleep` de cientos de
  segundos: su espera máxima es `sleep 15`, y el resto son bucles de sondeo de 1–4 s
  con tope (`esperar_tarea.yml`, `esperar_paso.yml`, `sonda.yml`). El problema no
  estaba en Ansible: estaba en la capa que lo llamaba.

## La decisión

1. **La capa del agente no espera a ciegas.** Se prohíbe `sleep N` como forma de
   aguardar un verbo, y en particular `sleep N; grep …`: una duración fija no es una
   espera, es una apuesta (o duerme de más, o mira antes de que el verbo acabe).
   Un `sleep` ciego mayor de 30 s en la capa del agente es un bug.
2. **Un verbo largo se ejecuta de una de estas dos formas, y sólo estas dos:**
   - **síncrona**, si cabe en el tope de la herramienta (el tope por defecto es
     420 s y el ciclo completo de un lab suele pasar de ahí, así que no es la forma
     por defecto);
   - **en background con aviso de fin**, y el aviso es el trigger del paso
     siguiente. En Hermes: `terminal(background=true, notify=["=== CICLO FIN"])`.
   El ciclo de desarrollo entero se lanza con una herramienta del repo,
   `scripts/ciclo.py`, que corre `plan → destroy → apply`, deja su diario y su estado
   y termina con esa marca: así el aviso que dispara el paso siguiente es un literal
   estable y no una frase de Ansible que puede cambiar.
3. **Toda espera con condición vive en el motor**, no en el agente. El motor ya
   bloquea hasta que el verbo termina y deja su diario; si hace falta esperar un
   evento intermedio, se hace con un bucle de sondeo **con condición y tope**
   (`esperar_tarea.yml` es el patrón), nunca con una duración ad hoc.
4. **Si de verdad hay que bloquear en el shell, el patrón es el sondeo acotado:**
   `timeout 900 bash -c 'until <condición>; do sleep 5; done'`. La condición manda
   y el tiempo es la red de seguridad; sale en cuanto el evento ocurre. En este repo
   ese patrón está empaquetado y probado: `scripts/esperar.py --lab <lab>` (o
   `--fichero/--patron`, o `--pid`) sondea cada 2 s, sale en el instante en que la
   condición se cumple y agotar el tope es un fallo, no un verde.
5. **Los `sleep` cortos del motor se quedan.** El arranque de un CHR, la espera de
   un puerto o el intervalo de un sondeo son espera real y acotada; la regla habla
   de la capa del agente, no del motor.

## Por qué así

- **El fallo era de primitiva, no de disciplina.** El agente recurrió al `sleep`
  porque el ciclo superaba el tope de `terminal` y no tenía otra forma de «esperar».
  Una regla sin primitiva se incumple sola: por eso la decisión no prohíbe y ya
  está, sino que fija la forma sancionada (background + aviso) que hace innecesaria
  la espera.
- **Frente a subir sólo el tope** (`timeouts.tools.sequential_call`): se puede
  subir para un repo concreto, pero deja el turno bloqueado 10–12 minutos y no
  resuelve el caso de varios ciclos. El aviso de fin es mejor: el agente no ocupa
  el turno y reacciona al evento.
- **Frente a esperar con `sleep` pequeño en bucle desde el agente**: se descarta
  porque duplica en la capa de fuera lo que el motor ya hace dentro, y el agente
  acabaría teniendo su propia política de reintentos. La espera es del motor; al
  agente le basta con lanzar, esperar la salida o recibir el aviso.

## Límites, dichos

- **La regla no arregla el verbo que falla.** El ciclo del lab 04 no falla por el
  `sleep`: falla porque `control` no converge en `preparar_terminal`. Esto sólo
  quita los minutos muertos y los timeouts de 420 s.
- **El aviso de fin depende del orquestador.** Hermes lo tiene (`notify`); otro
  agente puede no tenerlo. En ese caso, la forma sancionada es el sondeo acotado
  del punto 4, no el `sleep` fijo.
- **No se toca ningún playbook por esta decisión.** El motor ya cumple; el cambio
  es de contrato (AGENTS.md) y de forma de lanzar.
