# netlabs-iac — esquema y reglas del repositorio

Motor IaC en Ansible que despliega topologías (VMs y contenedores LXC) en un nodo
Proxmox **sólo por su API REST**, asigna por sí mismo la identidad de cada
invitado, **configura su interior** (RouterOS por su REST, Linux por SSH, cada uno
por su pasarela) y lo documenta. Este fichero se inyecta en el system prompt cuando
trabajas dentro del repo. Las **reglas** están aquí; los **procedimientos largos**
están en la skill `netlabs-v4_b` (`skill_view`).

*`AGENTS.md` lo leen Hermes, Codex, Claude Code y Cursor. Si el repo se usara sólo
con Hermes, `.hermes.md` sería equivalente — **nunca los dos** (Hermes carga
`.hermes.md` primero y `AGENTS.md` queda shadowed). Un `CLAUDE.md` sería una
tercera copia: no se crea.*

## Mapa: dónde vive cada cosa

| Ruta | Qué es | Quién lo escribe |
| --- | --- | --- |
| `README.md` | el motor: verbos, arquitectura, identidad, checks. **Ningún valor de ningún lab** | a mano |
| `AGENTS.md` | este fichero: esquema y reglas | a mano |
| `VERSION` | la última versión **publicada** (una línea: `0.1.0`) | a mano, al publicar (ADR 0017) |
| `CHANGELOG.md` | qué entró en cada versión, para leer | a mano, al publicar |
| `deployment_engine/tasks/pve_api.yml` | **la vía de acceso a Proxmox** (`/api2/json`) + `api.jsonl` | a mano |
| `deployment_engine/tasks/ros_api.yml` | **la vía de acceso a RouterOS** (`/rest/…`) + `api.jsonl` | a mano |
| `deployment_engine/tasks/interior_ssh.yml` | **la vía de acceso al interior Linux** (SSH) + `interior.jsonl` | a mano |
| `deployment_engine/tasks/console.yml` | **la vía de consola** (el único protocolo no-REST) + `console.jsonl` | a mano |
| `deployment_engine/` | todo lo demás compartido por todos los despliegues | a mano |
| `labs/<lab>/<lab>.yml` | el estado deseado de ESA topología (fuente de verdad) | a mano |
| `labs/<lab>/<lab>.md` | la topología explicada: región generada + región de prosa | **dos escritores** |
| `labs/<lab>/logs/` | `api.jsonl`, `interior.jsonl`, `console.jsonl` (los diarios), el **`resumen.md`** que se lee, `ultimo-verify.txt` (el veredicto), `plan.txt` y el último `verify-<sello>.json` (gitignored) | el motor, nunca a mano |
| `docs/decisiones/NNNN-*.md` | ADR: decisión + porqué, no se regenera | a mano |
| `docs/*.md` (crear-un-lab, tunnel-del-bastion, informes, encargos) | prosa de trabajo: guía, informe o registro de una fase; no se regenera | a mano |
| `docs/revisiones.json` | sellado por hash de los docs (caducidad) | `./lab check docs --sellar` |
| `scripts/` | herramientas de DESARROLLO: perfilar un verbo, lanzar un ciclo (`ciclo.py`) y esperar con condición y tope (`esperar.py`). El motor no las usa | a mano |
| `test/` | pruebas del asignador; `test/fixtures/` = clústeres simulados | a mano |

`./lab` es el **único** punto de entrada, y se ejecuta **desde la raíz del repo**:
`ansible.cfg` se busca en el directorio actual, así que lanzar `ansible-playbook`
desde otro sitio corre el motor sin inventario ni filtros, **en silencio**.

Regla de frontera: *¿esto seguiría igual si desapareciera el lab?* Sí →
`deployment_engine/`. No → `labs/<lab>/`.

## Reglas duras

1. **Sólo API de Proxmox.** `https://<nodo>:<puerto>/api2/json`. Prohibido
   `snippets`, `hookscripts`, `pct exec`, `qm`, SSH al hipervisor. Si algo no se
   puede por API, se para y se pregunta; no se rodea. El **motor** no entra por SSH
   jamás; para depurar a mano, ver §Depuración por SSH (último recurso).
