# netlabs-iac — motor de despliegue en Proxmox por su API REST

Un **motor IaC escrito en Ansible** que, a partir de la **declaración de una
topología**, crea, actualiza, arranca, verifica y destruye invitados (VMs QEMU y
contenedores LXC) en un nodo Proxmox **sólo por su API REST** —y que además
**configura el interior de cada invitado** (RouterOS por su REST, Linux por SSH),
dejando cada paso en su diario.

El valor de este repositorio no son las topologías que despliega: es **el motor y
su forma de trabajar** —declaración, verbos, identidad asignada por el propio
motor, **cuatro vías de acceso y tres diarios**, verificación por conjuntos en los dos
mundos (el de la API y el del interior), y documentación con punteros
bidireccionales—. Las topologías viven cada una en su carpeta (`labs/`) y **el
motor no conoce ninguna**.

---

## Arquitectura: dos capas y sólo dos

| Capa | Dónde | Qué es |
| --- | --- | --- |
| **El motor** | `deployment_engine/` | todo lo compartido por todos los despliegues: las **vías de acceso** (API de Proxmox, REST de RouterOS, interior Linux, consola) y sus diarios, el asignador de identidad, la validación, el plan, los **drivers del interior**, los checks y las plantillas |
| **Las topologías** | `labs/<nombre>/` | *una carpeta por lab*: su declaración (`<nombre>.yml`), su documento (`<nombre>.md`) y sus logs (`logs/`, gitignored) |

La pregunta que decide dónde va algo: **¿esto seguiría igual si desapareciera el
lab?** Sí → motor. No → lab.

El motor **no lee `labs/`**: el nombre del lab es siempre un parámetro del verbo,
nunca una ruta fija ni un valor incrustado. Los *checks* sí lo leen, porque son
herramientas de desarrollo, no el motor.

### El mapa del repositorio

```
netlabs-iac/
├── README.md            este fichero: el MOTOR. Ni un valor de ningún lab.
├── AGENTS.md            el esquema que se inyecta en el prompt de un agente IA.
├── VERSION              la última versión publicada (una línea: `0.1.0`) -- ADR 0017.
├── CHANGELOG.md         qué entró en cada versión. Se escribe a mano, al publicar.
├── lab                  ÚNICO punto de entrada (script Python 3, stdlib). También dice
│                        la versión: `./lab version`, `./lab check version`.
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
│   ├── tasks/                las CUATRO vías de acceso y sus diarios: pve_api.yml (API
│   │                         de Proxmox → api.jsonl), ros_api.yml (REST de
│   │                         RouterOS, por el túnel del puesto → api.jsonl),
│   │                         interior_ssh.yml (interior Linux → interior.jsonl),
│   │                         console.yml (consola → console.jsonl); más
│   │                         los drivers (configurar_routeros.yml,
│   │                         configurar_linux.yml), el túnel (tunnel.yml,
│   │                         tunnel_probe.yml), el inventario en memoria
│   │                         (guest_inventory.yml), la sonda (sonda.yml),
│   │                         la espera (esperar_tarea.yml) y validar.yml
│   ├── filter_plugins/       lo que Ansible calcula en Jinja: declaracion.py,
│   │                         identidad.py, estado.py, interior.py (el driver
│   │                         PURO del interior)
│   ├── tools/                capa Python stdlib: plan.py, documentos.py,
│   │                         console.py, framework_check.py
│   └── templates/            SÓLO la región generada del doc de un lab
├── docs/                     documentación que NO es código ni un lab:
│   ├── decisiones/           ADRs: pocos, y sólo los que no quieres re-litigar
│   ├── crear-un-lab.md       la guía de declaración, decisión por decisión
│   ├── tunnel-del-bastion.md cómo funciona el túnel (prosa)
│   ├── informe-*.md          informes de trabajo (estado del arte, rendimiento)
│   └── encargo-*.md          encargos ejecutados (registro de una fase)
├── scripts/                  herramientas de DESARROLLO (no las usa el motor):
│   ├── perfilar.sh           perfila UN verbo sellando cada línea de su salida
│   └── analizar_perfil.py    lee ese perfil y dice dónde se va el tiempo
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
./lab --lab <nombre> test        # ¿el lab HACE lo que promete? (ping/servicio/dns; 0/1/3)
./lab --lab <nombre> capture     # mira el tráfico de un bridge, un rato
./lab --lab <nombre> impair      # estropea el tráfico un rato, y lo deja como estaba
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
resto (vmid, MAC, el nombre, pool) lo deriva el motor leyendo el clúster.

**Cómo se declara un lab.** `./lab new <nombre>` scaffoldea la carpeta desde
`labs/.plantilla/` y le pone **delante el siguiente número libre** (`07_lo-que-sea`),
porque los labs se ordenan por antigüedad y `ls labs/` tiene que leerse en orden
histórico (ADR 0016). Se rellena el YAML — las decisiones, una por una, con su trampa
y el check que las vigila, están en [docs/crear-un-lab.md](docs/crear-un-lab.md):

```yaml
lab:
  nombre: 07_lo-que-sea    # EXACTAMENTE el nombre de la carpeta: es el pool
  stages: [1, 2]        # orden de arranque: primero el 1, después el 2
  bridges:                 # los crea el motor si faltan (los bridges son del nodo)
    - nombre: vmb_algo     # nombre de interfaz válido: sin guiones, ≤15 caracteres
      address: 192.0.2.1/24
