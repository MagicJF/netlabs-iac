# netlabs_v4_b — motor de despliegue en Proxmox por su API REST

Un **motor IaC escrito en Ansible** que, a partir de la **declaración de una
topología**, crea, actualiza, arranca, verifica y destruye invitados (VMs QEMU y
contenedores LXC) en un nodo Proxmox **sólo por su API REST** —y que además
**configura el interior de cada invitado** (RouterOS por su REST, Linux por SSH),
dejando cada paso en su diario.

El valor de este repositorio no son las topologías que despliega: es **el motor y
su forma de trabajar** —declaración, verbos, identidad asignada por el propio
motor, **cuatro puertas y tres diarios**, verificación por conjuntos en los dos
mundos (el de la API y el del interior), y documentación con punteros
bidireccionales—. Las topologías viven cada una en su carpeta (`labs/`) y **el
motor no conoce ninguna**.

---

## Arquitectura: dos capas y sólo dos

| Capa | Dónde | Qué es |
| --- | --- | --- |
| **El motor** | `deployment_engine/` | todo lo compartido por todos los despliegues: las **puertas** (API de Proxmox, REST de RouterOS, interior Linux, consola) y sus diarios, el asignador de identidad, la validación, el plan, los **drivers del interior**, los checks y las plantillas |
| **Las topologías** | `labs/<nombre>/` | *una carpeta por lab*: su declaración (`<nombre>.yml`), su documento (`<nombre>.md`) y sus logs (`logs/`, gitignored) |

La pregunta que decide dónde va algo: **¿esto seguiría igual si desapareciera el
lab?** Sí → motor. No → lab.

El motor **no lee `labs/`**: el nombre del lab es siempre un parámetro del verbo,
nunca una ruta fija ni un valor incrustado. Los *checks* sí lo leen, porque son
herramientas de desarrollo, no el motor.

### El mapa del repositorio

```
netlabs_v4_b/
├── README.md            este fichero: el MOTOR. Ni un valor de ningún lab.
├── AGENTS.md            el esquema que se inyecta en el prompt de un agente IA.
├── lab                  ÚNICO punto de entrada (script Python 3, stdlib).
├── ansible.cfg          inventario y filtros; Ansible lo busca en el cwd.
├── .ansible-lint        con la razón escrita de cada excepción.
├── requirements.txt     sólo linters. El motor no necesita colecciones.
├── .githooks/pre-commit guardas docs↔código (se activa una vez por clon).
├── deployment_engine/
│   ├── secrets.yml           credenciales reales (gitignored, 0600; a mano)
│   ├── inventory/hosts.yml   el nodo Proxmox como host local de la API
│   ├── vars/engine.yml       defaults del motor (timeouts, MAC, retención…)
│   ├── playbooks/            un fichero por verbo: plan, preflight, apply,
│   │                         verify, destroy
│   ├── tasks/                las CUATRO puertas y sus diarios: pve_api.yml (API
│   │                         de Proxmox → api.jsonl), ros_api.yml (REST de
│   │                         RouterOS, por el puesto de control → api.jsonl),
│   │                         interior_ssh.yml (interior Linux → interior.jsonl),
│   │                         camino_consola.yml (consola → camino.jsonl); más
│   │                         los drivers (configurar_routeros.yml,
│   │                         configurar_linux.yml), el camino (camino.yml,
│   │                         camino_mundo.yml), el inventario en memoria
│   │                         (inventario_invitados.yml), la sonda (sonda.yml),
│   │                         la espera (esperar_tarea.yml) y validar.yml
│   ├── filter_plugins/       lo que Ansible calcula en Jinja: declaracion.py,
│   │                         identidad.py, estado.py, interior.py (el driver
│   │                         PURO del interior)
│   ├── tools/                capa Python stdlib: plan.py, documentos.py,
│   │                         consola.py, framework_check.py
│   └── templates/            SÓLO la región generada del doc de un lab
├── docs/decisiones/          ADRs: pocos, y sólo los que no quieres re-litigar
├── docs/camino-del-puesto-de-control.md   cómo funciona el camino (prosa)
├── labs/.plantilla/          lo que copia `./lab new`
└── labs/<nombre>/            UNA CARPETA POR TOPOLOGÍA
```

**Presupuesto de tamaño:** el motor son pocas carpetas y un fichero por verbo, y
nada más. Ninguna ruta de `deployment_engine/` pasa de subdirectorio de segundo
nivel; si un cambio exigiera un tercero, hay que parar y justificarlo aquí.

---

## Cómo se usa

Todo se hace con un **único punto de entrada**, `./lab`, **desde la raíz del
repositorio**. El wrapper existe porque `ansible.cfg` se busca en el *directorio
actual*: lanzar `ansible-playbook` desde otro sitio correría el motor sin
inventario y sin filtros, **en silencio**.