2. **Una sola vía de acceso**: toda llamada pasa por
   `deployment_engine/tasks/pve_api.yml` con `ansible.builtin.uri`. Ningún play
   llama a la API por su cuenta, y el wrapper `./lab` **no llama a la API**.
3. **Sin variables de entorno, by design.** Ningún valor de configuración sale de
   `os.environ`: todo de `secrets.yml`, `vars/engine.yml` y la declaración del lab.
   El wrapper no exporta nada.
4. **`secrets.yml` en claro y gitignored** (MVP: simplicidad > seguridad; decisión
   consciente, escrita en el README). El header `Authorization` **nunca** se
   escribe en `api.jsonl`. Nunca imprimas su contenido.
5. **El diario de API es sagrado**: una línea JSON por petición (`ts`, `verb`,
   `lab`, `method`, `path`, `params`, `status`, `duration_ms`, `response`). Si una
   ejecución no dejó diario, no ocurrió.
6. **Idempotencia**: dos ejecuciones seguidas ⇒ la segunda `changed=0` **y** los
   **tres diarios** (`api.jsonl`, `interior.jsonl` y `console.jsonl`) con **sólo
   lecturas**.
7. **El motor no contiene ni un valor de ningún lab.** Conoce reglas genéricas
   (el menor vmid libre del clúster, el pool se llama como la carpeta del lab, la
   MAC se deriva del vmid), nunca valores. Añadir un lab **no toca ni un fichero
   del motor**.
8. **El motor no conoce ninguna topología.** El lab es un parámetro, nunca una
   ruta fija. El motor **no lee `labs/`**; los checks sí (son herramientas, no el
   motor). Prohibido copiar un verbo para un lab.
9. **El motor nunca borra** un invitado que no esté en la declaración. Destruir es
   `./lab --lab X destroy`, que se niega si el invitado sigue declarado.
10. **Un fichero = un propósito.** Si un cambio pide un tercer nivel de
    subdirectorios dentro de `deployment_engine/`, para y justifícalo en el README.
11. **Nada derivado se guarda en el repo**: ni vmids, ni MACs, ni un fichero de
    asignaciones. El estado vive en Proxmox y se re-deriva leyendo la API.
12. **Cuatro vías de acceso, tres diarios.** A Proxmox y a RouterOS se les habla **sólo**
    con `ansible.builtin.uri`, y cada llamada deja **una línea JSON** en
    `logs/api.jsonl` con un campo `api` (`proxmox` | `routeros`) y el rol del
    invitado. Al interior de un Linux se entra **sólo** desde
    `tasks/interior_ssh.yml`, y cada paso deja una línea en `logs/interior.jsonl`.
    Ningún otro fichero abre una conexión a un invitado. La contraseña o la clave
    **nunca** se escriben en un diario. La consola de la API se habla **sólo** desde
    `tasks/console.yml`, y cada uso deja una línea en `logs/console.jsonl`.
13. **RouterOS se configura sólo por su REST** (`/rest/…`). Su SSH existe en esta
    fase **sólo para depurar**; el motor no lo usa jamás para converger.
14. **La MAC no se declara nunca** (es la regla 11 aplicada al interior): las
    reservas DHCP de un router se **derivan** del vmid del invitado. Si un YAML de
    lab contiene una MAC, es un bug.
15. **El vocabulario del interior es cerrado**: un lab no puede inventarse
    primitivas; pide una nueva al motor, con ADR.
16. **El túnel lo construye el motor y se comprueba de punta a punta.** Si no
    responde, el verbo **para** diciendo qué pieza falta y cómo se arregla; nunca lo
    rodea por otra vía.
17. **El interior es de la declaración por áreas**: dentro de un área declarada, lo
    que no está en el YAML se quita del equipo; fuera de las áreas declaradas no se
    toca nada.