vms:                       # invitados QEMU
  - rol: <rol>             # el rol identifica a un invitado y sólo a uno
    tipo: rt               # QUÉ equipo es: rt/fw/srv/ws/sw/ctl -- obligatorio (ADR 0015)
    nombre: 1              # opcional: su alias corto. Sin él, el alias es el rol
    stage: 1
    cores: 2
    memory: 512
    disk: 8
    bridge: vmb_algo
    address: 192.0.2.2/24
containers:                # invitados LXC
  - rol: <otro-rol>
    tipo: ws
    stage: 2
    cores: 1
    memory: 256
    disk: 4
    bridge: vmb_algo
    address: 192.0.2.11/24
```

Los dos invitados de arriba se llamarán `rt-1` y `ws-<otro-rol>` en Proxmox — el nombre
dice qué **es** el equipo, no de qué lab es (ADR 0015).

Lo que **no** se declara, y es a propósito: ni `vmid`, ni MAC, ni el nombre entero (se
compone de `tipo` + alias), ni a qué pool va cada invitado. Eso lo **deriva** el motor
(§Identidad). El YAML dice *qué*, *cómo se llama* y *en qué orden*; nunca dice *con qué
número*.

**El vocabulario del interior (fase 2):** un lab puede además declarar **qué hay que
configurar dentro** de cada equipo, y el motor lo converge como una fase más de su plan.

- **`config:`**, con **exactamente una clave de tipo** (`linux` o `routeros`), que elige el
  driver. Dentro van las **áreas** (los campos que el motor sabe tocar y de los que
  responde): `identity`, `ip_services`, `addresses`, `routes`, `dhcp_server`, `uplink`,
  `firewall` (la tabla de filtrado entera, en orden: ADR 0019), `ip_forward`, `snmp` (que el
  equipo se deje preguntar por SNMP: el motor enciende su agente y le pone **una** comunidad de
  lectura, la constante del motor; ADR 0029), `tunnel`…
  En un Linux, además, **`servicio:`** — el NOMBRE de un servicio de un **vocabulario
  cerrado** (hoy `caddy` y `netxms`) que el motor instala, configura y **comprueba sirviéndolo**
  (ADR 0027 y 0028): el lab declara el nombre, nunca el paquete, su base ni su configuración —
  y **`monitorizacion:`**, que hace que ese servicio **vigile**: el motor le declara las redes
  que el invitado ALCANZA —la suya, derivada de su interfaz, y las de sus **rutas**
  declaradas— como objetivos del descubrimiento activo, y el servidor **ronda solo**; el
  sembrado espera a que sus hallazgos estén en la base. Lo que sondea sale de una RUTA
  declarada (ADR 0032): para que el vigilante llegue a una zona, el lab le da el camino. La
  comprobación de que el servicio SIRVE se hace **autenticando por el API web** (la puerta de la
  interfaz), nunca por la consola del servidor.
  Sólo vale junto a un servicio que sepa vigilar (hoy `netxms`; ADR 0029).
- **`latido:`** en un Linux: una **marca** (`latido: {}`, o con su cadencia `latido: {cada: 5min}`)
  que promete una sola cosa — que ese equipo **se vea** en la topología del vigilante **sin** que
  el vigilante tenga que preguntarle a él. El motor le pone un temporizador que da un toque **a su
  propia pasarela** cada `cada` (2 minutos por defecto): no configura nada suyo ni de la red —ni
  interfaz, ni ruta, ni regla— y lo único que hace es mantener su MAC en la tabla ARP de su router,
  que es lo que el sondeo del vigilante **lee** para encolarlo como nodo. Aparecer así no necesita
  agente SNMP, ni camino hasta el invitado, ni un solo boquete nuevo (ADR 0031).
- **`image:`** en una VM QEMU: el disco de fábrica que se importa al crearla (un CHR).
- **`address:`** admite cuatro formas: `<ip>/<prefijo>` (estática), **`dhcp`** (dinámica: el
  invitado no la declara; se lee del host y, si hay túnel, de la concesión del router),
  **`derived`** (el motor la calcula repartiendo en orden desde `lab.address_space`, sin que el
  lab escriba un número; un valor explícito manda: ADR 0020) o **ausente** (un equipo sin
  dirección: un conmutador puro). **Y va a donde va en una máquina
  de verdad** (ADR 0013): en un contenedor, el motor la escribe en la cadena de red de la interfaz
  (`ip=…`), así que `dhcp` nace **pidiendo** dirección al router de su red (que le da también
  pasarela y DNS) y una estática nace **con** ella. Una estática lleva su **`gateway:`**
  (declarada, no adivinada) para salir sin preguntar a nadie. Un invitado sin `address` nace
  sin ella, como siempre.
- **`ready:`** (por invitado), **`tests:`**, **`capture:`** e **`impairment:`** (del lab) son lo
  que el lab dice de sí mismo, no del equipo: cuánto se le espera a un invitado antes de seguir
  (ADR 0021), qué pruebas funcionales demuestran que el lab HACE lo que promete (`./lab test`:
  `ping`/`servicio`/`dns`; ADR 0022) y qué experimento se puede encender y apagar (`./lab
  capture`, `./lab impair`; ADR 0023). **Ninguno entra en la convergencia**: `apply` no captura,
  no estropea y no prueba nada.
- **`static_leases: derived`** es la única forma de declarar reservas DHCP de un router: el
  motor reserva, por la MAC que **deriva del vmid**, cada dirección estática declarada por
  otro invitado **de la misma red** —excluyendo al propio servidor—. El ámbito lo dice la
  **red que sirve cada servidor** (`red.prefijo`), así que un router con dos LANs reserva en
  cada una lo que vive en ella y no toca lo de la otra; y una concesión que no diga a qué
  servidor pertenece se atribuye a la red en la que cae su dirección. (Sin `red` declarada,
  el ámbito es el bridge del invitado: es el caso de un Linux que sirve la suya.) Una MAC en
  un YAML es un bug.
- **`lab.espacio de direcciones`** acota todo lo del lab (lo vigila el check `address_space`), y
  **`lab.túnel`** pide el bastión que construye el motor (§`docs/tunnel-del-bastion.md`).

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
./lab --lab <lab> test         # ¿HACE lo que promete? (lo que declara `tests:`)
./lab --lab <lab> capture      # mira el tráfico un rato (`capture:`)
./lab --lab <lab> impair       # lo estropea un rato y lo deja como estaba (`impairment:`)
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
```