```
./lab list                       # labs declarados en labs/
./lab new <nombre>               # scaffoldea labs/<nombre>/ desde labs/.plantilla/
./lab --lab <nombre> plan        # ORDENA y muestra las llamadas REST que haría
./lab --lab <nombre> preflight   # sólo lectura: qué hay, qué falta, qué difiere
./lab --lab <nombre> apply       # converge lo declarado + verifica
./lab --lab <nombre> verify      # TEST FINAL: ¿existe de verdad lo declarado?
./lab --lab <nombre> destroy     # único verbo que destruye; pide confirmación
./lab check [nombre]             # checks del motor, sin credenciales ni Proxmox
```

Cada verbo es **un playbook** en `deployment_engine/playbooks/`. Los verbos
comparten tareas por `deployment_engine/tasks/`; nunca se copia un verbo para un
lab. El wrapper resuelve el lab, comprueba que existan declaración y `logs/`,
verifica el entorno **antes** de empezar y captura la salida humana de Ansible en
`labs/<lab>/logs/ansible.log` (por redirección desde el propio wrapper).

### Dónde se dice QUÉ se despliega

La entrada del motor son **dos ficheros, y ninguno de los dos es código**:

| Qué | Dónde | Versionado |
| --- | --- | --- |
| **la topología**: qué se despliega | `labs/<lab>/<lab>.yml` | sí |
| **las credenciales**: dónde se despliega | `deployment_engine/secrets.yml` | no (gitignored, 0600) |

Y nada más. `deployment_engine/vars/engine.yml` son los **defaults del motor**
(timeouts, prefijo de MAC, retención del diario), no topología: ahí no hay ni un
invitado, ni un bridge, ni una dirección. Tampoco hay fichero de estado ni
inventario que mantener: lo que se despliega es **exactamente lo declarado**, y el
resto (vmid, MAC, nombre canónico, pool) lo deriva el motor leyendo el clúster.

**Cómo se declara un lab.** `./lab new <nombre>` scaffoldea la carpeta desde
`labs/.plantilla/` y se rellena el YAML:

```yaml
lab:
  nombre: <lab>            # EXACTAMENTE el nombre de la carpeta: es el pool
  escalones: [1, 2]        # orden de arranque: primero el 1, después el 2
  bridges:                 # los crea el motor si faltan (los bridges son del nodo)
    - nombre: vmb_algo     # nombre de interfaz válido: sin guiones, ≤15 caracteres
      direccion: 192.0.2.1/24
vms:                       # invitados QEMU
  - rol: <rol>             # el rol identifica a un invitado y sólo a uno
    escalon: 1
    cores: 2
    memoria: 512
    disco: 8
    bridge: vmb_algo
    direccion: 192.0.2.2/24
containers:                # invitados LXC
  - rol: <otro-rol>
    escalon: 2
    cores: 1
    memoria: 256
    disco: 4
    bridge: vmb_algo
    direccion: 192.0.2.11/24
```

Lo que **no** se declara, y es a propósito: ni `vmid`, ni MAC, ni el nombre
canónico, ni a qué pool va cada invitado. Eso lo **deriva** el motor (§Identidad).
El YAML dice *qué* y *en qué orden*; nunca dice *con qué número*.

**El vocabulario del interior (fase 2):** un lab puede además declarar **qué hay que
configurar dentro** de cada equipo, y el motor lo converge como una fase más de su plan.

- **`config:`**, con **exactamente una clave de tipo** (`linux` o `routeros`), que elige el
  driver. Dentro van las **áreas** (los campos que el motor sabe tocar y de los que
  responde): `identidad`, `servicios`, `direcciones`, `rutas`, `dhcp`, `cortafuegos`,
  `reenvio`, `dhcp_servidor`, `camino`…
- **`imagen:`** en una VM QEMU: el disco de fábrica que se importa al crearla (un CHR).
- **`direccion:`** admite tres formas: `<ip>/<prefijo>` (estática), **`dhcp`** (dinámica: el
  invitado no la declara; se lee del host y, si hay camino, de la concesión del router) o
  **ausente** (un equipo sin dirección: un conmutador puro).
- **`reservas: derivadas`** es la única forma de declarar reservas DHCP de un router: el
  motor reserva, por la MAC que **deriva del vmid**, cada dirección estática declarada por
  otro invitado del mismo bridge —excluyendo al propio servidor—. Una MAC en un YAML es un bug.
- **`lab.supernet`** acota todo lo del lab (lo vigila el check `supernet`), y
  **`lab.camino`** pide el puesto de control que construye el motor (§`docs/camino-del-puesto-de-control.md`).

**Dentro de un área declarada, lo que no está en el YAML se quita del equipo; fuera de las
áreas declaradas, el motor no opina** (regla 17).

**Qué se despliega se dice al llamar al verbo**: el nombre del lab es el único
parámetro que el motor necesita, y el nombre del pool sale de él.