18. **Nunca se arranca una etapa antes de que el anterior esté convergido y
    sirviendo.** Es lo que mata la carrera del DHCP por construcción, no por suerte.
19. **La consola de la API tiene una sola tarea, y una sola línea.** Sólo para poner
    el arranque del bastión, nunca para configurar un equipo: lo que se
    configura, se configura por su pasarela (REST del router, SSH del Linux) y queda en
    su diario.

## Depuración por SSH (último recurso)

El motor habla con Proxmox **sólo por la API** (regla 1). Pero cuando la API no
alcanza —no da el error real, no expone un fichero del nodo, no explica por qué
falla una tarea— existe una vía de depuración por SSH **para quien diagnostica**
(persona o agente), **nunca para el motor**:

- **Último recurso, de verdad.** Antes hay que **AGOTAR la API**: probar cada método
  y cada ruta que permita la documentación oficial de Proxmox, y leer la respuesta y
  el diario. Si algo se puede saber por API, se sabe por API.
- **Sólo para DIAGNOSTICAR**, no para cambiar el mundo. El motor no entra por SSH
  jamás: ningún play, tarea, filtro ni herramienta usa SSH, y `./lab check access`
  lo vigila.
- **Credenciales en `secrets.yml`**, en claro y gitignored como el resto, y **sólo las
  del nodo**: el token de la API. No hay claves de contraseña (las `pve_ssh_*` se dieron
  de baja: ningún fichero del motor las leía). Si el nodo sólo admite clave pública, se
  autoriza la `.pub` que haga falta; **no** se toca la configuración de `sshd` del nodo.
- **Cuando la API no llega, se dice**: qué se intentó por API, por qué no bastó y qué
  se hizo por SSH. Sin maquillar.

## Identidad: quién pone los números

- El **lab declara roles** (`switch`, `workstation-1`), su topología (bridges,
  direcciones, recursos), el **tipo de equipo** de cada invitado (`tipo:`, obligatorio y del
  vocabulario cerrado `rt`/`fw`/`srv`/`ws`/`sw`/`ctl`) y, si quiere que el motor entre en ellos,
  **qué configurar dentro** (`config:`, `image:`). Un `nombre:` corto por invitado es
  opcional: es su alias, y si falta se usa el rol. **El lab no declara vmids ni MACs, nunca**
  (la MAC es función del vmid, y las reservas DHCP se derivan de él: regla 14).
- **El tipo de equipo manda sobre lo que el equipo puede declarar** (ADR 0026): un equipo hace
  **una** cosa. Un `rt` enruta y sale (y no filtra), un `fw` filtra (y no traduce, ni reparte
  direcciones, ni es la vía de acceso de nadie), un `sw` conmuta (y no enruta, ni filtra, ni
  traduce, ni reparte). El validador lo caza con el motivo antes de tocar nada. Cuando un lab
  necesita dos funciones, se levantan **dos equipos**.
- El **motor deriva** el vmid (el menor libre **de todo el clúster**), el NOMBRE
  (`<tipo>-<alias>`: dice qué EQUIPO es, no de qué lab es — `rt-borde`, `srv-1`; dos labs
  pueden repetir `rt-nucleo`, y por eso el nombre no es una prueba de pertenencia), la MAC
  (`f(vmid)`) y la descripción del invitado (`lab=<lab> rol=<rol> gestionado por
  netlabs_v4_b`), que es la que dice de quién es cada uno.
- **Sin fichero de estado.** La asignación se re-deriva leyendo la API: el **pool**
  del lab (llamado como su carpeta) es la frontera de propiedad, y la
  **descripción** de cada invitado lleva el rol.
- **Un bridge no está en ningún pool**, así que ahí la frontera no vale: la prueba
  de propiedad es el `comments` que el plan le escribe **al crearlo**
  (`lab=<lab> gestionado por netlabs_v4_b`). `destroy` sólo borra un bridge que
  lleve esa marca **y** que no esté usando ningún invitado de fuera del lab; sin
  marca no se adopta y no se toca, porque el plan crea el bridge sólo si falta.