Los avisos que ya estaban escritos siguen valiendo: el token de Proxmox
**equivale a root y no caduca** —trátalo como una contraseña de root—, y
`pve_nodo` y `pve_nombre_nodo` son **dos valores distintos**: el host de la URL y
el nombre con el que la API conoce al nodo. Usar el host como nombre de nodo hace
que la API conteste `596 no such node`.

`./lab` comprueba que el fichero exista **antes de lanzar nada** cuando el verbo
necesita la API, y lo dice en claro si falta. `plan` sin `--api` no lo necesita:
usa un fixture.

#### Si prefieres no tenerlos en claro: sops/age (ADR 0025)

Los mismos secretos pueden vivir **cifrados y versionados** en
`deployment_engine/secrets.sops.yml` (con [sops](https://github.com/getsops/sops) y
age). El wrapper es el único que lo sabe: si encuentra el cifrado y no hay un
`secrets.yml` en claro más nuevo, lo descifra a ese mismo `secrets.yml` (gitignored,
0600) y sigue. **Ninguna tarea del motor cambia.**

La clave privada vive en `deployment_engine/age.key` (gitignored, 0600) y se le pasa a
sops con `--age-key-file`, **una bandera y no una variable**: el motor sigue sin leer
`os.environ` (regla 3). Cifrar, una vez:

```sh
age-keygen -o deployment_engine/age.key            # guarda la PÚBLICA que imprime
chmod 600 deployment_engine/age.key
sops --encrypt --age <tu-clave-pública> --input-type yaml --output-type yaml \
     deployment_engine/secrets.yml > deployment_engine/secrets.sops.yml
git add deployment_engine/secrets.sops.yml         # el CIFRADO sí; la clave NO
```

Si falta el binario `sops` o la clave, el verbo **para** diciendo cuál falta — pero
**sólo si el verbo va a hablar con la API**: `plan` sin `--api` planifica contra un
fixture y no necesita credenciales, así que no las descifra. El candado
`./lab check secretos` no bloquea el fichero cifrado (un valor `ENC[...]` no es
un secreto en claro) y sí reconoce la forma de la clave de age, que no se versiona.

Cuidado con la vía de SSH, que es **sólo para quien diagnostica** (el motor no entra
por SSH jamás, ni para converger ni para leer): no hay contraseña en `secrets.yml` que
valga —el nodo **no acepta contraseña**: su `sshd` ofrece `publickey` a secas—. Lo que
entra es la clave `~/.ssh/netlabs_v4b_debug`, ya autorizada en el nodo. Y sigue siendo
**el último recurso**: primero se agota la API, y si algo no se puede saber por API se
dice, no se rodea.

### El agente de invitado: lo que el motor puede LEER de una VM

El token lleva `VM.GuestAgent.Audit` y con eso el motor le pregunta a una VM por sus
interfaces (`GET /nodes/<n>/qemu/<vmid>/agent/network-get-interfaces`) **por la
vía de acceso**, como cualquier otra llamada: su respuesta queda en `api.jsonl`. Es la única
forma de saber qué dirección usa una VM QEMU —su config no la lleva, la pone el
invitado por dentro—, así que es lo que permite que el bastión ya no elija la
suya dándole la espalda a las VMs. Por eso **toda VM nace con `agent: 1`**: el canal
aparece al arrancar, y esto se decide al nacer, como el bus del disco. Lo que ese
privilegio concede es corto y está medido en el código de PVE del nodo: lecturas y
`ping`. Lo que el motor NO puede hacer con él —leer o escribir ficheros dentro del
invitado, congelar su sistema de ficheros, ejecutar programas— sigue vedado a
propósito: es un canal de lectura, no una vía de acceso al interior. Está razonado, con su
medida y su A/B, en [0011](docs/decisiones/0011-el-agente-de-invitado.md).

### Los bridges: qué se lleva `destroy` y qué no

`destroy` borra los invitados del lab, su pool y **los bridges que creó él** —y nada
más—. La diferencia importa, porque un bridge **no está en ningún pool**: Proxmox no
mete interfaces de red en pools, así que aquí la frontera de propiedad no sirve y el
motor necesita otra prueba.

La tiene: cuando `apply` **crea** un bridge le escribe en el `comments` la marca del
motor (`lab=<lab> gestionado por netlabs_v4_b`), y `destroy` sólo borra un bridge si
se cumplen **las dos** condiciones:

1. su `comments` lleva la marca de **este** lab (consta que lo creó él), y
2. **ningún invitado de fuera del lab lo está usando** — se miran **todas** las interfaces
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

## Las cuatro vías de acceso, y un diario de cada una

Al mundo se le habla por **cuatro vías de acceso**, y por ninguna otra: a **Proxmox** por
`tasks/pve_api.yml` (`/api2/json`, con `ansible.builtin.uri`), a **RouterOS** por
`tasks/ros_api.yml` (su `/rest/…`, al que el motor llega por el túnel del puesto de
control: la llamada la hace el motor en su máquina, sin `delegate_to`), al
**interior Linux** por `tasks/interior_ssh.yml` (SSH), y a la **consola de la API**
sólo desde `tasks/console.yml`. Ningún play llama "por fuera", y el wrapper
`./lab` **no llama a nada**: sólo valida y lanza `ansible-playbook`.

Cada vía de acceso deja **su diario**, y los tres son sagrados: `logs/api.jsonl` (cada
llamada a Proxmox y a RouterOS, con un campo `api` que dice a cuál y el rol del
invitado), `logs/interior.jsonl` (cada paso dentro de un Linux) y
`logs/console.jsonl` (cada uso de la consola). Una línea JSON por operación, con su
`ts`, su verbo y su resultado (truncado a `engine_diario_max_cuerpo`). **Si una
ejecución no dejó diario, no ocurrió.** Ni la cabecera `Authorization` ni una
contraseña o una clave se escriben jamás en un diario.

El check `gateway` vigila mecánicamente las cuatro: la ruta base de Proxmox
(`/api2/json`) sólo puede aparecer en `pve_api.yml`, la de RouterOS (`/rest`) en
`ros_api.yml`, los parámetros de conexión SSH a un invitado en `interior_ssh.yml` /
`guest_inventory.yml`, y el protocolo de consola en `console.yml`.

Los logs son **del lab** y van gitignored: son artefactos de ejecución que rotan,
y lo que se versiona es la evidencia que se cita en la prosa del lab, no el
fichero entero.

### Lo asíncrono se espera, y se espera por la vía de acceso

Proxmox crea, borra y recarga la red **en segundo plano**: la llamada responde un
`UPID` y el trabajo continúa. Un paso que arranca un invitado no puede correr
contra algo que aún se está creando. Por eso cada paso del plan pasa por
`deployment_engine/tasks/pve_api_y_esperar.yml`, que ejecuta la llamada por la
vía de acceso y, **si la respuesta es un `UPID`**, espera sondeando
`GET /nodes/<nodo>/tasks/<upid>/status` hasta que la tarea deja de estar `running`.

La espera es **una regla, no una lista**: cualquier paso asíncrono (crear, borrar,
recargar la red) queda cubierto sin enumerarlo. Y **cada sondeo pasa por la misma
vía de acceso**, así que cada uno deja su línea en el diario: la espera no es una llamada
a espaldas del diario. El bucle es finito: `engine_tarea_intentos` sondeos (40 por
defecto) con una espera **creciente** entre uno y otro —`engine_tarea_intervalo` (2 s)
al principio y hasta `engine_tarea_intervalo_max` (15 s) al final, ≈5 min 40 s de
tope—, para detectar una tarea corta enseguida sin pagar las vueltas que no hacen falta
cuando la tarea ya terminó. Si se agota, o si la tarea termina con `exitstatus`
distinto de `OK`, el verbo **falla** y lo dice.

---

## Identidad: quién pone los números

El motor **no conoce topologías, pero sí el mecanismo de identidad**. Lo que no
puede haber dentro del motor es un **valor**: ni una lista de labs, ni bandas de
vmids, ni el nombre de un bridge. Sí hay **reglas**.

| El lab declara | El motor deriva |
| --- | --- |
| roles lógicos y su virtualización (VM/LXC) | el **vmid**: el menor libre **de todo el clúster** |
| el **tipo de equipo** de cada invitado (`tipo:`: `rt`/`fw`/`srv`/`ws`/`sw`/`ctl`) | el **nombre**: `<tipo>-<alias>` — qué EQUIPO es, no de qué lab es (ADR 0015) |
| el `nombre:` corto de un invitado (opcional: su alias) | ...y si no lo declara, el alias es su rol: `rt-borde`, `srv-1`, `ws-2` |
| recursos (cores, memoria, disco) | la **MAC**: derivada del vmid (`BC:24:11:` + los 3 bytes bajos) |
| bridges del lab y direcciones | la **descripción**: `lab=<lab> rol=<rol> gestionado por netlabs_v4_b` |
| orden de arranque por etapas | la **pertenencia al pool**: el invitado se crea dentro del pool del lab |
| | el **`comments` del bridge**: `lab=<lab> gestionado por netlabs_v4_b`, sólo si el motor lo crea él |

**El vmid y la MAC no se declaran nunca**, y el **tipo de equipo sí**: sin él no hay nombre que
derivar. **Dos labs pueden repetir nombre** (`rt-nucleo` en tres labs a la vez) porque el nombre
no es una prueba de pertenencia a propósito — quien la dice es el pool y la descripción. Lo que
**no** se puede repetir es el nombre dentro de un lab: el validador lo rechaza con los dos roles
que chocan. Las pruebas: añadir un lab nuevo no modifica ni un fichero de `deployment_engine/`
(`check pureza-lab`), y dos labs distintos reciben **vmids y descripciones disjuntos** (tests con
fixtures).

**El tipo no es sólo el nombre: manda sobre lo que el equipo puede declarar (ADR 0026).** Un
equipo hace **una** cosa, y el tipo dice cuál: un `rt` **enruta y sale** (y no filtra), un `fw`
**filtra** (y no traduce, ni reparte direcciones, ni es la vía de acceso de nadie), un `sw`
**conmuta** (y no enruta). El validador lo caza con el motivo y con el equipo al que sí le toca,
antes de tocar nada — «un `rt` que filtra es un router con dos trabajos: eso es un `fw`». Cuando
un lab necesita dos funciones, se levantan **dos equipos**: es lo que hace el `08` con su router
y su cortafuegos de borde.

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
   vía de acceso —REST del router, SSH del Linux— y las compara con lo declarado **en los
   dos sentidos**, con el **mismo driver** que usa `apply` pero en modo **sólo
   lectura** (no escribe nada: comprobar no cambia el mundo). Si el túnel no
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
| `access` | las cuatro vías de acceso: `/api2/json` sólo en `pve_api.yml`, `/rest` sólo en `ros_api.yml`, el SSH del interior sólo en `interior_ssh.yml` / `guest_inventory.yml`, el protocolo de consola sólo en `console.yml` |
| `privilegios` | nada del motor concede privilegios de la API fuera de la guarda de `preflight`, y ningún invitado declarado nace privilegiado |
| `address_space` | toda dirección y todo rango de un lab cae dentro de su `lab.address_space`, y los espacios de direcciones de dos labs no se solapan |
| `declaracion` | coherencia del estado deseado: un rol en dos listas, un bridge citado que no existe, dos roles con la misma dirección, un bridge con un nombre que el núcleo rechazaría (guiones, >15 caracteres), un `dhcp` con áreas que pidan entrar… **y además ACONSEJA** lo que es legal pero casi siempre es un olvido (arrancar en la misma etapa que quien te da la dirección, una dirección estática dentro del rango del DHCP, una pasarela que no es nadie del lab, una VM sin imagen, un bridge por el que no pasa nadie, dos DHCP en un bridge): un consejo dice dónde, qué pasa y qué escribir, y **no bloquea** |
| `colisiones` | los labs declarados no comparten bridges, direcciones ni nombres |
| `pureza-lab` | ni un valor de lab (ni su nombre) dentro de `deployment_engine/` |
| `readme` | el README no lleva ningún valor de lab |
| `version` | la versión publicada cuenta lo mismo en los tres sitios donde vive: `VERSION`, el último tag `vX.Y.Z` y su entrada del `CHANGELOG.md` (es del **repositorio**, no del motor: por eso su código vive en `./lab` y no entre los de arriba) |

Cada check grita con **el fichero y el comando que lo arregla**.

### Si pasa X, corre Y

| Si… | Corre |
| --- | --- |
| cambiaste `labs/<lab>/<lab>.yml` | `./lab --lab <lab> plan` y luego `./lab check docs` |
| cambiaste un lab con `config:` (un driver, un área) | `./lab --lab <lab> plan --api` y `./lab check docs` |
| cambiaste un playbook, tarea, filtro o herramienta | `./lab check refs <ruta>` y revisa los docs que salgan |
| tocaste un driver del interior (`routeros`/`linux`) | `./lab check access` + `python3 test/test_interior.py` y `test/test_routeros.py` |
| cambiaste el texto de prosa de un `.md` | `./lab check docs --sellar <doc>` |
| tocaste `VERSION` o el `CHANGELOG.md`, o vas a publicar | `./lab check version` |
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
  etapas, el bastión con su túnel) se despliega, **converge en UNA sola
  pasada** y da `verify` CORRECTO (`labs/<lab>/logs/verify-<ts>.json`); la
  segunda pasada de `apply` deja el diario de la API y el del interior **sólo con
  lecturas**, y el plan ya **no reemite** `construir_túnel` cuando el túnel responde.