```
./lab list                     # las topologías declaradas en labs/
./lab --lab <lab> plan         # qué llamadas REST haría (offline, sin credenciales)
./lab --lab <lab> preflight    # qué hay, qué falta, qué difiere (sólo lectura)
./lab --lab <lab> apply        # converge lo declarado y verifica
./lab --lab <lab> verify       # test final: ¿existe de verdad lo declarado?
./lab --lab <lab> destroy      # único verbo que destruye (pide confirmación)
```

Si el nombre no coincide con la carpeta, el motor se niega **antes de tocar la
API**: el pool se llama como la carpeta, y es lo que distingue «esto es de este
lab».

### Las credenciales se escriben a mano: `deployment_engine/secrets.yml`

El motor **no lee variables de entorno** ni ningún fichero externo: las
credenciales salen de `deployment_engine/secrets.yml`, que está gitignored y tiene
que quedar en **0600**. Se crea a mano —ya no se versiona ningún `.example`: el
repositorio se considera lo bastante maduro como para no mantener un fichero de
relleno que hay que borrar antes de usarlo—:

```yaml
pve_nodo: "<host o IP del nodo>"              # lo que va en la URL
pve_nombre_nodo: "<nombre del nodo>"          # lo que va en /nodes/<nombre>/...
pve_puerto: "8006"
pve_token_id: "<usuario>@pve!<nombre-del-token>"
pve_token_secreto: "<secreto del token>"
pve_verificar_tls: false                      # true con certificado de verdad
pve_ssh_usuario: "<usuario>"                  # SÓLO diagnóstico manual
pve_ssh_password: "<clave>"                   # el motor no usa SSH nunca
```

Los avisos que ya estaban escritos siguen valiendo: el token de Proxmox
**equivale a root y no caduca** —trátalo como una contraseña de root—, y
`pve_nodo` y `pve_nombre_nodo` son **dos valores distintos**: el host de la URL y
el nombre con el que la API conoce al nodo. Usar el host como nombre de nodo hace
que la API conteste `596 no such node`.

`./lab` comprueba que el fichero exista **antes de lanzar nada** cuando el verbo
necesita la API, y lo dice en claro si falta. `plan` sin `--api` no lo necesita:
usa un fixture.

### Los bridges: qué se lleva `destroy` y qué no

`destroy` borra los invitados del lab, su pool y **los bridges que creó él** —y nada
más—. La diferencia importa, porque un bridge **no está en ningún pool**: Proxmox no
mete interfaces de red en pools, así que aquí la frontera de propiedad no sirve y el
motor necesita otra prueba.

La tiene: cuando `apply` **crea** un bridge le escribe en el `comments` la marca del
motor (`lab=<lab> gestionado por netlabs_v4_b`), y `destroy` sólo borra un bridge si
se cumplen **las dos** condiciones:

1. su `comments` lleva la marca de **este** lab (consta que lo creó él), y
2. **ningún invitado de fuera del lab lo está usando** — se miran **todas** las patas
   (`net0`, `net1`…) de todos los invitados que no son del lab; y si la config de
   alguno no se pudo leer, **no se borra**: en la duda se conserva.

Un bridge que ya estaba en el nodo antes de que el lab llegara (el plan sólo lo crea
si falta) **no se marca**, así que no se adopta y no se borra: es del nodo, no del
lab. `destroy` lo dice en su salida, bridge a bridge, con el motivo.

La recarga de red (`PUT /nodes/<nodo>/network`, la llamada más delicada del motor
porque reescribe la red del nodo) se hace **una sola vez** y sólo si de verdad se ha
borrado algún bridge.

**Lo que sigue sin tener verbo:** los bridges que el lab encontró puestos, los que
marcó otro lab y los huérfanos anteriores a esta marca (no llevan `comments`, así que
no se pueden reclamar). Limpiarlos es cirugía del nodo, no del despliegue, y se hace
a mano por la API:

```
DELETE /nodes/<nodo>/network/<bridge>    # una por bridge huérfano
PUT    /nodes/<nodo>/network             # UNA recarga al final, no una por bridge
```

### `plan` no necesita credenciales

`plan` deriva y ordena las llamadas REST a partir de la declaración **y del estado
del mundo**. Por defecto el estado del mundo es un **clúster vacío simulado**
(`test/fixtures/cluster-vacio.json`), así que `plan` es demostrable sin tocar
ningún Proxmox. Con `--api` lee el estado real por la API.

`apply` ejecuta **ese mismo plan**: no hay una segunda lógica de decisión. Lo
único que cambia es de dónde sale el estado del mundo.

---

## Las cuatro puertas, y un diario de cada una

Al mundo se le habla por **cuatro puertas**, y por ninguna otra: a **Proxmox** por
`tasks/pve_api.yml` (`/api2/json`, con `ansible.builtin.uri`), a **RouterOS** por
`tasks/ros_api.yml` (su `/rest/…`, alcanzado por el puesto de control), al
**interior Linux** por `tasks/interior_ssh.yml` (SSH), y a la **consola de la API**
sólo desde `tasks/camino_consola.yml`. Ningún play llama "por fuera", y el wrapper
`./lab` **no llama a nada**: sólo valida y lanza `ansible-playbook`.