- El asignador (`filter_plugins/identidad.py`) es una **función pura** —*(estado
  del mundo, declaración) → mapa rol→identidad*—, y por eso se prueba con
  **fixtures**, sin Proxmox.
- **Convivencia**: varios labs a la vez en el mismo nodo. Los vmids no chocan por
  construcción; lo declarado (bridges, direcciones, nombres) lo vigila
  `./lab check colisiones`, que **no** puede probar la disjunción de vmids sin
  credenciales (eso se dice, no se maquilla).

## Documentación: un escritor por región

Un fichero con dos escritores es el que envejece mal. `labs/<lab>/<lab>.md` tiene
**dos regiones**:

```markdown
<!-- generado:inicio -->
| rol | tipo | cores | memory | disk | bridge | address | stage |
...tablas y datos derivados de la declaración...
<!-- generado:fin -->

## Por qué así   <- prosa libre: decisiones, trampas, qué se aprendió
```

- **Dentro de los marcadores: prohibido escribir a mano.** Lo reescribe
  `deployment_engine/tools/documentos.py` desde la declaración (con
  `deployment_engine/templates/lab-region.md.j2` como esqueleto). `./lab check
  docs` falla si el fichero difiere de su render, y la herramienta falla (no
  adivina, no trunca) si los marcadores faltan o se duplican.
- **Fuera: prosa libre, ningún check opina sobre su contenido.** Ahí va lo que el
  YAML no puede decir. Es donde se archiva lo aprendido al ejecutar (*filing back*).
- La prosa **no repite valores** de la región generada: los cita y, si hace falta
  el dato, se añade a la tabla.
- No construyas una wiki con índice, páginas de entidad ni grafo: eso es el fallo
  del repo anterior. El **esqueleto es rígido; el cuerpo es libre**.

## Qué correr y cuándo

| Si… | Corre |
| --- | --- |
| cambiaste `labs/*/<lab>.yml` | `./lab --lab <lab> plan` y luego `./lab check docs` |
| cambiaste un lab con `config:` (un driver, un área) | `./lab --lab <lab> plan --api` y `./lab check docs` |
| cambiaste un playbook, tarea, filtro o herramienta | `./lab check refs deployment_engine/<ruta>` y revisa los docs que salgan |
| cambiaste el texto de prosa de un `.md` | `./lab check docs --sellar labs/<lab>/<lab>.md` |
| creaste o borraste ficheros | `./lab check links` |
| tocaste `VERSION`, el `CHANGELOG.md`, o vas a publicar | `./lab check version` |
| antes de cualquier commit | `./lab check` (todo) + `ansible-lint` |
| tocaste la propiedad de los bridges (`plan`, `destroy`, `estado`) | `python3 test/test_bridges.py` y `./lab check` |
| tocaste `tools/plan.py` (lo que el plan da por bueno) | `python3 test/test_plan.py` y `python3 test/test_regresion_planes.py` |
| tocaste un driver del interior (`routeros`/`linux`) | `./lab check access` + `python3 test/test_interior.py` y `test/test_routeros.py` |
| vas a decir "hecho" | `./lab check` verde y la evidencia pegada en la respuesta |
| vas a iterar (un ciclo de desarrollo) | `python3 scripts/ciclo.py --lab <lab>` en segundo plano y el aviso `=== CICLO FIN` dispara el paso siguiente (ver §El agente no espera) |
| tocaste `scripts/ciclo.py` o `scripts/esperar.py` | `python3 test/test_ciclo.py` y `./lab check` |
| vas a subir a GitHub | ciclo `destroy → apply → verify` verde + `./lab check` (ver §Commits y subida a GitHub) |

`./lab check [nombre]` corre todo: `links`, `docs`, `refs`, `access`,
`privilegios`, `declaracion`, `address_space`, `colisiones`, `pureza-lab` y `readme`,
más `version` (que es del **repositorio**, no del motor: vive en `./lab`).
Un check que no puede fallar no es un check: para cada uno hay que haberlo visto
gritar rompiendo a propósito lo que vigila.

