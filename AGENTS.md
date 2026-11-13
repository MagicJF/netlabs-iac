# netlabs_v4_b — esquema y reglas del repositorio

Motor IaC en Ansible que despliega topologías (VMs y contenedores LXC) en un nodo
Proxmox **exclusivamente por su API REST**, asigna por sí mismo la identidad de
cada invitado y lo documenta. Este fichero se inyecta en el system prompt cuando
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
| `deployment_engine/tasks/pve_api.yml` | **la única puerta** a la API + el diario | a mano |
| `deployment_engine/` | todo lo demás compartido por todos los despliegues | a mano |
| `labs/<lab>/<lab>.yml` | el estado deseado de ESA topología (fuente de verdad) | a mano |
| `labs/<lab>/<lab>.md` | la topología explicada: región generada + región de prosa | **dos escritores** |
| `labs/<lab>/logs/` | `api.jsonl`, `ansible.log`, `verify-*.json` (gitignored) | el motor, nunca a mano |
| `docs/decisiones/NNNN-*.md` | ADR: decisión + porqué, no se regenera | a mano |
| `docs/revisiones.json` | sellado por hash de los docs (caducidad) | `./lab check docs --sellar` |
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
2. **Una sola puerta**: toda llamada pasa por
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
6. **Idempotencia**: dos ejecuciones seguidas ⇒ la segunda `changed=0` **y** su
   diario sólo con `GET`.
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

## Depuración por SSH (último recurso)

El motor habla con Proxmox **sólo por la API** (regla 1). Pero cuando la API no
alcanza —no da el error real, no expone un fichero del nodo, no explica por qué
falla una tarea— existe una vía de depuración por SSH **para quien diagnostica**
(persona o agente), **nunca para el motor**:

- **Último recurso, de verdad.** Antes hay que **AGOTAR la API**: probar cada método
  y cada ruta que permita la documentación oficial de Proxmox, y leer la respuesta y
  el diario. Si algo se puede saber por API, se sabe por API.
- **Sólo para DIAGNOSTICAR**, no para cambiar el mundo. El motor no entra por SSH
  jamás: ningún play, tarea, filtro ni herramienta usa SSH, y `./lab check puerta`
  lo vigila.
- **Credenciales en `secrets.yml`** (`pve_ssh_usuario`, `pve_ssh_password`), en claro
  y gitignored como el resto. Si el nodo sólo admite clave pública, se autoriza la
  `.pub` que haga falta; **no** se toca la configuración de `sshd` del nodo.
- **Cuando la API no llega, se dice**: qué se intentó por API, por qué no bastó y qué
  se hizo por SSH. Sin maquillar.

## Identidad: quién pone los números

- El **lab declara roles** (`switch`, `workstation-1`) y su topología (bridges,
  direcciones, recursos). **El lab no declara vmids ni MACs, nunca.**
- El **motor deriva** el vmid (el menor libre **de todo el clúster**), el nombre
  canónico (`<lab>-<rol>`), la MAC (`f(vmid)`) y la descripción del invitado
  (`lab=<lab> rol=<rol> gestionado por netlabs_v4_b`).
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
| rol | tipo | cores | memoria | disco | bridge | dirección | escalón |
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
| cambiaste un playbook, tarea, filtro o herramienta | `./lab check refs deployment_engine/<ruta>` y revisa los docs que salgan |
| cambiaste el texto de prosa de un `.md` | `./lab check docs --sellar labs/<lab>/<lab>.md` |
| creaste o borraste ficheros | `./lab check links` |
| antes de cualquier commit | `./lab check` (todo) + `ansible-lint` |
| tocaste la propiedad de los bridges (`plan`, `destroy`, `estado`) | `python3 test/test_bridges.py` y `./lab check` |
| vas a decir "hecho" | `./lab check` verde y la evidencia pegada en la respuesta |
| vas a subir a GitHub | ciclo `destroy → apply → verify` verde + `./lab check` (ver §Commits y subida a GitHub) |

`./lab check [nombre]` corre todo: `links`, `docs`, `refs`, `puerta`,
`declaracion`, `colisiones`, `pureza-lab` y `readme`. Un check que no puede
fallar no es un check: para cada uno hay que haberlo visto gritar rompiendo a
propósito lo que vigila.

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
(`MagicJF/netlabs_v4_b`), sin pedir permiso para ello.

- Commits en estilo convencional (`feat:`, `fix:`, `docs:`, `test:`...), en
  imperativo y en castellano.
- **Nunca** se sube `secrets.yml` ni `labs/*/logs/` (gitignored; si aparecieran, algo
  va mal).
- Si el ciclo **no** pasa, no se sube: se arregla, o se dice en claro qué falta y por
  qué. Un commit que no ha pasado el ciclo es una promesa sin respaldo.

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