Cada puerta deja **su diario**, y los tres son sagrados: `logs/api.jsonl` (cada
llamada a Proxmox y a RouterOS, con un campo `api` que dice a cuál y el rol del
invitado), `logs/interior.jsonl` (cada paso dentro de un Linux) y
`logs/camino.jsonl` (cada uso de la consola). Una línea JSON por operación, con su
`ts`, su verbo y su resultado (truncado a `engine_diario_max_cuerpo`). **Si una
ejecución no dejó diario, no ocurrió.** Ni la cabecera `Authorization` ni una
contraseña o una clave se escriben jamás en un diario.

El check `puerta` vigila mecánicamente las cuatro: la ruta base de Proxmox
(`/api2/json`) sólo puede aparecer en `pve_api.yml`, la de RouterOS (`/rest`) en
`ros_api.yml`, los parámetros de conexión SSH a un invitado en `interior_ssh.yml` /
`inventario_invitados.yml`, y el protocolo de consola en `camino_consola.yml`.

Los logs son **del lab** y van gitignored: son artefactos de ejecución que rotan,
y lo que se versiona es la evidencia que se cita en la prosa del lab, no el
fichero entero.

### Lo asíncrono se espera, y se espera por la puerta

Proxmox crea, borra y recarga la red **en segundo plano**: la llamada responde un
`UPID` y el trabajo continúa. Un paso que arranca un invitado no puede correr
contra algo que aún se está creando. Por eso cada paso del plan pasa por
`deployment_engine/tasks/pve_api_y_esperar.yml`, que ejecuta la llamada por la
puerta y, **si la respuesta es un `UPID`**, espera sondeando
`GET /nodes/<nodo>/tasks/<upid>/status` hasta que la tarea deja de estar `running`.

La espera es **una regla, no una lista**: cualquier paso asíncrono (crear, borrar,
recargar la red) queda cubierto sin enumerarlo. Y **cada sondeo pasa por la misma
puerta**, así que cada uno deja su línea en el diario: la espera no es una llamada
a espaldas del diario. El bucle es finito (`engine_tarea_intentos` ×
`engine_tarea_intervalo`, por defecto 150 × 2 s = 5 min); si se agota, o si la
tarea termina con `exitstatus` distinto de `OK`, el verbo **falla** y lo dice.

---

## Identidad: quién pone los números

El motor **no conoce topologías, pero sí el mecanismo de identidad**. Lo que no
puede haber dentro del motor es un **valor**: ni una lista de labs, ni bandas de
vmids, ni el nombre de un bridge. Sí hay **reglas**.

| El lab declara | El motor deriva |
| --- | --- |
| roles lógicos y su tipo (VM/LXC) | el **vmid**: el menor libre **de todo el clúster** |
| recursos (cores, memoria, disco) | el **nombre canónico**: `<nombre-lab>-<rol>` |
| bridges del lab y direcciones | la **MAC**: derivada del vmid (`BC:24:11:` + los 3 bytes bajos) |
| orden de arranque por escalones | la **descripción**: `lab=<lab> rol=<rol> gestionado por netlabs_v4_b` |
| | la **pertenencia al pool**: el invitado se crea dentro del pool del lab |
| | el **`comments` del bridge**: `lab=<lab> gestionado por netlabs_v4_b`, sólo si el motor lo crea él |

**El vmid y la MAC no se declaran nunca.** Las pruebas: añadir un lab nuevo no
modifica ni un fichero de `deployment_engine/` (`check pureza-lab`), y dos labs
distintos reciben identidades disjuntas (tests con fixtures).

**Sin fichero de estado.** La asignación se **re-deriva** en cada ejecución
leyendo la API, con tres piezas: el **pool del lab** (llamado como su carpeta) es
la frontera de propiedad, la **descripción** de cada invitado lleva el rol, y el
**`comments` de cada bridge que creó el motor** lleva el lab —sin esa marca, un
bridge no se puede reclamar, porque no hay pool que lo contenga (§Los bridges). Eso
es el estado del sistema, no una caché nuestra. Un invitado borrado a mano no se
recupera del repo: se declara como falta y `apply` lo recrea con el vmid libre que
toque.

El asignador (`filter_plugins/identidad.py`) es una **función pura** —*(estado del
mundo, declaración) → mapa rol→identidad*— y por eso se prueba con fixtures, sin
Proxmox.

### Convivencia entre labs

Varios labs pueden estar desplegados a la vez en el mismo nodo.

- Cada lab tiene **su pool**, y el pool nunca se comparte.
- El vmid se elige mirando **todo el clúster**, no sólo el pool: un vmid de otro
  lab jamás se reutiliza. Por eso dos labs **no pueden chocar de vmids por
  construcción**.