## El agente no espera: se le avisa

Un `sleep` de duración fija para aguardar un trabajo es una apuesta: o duerme de más
(minutos tirados) o de menos (mira antes de que acabe). La distinción que manda no es
«espera sí / espera no», es **condición con tope** contra **duración a ciegas**. ADR 0036.

- **Dentro del motor la espera ya es la buena**: `esperar_tarea.yml` sondea el UPID cada
  2–15 s hasta que deja de correr, y `sonda.yml` espera a que un escalón conteste antes de
  tocar el siguiente (regla 18). Eso se queda: es espera real, acotada, y deja su línea en
  el diario.
- **En la capa que orquesta no hay `sleep` a ciegas.** Ni `sleep 420; grep …` ni
  `while pgrep -f …; do sleep …; done` (ese guardia se espera a sí mismo: su propia línea
  de órdenes contiene el patrón). Un verbo largo se ejecuta de una de estas dos formas, y
  sólo estas dos: **síncrona**, si cabe en el tope de la herramienta; o **en segundo plano
  con aviso de fin**, y ese aviso es el disparador del paso siguiente. Mientras corre se
  hace otra cosa: el reloj no decide nada.
- **Si de verdad hay que bloquearse**, hay una sola primitiva: `scripts/esperar.py`, que
  sondea cada 2 s y sale **en el instante** en que la condición se cumple, con tope
  (`--lab`, `--fichero`+`--patron`, `--pid`). Agotar el tope es un fallo, no un verde.
- **El ciclo de desarrollo se lanza con `scripts/ciclo.py`**: `plan` → `destroy` → `apply`,
  con diario propio por ciclo, estado en JSON (`labs/<lab>/logs/ciclo-estado.json`) y la
  marca `=== CICLO FIN`. `apply` ya importa `verify.yml`, así que el ciclo verifica por su
  cuenta; la pasada suelta de `verify` se añade (`--fases plan,destroy,apply,verify`) sólo
  cuando se va a publicar. No es un verbo del motor y el motor no lo usa: es una
  herramienta de desarrollo, como `perfilar.sh`.

## Versionado y entrega

La versión es un número (`MAYOR.MENOR.PARCHE`, SemVer) y **no** parte del nombre del
repositorio. Mientras la MAYOR sea `0` el producto está en desarrollo y **cualquier
MENOR puede romper**: eso significa la serie 0.x. `1.0.0` será el día que haya algo
que prometer (declaración de lab estable y terceros usándola). ADR 0017.

- **La versión publicada vive en tres sitios y los tres dicen lo mismo**: el fichero
  `VERSION` (una línea), el tag `vX.Y.Z` de `main` y su entrada del `CHANGELOG.md`. Lo
  vigila `./lab check version`, y `./lab version` lo imprime. Lo que entra en `main` sin
  publicarse se apunta bajo `## [No publicado]`.
- **Una rama corta por cambio**, nombrada por el tipo de Conventional Commits
  (`feat/…`, `fix/…`, `refactor/…`, `docs/…`, `chore/…`, `test/…`): se abre para UN
  cambio, se cierra con un pull request y se borra. `main` es lo publicado y está
  siempre verde. Un commit de una línea o una errata puede ir directo: lo que no se
  sostiene es TODO directo.
- **Publicar es un acto explícito**: pasar `[No publicado]` a `## [X.Y.Z] - fecha`,
  subir `VERSION`, `git tag -a vX.Y.Z`, `git push --follow-tags` y `gh release create`
  con esa entrada del CHANGELOG. Sin ciclo verde contra un Proxmox real, no se publica.

## Commits y subida a GitHub

Un cambio del motor **no se da por bueno hasta que el ciclo completo pasa de
verdad** contra un Proxmox real:

```
./lab --lab <lab> destroy --yes
./lab --lab <lab> apply      # debe converger en UNA sola pasada
./lab --lab <lab> verify     # debe dar CORRECTO
```