- **`verify` mira DENTRO**, no sólo el mundo de la API: relee cada invitado que declara
  `config` por su pasarela —REST del router, SSH del Linux— y lo compara con lo declarado
  **en los dos sentidos**, con el **mismo driver** que usa `apply` pero en modo **sólo
  lectura**. Medido: `verify` da CORRECTO con «**3/3 invitado(s) leído(s) por dentro y
  coincidente(s)**» y **cero** escrituras en el diario de la API; y con el túnel caído
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
  - labs/02_lab-minimo/02_lab-minimo.md: el enlace `../../deployment_engine/tasks/NO-EXISTE.yml` no resuelve a ninguna ruta
```

**2. La tabla generada editada a mano** (un valor cambiado dentro de los marcadores):

```
FALLA docs: la región generada de labs/02_lab-minimo/02_lab-minimo.md no coincide con su render.
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

**5. Una llamada a la API fuera de la vía de acceso** (en `deployment_engine/playbooks/plan.yml`):

```
FALLA gateway: alguien llama a la API fuera de deployment_engine/tasks/pve_api.yml:
  - deployment_engine/playbooks/plan.yml
```

**6. El mismo rol en dos listas del estado deseado** (`vms` y `containers`):

```
FALLA declaracion: el estado deseado es incoherente:
  - labs/02_lab-minimo/02_lab-minimo.yml: roles repetidos: ['workstation-1']. Un rol identifica a un invitado y sólo a uno: el nombre canónico y la descripción se derivan de él.
```