- Lo que sí puede chocar es lo **declarado** (un bridge con el mismo nombre en dos
  labs, dos labs usando la misma dirección). Eso lo caza un check offline:
  `./lab check colisiones` deriva la declaración de **todos** los labs y exige que
  los conjuntos declarados (bridges, direcciones, nombres canónicos) sean
  **disjuntos dos a dos**.

**Honestidad:** `colisiones` prueba la disjunción de *lo declarado*. La disjunción
de los *vmids* **no se puede probar sin credenciales** —los asigna el motor al
aplicar—. Está dicho aquí y no se maquilla.

**El límite de esa garantía: es *en serie*.** La identidad se deriva **una vez**, al
calcular el plan, de una sola lectura del clúster: dos `apply` **en vuelo a la vez**
leen el mismo mundo y proponen el mismo vmid libre. Está medido sin escribir nada —
dos `plan --api` lanzados en paralelo sobre el mismo clúster proponen el mismo
número, y sus diarios sólo tienen `GET`—, y el segundo `create` lo rechazaría la API
por vmid ocupado. Concurrencia de verdad exigiría serializar la asignación, o
reintentar el paso, y no está: **se aplica un lab y luego el siguiente**.

Los tres labs de este repositorio **sí conviven** desplegados a la vez —nueve
invitados, tres pools, vmids disjuntos, cada uno en su bridge y todos verificados—
porque se aplicaron **uno tras otro**. Lo que no está probado, y por eso no se debe,
es lanzarlos en paralelo.

---

## Verificación: no se cree a sí misma

`verify` (y la parte de verificación de `apply`):

1. **deriva de la declaración** el conjunto de roles, bridges y campos que *deben*
   existir;
2. **lee de la API** el conjunto que *existe* —el pool del lab y la configuración
   de cada invitado— y de ahí reconstruye el mapa **rol→vmid**;
3. compara **en los dos sentidos**: falta algo = fallo; **sobra algo = también
   fallo** (un invitado en el pool del lab que ya no está declarado delata una
   copia a mano o un borrado que se quedó atrás);
4. por invitado, comprueba los campos declarados (cores, memoria, red, descripción,
   bridge) y si está arrancado;
5. **mira DENTRO de cada invitado** que declara `config`: relee sus áreas por su
   puerta —REST del router, SSH del Linux— y las compara con lo declarado **en los
   dos sentidos**, con el **mismo driver** que usa `apply` pero en modo **sólo
   lectura** (no escribe nada: comprobar no cambia el mundo). Si el camino no
   responde, no se entra y cada invitado queda **«no comprobable»** con su motivo:
   el veredicto cae, porque **no se aprueba lo que no se ha mirado**;
6. falla con código de salida ≠ 0 si hay drift, dejando el informe en
   `labs/<lab>/logs/verify-<timestamp>.json` **y** un resumen humano en la salida.

El test **nunca recorre la lista que él mismo trae**: el conjunto esperado se
deriva de la declaración; la declaración es la entrada, no el resultado.

**Lo que `preflight` no puede probar:** un `preflight` de sólo lectura no puede
demostrar que una tarea de Proxmox vaya a completarse. Y un invitado que existe
pero está en el pool de otro lab se reporta como **"de otro lab"**, no como propio.

---

## Documentación con dos regiones y punteros bidireccionales

El fichero de un lab (`labs/<lab>/<lab>.md`) tiene **dos escritores y dos
regiones**, porque el problema no es "plantilla contra libertad": es **dos
escritores sobre el mismo fichero**.

- **Región generada**, entre `<!-- generado:inicio -->` y `<!-- generado:fin -->`:
  tablas y datos derivados de la declaración, escritos por
  `deployment_engine/tools/documentos.py`. **Prohibido escribir a mano dentro**:
  `./lab check docs` falla si el fichero no coincide con su render, y la
  herramienta **falla** (no adivina, no trunca) si los marcadores faltan o se
  duplican.
- **Región de prosa**, todo lo que queda fuera: narrativa libre —por qué esta
  topología, qué se rompió, qué límite tiene, qué se aprendió al ejecutarla—.
  **Ningún check opina sobre su contenido.** La única regla es no repetir valores
  que ya están en la tabla: si hace falta el dato, se añade a la tabla.

Regla de oro: **los datos no envejecen porque se regeneran; la prosa no envejece
porque se revisa con un aviso de caducidad, no con un render.**

### Las tres guardas

1. **Punteros vivos** (`./lab check links`): cada enlace de un `.md` a una ruta
   del repo tiene que resolver a un fichero existente.
2. **Índice inverso + caducidad** (`./lab check refs <ruta>`): dado un fichero del
   motor, dice **qué documentos lo citan** —el cambio va al revés del puntero: quien
   cambia el código revisa los docs—. Un **sellado por hash**
   (`docs/revisiones.json`) guarda el hash de cada fichero citado en el momento en
   que el documento se revisó; el check **avisa solo** de qué documentos han dejado
   de estar revisados, y se re-sella al confirmar que la prosa sigue siendo cierta.
