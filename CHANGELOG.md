# Registro de cambios

Lo que ha entrado en cada versión, de la más nueva a la más vieja. El formato es
[Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/) y el versionado
[SemVer](https://semver.org/lang/es/): `MAYOR.MENOR.PARCHE`.

Mientras la versión MAYOR sea `0`, el motor está **en desarrollo**: la declaración de un
lab y los verbos todavía pueden cambiar, y cualquier versión MENOR puede traer un cambio
que rompa. Es la regla de SemVer para la serie 0.x, y es la razón de que la primera
entrega sea `0.1.0` y no `1.0.0`: no hay nada estable que prometer todavía. La `1.0.0` se
publicará cuando lo haya —una declaración de lab que no queramos volver a tocar y
terceros usándola—.

El fichero `VERSION` lleva la **última versión publicada**, el tag `vX.Y.Z` la marca y
aquí está su entrada; los tres tienen que contar lo mismo, y eso es lo que vigila
`./lab check version`. Lo que entra en `main` sin publicarse se apunta bajo
`[No publicado]`, y se convierte en una versión el día que se publica.

## [No publicado]

### Añadido

- **El `latido`: aparecer en la topología sin agente y sin abrir camino (ADR 0031).** Un
  invitado Linux declara `latido: {}` (o `latido: {cada: 5min}`) y el motor le pone un
  temporizador que da un toque **a su propia pasarela** —2 minutos por defecto—. No configura
  nada del equipo ni de la red: lo que hace es mantener su MAC en la tabla ARP de su router,
  que es lo que el sondeo del vigilante **lee** para encolarlo como nodo (medido en su código:
  no exige que el invitado conteste). Los equipos de las zonas aparecen así **sin** agente
  SNMP, **sin** rutas nuevas y **sin** una sola regla nueva en ningún cortafuegos.
- **Un servidor de VIGILANCIA: el área `snmp` de RouterOS, el área `monitorizacion` de Linux y la
  pata de gestión que publica un servicio (ADR 0029).** Un lab puede declarar `snmp: {}` en un
  equipo de red —el motor enciende su agente y le pone **una** comunidad de LECTURA, la constante
  del motor, la misma con la que el vigilante pregunta— y `monitorizacion: {}` en un `servicio`
  que sepa vigilar (hoy `netxms`): el motor le **declara la red que tiene que rondar** —la del
  propio invitado, derivada, nunca un valor declarado— **con el descubrimiento activo encendido**,
  así que la ronda la hace el servidor **solo** y la topología aparece en la web según encuentra
  los equipos; el sembrado espera a que sus hallazgos estén en la base y deja su marca. La pata de
  gestión del plan deja de ser exclusiva del bastión: **quien publica un
  servicio sale por donde sale el nodo**, con sus propias interfaces y sin una pata por cada
  bridge del lab. Y el `estado` del `servicio` ya no se conforma con «esquema sí y WAR sí»:
  **comprueba que se puede ENTRAR**, por el **API WEB** — la misma puerta por la que entra la
  interfaz —, nunca por la consola de depuración: se midió que un `nxadm` que **autentica bien**
  deja la clave rota para la web (`403 errorCode 61`, sin recuperación), así que el motor no usa
  la consola para nada.
- **`08_dunder-mifflin-con-fw` estrena `monitor` (`ctl-2`)**: un NetXMS en la red de gestión que
  mira por SNMP a los cinco equipos de red del lab —el único sitio desde el que los ve a todos sin
  abrir una sola regla— y publica su web como pieza de gestión del nodo.

### Corregido

- **Cuatro cosas que la relectura del PR cazó, todas con su prueba.** (1) Un lab que sólo declara
  `servicio: netxms` —el 10— ya **no** enciende la vigilancia: los ajustes de descubrimiento
  viven detrás del área `monitorizacion`. (2) Una **caída de la API** (sin respuesta, o un 5xx)
  ya no se confunde con un rechazo de credenciales, así que `preparar` no puede borrar una base
  poblada con un `DROP DATABASE`; la consulta que falla no es un esquema vacío, y la marca de
  sembrado exige un recuento válido y mayor que cero. (3) Las rutas de un invitado Linux
  **sobreviven al reinicio**, y las rutas a un host se comparan normalizadas (`/32` y
  `10.44.1.5` son la misma; `default` y `0.0.0.0/0`, también). (4) La red del descubrimiento se
  deriva del prefijo **completo**, no de un `/24` supuesto, y la lectura comprueba el `rc` de
  `ip route` antes de creerse una tabla vacía.
- **Los objetivos del vigilante comparan contra la DECLARACIÓN, no contra el equipo (ADR 0032).**
  Si no, cambiar las rutas de un lab ya desplegado no se notaba —la marca de sembrado seguía
  valiendo— y el vigilante seguía sondeando las redes **viejas**. Y «clave ausente» no es «clave
  presente pero vacía»: `routes: []` declara el área y va a borrar las rutas, así que ahí la
  expectativa es la red propia.
- **La clave del motor se deja al CREAR, y si falta se para diciéndolo (ADR 0033).** Proxmox
  admite `ssh-public-keys` sólo en el endpoint de creación (comprobado en su código: no está en
  el esquema de configuración), así que un invitado que existía de antes sin ella no se puede
  arreglar por la API: el motor reconoce la firma —«Permission denied (publickey)», `rc` 255—
  y para con la causa y el remedio en vez de dejar un error que no explica nada.
- **Un latido con cadencia CERO se caza en la declaración.** En systemd un cero BORRA la
  expresión del temporizador: el latido no se repetiría y el invitado se caería de la topología
  sin que nada lo dijera. El lector del latido compara además los **tres** artefactos (guion,
  unidad y temporizador), no sólo el comentario.
- **El plan cuenta como usadas las direcciones que reparte la propia pasada.** Dos invitados con
  pata de gestión creados en el MISMO plan derivaban la misma dirección del bridge del nodo (el
  bastión y un publicador salían los dos por la `10.10.10.254`, que además es la del propio
  nodo), y eso rompía a medias la conexión del motor con el segundo. Ahora el segundo mira lo que
  el primero acaba de recibir. Lo blinda `test/test_plan.py`.
- **El área `servicio` aprende un segundo miembro, y deja de tener la forma de `caddy`
  (ADR 0028).** Cada miembro del vocabulario cerrado declara sus PIEZAS —paquetes, ejecutables,
  unidad, ficheros, el comando que prueba que SIRVE, una lectura adicional opcional y los pasos
  para dejarlo en estado de arrancar— y el motor los gobierna igual para todos. `netxms` es el
  segundo miembro: añade su repositorio APT (no está en Debian), instala PostgreSQL y Tomcat,
  crea la base, el usuario y el esquema (`nxdbmgr init`, sólo si la base no tiene tablas) y
  despliega el WAR del cliente web, y luego prueba que sirve con un `curl` a
  `127.0.0.1:8080/nxmc/`. Hay una operación nueva, `prepare_service`, que va DESPUÉS de escribir
  los ficheros y ANTES de arrancar la unidad.
- **`10_lxc-netxms`**: el lab mínimo otra vez —un contenedor LXC que es bastión y servidor—,
  pero con NetXMS dentro. La declaración es la misma línea (`servicio: netxms`): la base, la
  contraseña, la versión y la URL de su web son vocabulario del motor, no del lab.
- **El tipo de equipo manda sobre las áreas: un equipo, una responsabilidad (ADR 0026).** El
  validador caza un área declarada en el tipo al que no le toca, con el motivo y con el equipo
  que sí puede — «un `rt` que filtra es un router con dos trabajos: eso es un `fw`». Cubre los
  dos ejes que el encargo pidió separar: filtrar no es enrutar (`firewall` es de un `fw`, y
  `uplink`/`dhcp_server` no) y **conmutar no es enrutar** (un `sw` no enruta, no filtra, no
  traduce y no reparte), así que el día que llegue el área `bridges` ya tiene dónde caer.
- **`08_dunder-mifflin-con-fw` gana un cortafuegos de borde (`fw-borde`)** y su router pierde la
  tabla de filtrado: `rt-nucleo` enruta y sale, y el borde filtra. Seis bridges y once invitados.
- **La topología de cada lab se dibuja como diagrama de RED.** La región generada del documento
  lleva un diagrama Mermaid con un nodo por segmento (el bridge y su subred), un nodo por equipo
  con su nombre canónico, su dirección y su etapa, y la SALIDA del lab en discontinuo para quien
  la declara (`uplink`). La forma y el color del nodo dicen qué es el equipo —estadio el `rt`,
  hexágono el `fw`, paralelogramo el `sw`, cilindro el `srv`, rectángulo el `ws`, subrutina el
  `ctl`—, con una leyenda de los tipos que el lab USA. Se deriva de la declaración, como el
  resto de la región: no hay prosa que mantener.
- **`test/test_documentos.py`**, que no existía: la región generada (la que ningún humano
  escribe, y cuyos fallos son silenciosos) tenía cero pruebas.
- **El candao del Greptile es mecánico (`.github/workflows/greptile-gate.yml`).** Lee la
  puntuación del CUERPO del resumen de Greptile —no de su fecha, que es leer una puntuación
  vieja— y publica el *status check* `greptile-5-de-5` sobre el SHA de la cabecera del PR:
  sólo pasa con 5/5, y `pending` (sin puntuación legible) no es aprobar. Por debajo de 5/5
  re-dispara la revisión hasta `MAX_REINTENTOS` veces por cabecera, sin reaccionar a sus
  propios comentarios. Bloquea el merge el día que se exija en la protección de rama (el
  comando está en el README); sin eso es un aviso que se ve, y así se dice.
- **Un Linux puede declarar un `servicio`, y el motor lo instala y lo deja SIRVIENDO (ADR 0027).**
  El área `servicio` de `config.linux` toma el NOMBRE de un servicio de un vocabulario **cerrado**
  (hoy sólo `caddy`): el motor instala el paquete, escribe su configuración y su página, habilita
  y arranca la unidad, y lo comprueba **sirviéndolo** (un `curl` a 127.0.0.1 desde dentro). Un
  invitado ya convergido no produce **ninguna** operación, y un nombre que no esté en el
  vocabulario —o una clave presente pero vacía— se **rechaza** con su motivo, no se ignora. La
  convergencia se decide comparando el **contenido entero** de los dos ficheros que el área
  gobierna (la marca sola no prueba que estén bien) y mirando `is-active` **y** `is-enabled`.
- **`09_lxc-caddy`**: el lab más simple que enseña el YAML declarativo —un contenedor Linux
  con Caddy dentro, en su propio bridge, sin un solo RouterOS— y a la vez el que destapó el
  gemelo de abajo. Su `tipo: ctl` lo hace el bastión de su propio lab: es el único invitado y su
  túnel es la vía por la que el motor entra a configurarlo (el paquete sale a internet por su
  pata de gestión, no por el túnel).

### Corregido

- **El motor creaba un GEMELO de un invitado al aplicarlo por primera vez.** Medido en un
  `apply` en frío real: el paso de creación se ejecutaba más de una vez, el segundo POST
  chocaba con el vmid que el primero acababa de crear (`CT 114 already exists`), el
  clasificador lo tomaba por un choque con otro lab —no podía saber que el vmid era suyo— y
  el reintento de `converger` re-derivaba el mundo y creaba un segundo invitado con el vmid
  siguiente (dos CT para un rol, `esperados=1 encontrados_en_el_pool=2`). Ahora el paso de
  creación **se pregunta antes de crear**: `es_guest_del_lab` mira la descripción del vmid que
  va a ocupar y, si la marca `lab=… rol=…` es NUESTRA, el paso ya está dado y no se crea; un
  invitado ajeno (o sin marca) sigue siendo una colisión de verdad y el reintento es el
  correcto. La comparación es por palabra completa, para que `lab=01` no case dentro de
  `lab=011`. Verificado con el ciclo real: **una sola creación** donde antes había tres.
- **El estado compartido no guardaba más que la primera interfaz.** `estado_desde_api` se
  quedaba con `bridge` y `mac` —los de `net0`— y tiraba las demás `netN`, así que la
  comprobación que compara las interfaces declaradas con las que hay veía TODAS las patas «en
  ningún bridge» y tumbaba con `ErrorMotor` el `plan --api` de un lab desplegado y correcto.
  Ahora el estado guarda el bridge de cada interfaz (`interfaces`, con las claves en texto
  porque viajan por variables de Ansible), y `bridge`/`mac` siguen siendo los de `net0`.
- **La columna `tipo` de las tablas enseñaba la PLATAFORMA.** Decía «VM (qemu)» donde el repo
  entiende el tipo de EQUIPO (`rt`, `fw`, `srv`...), porque el normalizador pisaba `tipo` con
  la virtualización. Ahora la tabla lleva las dos columnas: `tipo` (el del equipo) y
  `plataforma` (`VM (qemu)`/`LXC`).
- **El nombre canónico salía sin sustituir.** La región enseñaba el literal `{equipo}-{alias}`:
  se sustituían `{lab}` y `{rol}`, que no están en la plantilla del motor. Se deriva con la
  MISMA plantilla (`engine_plantilla_nombre`), así que si la plantilla cambia, el documento
  cambia con ella.
- **El check de marcadores sin sustituir buscaba un `{{` a secas**, y el hexágono del `fw` en el
  diagrama de red usa esa forma (`{{"..."}}`): ahora busca la forma de un marcador de verdad,
  `{{ clave }}`.
- **`rt-nucleo` (lab 08) filtraba.** Era el router con dos trabajos que la regla prohíbe, y
  estaba justificado en su propio comentario. La política del borde (lo que sale, sale; lo que
  entra de internet, no pasa) vive ahora en `fw-borde`, que es un equipo cuya responsabilidad es
  filtrar. El precio queda medido y escrito en el documento del lab: la pata de fuera del router
  no la filtra nadie, porque la vía de acceso es una primitiva cerrada y un `fw` no puede
  traducir.
- La definición de `fw` decía «no enruta», y un cortafuegos **en línea** reenvía el paquete que
  deja pasar. Se corrige el vocabulario: no traduce, no reparte direcciones y no es la vía de
  acceso de nadie.

## [0.3.0] - 2026-11-17

### Añadido

- **CI offline** (`.github/workflows/ci.yml`, informe §6.5): en cada push a `main` y en cada pull
  request corren las pruebas del motor, `./lab check`, `ansible-lint` y `yamllint` **sin
  credenciales y sin tocar Proxmox**.
- **Los secretos pueden ir cifrados** (ADR 0025, informe §6.6): `deployment_engine/secrets.sops.yml`
  vive versionado y cifrado con sops/age, y el wrapper lo descifra al `secrets.yml` de siempre antes
  de lanzar nada. La clave se pasa con `--age-key-file` (bandera, no variable), así que el motor
  sigue sin leer el entorno.
- **El choque de vmid converge** (informe §6.7): si dos `apply` en paralelo eligen el mismo vmid, el
  motor re-lee el mundo, recalcula el plan y lo reintenta una vez — sin guardar estado en disco.
- **El diagrama de la topología, autogenerado** (informe §6.8): la región generada de cada lab lleva
  ahora un **Mermaid** derivado de la declaración (bridges como segmentos, invitados por tipo).
- **`./lab check secretos`** (ADR 0024): el candado de lo que abre el **nodo**. Caza en lo
  versionado el token de la API con su valor, un ticket de sesión, una clave privada y el propio
  `secrets.yml`, y se cierra en el hook de pre-commit mirando el **índice** —lo que va a entrar en
  el commit, no el árbol de trabajo—. Las credenciales de los labs se siguen citando en claro: la
  política es asimétrica, y ahora está escrita y vigilada en vez de confiada.

### Cambiado

- **La raíz en su sitio.** `informe-rendimiento-despliegue.md` se fue a `docs/`,
  `GOAL-capa-de-configuracion.md` a `docs/encargo-capa-de-configuracion.md`, y `analizar_perfil.py` y
  `perfilar.sh` a `scripts/` (herramientas de DESARROLLO). El mapa del README y de AGENTS.md ya
  mencionan `scripts/`, y las referencias internas están actualizadas.
- **El candado de los secretos, más fino.** Cierra las formas escurridizas que destaparon las
  revisiones: nombres de fichero no ASCII, claves entrecomilladas o en JSON, valores en la línea
  siguiente, valores entrecomillados con coma, comentarios entre comillas — y no bloquea un binario
  ni un fichero limpio con una línea hermana.
- **Fuera la configuración muerta.** Se fueron las claves `pve_ssh_usuario`/`pve_ssh_password`
  (ningún fichero del motor las leía, y el nodo no acepta contraseña), `engine_clave_tunnel` (la
  clave vive en el vocabulario del interior, no en una variable) y quince alias viejos del registro
  de filtros, más dos funciones que ya no llamaba nadie. Nada de eso se ejecutaba: por eso ningún
  lab cambia de comportamiento.

### Corregido

- **La región generada de un lab ya no depende de `secrets.yml`.** La tabla de acceso imprimía
  el VALOR de `routeros_clave` leído de `secrets.yml`, así que en un clon sin credenciales (el CI)
  rendía otra cosa — `./lab check docs` no podía pasar nunca — y el `.md` publicado llevaba la
  contraseña dentro. Ahora se cita la credencial **por su origen**. Lo destapó el CI del §6.5 en su
  primera pasada; ADR 0024 y el README quedan corregidos.
- **El reintento por choque de vmid (§6.7) ya no se muerde la cola.** `intentos_restantes` se
  descontaba sobre sí misma en el `vars:` del `include_tasks` —autorreferencia, bucle de
  plantilla—; ahora el contador baja en una variable propia. Y si la relectura del mundo falla, el
  reintento **para** en vez de rehacer el plan con la foto de ANTES del choque.
- **`plan` sin `--api` ya no exige credenciales.** El descifrado de sops/age sólo ocurre cuando el
  verbo va a hablar con la API: un clon con `secrets.sops.yml` versionado y sin `sops` ni la clave
  de age puede seguir planificando contra un fixture.
- **El diagrama no confunde un bridge con un invitado.** Los identificadores de Mermaid llevan la
  clase por delante (`b_`/`i_`): un bridge llamado `control` y un rol `control` compartían nodo y el
  diagrama dibujaba un bucle sobre sí mismo en vez de una pata.

## [0.2.0] - 2026-11-16

### Añadido

- **El área `firewall` de RouterOS** (ADR 0019): un lab puede declarar la **tabla de
  filtrado entera**, en orden, con vocabulario cerrado (`chain`, `action`, `protocol`,
  `src_address`/`dst_address`, `src_port`/`dst_port`, `in_interface`/`out_interface`,
  `connection_state`, `comment`, `disabled`). Es la única área que converge **después de la
  credencial**, porque es la única capaz de dejar al motor fuera de su propio equipo; y el
  validador **rechaza** un `drop` de `input` sin un `accept` de `input` antes, que es
  exactamente esa situación.
- **El tipo de equipo `fw`** (`tipo: fw` → `fw-oficina`): una máquina cuya responsabilidad es
  filtrar, que es lo que permite repartir una topología en «1 máquina = 1 responsabilidad».
- **El lab `08_dunder-mifflin-con-fw`**: la versión con zonas del lab 07 — un router que
  enruta y sale, tres cortafuegos que filtran (uno por zona), ninguno con dos
  responsabilidades.
- **La tabla de accesos en el documento de cada lab** incluye, además del usuario y el
  método, el **valor** de la credencial con la que se entra y **de dónde sale**
  (`secrets.yml`). Es una decisión explícita para labs efímeros de aprendizaje: se citan
  para poder entrar, no porque el secreto importe.
- **`derived` en una dirección** (ADR 0020): el lab escribe la marca y el motor calcula el
  valor repartiendo en orden desde `lab.address_space` (la pasarela de cada bridge primero,
  los routers antes que los puestos). Un valor explícito manda. Es opcional y aditivo: donde
  no se declara, nada cambia.
- **`ready:` por invitado** (ADR 0021): el lab declara cuánto se le espera antes de
  configurar lo que va detrás —`tipo: ssh|routeros_rest|ninguno` y `espera:` en segundos—, y
  ahora también un invitado **sin `config:`** puede declarar su barrera (antes no podía
  ninguna). Sin `ready:`, cada invitado se comporta exactamente como antes.
- **`./lab test`** (ADR 0022): las **pruebas funcionales** que declara el lab (`tests:`, con
  `ping`, `servicio` y `dns`). Contesta lo que `verify` no puede —«¿el lab HACE lo que
  promete?»— con tres salidas: `0` OK, `1` KO y **`3` OMITIDA** cuando el entorno no puede
  comprobar algo (un `ping` sin privilegios no es un lab roto). Deja evidencia por prueba en
  `labs/<lab>/logs/`. Sólo prueba desde donde el motor llega (el bastión).
- **`./lab capture` y `./lab impair`** (ADR 0023): mirar el tráfico de un bridge y estropearlo
  desde el bastión, **acotado** (se aplica, se espera y se retira en el mismo comando, así que
  no queda un `netem` huérfano). Son experimentos: `apply` no los toca. Ojo a lo que hace el
  impairment: estropea el tráfico **del bastión**, no el del bridge.
- **El informe de estado del arte** (`docs/informe-estado-del-arte-2026-11.md`), con las cuatro
  P0 **medidas sobre labs reales**: lo que aporta cada una, lo que no hace, y el A/B en frío de
  un lab mínimo (665 s antes, 662 s después: no cuestan despliegue).

### Cambiado

- **El repositorio se llama `netlabs-iac`** (antes `netlabs_v4_b`): la versión y la
  variante salen del nombre, que era un sitio del que ya no podían salir nunca. El URL
  viejo de GitHub redirige. **El motor sigue escribiendo su marca `netlabs_v4_b`** en la
  descripción de cada invitado y en el comentario de cada bridge: esa marca es estado ya
  desplegado —de ella depende la propiedad de los bridges y la idempotencia—, así que
  cambiarla tiene su propia migración, y no va en este cambio.

### Arreglado

- **Una escritura que converge DESPUÉS del cambio de credencial viajaba con la de fábrica**,
  y RouterOS contestaba 401 a media convergencia (medido en el lab 08, ADR 0018). Ahora la
  capa pura marca cada llamada con la credencial que le toca (`credencial: motor`) y el
  driver la obedece.
- **`./lab plan` sin credenciales fallaba en cualquier lab con salida**: el fixture offline
  no modelaba la dirección del bridge de gestión del nodo.
- Un aviso de plantilla en `tasks/tunnel.yml`: una tarea hablaba de un rol que no existía en
  esa pasada.

## [0.1.0] - 2026-11-15

Primera entrega. Recoge lo que el motor es hoy, después de siete labs: un motor IaC en
Ansible que despliega topologías —VMs QEMU y contenedores LXC— en un nodo Proxmox **sólo
por su API REST**, pone él mismo la identidad de cada invitado, **configura el interior**
de cada equipo (RouterOS por su REST, Linux por SSH) y lo documenta.

### Añadido

**La declaración**
- Una carpeta por topología (`labs/NN_<nombre>/`) con su declaración, su documento y sus
  diarios. El motor **no conoce ninguna topología**: el lab es siempre un parámetro.
- El lab declara roles, el tipo de equipo (`rt`/`srv`/`ws`/`sw`/`ctl`), bridges,
  direcciones, etapas de arranque, recursos y —si quiere que el motor entre dentro— qué
  configurar y con qué imagen. **Nunca** declara vmids ni MACs.

**La identidad, derivada**
- vmid (el menor libre de todo el clúster), nombre `<tipo>-<alias>`, MAC `f(vmid)`,
  descripción y pool del lab. **Sin fichero de estado**: se re-deriva leyendo la API.

**Los verbos**
- `plan` (ordena y explica cada llamada REST que haría), `preflight` (sólo lectura: qué
  hay, qué falta, qué difiere), `apply` (converge y verifica), `verify` (¿existe de verdad
  lo declarado?) y `destroy` (el único que borra, y sólo lo que él creó).
- El plan es una **explicación**: dice por qué cada llamada, no sólo cuál.

**Las cuatro vías de acceso y los tres diarios**
- API de Proxmox y REST de RouterOS, siempre con `ansible.builtin.uri`, y cada llamada
  deja su línea en `logs/api.jsonl` (`api: proxmox` | `routeros`).
- El interior de un Linux, sólo por SSH, con una línea por paso en `logs/interior.jsonl`.
- La consola de la API —el único protocolo no-REST— para una sola cosa: el arranque del
  bastión. Su diario es `logs/console.jsonl`. Ninguna credencial se escribe en un diario.

**El interior de un invitado**
- Un driver por familia (RouterOS por REST, Linux por SSH) con la misma forma: leer dentro
  → decidir la diferencia en los dos sentidos → escribir lo que falta → releer y comprobar.
- DHCP con reservas derivadas de la MAC del invitado, direcciones estáticas por interfaz,
  rutas, cortafuegos, identidad y servicios. Dentro de un área declarada, lo que no está en
  la declaración se quita; fuera de las áreas declaradas no se toca nada.

**El túnel**
- Lo construye el motor y lo comprueba de punta a punta antes de seguir. Por él van el REST
  de RouterOS y el SSH al interior: el motor no necesita llegar solo a la red del lab.

**La red y el orden de arranque**
- Los bridges los crea el plan si faltan, con su marca de propiedad; `destroy` sólo borra
  los que llevan esa marca y no están usando invitados de fuera del lab.
- Cada etapa arranca sólo cuando la anterior está convergida y sirviendo: la carrera del
  DHCP que mató a la fase anterior se evita por construcción, no por suerte.
- El agente de invitado en toda VM, para poder LEER direcciones que la API no expone.

**Los checks y la documentación**
- Checks mecánicos (`./lab check`), sin credenciales y sin Proxmox, cada uno diciendo el
  fichero y el comando que lo arregla.
- El documento de un lab tiene dos regiones: la generada (nadie la escribe a mano) y la
  prosa libre. Los documentos que citan el motor se sellan por hash y **caducan avisando**.
- ADRs para lo que no se quiere re-litigar, un pre-commit que vigila docs↔código, y una
  suite de pruebas con fixtures para el asignador: el asignador se prueba sin Proxmox.