**7 y 8. `readme` y `refs`** se vieron fallar al construir el repositorio: el primero,
cuando el README afirmaba por su cuenta el nombre de un bridge de un lab; el segundo,
cuando un documento citaba el motor y no estaba sellado. El aviso de caducidad de
`refs`, además, sale en cada edición del motor:

```
AVISO refs: README.md cita `deployment_engine/tools/framework_check.py`, que ha cambiado desde que se revisó
```

---

## Versionado y entrega

La versión es un número, `MAYOR.MENOR.PARCHE` (SemVer), y **no** parte del nombre del
repositorio. Mientras la MAYOR sea `0`, el motor está en desarrollo y **cualquier versión
MENOR puede romper**: es la regla de SemVer para la serie 0.x, y por eso la primera
entrega es `0.1.0` y no `1.0.0`.

La versión publicada vive en **tres sitios** —el fichero `VERSION` (una línea), el tag
`vX.Y.Z` de `main` y su entrada del `CHANGELOG.md`— y los tres tienen que contar lo mismo:
eso es lo que comprueba `./lab check version`, y `./lab version` lo dice en una línea.

El trabajo va en **ramas cortas, una por cambio** (`feat/…`, `fix/…`, `refactor/…`,
`docs/…`, `chore/…`), se cierra con un pull request —donde se cuenta qué cambia y cómo se
ha comprobado— y se mezcla con *squash*: un cambio, un commit en `main`. `main` es lo
publicado y está **siempre verde**. Y publicar es un acto explícito: se pasa
`[No publicado]` del `CHANGELOG.md` a su versión con fecha, se sube `VERSION`, se pone el
tag anotado y se crea la *release*. Una versión no se publica sin el ciclo completo
`destroy → apply → verify` contra un Proxmox real.