3. **Hook `pre-commit`** (se activa una vez por clon con
   `git config core.hooksPath .githooks`): si lo que commiteas toca
   `deployment_engine/`, imprime los `refs` de cada fichero y **bloquea** si la
   región generada de algún `.md` difiere de su render (es un hecho mecánico, se
   puede bloquear); la caducidad sólo **avisa** (exige criterio).

La frase que lo justifica: **«una afirmación de comportamiento que puede ser un
check, no se queda en prosa».**

---

## Checks: uno solo, mecánico y sin credenciales

`./lab check` (o `./lab check <nombre>`) corre todos los checks del motor **sin
credenciales y sin Proxmox**:

| check | qué exige |
| --- | --- |
| `links` | cada enlace markdown de un `.md` resuelve a una ruta existente |
| `docs` | la región generada de cada `.md` es **idéntica** a su render |
| `refs` | qué documentos citan un fichero, y cuáles están caducados desde su sellado |
| `puerta` | las cuatro puertas: `/api2/json` sólo en `pve_api.yml`, `/rest` sólo en `ros_api.yml`, el SSH del interior sólo en `interior_ssh.yml` / `inventario_invitados.yml`, el protocolo de consola sólo en `camino_consola.yml` |
| `privilegios` | nada del motor concede privilegios de la API fuera de la guarda de `preflight`, y ningún invitado declarado nace privilegiado |
| `supernet` | toda dirección y todo rango de un lab cae dentro de su `lab.supernet`, y los supernets de dos labs no se solapan |
| `declaracion` | coherencia del estado deseado: un rol en dos listas, un bridge citado que no existe, dos roles con la misma dirección, un bridge con un nombre que el núcleo rechazaría (guiones, >15 caracteres), un `dhcp` con áreas que pidan entrar… |
| `colisiones` | los labs declarados no comparten bridges, direcciones ni nombres |
| `pureza-lab` | ni un valor de lab (ni su nombre) dentro de `deployment_engine/` |
| `readme` | el README no lleva ningún valor de lab |

Cada check grita con **el fichero y el comando que lo arregla**.

### Si pasa X, corre Y

| Si… | Corre |
| --- | --- |
| cambiaste `labs/<lab>/<lab>.yml` | `./lab --lab <lab> plan` y luego `./lab check docs` |
| cambiaste un lab con `config:` (un driver, un área) | `./lab --lab <lab> plan --api` y `./lab check docs` |
| cambiaste un playbook, tarea, filtro o herramienta | `./lab check refs <ruta>` y revisa los docs que salgan |
| tocaste un driver del interior (`routeros`/`linux`) | `./lab check puerta` + `python3 test/test_interior.py` y `test/test_routeros.py` |
| cambiaste el texto de prosa de un `.md` | `./lab check docs --sellar <doc>` |
| creaste o borraste ficheros | `./lab check links` |
| antes de cualquier commit | `./lab check` (todo) + `ansible-lint` |
| vas a decir "hecho" | `./lab check` verde y la evidencia pegada en la respuesta |

---

## Qué está verificado y qué no

Esta sección no lleva adjetivos.

**Verificado dentro de este repositorio, con la salida real del comando:**

- `./lab check` en verde con los **diez** checks, **y cada uno se ha visto fallar** al
  romper a propósito lo que vigila (los del ejercicio de abajo, con su salida literal;
  `refs` y `readme` al construir el repositorio).
- `ansible-lint` sin hallazgos y `--syntax-check` correcto en todos los playbooks.
- `./lab list` y `./lab --lab <lab> plan` de las **tres topologías declaradas**:
  planes **distintos**, coherentes y ordenados, derivados de la declaración.
- El asignador de identidad probado con fixtures (`test/`), incluido el caso que
  **debe** fallar.
- `./lab --lab <lab> verify` **alcanza la API y falla limpiamente** (sin traceback)
  cuando las credenciales no son válidas, dejando su informe en `logs/`.

**Desplegado contra un Proxmox real (VE 9.2.21), con la evidencia en `logs/`:**

- **Tres topologías** (dos de ejemplo y una de complejidad media) desplegadas y
  verificadas **una tras otra**: `apply` converge y `verify` da CORRECTO con los
  invitados existiendo, coincidiendo y arrancados
  (`labs/<lab>/logs/verify-<ts>.json`).
- **Idempotencia**: una segunda ejecución seguida de `apply` sale `changed=0` y su
  diario sólo tiene `GET` (regla 6).
- **La fase 2, contra el mismo VPS**: el lab de aceptación (seis invitados, dos CHR, tres
  escalones, el puesto de control con su camino) se despliega, **converge en UNA sola
  pasada** y da `verify` CORRECTO (`labs/<lab>/logs/verify-<ts>.json`); la
  segunda pasada de `apply` deja el diario de la API y el del interior **sólo con
  lecturas**, y el plan ya **no reemite** `construir_camino` cuando el camino responde.
