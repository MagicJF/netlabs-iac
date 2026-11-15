# ADR 0004 — El camino: el motor entra por un puesto de control que él mismo saca de casa

<!-- PROPÓSITO: dejar escritas las dos decisiones que hacen posible configurar el
     interior de los invitados sin romper la regla 1: (a) CÓMO entra el motor -- un
     puesto de control por lab que abre un túnel SSH inverso hacia el nodo de
     control -- y (b) CON QUÉ -- un token de la API con cinco roles, uno por ruta,
     que no puede darse un privilegio más.
     INVARIANTES: el hipervisor se sigue tocando SÓLO por su API (regla 1); el
     motor no se concede privilegios (regla 16); nada derivado se guarda (regla 11:
     el puerto sale del vmid, la clave sale del nombre del lab).
     LÍMITES: el camino es el ÚNICO camino, y no es invisible: quien lea el diario
     ve cada llamada y cada intento. Lo que aquí no está probado se dice abajo.
     VER: deployment_engine/tasks/camino.yml, camino_consola.yml,
     guardia_privilegios.yml, guardia_privilegios_rol.yml,
     deployment_engine/vars/engine.yml (`engine_privilegios_por_rol`),
     deployment_engine/tools/consola.py, docs/camino-del-puesto-de-control.md -->

**Estado:** aceptada (la parte del token está implementada y probada; los ejecutores
del interior -- RouterOS y Linux -- están en construcción: ver LÍMITES).

**Contexto.** La fase 1 despliega topologías y no entra en ellas. La fase 2 tiene que
entrar, y **hoy no hay por dónde** -- medido, no supuesto:

- Desde el nodo de control **no se alcanza ninguna red interna** del hipervisor: las
  redes del lab viven en bridges del nodo, y el nodo no enruta hacia ellas.
- **La API de Proxmox no sabe ejecutar nada dentro de un invitado.** No hay endpoint
  que corra un comando.
- Lo único que la API sí da es la **consola** de un invitado (`termproxy` +
  `vncwebsocket`): una shell, pero a mano y sin estructura.
- Y el motor no puede entrar por SSH **al hipervisor**: eso lo prohíbe la regla 1, sin
  excepciones para el motor (el SSH al nodo es para diagnosticar, y a mano).

Hacía falta un camino que el motor construya solo, sin pasos manuales y sin tocar el
hipervisor.

**Decisión (a): un puesto de control por lab, y un túnel inverso hacia el nodo de
control.** El lab declara un invitado más -- un contenedor `camino` -- con una pata en
**cada bridge del lab** (primero) y una pata en el bridge de **gestión** (la última,
la que sale hacia fuera). Ese contenedor es el que sí ve las redes del lab por dentro.
Al arrancarlo, el motor le inyecta por **consola** un guion que abre
`ssh -R <puerto>:127.0.0.1:22` contra el nodo de control; a partir de ahí, el nodo de
control tiene un puerto propio que aterriza **dentro** de la red del lab, y desde ese
puesto se llega a cada invitado. El puerto **se deriva** del vmid del puesto
(`20000 + vmid`), así que no hay que guardar ninguna asignación (regla 11). El MISMO túnel
lleva también el **REST de cada RouterOS** (a `21000 + vmid`), para que las llamadas las haga
el motor en su propia máquina y el puesto sólo haga de camino (ADR 0010).

Tres cosas que se aprendieron midiendo, y que están en el código:

1. **La consola traga las primeras pulsaciones.** Justo tras arrancar el contenedor, la
   sesión no entrega shell interactiva, así que el guion se inyecta con **reintentos**
   (3 intentos, 12 s de espera) y cada intento se diariza en `labs/<lab>/logs/camino.jsonl`.
   Sin esto, la inyección falla de vez en cuando -- y un fallo de vez en cuando es peor
   que uno fijo.
2. **Una clave SSH por lab, no una compartida.** OpenSSH, en `authorized_keys`, se
   queda con la **primera** clave que casa y **ignora las líneas siguientes**: con una
   clave compartida y un `permitlisten` por lab, el segundo lab recibía
   `Remote: port forwarding refused`. La clave se deriva del nombre del lab
   (`netlabs_camino_<lab>_ed25519`), y sus líneas llevan la marca
   `# netlabs_v4_b-camino-<lab>`, de modo que la purga toca **sólo** lo suyo: se borró
   una clave que no era del motor, y esa es la razón de la marca (nunca más purgar
   "por patrón": se purga por marca).