El porqué, entero, en [docs/decisiones/0017-la-version-es-un-numero.md](docs/decisiones/0017-la-version-es-un-numero.md).

---

## Cómo se comprueba todo, con los comandos exactos

```bash
./lab check                          # todos los checks (los del motor + `version`), sin
                                     # credenciales ni Proxmox
python3 test/test_identidad.py       # los casos del asignador, con fixtures
python3 test/test_bridges.py         # la propiedad de los bridges: qué borra destroy
python3 test/test_interior.py        # el driver PURO del interior: (declarado, leído) → pasos
python3 test/test_routeros.py        # el driver de RouterOS: el baile de credenciales, la retirada
python3 test/test_declaracion.py     # el validador: caza lo que tiene que cazar
python3 test/test_regresion_planes.py  # los labs de fase 1 no cambian ni un paso
python3 test/test_secretos.py        # el candado: caza lo que abre el NODO, deja en paz lo demás
python3 test/test_secretos_cifrados.py  # el descifrado de `secrets.sops.yml` (sops/age)
python3 test/test_colision.py        # la decisión de reintentar por un vmid que se ocupó
python3 test/test_plan.py            # el plan no da por bueno un invitado en otro sitio
ansible-lint                         # perfil basic, 0 hallazgos
yamllint -c .yamllint .              # 0 hallazgos
for p in deployment_engine/playbooks/*.yml; do ansible-playbook --syntax-check "$p"; done
./lab list
./lab --lab <lab> plan               # offline: no hace falta ningún Proxmox
```