- **`verify` mira DENTRO**, no sólo el mundo de la API: relee cada invitado que declara
  `config` por su puerta —REST del router, SSH del Linux— y lo compara con lo declarado
  **en los dos sentidos**, con el **mismo driver** que usa `apply` pero en modo **sólo
  lectura**. Medido: `verify` da CORRECTO con «**3/3 invitado(s) leído(s) por dentro y
  coincidente(s)**» y **cero** escrituras en el diario de la API; y con el camino caído
  cada invitado queda «no comprobable» y el veredicto **cae**, porque no se aprueba lo
  que no se ha mirado.
- **Convivencia**: las tres topologías declaradas, **desplegadas a la vez** (nueve
  invitados en tres pools, con vmids disjuntos y cada invitado en el bridge de su
  lab) y verificadas las tres con `verify` en verde. Después se destruyeron las
  tres y el nodo quedó **sin ningún pool**.
- **El ciclo entero, con vuelta**: `destroy` se lleva los invitados, el pool y
  **sus** bridges, y lo dice bridge a bridge en su salida. Probado en las dos
  direcciones contra el nodo real: un bridge que **ya estaba** en el nodo antes de
  que el lab llegara (sin marca) se **conserva** —`destroy` lo reporta con su motivo
  y no gasta ni una llamada en mirar quién lo usa—, y un bridge **creado** por el
  motor (con su marca `lab=<lab>` en el `comments`) se **borra**: `DELETE
  /nodes/<nodo>/network/<bridge>` por bridge y **una sola** `PUT /nodes/<nodo>/network`
  al final, con el nodo quedando limpio (cero pools, cero invitados del lab, cero
  bridges suyos). Los huérfanos anteriores a la marca se quitaron a mano por la API.

**No verificado, y por qué:**

- **La disjunción de vmids no se puede comprobar sin credenciales**: los asigna el
  motor al aplicar, leyendo el clúster.
- `preflight` de sólo lectura **no puede probar** que una tarea de Proxmox vaya a
  completarse.

### El ejercicio de romper los checks a propósito

Para saber que un check sirve hay que verlo gritar. Esto es lo que se rompió y lo
que dijo, **literal**:

**1. Un enlace a una ruta borrada** (en la prosa del documento de un lab):

```
FALLA links: hay punteros a rutas que ya no existen:
  - labs/lab-minimo/lab-minimo.md: el enlace `../../deployment_engine/tasks/NO-EXISTE.yml` no resuelve a ninguna ruta
```

**2. La tabla generada editada a mano** (un valor cambiado dentro de los marcadores):

```
FALLA docs: la región generada de labs/lab-minimo/lab-minimo.md no coincide con su render.
            Arréglalo con: ./lab check docs --actualizar
```

**3. El nombre de un lab escrito dentro del motor** (`deployment_engine/vars/engine.yml`):

```
FALLA pureza-lab: el motor contiene valores de un lab (el motor no conoce topologías):
  - deployment_engine/vars/engine.yml contiene el valor del lab 'lab-minimo'
  - deployment_engine/vars/engine.yml contiene el valor del lab 'vmb-lab-minimo'
```

**4. El mismo bridge declarado en los dos labs:**

```
FALLA colisiones: dos labs declaran lo mismo (no pueden convivir):
  - 'ejemplo-topologia' y 'lab-minimo' comparten el bridge: vmb-ejemplo-topologia
```

**4b. Un lab nuevo scaffoldeado sin sustituir el relleno** (`./lab new` copia la
plantilla, y la plantilla lleva direcciones de ejemplo):

```
FALLA colisiones: dos labs declaran lo mismo (no pueden convivir):
  - 'ejemplo-topologia' y 'prueba-temporal' comparten la dirección: 192.0.2.11
```

**5. Una llamada a la API fuera de la puerta** (en `deployment_engine/playbooks/plan.yml`):

```
FALLA puerta: alguien llama a la API fuera de deployment_engine/tasks/pve_api.yml:
  - deployment_engine/playbooks/plan.yml
```

**6. El mismo rol en dos listas del estado deseado** (`vms` y `containers`):

```
FALLA declaracion: el estado deseado es incoherente:
  - labs/lab-minimo/lab-minimo.yml: roles repetidos: ['workstation-1']. Un rol identifica a un invitado y sólo a uno: el nombre canónico y la descripción se derivan de él.
```

**7 y 8. `readme` y `refs`** se vieron fallar al construir el repositorio: el primero,
cuando el README afirmaba por su cuenta el nombre de un bridge de un lab; el segundo,
cuando un documento citaba el motor y no estaba sellado. El aviso de caducidad de
`refs`, además, sale en cada edición del motor:

```
AVISO refs: README.md cita `deployment_engine/tools/framework_check.py`, que ha cambiado desde que se revisó
```

## Cómo se comprueba todo, con los comandos exactos