3. **La espera del puerto, no del proceso.** El motor no da por hecho el camino porque
   el contenedor esté arrancado: espera a que el puerto **conteste** en el nodo de
   control. Medido: contesta.

**Decisión (b): cinco roles, uno por ruta, y una guarda que lo prueba.** El token del
motor tenía **un** rol concedido en cinco rutas (`/vms`, `/pool`, `/nodes/<nodo>`,
`/storage`, `/sdn`), y eso da la **unión** de todo en todas partes. Medido en el nodo:
el rol de `/vms` llevaba además `Sys.Modify` y `Datastore.AllocateSpace`, que no
pintan nada ahí. Ahora hay **un rol por ruta** con lo que el motor exige en esa ruta
(`engine_privilegios_por_rol`), y **nunca en `/`**, que propaga y da a todas partes lo
de una. `VM.Console` vive en el rol de `/vms` porque es la puerta del camino: sin él,
el motor no puede poner en marcha el puesto de control; con él, root en un invitado
Linux es root **dentro de ese invitado**, y por eso todo invitado nace `unprivileged`
(lo vigila el check `privilegios`).

**Por qué la guarda es una llamada y no una intención.** *Un mínimo privilegio que no
se prueba es una intención.* `preflight` hace dos cosas, y las dos son necesarias:

1. **Lee** los roles del nodo (una sola llamada, `GET /access/roles`) y los compara
   con lo exigido **rol a rol** -- no contra la unión, que es justo el defecto que se
   colaba -- diciendo **cuál** sobra, **cuál** falta y **cuál** no existe.
   Medido: esa lectura responde 200 con el token mínimo, así que la mitad lógica no
   obliga a ampliar ninguna ACL.
2. **La operación nula, sobre cada rol**: `PUT /access/roles/<el suyo>` con la **misma**
   lista de privilegios que ya tiene. No cambia nada si se permite; por eso prueba
   exactamente lo que hay que probar: **si eso respondiera 200, la llamada siguiente
   -- con otra lista -- le daría `VM.Console`, `Sys.Console` o `Permissions.Modify`.**

**Probado en los dos sentidos** (no se da por bueno lo que no se ha visto fallar):
concediendo a propósito `Sys.Modify` sobre `/access` al token, `preflight` **para**
nombrando el rol y diciendo que respondió 200 en vez de 403; retirado el privilegio,
vuelve a verde. La mitad mecánica está en `check privilegios`, que además **se ha
visto gritar**: metiendo un `include_tasks: guardia_privilegios.yml` en `apply.yml`,
el check falla y nombra el fichero.

**Consecuencia.** El motor tiene ahora dos puertas y las dos se vigilan: la API de
Proxmox (sólo por `tasks/pve_api.yml`, con su diario) y el camino (consola una vez por
puesto, y SSH **a los invitados**, nunca al hipervisor). La regla 1 se mantiene donde
importa: **lo que la API sabe hacer, por API**; el camino es el que salva lo que la
API no sabe hacer -- y sólo eso.

**LÍMITES (lo que todavía NO está probado, dicho sin maquillar).**

- El camino está probado **de punta a punta hasta el puerto**: el puesto de control se
  crea, arranca, inyecta su guion y el puerto contesta en el nodo de control.
- **El interior de los invitados todavía no se configura**: falta el ejecutor de
  RouterOS (`ros_api.yml`, la puerta a la API REST del CHR, con su propio diario) y el
  de Linux (`interior_ssh.yml` + `configurar_linux.yml`). El plan ya los nombra y
  `apply` **para** en ese paso diciendo que falta el driver: un plan que promete lo
  que no puede hacer es peor que un plan corto.
- El camino **depende de que el invitado tenga un sistema que arranque**: un RouterOS
  CHR recién creado tiene una configuración de fábrica que hay que poner por consola
  **antes** de que haya IP y SSH. Eso está previsto (imagen de fábrica al crear) y
  **no está hecho**.
- El camino usa `VM.Console`, y por tanto la consola del hipervisor: quien tenga el
  log del nodo puede ver lo que pasa por ella. Se acepta porque la alternativa es no
  entrar, y se acota a lo mínimo (un solo uso, por puesto).