Eso mismo es lo que corre el **CI** en cada push a `main` y en cada pull request
(`.github/workflows/ci.yml`): las pruebas, `./lab check`, `ansible-lint` y `yamllint`,
**sin credenciales y sin tocar ningún Proxmox**. El ciclo `destroy → apply → verify`
contra el nodo de verdad NO lo cubre el CI —necesita el host— y sigue siendo lo que
hace falta antes de dar un cambio por bueno (AGENTS.md §Commits y subida a GitHub).

Además, cada **pull request** pasa por dos revisores automáticos: **Greptile** y
**CodeRabbit** (`.coderabbit.yaml`). CodeRabbit sólo revisa a petición mientras el
repositorio tenga menos de 10 estrellas (es su plan OSS); aun así, su configuración
está en el árbol para que revise con las reglas de la casa el día que le toque.
Ninguno de los dos sustituye al ciclo `destroy → apply → verify`.

**Un PR no se mezcla con Greptile por debajo de 5/5**, y eso no depende de que nadie se
acuerde: lo vigila `.github/workflows/greptile-gate.yml`. Lee la puntuación del **cuerpo
del resumen de Greptile** (que Greptile edita en su sitio: mirar su fecha es leer una
puntuación vieja) y publica un *status check* `greptile-5-de-5`, sobre el SHA de la
**cabecera** del PR, que sólo pasa con 5/5; sin puntuación legible queda en `pending`, que
no es aprobar. Si baja de 5/5, además re-dispara la revisión (`@greptileai review`) hasta
`MAX_REINTENTOS` veces por cabecera, y nunca reacciona a sus propios comentarios.

Ese check **sólo bloquea el merge si está exigido en la protección de rama**, que es un
ajuste de GitHub y no algo que `./lab check` pueda vigilar. Se activa así (deja los push
directos a `main` como están: exige el check al *mezclar*, no al empujar):

```
gh api -X PUT repos/MagicJF/netlabs-iac/branches/main/protection \
  -H "Accept: application/vnd.github+json" \
  -F 'required_status_checks[strict]=false' \
  -F 'required_status_checks[contexts][]=greptile-5-de-5' \
  -F 'enforce_admins=false' \
  -F 'required_pull_request_reviews=' \
  -F 'restrictions='
```