```bash
./lab check                          # los diez checks, sin credenciales ni Proxmox
python3 test/test_identidad.py       # los casos del asignador, con fixtures
python3 test/test_bridges.py         # la propiedad de los bridges: qué borra destroy
python3 test/test_interior.py        # el driver PURO del interior: (declarado, leído) → pasos
python3 test/test_routeros.py        # el driver de RouterOS: el baile de credenciales, la retirada
python3 test/test_declaracion.py     # el validador: caza lo que tiene que cazar
python3 test/test_regresion_planes.py  # los labs de fase 1 no cambian ni un paso
ansible-lint                         # perfil basic, 0 hallazgos
yamllint -c .yamllint .              # 0 hallazgos
for p in deployment_engine/playbooks/*.yml; do ansible-playbook --syntax-check "$p"; done
./lab list
./lab --lab <lab> plan               # offline: no hace falta ningún Proxmox
```

---

## Decisiones conscientes

- **Las credenciales van en claro** en `deployment_engine/secrets.yml`
  (gitignored, 0600, escrito a mano: no se versiona ningún `.example`). En este
  MVP, funcionalidad y simplicidad por encima de seguridad; no hay cifrado de
  secretos ni lectura de variables de entorno. El aviso está en la cabecera de
  `AGENTS.md` §Reglas duras.
- **No hay variables de entorno, by design.** Ningún valor de configuración se lee
  de `os.environ`: sale de `secrets.yml`, `vars/engine.yml` y la declaración del
  lab. El wrapper `./lab` no exporta nada.
- **El host de la API y el nombre del nodo son DOS valores.** `pve_nodo` es el host
  de la URL; `pve_nombre_nodo` es el nombre con el que Proxmox conoce al nodo (lo
  que va en las rutas `/nodes/<nombre>/...`). En un nodo único suelen coincidir,
  pero pueden no hacerlo (un nodo llamado `Proxmox` alcanzado por su IP): usar el
  host como nombre de nodo hace que la API responda 596 "no such node".
- **Lo asíncrono se espera sondeando la API, no con un `until`.** Proxmox responde
  un `UPID` y trabaja en segundo plano; el motor sondea la tarea por la puerta
  (`tasks/esperar_tarea.yml`) para que **cada sondeo deje su línea en el diario**.
  Un `retries`/`until` de Ansible habría sondeado a espaldas del diario.
- **Sólo `ansible.builtin`.** El motor no instala ni usa ninguna colección.
- **El motor nunca borra** un invitado que no esté en la declaración: borrar es
  `destroy`, que se niega si el invitado sigue declarado.

## Fuera de alcance (extensiones futuras)

Una línea cada una, y nada más:

- **Aplicaciones dentro de los invitados** (ficheros, paquetes, servicios): el
  vocabulario llega a la **configuración de red del equipo** (RouterOS, Linux), no a
  lo que corre encima. El punto de extensión es una primitiva nueva del motor, con
  su ADR.
- **Cloud-init y plantillas de disco** más allá del mínimo para que un invitado
  arranque.
- **Inventario dinámico** de los invitados desplegados.
- **Clúster y multi-nodo**, HA, Ceph.
- **Snapshots y backups**.
- **CI/CD** y cifrado de secretos.

## Ver también (punteros al código, del documento al fichero)

- La **puerta única** a la API y el diario de cada llamada:
  [deployment_engine/tasks/pve_api.yml](deployment_engine/tasks/pve_api.yml)
- El **asignador de identidad** (vmid, nombre canónico, MAC):
  [deployment_engine/filter_plugins/identidad.py](deployment_engine/filter_plugins/identidad.py)
- La **comparación por conjuntos** de la verificación:
  [deployment_engine/filter_plugins/estado.py](deployment_engine/filter_plugins/estado.py)
- El **plan ordenado**:
  [deployment_engine/tools/plan.py](deployment_engine/tools/plan.py)
- Los **checks** del motor:
  [deployment_engine/tools/framework_check.py](deployment_engine/tools/framework_check.py)
- El **driver puro del interior** (declarado + leído → pasos, en los dos sentidos):
  [deployment_engine/filter_plugins/interior.py](deployment_engine/filter_plugins/interior.py)
- El **camino del puesto de control** (la consola, el túnel, el puerto derivado):
  [docs/camino-del-puesto-de-control.md](docs/camino-del-puesto-de-control.md)
- Las **decisiones** que no se re-litigan:
  [0001](docs/decisiones/0001-solo-api-de-proxmox.md),
  [0002](docs/decisiones/0002-el-pool-como-frontera-de-propiedad.md),
  [0003](docs/decisiones/0003-documento-con-dos-regiones.md),
  [0004](docs/decisiones/0004-el-camino-y-el-token.md),
  [0005](docs/decisiones/0005-el-driver-del-interior.md),
  [0006](docs/decisiones/0006-escribir-en-routeros.md),
  [0007](docs/decisiones/0007-las-patas-se-declaran.md),
  [0008](docs/decisiones/0008-una-direccion-por-pata.md),
  [0009](docs/decisiones/0009-verify-mira-dentro.md)