Cuando ese **ciclo `destroy → apply → verify` pasa en verde** (y `./lab check` está
verde), el cambio está listo: **se puede commitear y subir a GitHub**
(`MagicJF/netlabs-iac`), sin pedir permiso para ello. Rama, commits y pull request —o
directo a `main`, si es de una línea—; el PR cuenta qué cambia, por qué y con qué
evidencia, y se mezcla con *squash*: un cambio, un commit en `main`.

- Commits en estilo convencional (`feat:`, `fix:`, `docs:`, `test:`...), en
  imperativo y en castellano.
- **Nunca** se sube `secrets.yml` ni `labs/*/logs/` (gitignored; si aparecieran, algo
  va mal).
- Si el ciclo **no** pasa, no se sube: se arregla, o se dice en claro qué falta y por
  qué. Un commit que no ha pasado el ciclo es una promesa sin respaldo.
- Una entrega de partida es la excepción, y se dice: `0.1.0` marca el estado que YA
  estaba verificado, para tener de dónde comparar.

### Nada se mezcla con Greptile por debajo de 5/5

Greptile puntúa cada PR de 0 a 5. Un PR **no se da por bueno** mientras su confianza sea menor
que 5/5: se leen sus hallazgos (los **P1** primero), se arreglan de verdad —no se silencian con
un comentario—, se empuja y se **re-dispara el bucle** hasta que dé 5/5. No es un extra: es el
último paso de cualquier PR, como `./lab check`.

- Confianza < 5/5 casi siempre señala un caso que **ninguna prueba cubría**. El arreglo entra
  **con su prueba**, y si el hallazgo era un falso positivo se dice **por qué** con evidencia.
- Se re-dispara comentando `@greptileai review` (y `@coderabbitai review` para el otro revisor).
  La puntuación y los hallazgos inline se leen con `gh`, nunca se adivinan; y se leen **del
  cuerpo del resumen**, que Greptile EDITA en su sitio: mirar `created_at` en vez de lo que dice
  el cuerpo ahora mismo es leer una puntuación vieja.
- Un hallazgo del bot **no se acepta por fe** ni se rechaza por fe: se **reproduce** (con una
  prueba, o contra el nodo real) antes de tocar nada. En `labs/08` un P1 describía un fallo que
  el bot no podía ejecutar y que sí era real: el estado compartido no guardaba más que la
  primera interfaz, así que un `plan --api` tumbaba un lab desplegado y correcto.

## Cabecera obligatoria de cada fichero

Playbooks, tareas, filtros, plantillas, herramientas y declaraciones empiezan con:

```yaml
# PROPÓSITO:   qué hace, en una frase.
# INVARIANTES: lo que debe cumplirse siempre; si falla, es un bug.
# LÍMITES:     lo que la API o Ansible NO pueden hacer aquí.
# VER:         el doc/ADR/check que lo explica (puntero inverso a la prosa).
```

Dentro del fichero, cada sección con un comentario de **qué es y por qué** (no
*cómo*: el cómo se lee). Jinja complejo: comentario que lo traduzca a castellano,
o se mueve a un filtro comentado.

## Estilo

- `snake_case`, sin abreviar (`containers`, no `ctns`); dominio en castellano,
  claves de la API de Proxmox **literales**.
- Constantes y rutas declaradas arriba del fichero, no incrustadas.
- No normalices datos a espaldas del usuario: conserva el literal y avisa.
- El comentario no repite al documento; el comentario y el check **mandan** sobre
  cualquier documento que los contradiga.

## Prohibiciones

- Copiar código o estructura de `ansible-netlabs-v3` (el experimento anterior), o
  añadir colecciones (el motor usa sólo `ansible.builtin`).
- Instalar dependencias fuera de `requirements.txt`, o usar un venv distinto.
- Escribir en `labs/*/logs/` a mano, o declarar un vmid o una MAC en un lab.
- Decir que algo funciona sin la salida real del comando que lo prueba.
- Cambiar la estructura de carpetas sin actualizar este fichero y el README.