Sin ese ajuste, el check se ve pero no cierra la puerta: se dice, no se maquilla.

---

## Decisiones conscientes

- **Las credenciales van en claro** en `deployment_engine/secrets.yml`
  (gitignored, 0600, escrito a mano: no se versiona ningún `.example`) — o **cifradas**
  en `deployment_engine/secrets.sops.yml` si prefieres versionarlas (ADR 0025). En este
  MVP, funcionalidad y simplicidad por encima de seguridad; **nunca** se leen variables
  de entorno. El aviso está en la cabecera de `AGENTS.md` §Reglas duras.
- **La región generada de un lab no lleva credenciales, ni depende de ellas.** La tabla
  de acceso cita la credencial por su **origen** (`secrets.yml` → `routeros_clave`), no
  por su valor: si dependiera del valor, la región dejaría de ser función de la
  declaración y `./lab check docs` no podría pasar en un clon sin `secrets.yml` (el CI).
- **No hay variables de entorno, by design.** Ningún valor de configuración se lee
  de `os.environ`: sale de `secrets.yml`, `vars/engine.yml` y la declaración del
  lab. El wrapper `./lab` no exporta nada.
- **El host de la API y el nombre del nodo son DOS valores.** `pve_nodo` es el host
  de la URL; `pve_nombre_nodo` es el nombre con el que Proxmox conoce al nodo (lo
  que va en las rutas `/nodes/<nombre>/...`). En un nodo único suelen coincidir,
  pero pueden no hacerlo (un nodo llamado `Proxmox` alcanzado por su IP): usar el
  host como nombre de nodo hace que la API responda 596 "no such node".
- **Lo asíncrono se espera sondeando la API, no con un `until`.** Proxmox responde
  un `UPID` y trabaja en segundo plano; el motor sondea la tarea por la vía de acceso
  (`tasks/esperar_tarea.yml`) para que **cada sondeo deje su línea en el diario**.
  Un `retries`/`until` de Ansible habría sondeado a espaldas del diario.
- **Sólo `ansible.builtin`.** El motor no instala ni usa ninguna colección.
- **El motor nunca borra** un invitado que no esté en la declaración: borrar es
  `destroy`, que se niega si el invitado sigue declarado.

## Fuera de alcance (extensiones futuras)

Una línea cada una, y nada más:

- **Aplicaciones ARBITRARIAS dentro de los invitados** (ficheros que el lab elija, paquetes,
  servicios, su configuración): el vocabulario llega a la **configuración de red del equipo**
  (RouterOS, Linux) y, desde ADR 0027, a **UN servicio de un vocabulario cerrado** por área
  `servicio` (`caddy` y `netxms` hoy) — nunca a lo que un lab quiera inventarse. El punto de
  extensión sigue siendo una primitiva nueva del motor, con su ADR.
- **Cloud-init y plantillas de disco** más allá del mínimo para que un invitado
  arranque.
- **Inventario dinámico** de los invitados desplegados.
- **Clúster y multi-nodo**, HA, Ceph.
- **Snapshots y backups**.
- **CI/CD** y cifrado de secretos.

## Ver también (punteros al código, del documento al fichero)

- La **vía de acceso única** a la API y el diario de cada llamada:
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
- La **guía para escribir un lab** (las decisiones, en orden, con su trampa y su check):
  [docs/crear-un-lab.md](docs/crear-un-lab.md)
- El **túnel del bastión** (la consola, el túnel, el puerto derivado):
  [docs/tunnel-del-bastion.md](docs/tunnel-del-bastion.md)
- Las **decisiones** que no se re-litigan:
  [0001](docs/decisiones/0001-solo-api-de-proxmox.md),
  [0002](docs/decisiones/0002-el-pool-como-frontera-de-propiedad.md),
  [0003](docs/decisiones/0003-documento-con-dos-regiones.md),
  [0004](docs/decisiones/0004-el-tunnel-y-el-token.md),
  [0005](docs/decisiones/0005-el-driver-del-interior.md),
  [0006](docs/decisiones/0006-escribir-en-routeros.md),
  [0007](docs/decisiones/0007-las-interfaces-se-declaran.md),
  [0008](docs/decisiones/0008-una-direccion-por-interface.md),
  [0009](docs/decisiones/0009-verify-mira-dentro.md),
  [0010](docs/decisiones/0010-el-rest-por-el-tunnel.md),
  [0011](docs/decisiones/0011-el-agente-de-invitado.md),
  [0012](docs/decisiones/0012-la-salida-del-lab.md)
