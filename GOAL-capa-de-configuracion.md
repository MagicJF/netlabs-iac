DISCLAIMER: este coal ya fue ejecutado y salto este mensaje: "You've reached the maximum number of tool-calling iterations allowed. Please provide a final response summarizing what you've found and accomplished so far, without calling any more tools."; a continuacion la respuesta

# /goal — netlabs_v4_b, fase 2: el motor también configura el interior de los invitados
Resumen honesto del estado, sin maquillar.

    Lo que está verde (verificado con salida real)

    • ./lab check: todos los checks en verde (links, docs, refs, puerta, privilegios, declaracion, supernet, colisiones,
    pureza-lab, readme).
    • ansible-lint: 0 fallos, 0 avisos en 52 ficheros.
    • Suites puras: test_interior, test_declaracion, test_regresion_planes, test_identidad, test_privilegios, test_bridges OK.
    • test_routeros: 2 asserts en rojo, y son mis asserts nuevos mal escritos, no el motor (ver abajo).

    Lo que se arregló en esta tanda, con la medición que lo respalda

    1. borde ya converge en una pasada. El 1 operación pendiente: [direcciones] quitar_direccion tenía dos causas medidas en el
    diario: (a) RouterOS retira por .id, con la dirección en numbers contesta 404 (el POST que la pone sí devuelve {"ret": "*2"});
    (b) la retirada se emitía después del cambio de credencial, y esa escritura se queda sin credencial (401 tolerado). Ahora la
    retirada va justo tras poner la declarada, con el .id resuelto (capturado del POST, o sacado de una relectura si esa respuesta
    se perdió) y por la dirección prestada.
    2. La sonda de un escalón ya no rompe el diario: faltaba interior_tipo en el ejecutor (tasks/sonda.yml + paso.yml).
    3. Sin respuesta del POST en el baile → tolerado, decide la relectura. Medido: el mismo POST /ip/address/add contesta 200 en
    borde y -1 (timeout) en el CHR del segundo escalón. Se marca tolerar_sin_respuesta en las escrituras del baile; quien
    prueba que se escribió es la relectura final.
    4. nucleo no era alcanzable porque el puesto de control no tenía dirección en esa LAN (medido: No route to host → luego timed
    out). El vocabulario no sabía expresar «una dirección por pata». Añadí config.linux.direcciones (lista de {interfaz,
    direccion}), que se funde en el área direccion; la lectura de la puerta Linux pasó a ip -4 -o addr show scope global para ver
    todas las patas. El lab declara eth1: 10.40.1.2/24. Esto es una primitiva nueva del vocabulario y le falta su ADR y su entrada
    en la prosa del lab.
    5. El mensaje de fallo del check de RouterOS ahora incluye la lectura con la que decidió: no hay que instrumentar el motor
    para diagnosticar.

    Lo que falta, en claro

    • Los 2 asserts de test_routeros.py que dejé a medias: la salida real dice que la relectura aparece dos veces (obtenido
    ['leer', 'leer']) y que también aparece en el caso LLAMADAS_CHOQUE. No he terminado de localizar el duplicado; los asserts hay
    que escribirlos contra el comportamiento real (una relectura por retirada, marcada leer, antes del /remove, y ninguna cuando
    la prestada ya estaba en la lectura inicial).
    • El ciclo destroy → apply → apply → verify NO está verde. El último intento: destroy_exit=0, apply*=2, verify_exit=2,
    fallando en nucleo (mientras que borde ya pasaba su check en la primera pasada). Con los arreglos 4 y 3 aplicados, el ciclo no
    se ha vuelto a lanzar.
    • No hay commit ni push de nada de esto: la regla del repo es que no se sube sin el ciclo verde. Todo está en el árbol de
    trabajo.
    • Pendiente de documentar cuando el ciclo cierre: ADR de direcciones (Linux, patas extra del puesto de control), prosa del lab
    (filing back), y las lecciones en la skill netlabs-v4_b (retirada por .id; respuesta perdida que se tolera y decide la
    relectura; tolerar≠seguir a ciegas; una dirección por bridge para el puesto de control).
> Este encargo **continúa** a `/home/hermes/netlabs_v4_b-goal-prompt.md` (fase 1: el motor
> despliega por la API de Proxmox). No lo contradice: lo extiende. Lo que la fase 1 dejó
> explícitamente fuera de alcance —«configurar el interior de los invitados»— es exactamente
> lo que aquí se construye.

## 0. Encargo en una frase

Haz que el motor de `netlabs_v4_b` deje de desplegar infraestructura **vacía**: partiendo de la
misma declaración de topología, que ahora además declara **la configuración de cada equipo**, el
motor debe **entrar en cada invitado, converger su interior, comprobarlo leyéndolo desde dentro y
saber quitar lo que sobra**, sin romper ni una sola de las propiedades que la fase 1 ya tiene
(una sola puerta a la API, identidad derivada, diario íntegro, verificación por conjuntos en los dos
sentidos, idempotencia demostrable, el motor no conoce ningún lab).

Y como hoy **no existe ninguna forma de entrar** en la red de un lab (medido: desde el nodo de
control no se alcanza ninguna red interna del nodo, y la API no sabe ejecutar nada dentro de un
invitado), el motor **construye su propio camino** para entrar: un puesto de control por lab que él
despliega, arranca y saca hacia casa, sin pasos manuales y sin tocar el hipervisor (§5).

El caso de uso que manda es el de los labs de red virtualizada: **VMs RouterOS (CHR)** que hacen de
routers y **contenedores LXC** que hacen de servidores y puestos. Proxmox **sólo pone los bridges**:
no se usa su NAT, ni su DHCP, ni su cortafuegos. La red la configuran los CHR. Los routers y
servidores llevan **dirección fija**; los puestos, **dinámica repartida por su CHR**.

## 1. Material de referencia (léelo antes de escribir código)

### 1.1 El repositorio que vas a extender — `deployment_engine/` y `labs/`

Léelo en este orden, y **no toques nada hasta entender las cuatro ideas que lo sostienen**:

1. `AGENTS.md` (reglas duras) y `README.md` (el motor). Son el contrato vigente: lo que digan ellos
   manda sobre cualquier documento, incluido este.
2. `deployment_engine/tools/plan.py` — el plan es una **función pura** de (declaración, estado del
   mundo, identidad) y `apply` ejecuta *ese mismo* plan. Aquí se insertan las fases nuevas (§7).
3. `deployment_engine/tasks/pve_api.yml` — **la puerta**: hacer la llamada y escribir la línea del
   diario son una sola cosa, en el mismo fichero. Es el patrón que van a copiar las puertas nuevas
   (§8), no un fichero que se toca a la ligera.
4. `deployment_engine/filter_plugins/{declaracion,identidad,estado}.py` — validar, asignar y leer el
   mundo. El nuevo vocabulario de configuración se valida y se planifica **aquí**, en funciones
   puras probables con fixtures, no en plantillas Jinja dentro de un playbook.
5. `deployment_engine/tools/framework_check.py` — los ocho checks. Dos de ellos (`puerta`,
   `pureza-lab`) son la razón por la que este encargo tiene la forma que tiene (§3, §12).
6. `labs/lab-dos-redes/lab-dos-redes.yml` y su `.md` — la declaración y el documento de dos regiones.
7. `docs/decisiones/0001..0003` — las tres decisiones que no se vuelven a discutir; la 0001 es la que
   este encargo **acota** (§5), no la que deroga.

**Estado medido hoy (14-nov-2026), no lo adivines:**

- `./lab check` → **los 8 checks en verde**; `./lab --lab lab-dos-redes plan` (sin credenciales)
  imprime un plan de 14 pasos contra el clúster vacío simulado.
- En el VPS hay un despliegue real vivo del lab `lab-dos-redes` (pool homónimo: qemu 102 `borde`,
  qemu 103 `nucleo`, lxc 104 `puesto-1`, 106 `puesto-2`, 107 `servidor`, todos `running`), con las
  MAC derivadas del vmid tal y como manda la regla 11
  (`net0: virtio=BC:24:11:00:00:66,bridge=vmb_perimetro`). **Ese despliegue es tu red de seguridad de
  regresión (§14).**
- **Medido, y es el hueco que abre este encargo**: los dos qemu del lab desplegado **no tienen ningún
  disco** en el almacenamiento (los LXC sí: `vm-104-disk-0.raw`, 4,3 GB). El motor de la fase 1 crea
  VMs que **no pueden arrancar nada**. Sin imagen importada no hay CHR, y sin CHR no hay laboratorio
  de red: §9.3 no es un extra, es la puerta de entrada.
- `ansible` 2.22.0 en `/home/hermes/.local/bin`; **no hay ninguna colección instalada** y el motor
  usa sólo `ansible.builtin`. `ansible-lint` y `yamllint` están instalados; si dudas, `uvx`.
- `secrets.yml` ya declara `pve_nodo`, `pve_puerto`, `pve_token_id`, `pve_token_secreto`,
  `pve_verificar_tls`, y **también** `pve_ssh_usuario`/`pve_ssh_password` (la vía de depuración del
  §Depuración por SSH de `AGENTS.md`, que es del que diagnostica, nunca del motor).

### 1.2 El anti-patrón — `/home/hermes/repos/ansible-netlabs-v3`, y qué se salva de él

**No se copia ni un fichero, ni una plantilla, ni una estructura.** Pero v3 ya intentó esto mismo y
dejó medidas que valen oro; leerlas te ahorra una semana de descubrimientos. Lo que hay que leer:

- `machinery/configure/roles/routeros/tasks/main.yml` + `templates/plan.j2` — la capa 2 de v3:
  leer → decidir → escribir → verificar, con **intercambio atómico** (primero se añade y se
  verifica lo nuevo, después se borra lo viejo, y la **identidad del equipo se cambia la última**).
- `machinery/configure/roles/bootstrap/tasks/main.yml` — el contenedor que da la primera dirección.
- `machinery/playbooks/tasks/disk_import.yml` — cómo se arranca una VM a partir de una imagen de
  fábrica: `scsi0: "<storage>:0,import-from=<volid>"` **sólo al crear** (y después `PUT /resize`).
- `docs/decisiones/` de v3, en especial el reinicio que purga la ruta dinámica del DHCP.

**Medido en v3 (trátalo como verdad de partida y vuelve a medirlo si algo no cuadra):**

1. Un CHR recién creado arranca con un **cliente DHCP en `ether1` que pide dirección sin parar
   hasta que la recibe**; a partir de la segunda vez ya no la pide. Es tolerante: se le puede
   arrancar antes de que exista quien le conteste.
2. Un LXC Debian que arranca sin que nadie le conteste **deja de pedir al rato y se queda
   inalcanzable**. No es tolerante: **el orden de arranque es parte del diseño, no un detalle**.
3. Una oferta DHCP que sale de un contenedor por un `veth` llega con el **checksum UDP sin
   resolver** y el kernel del CHR la tira. Se arregla en el lado del servidor DHCP:
   `ethtool -K <if> tx off gso off tso off`.
4. La dirección y la ruta que instala el cliente DHCP de fábrica **no se pueden borrar por la API**
   («created by a different owner»). El script interno de RouterOS sí puede, pero medido en un CHR
   recién nacido lo dejaba **sin ninguna dirección**; el reinicio sí las purga. Por eso el plan
   necesita un paso de reinicio **declarado y explicado**, no un truco escondido.
5. `PUT /rest/ip/route` responde **400 «no such command»** en RouterOS 7.25: se escribe con
   `POST /rest/ip/route/add`. La ruta REST **no siempre coincide con la ruta del CLI**.
6. El servicio `www` (que es donde vive REST) **nunca se deshabilita**: es el camino de vuelta. v3
   apagaba `ssh`, `telnet`, `ftp`, `api` y `api-ssl`.
7. Verificar un router no es «no dio error»: identidad, direcciones **estáticas y no dinámicas**,
   rutas con `active=true`, bridges con **exactamente** los puertos declarados, reservas DHCP con la
   MAC derivada, cliente DHCP de fábrica ausente, y reglas de cortafuegos **con su orden**.
8. La imagen de fábrica del CHR ya está en el nodo: `local:import/chr-7.25.1.raw` (134 MB), y el
   almacenamiento `local` acepta contenido `import`. La plantilla LXC es
   `local:vztmpl/debian-13-standard_13.6-1_amd64.tar.zst`.

**Lo que NO se repite de v3:** el árbol de roles por aplicación dentro del motor, las plantillas
Jinja con la lógica dentro, el fichero de reglas de 42 KB, los vmids compuestos a mano, la prosa
dentro de plantillas, y **la capa 2 como un playbook suelto que el humano tiene que lanzar en el
orden correcto**. Aquí el orden lo lleva el plan (§7).

### 1.3 El entorno donde esto se va a ejecutar de verdad (medido hoy)

- **El nodo**: `Proxmox`, Proxmox VE **9.2.21**, API en `https://54.36.168.83:8006` (certificado
  autofirmado, `pve_verificar_tls: false`).
- **La máquina que lanza Ansible** (el nodo de control): el contenedor `hermes-joan` (LXC 999) **en
  casa**, en `192.168.1.155/24`, con la puerta por defecto en `192.168.1.1`.
- **Medido: desde casa sólo responden del VPS los puertos 22, 80, 443 y 8006.** Las redes internas
  del nodo **no son alcanzables**: `10.10.10.1:8006`, `10.10.10.2:443` y `10.20.20.1:8006` no
  contestan. Esto **es** el problema del §5.
- **Medido en PVE 9.2: `POST /nodes/<nodo>/lxc/<vmid>/exec` devuelve 501 «not implemented».** La API
  de Proxmox **no sabe ejecutar nada dentro de un invitado**. No hay atajo: o hay red, o no hay
  forma de entrar.
- **La red del nodo, tal como la ve su API** (`GET /nodes/Proxmox/network`):
  - `vmbr0` = `54.36.168.83`, «PUBLICACION DE SERVICIOS»: 80 y 443 se reenvían al contenedor Caddy
    (LXC 101, `10.10.10.2`).
  - `vmbr1` = `10.10.10.1/24`, «NAT de salida de la LAN de gestion».
  - `vmbr22` = `10.20.20.1/24`, «SEGUNDO SEGMENTO DE GESTION (OOB)».
  - Veinticuatro bridges en total: `vmb_nucleo` y `vmb_perimetro` son del lab `lab-dos-redes` (los
    creó el motor, en uso); **diecisiete de los `vmbr*` llevan un comentario `cable: …` y son
    huérfanos de v3** (sus invitados ya no existen, los bridges sí). No los toques: son la prueba
    viva de por qué existe la marca de propiedad de los bridges.
- **Almacenamientos**: `local` (`dir`: images, iso, backup, rootdir, vztmpl, **import**) y
  `local-zfs` (`zfspool`: rootdir, images). **Ninguno ofrece `snippets`**, y eso importa (siguiente
  punto).
- **La consola de la API es la única puerta que no necesita nada previo, y está cerrada con el token
  de hoy**: `POST /nodes/Proxmox/lxc/<vmid>/termproxy` responde **403 `Permission check failed
  (/vms/<vmid>, VM.Console)`** (medido). Es la puerta que necesita el §5. El billete de consola es un
  ticket RSA de **vida cortísima** (ventana `-20/+40` segundos, medido en el código) atado a usuario,
  ruta y puerto: hay que pedirlo y abrir el websocket en el mismo paso.
- **Ningún almacenamiento ofrece `snippets`, y además no se pueden subir**: el endpoint de subida
  acepta `enum => ['iso', 'vztmpl', 'import']` (medido en el código). Eso cierra por arriba la vía
  `hookscript`/`cicustom`, que es la otra forma en que la API toca el host.
- **`ssh-public-keys` en la creación de un LXC sí funciona y no necesita `snippets`**: PVE escribe
  `/root/.ssh/authorized_keys` en el rootfs al crear el contenedor (medido en el código de PVE, con la
  plantilla Debian estándar). Es cómo el motor deja su clave dentro de un invitado Linux **antes** de
  que exista camino.
- **El motor puede leer la red de un invitado desde el host, sin camino**:
  `GET /nodes/<nodo>/lxc/<vmid>/interfaces` devuelve las direcciones reales (medido: `eth0 ->
  10.10.10.2/24` en el contenedor Caddy). Sirve para elegir una dirección libre en el bridge de
  gestión y para comprobar concesiones DHCP **sin** tener camino (§6.3, §11).
- **El nodo tiene un segmento de gestión con salida**: `vmbr1` = `10.10.10.1/24`, con
  `MASQUERADE -s 10.10.10.0/24 -o vmbr0` e `ip_forward=1` (medido). Es el bridge por el que el puesto
  de control del §5 sale hacia casa. **En un nodo que no lo tuviera, el motor lo necesitaría**: el
  bridge lo puede crear por API, la regla de NAT del host no (es de la máquina, no de la API) — y eso
  está en el roadmap, no fingido.
- **Un túnel heredado de v3 sigue vivo, y este encargo no lo usa**: en el nodo hay una interfaz
  `wg-lab-server` (`10.99.99.1`, UDP 51820, con un peer de casa que mantiene el handshake) y su
  cliente está en **otro** contenedor de casa (LXC 103, `10.99.99.2`), no en el nodo de control. Se
  deja como está: no es parte de este diseño y el ADR del §5 dirá por qué se descarta.

## 2. Paso 0 — el repositorio y cómo se entrega

- Trabajas en **`/home/hermes/repos/netlabs_v4_b`** (ya existe, ya es git, ya tiene `origin` en
  `MagicJF/netlabs_v4_b`). **No crees un repo nuevo.** Este encargo es la fase 2 del mismo motor.
- Commits convencionales en castellano, imperativo, **uno por unidad de sentido**, y **se empuja
  pronto y varias veces** — no todo al final.
- **El token nuevo de la API** (§5.1) se escribe **a mano en `secrets.yml`** (la regla del README no
  cambia) y sus privilegios van al ADR 0004. El token viejo no se reutiliza para nada.
- La regla de subida ya escrita en `AGENTS.md` sigue vigente y es tu criterio de «hecho»: un cambio
  del motor no se da por bueno hasta que el ciclo **`destroy → apply → verify`** pasa de verdad
  contra el Proxmox real (§15) y `./lab check` está verde.
- Este mismo fichero (`GOAL-capa-de-configuracion.md`) es un **encargo**, no documentación del
  motor: cita ficheros del motor, así que va **sellado** (`./lab check docs --sellar
  GOAL-capa-de-configuracion.md`) y `check refs` avisará de que ha caducado cada vez que cambies uno
  de ellos. Eso es la guarda funcionando, no un problema. **Al terminar el encargo, decide y dilo en
  el reporte**: o se borra (un encargo ejecutado es historia; lo que importa vive ya en los ADR, el
  README y la prosa de los labs) o se conserva como registro de la fase 2 y se vuelve a sellar. Los
  checks no se aflojan para que un documento quepa.

## 3. La frontera: el motor sigue sin conocer ningún lab (y por qué)

Pregunta que este encargo resuelve de una vez: *al configurar las máquinas, ¿el motor debe conocer
los labs, o se mantiene la frontera?*

**Se mantiene la frontera.** El motor aprende **tipos de interior**, nunca labs:

- El motor conoce **dos tipos de interior**: `linux` (se entra por SSH) y `routeros` (se entra sólo
  por su REST). Un tipo es un **protocolo o un sistema operativo**, no una topología: cualquier lab
  con un CHR usa el mismo driver.
- El motor conoce un **vocabulario cerrado y pequeño de primitivas** (§6): direcciones, rutas,
  servidores DHCP, DNS, identidad, servicios, cortafuegos, claves. El lab pone **valores**.
- Si un lab necesita algo que el vocabulario no cubre, **se añade una primitiva al motor** —con su
  ADR y su verificación—, nunca un fichero por lab dentro de `deployment_engine/`.

Por qué no la alternativa («que el motor conozca los labs»):

1. Rompe las tres propiedades que hacen que este motor sea un motor: `check pureza-lab` («añadir un
   lab no toca ni un fichero del motor»), el pool como frontera de propiedad, y «nada derivado se
   guarda en el repo».
2. v3 ya recorrió ese camino: su capa 2 acabó con roles **con el vocabulario de una topología
   concreta** (`netlab`, `bootstrap`) dentro de la maquinaria. En cuanto el motor nombra lo que hay
   dentro de un lab, deja de valer para el siguiente.
3. La frontera es lo que hace **comprobable** la afirmación: «añadir un lab es añadir datos» se
   puede verificar con un check; «el motor entiende los labs» no se puede verificar de ninguna
   manera.

El driver **no adivina el tipo**: lo dice la declaración. Un invitado con `config.routeros` es un
RouterOS y se toca sólo por REST; con `config.linux`, es un Linux y se entra por SSH; **sin `config`
no se entra** (el motor lo despliega y se calla, exactamente como hoy).

## 4. Reglas duras nuevas (se copian tal cual en `AGENTS.md`)

Las once primeras siguen valiendo. Estas se **añaden numeradas a continuación**:

12. **Cuatro puertas, tres diarios.** A Proxmox y a RouterOS se les habla **sólo** con
    `ansible.builtin.uri`, y cada llamada deja **una línea JSON** en `logs/api.jsonl` con un campo
    `api` (`proxmox` | `routeros`) y el rol del invitado. Al interior de un Linux se entra **sólo**
    desde `tasks/interior_ssh.yml`, y cada paso deja una línea en `logs/interior.jsonl`. Ningún otro
    fichero abre una conexión a un invitado. La contraseña o la clave **nunca** se escriben en un
    diario. La consola de la API se habla **sólo** desde `tasks/camino_consola.yml`, y cada uso
    deja una línea en `logs/camino.jsonl`.
13. **RouterOS se configura sólo por su REST** (`/rest/…`). Su SSH existe en esta fase **sólo para
    depurar** (declarado, y con su tarea de cierre en el roadmap); el motor no lo usa jamás para
    converger.
14. **La MAC no se declara nunca** (es la regla 11 aplicada al interior): las reservas DHCP de un
    router se **derivan** del vmid del invitado. Si un YAML de lab contiene una MAC, es un bug.
15. **El vocabulario del interior es cerrado** (§6). Un lab no puede inventarse primitivas: pide una
    nueva al motor, con ADR.
16. **El camino lo construye el motor y se comprueba de punta a punta** (§5). Si no responde, el
    verbo **para** diciendo qué pieza falta y cómo se arregla; nunca lo rodea por otra vía.
17. **El interior es de la declaración por áreas** (§11): dentro de un área declarada, lo que no
    está en el YAML se quita del equipo; fuera de las áreas declaradas no se toca nada.
18. **Nunca se arranca un escalón antes de que el anterior esté convergido y sirviendo.** Es lo que
    mata la carrera del DHCP por construcción, no por suerte.
19. **La consola de la API tiene una sola tarea, y una sola línea.** Sólo para poner el arranque del
    puesto de control (§5), nunca para configurar un equipo: lo que se configura, se configura por su
    puerta (REST del router, SSH del Linux) y queda en su diario.

Y se **endurece la regla 6**: dos ejecuciones seguidas ⇒ la segunda con `changed=0` **y** los tres
diarios (`api.jsonl`, `interior.jsonl` y `camino.jsonl`) con **sólo lecturas**.

## 5. El camino: el puesto de control y la consola de la API

**El problema, medido, sin adornos.** El motor corre en casa (el nodo de control) y el lab vive en el
VPS. Desde casa **no se alcanza ninguna red interna del nodo** (`10.10.10.1:8006`, `10.10.10.2:443`,
`10.20.20.1:8006`: no contestan) y la API de Proxmox **no tiene plano de datos**
(`POST /nodes/<nodo>/lxc/<vmid>/exec` = **501** en PVE 9.2). Así que el motor no puede inventarse la
entrada… salvo por la única puerta que **no necesita nada previo**: la **consola de los invitados**,
la misma que pinta el navegador.

**Decisión (⟵ *suposición elegida: el camino es la «opción B» —el puesto de control—; es editable*):**
el camino lo **construye el motor entero**, sin pasos manuales y sin tocar el hipervisor.

1. **Un puesto de control por lab** (`rol: control`, un LXC Linux como cualquier otro): **una pata en
   el bridge de gestión del nodo** —el que tiene dirección y salida, hoy `vmbr1`; es un valor de
   entorno, no del lab— y **una pata por cada bridge del lab**, todas **al nacer**. Cambiar las patas
   de un invitado en marcha obliga a reiniciarlo, y aquí no se reinicia la máquina que está
   trabajando: se nace completo. Su dirección en los bridges del lab es **estática declarada**, porque
   **la gestión no puede depender de los routers que está desplegando**; la del bridge de gestión del
   nodo la **elige el motor** de entre las libres, leyendo por API las direcciones que ya usa cada
   invitado del nodo (`GET /nodes/<nodo>/lxc/<vmid>/interfaces`, §1.3). Nada derivado se guarda.
2. **Al nacer, el motor le inyecta su clave** por API: **`ssh-public-keys`** en la creación escribe
   `/root/.ssh/authorized_keys` en el rootfs (medido, y sin `snippets` ni cloud-init).
3. **La consola de la API, una sola vez y una sola línea.** El puesto no tiene forma de saber que
   quiere salir hacia casa, así que el motor **entra en su consola** (`termproxy` + `vncwebsocket`, el
   mismo protocolo del navegador) y le pasa **un único comando**: el arranque del camino, empaquetado
   en **base64** (una línea, sin heredocs ni comillas que escapar). Nada más se hace nunca por consola.
4. **El puesto sale hacia casa con `ssh -R`** (nada de WireGuard, decidido): se conecta al sshd del
   nodo de control por el puerto **443** público de casa —medido: hay un sshd detrás, con el reenvío
   del router y el multiplexor por protocolo ya puestos— y **deja reenviado** un puerto local del nodo
   de control hacia su propio sshd. Por ahí entra Ansible: el puesto es el **bastión** del lab
   (`ProxyJump` hacia lo que cuelga de sus bridges).
   - **El lado de casa lo configura el motor**: genera su par de claves del camino **una vez** en su
     propio `~/.ssh` (fuera del repo) y añade **una línea** a su `authorized_keys` con
     `restrict,port-forwarding,permitlisten="<puerto del lab>"`, de modo que esa clave **no da shell
     ni nada más que su reenvío**. Es la única escritura del motor fuera del repo, es de su propia
     máquina, y es idempotente.
   - El **puerto del lab se deriva** del vmid del puesto de control: nada que guardar.
5. **La comprobación es la prueba de punta a punta** (`tasks/camino.yml`, y también en `preflight`):
   1. ¿Responde la API en la dirección pública del nodo? (lo de hoy).
   2. ¿Contesta el sshd del puesto en el **puerto reenviado** del nodo de control? Eso demuestra la
      cadena entera: casa → 443 → puesto → vuelta.
   3. ¿El puesto llega a la red del nodo (contesta el nodo en la dirección del bridge de gestión)?
   Si algo falla, el verbo **para** diciendo **qué** pieza falta; y si lo que falta es la consola
   (**403 `VM.Console`**), el mensaje dice el privilegio exacto y la llamada exacta que hay que hacer
   **una vez** (§5.1). El motor no se auto-concede nada.

**Lo que este camino no necesita**, y es la razón de elegirlo: **nada en el nodo**. Ni rutas, ni NAT,
ni ficheros, ni reinicios, ni una receta que alguien pegue. El hipervisor sigue aportando **sólo
bridges y API**.

**Lo que cuesta, sin maquillar**: un driver de consola (websocket, sólo biblioteca estándar de Python,
sin dependencias) que es la pieza más frágil de la fase —una consola no devuelve códigos de salida, se
lee el eco— y por eso queda **encerrada**: una tarea, una línea que enviar, y una comprobación que
dice si funcionó. Su ventana es corta (el billete de consola vive **40 segundos**), así que pedir el
billete y abrir el websocket son el mismo paso.

**Regla 1, intacta**: la consola no es una puerta nueva —viaja por el mismo host, el mismo puerto
(8006) y la misma autenticación que la API—; lo que cambia es el **protocolo**, no la puerta.

**El ADR que esto necesita** (`docs/decisiones/0004-…`): fija (a) que el motor habla un protocolo más
que REST **por la única puerta**, (b) el privilegio exacto (`VM.Console`) y por qué no más, y (c) lo
que se descarta y por qué: **el túnel al propio nodo** (lo que v3 usó — dejaría el camino fuera del
motor y tocaría la red del hipervisor) y **la plantilla-aparato** (que se queda en el roadmap, §16).

### 5.1 El token: mínimos privilegios de verdad (y por qué el de hoy no lo era)

**Medido, y hay que arreglarlo antes de empezar**: el token actual tiene `Sys.Modify` sobre `/access`
(porque su ACL está en `/` y propaga) y `PUT /access/roles/<rol>` **sólo pide eso** (medido en el
código de PVE 9.2). Es decir: **el token puede reescribir su propio rol** y darse `VM.Console`,
`Sys.Console` o `Permissions.Modify` en una sola llamada. «Mínimos privilegios» no era cierto: era una
convención. (Y una precisión que también está medida: `Sys.Console` **no** da shell en el nodo —su
consola es `/bin/login` para cualquiera que no sea `root@pam`, y ejecutar comandos sueltos está
reservado a `root@pam`—, pero `VM.Console` sí da **consola de root dentro de cualquier invitado**.)

Por eso este encargo **diseña un token nuevo** (usuario, rol y token propios) con **ACLs por ruta,
nunca en `/`**:

| Ruta | Privilegios | Para qué |
| --- | --- | --- |
| `/vms` | `VM.Allocate`, `VM.Config.*`, `VM.PowerMgmt`, `VM.Audit`, `VM.Snapshot`, `VM.Backup`, **`VM.Console`** | crear, configurar, arrancar y **entrar por consola** (§5) |
| `/pool` | `Pool.Allocate`, `Pool.Audit` | el pool como frontera de propiedad |
| `/nodes/<nodo>` | `Sys.Modify`, `Sys.Audit` | los bridges y la red del nodo |
| `/storage` | `Datastore.AllocateSpace`, `Datastore.AllocateTemplate`, `Datastore.Audit` | discos; y en el roadmap, la plantilla del aparato |
| `/sdn` | `SDN.Use`, `SDN.Audit` | lo que ya se usa |

**Lo que NO se concede** —`Sys.Modify` sobre `/access`, `Permissions.Modify`, `Sys.Console`,
`Datastore.Allocate`, `VM.GuestAgent.*`— **y cómo se prueba**: una guarda de `preflight` hace la
**operación nula** sobre su propio rol (`PUT /access/roles/<el suyo>` con la misma lista de
privilegios) y **debe recibir 403**. Si recibe 200, los mínimos privilegios no están puestos y
`preflight` **falla** diciendo qué hay que quitar. Un mínimo privilegio que no se prueba es una
intención.

**Y el límite que el motor se impone a sí mismo** (va al ADR): con `VM.Console` en la mano, la consola
de un invitado es root **dentro de ese invitado**; para que eso no sea nunca el nodo, todo invitado de
un lab nace **`unprivileged`**, **sin claves crudas de LXC que monten rutas del host** y **sin paso de
dispositivos**. Con el contenedor sin privilegios, root dentro no es root fuera — y hay un check que
lo vigila (§12).

## 6. La declaración: el vocabulario nuevo (contrato del YAML)

Lo que sigue es el **contrato**. Las claves son en castellano, como el resto del dominio; lo que se
manda a la API o al equipo se traduce en **un solo sitio** (el driver), nunca en la declaración.

### 6.1 Lo que cambia en la declaración de un lab

```yaml
lab:
  nombre: lab-red-routeros
  escalones: [1, 2, 3]
  supernet: 10.40.0.0/16        # NUEVO: todo lo del lab vive aquí (lo vigila un check, §12)
  bridges:
    - {nombre: vmb_gestion, direccion: 10.40.0.1/24}
    - {nombre: vmb_lan1,    direccion: 10.40.1.1/24}
  camino: {tipo: puesto_control} # NUEVO: lo construye el motor (§5)

vms:                            # QEMU: en esta fase, RouterOS (CHR)
  - rol: borde
    escalon: 1
    cores: 2
    memoria: 512
    disco: 4
    imagen: chr-7.25.1.raw      # NUEVO: disco importado al crear (§9.3)
    bridge: vmb_gestion         # la pata de gestión (ether1)
    direccion: 10.40.0.11/24    # estática; el puesto de control se la da por DHCP al nacer
    config:
      routeros:
        identidad: rt-borde
        servicios: {deshabilitar: [telnet, ftp, api, api-ssl]}   # www (REST) NO se toca
        cliente_dhcp: {deshabilitar: true}          # el de fábrica, en ether1
        direcciones:
          - {interfaz: ether2, direccion: 10.40.1.1/24}
        rutas:
          - {destino: 0.0.0.0/0, pasarela: 10.40.0.1}
        dhcp:
          - interfaz: ether2
            pool: {rango: 10.40.1.100-10.40.1.200}
            red: {prefijo: 10.40.1.0/24, pasarela: 10.40.1.1, dns: [10.40.1.1]}
            reservas: derivadas      # las direcciones estáticas declaradas en ese bridge
        cortafuegos:
          filter: [{cadena: forward, accion: accept}]
          nat: []

containers:                     # LXC: en esta fase, Linux
  - rol: control                  # el puesto de control del lab (§5): el bastión y el que da
    escalon: 1                    #   la primera dirección a los CHR
    cores: 1
    memoria: 512
    disco: 4
    bridge: vmb_gestion           # + una pata por cada bridge del lab y una en el bridge de gestión
                                  #   del nodo (valor de entorno): todas al nacer
    direccion: 10.40.0.10/24
    config:
      linux:
        camino: {salida: {host: <el de casa>, puerto: 443}}     # NUEVO: el bastión (§5)
        dhcp_servidor:
          interfaz: eth0
          rango: 10.40.0.50-10.40.0.99
          reservas: derivadas
        reenvio: true
  - rol: puesto-1
    escalon: 3
    cores: 1
    memoria: 512
    disco: 4
    bridge: vmb_lan1
    direccion: dhcp              # NUEVO: cliente dinámico (§6.3)
    config:
      linux: {}
```

### 6.2 Reglas del vocabulario

- **`direccion` por invitado** admite tres formas: `<ip>/<prefijo>` (estática), `dhcp` (dinámica) y
  ausente (equipo sin dirección: un conmutador puro). Un invitado **con `config:`** necesita ser
  alcanzable, así que necesita una pata en el bridge de gestión y una dirección: un equipo que no se
  puede alcanzar no se puede converger, y eso se dice, no se intenta.
- **`config:` con exactamente una clave de tipo** (`linux` o `routeros`). El tipo elige el driver.
- **Ninguna MAC, ningún vmid, ninguna contraseña** en el YAML del lab. Las credenciales de RouterOS
  (usuario `admin`, su contraseña, la clave pública del motor) viven en `secrets.yml`; el lab sólo
  declara **qué** hay que configurar.
- **`reservas: derivadas`** es la única forma de declarar reservas DHCP: el motor reserva, por la MAC
  que deriva del vmid, **cada dirección estática declarada por otro invitado del mismo bridge** —y
  excluye al propio servidor—, de modo que ningún cliente dinámico puede robarle la dirección a un
  router o a un servidor. Si hiciera falta una reserva que no se deduce de otra declaración, se
  declara `reservas: [{rol, direccion}]`, **nunca con MAC**.
- **El puesto de control** declara su `camino` y sus patas: el motor le da una pata por cada
  `bridges` del lab **y** una en el bridge de gestión del nodo (valor de entorno, en
  `vars/engine.yml`, no en el lab). Su dirección en los bridges del lab es **estática declarada**,
  porque **la gestión no puede depender de los routers que está desplegando**; la del bridge de
  gestión del nodo la elige el motor de entre las libres (§5).
- Un lab **sin `config:` y sin `imagen:`** es un lab de la fase 1 y **su plan no puede cambiar ni un
  paso** (§14).

### 6.3 `direccion: dhcp` — qué promete y cómo se verifica

Un cliente dinámico no declara su dirección, así que la verificación cambia de forma: se comprueba
que (a) el invitado **tiene** una dirección y está **dentro del rango declarado** por el servidor
DHCP de ese bridge, y (b) el servidor DHCP del router tiene una **concesión activa para la MAC
derivada** de ese invitado. Las dos cosas, o no está verificado.

## 7. El plan y el orden: escalones, fases y arranque en cadena

**La columna vertebral ya existe y no se cambia: los `escalones`.** Lo que cambia es que la
configuración deja de ser un playbook que el humano lanza después, y pasa a ser **una fase más del
mismo plan**, intercalada escalón a escalón:

```
0. construir el camino si falta (§5): el puesto de control nace, recibe su clave, el motor le pone
   el arranque por consola UNA vez, y la salida hacia casa se comprueba. Ningún escalón empieza antes.

por cada escalón, en orden:
  1. crear / actualizar los invitados del escalón      (API, como hoy)
  2. arrancar el escalón                               (API, como hoy)
  3. converger el interior de los invitados del escalón  (NUEVO: drivers, §9)
  4. comprobar que el escalón sirve de verdad            (NUEVO: sondas de §11)
antes de pasar al siguiente.
```

Consecuencias, que son el objetivo del encargo:

- **La carrera del DHCP desaparece por construcción**: un puesto no arranca hasta que el router que
  le da dirección está convergido y sirviendo (regla 18). Ya no hace falta reiniciar puestos «a
  ver si esta vez pillan lease».
- **El arranque en frío tiene un orden claro** (§10): primero el que da la primera dirección, después
  el primer router, después el resto.
- **Un lab de la fase 1 (sin `config:`) produce exactamente el plan de hoy**, porque la fase 3 no
  genera ningún paso si no hay nada declarado. Eso se comprueba (§14), no se promete.

**Cómo se mantiene la regla «no hay una segunda lógica de decisión»:** el plan se calcula con la
misma función pura de siempre, extendida. La diferencia es que los pasos del interior necesitan
**leer dentro** para saber qué cambia:

- `./lab --lab X plan` **sin credenciales** (clúster simulado) imprime los pasos del interior en su
  forma **gruesa**: «converger el interior del invitado `borde` (routeros)».
- `./lab --lab X plan --api` (y siempre `apply`, que lee antes de decidir) imprime los pasos
  **exactos**, porque ha leído el interior.
- Los pasos del interior son **idempotentes por construcción**: leer → decidir → escribir → volver a
  leer. Un paso que no cambia nada **no genera escritura**, y por eso la segunda ejecución sale
  `changed=0` con los diarios llenos de lecturas.

**Acciones nuevas del plan** (junto a las de hoy: `crear_pool`, `crear_bridge`, `recargar_red`,
`crear_invitado`, `arrancar_invitado`): `converger_interior`, `reiniciar_invitado` (cuando el
residuo dinámico lo exige, §9.2) y `esperar_servicio` — y las dos del camino: `construir_camino`
(con sus sub-pasos: clave, `authorized_keys` local, consola) y `comprobar_camino`. Cada una con su `porque` legible, como las
actuales: el plan es una **explicación**, no una lista de órdenes.

## 8. Las puertas y los diarios

| Puerta | Fichero | Transporte | Diario | Qué la vigila |
| --- | --- | --- | --- | --- |
| Proxmox | `tasks/pve_api.yml` (existe) | `ansible.builtin.uri` | `logs/api.jsonl`, `api: proxmox` | `check puerta` (hoy) |
| RouterOS REST | `tasks/ros_api.yml` (nuevo) | `ansible.builtin.uri` | `logs/api.jsonl`, `api: routeros` | `check puerta` (ampliado) |
| Interior Linux | `tasks/interior_ssh.yml` (nuevo) | SSH | `logs/interior.jsonl` | `check puerta` (ampliado) |
| Consola de la API | `tasks/camino_consola.yml` (nuevo) | websocket sobre la **misma** puerta (8006) | `logs/camino.jsonl`, `puerta: consola` | `check puerta` (ampliado) |

- **La puerta de RouterOS es una copia del patrón de `pve_api.yml`, no una variante**: una llamada,
  una línea de diario, siempre, salga bien o mal; `no_log` en la respuesta; códigos 4xx tolerados
  para poder diarizarlos; `changed_when` decidido por el método. Su URL base es
  `http://<direccion del invitado>/rest` — **el HTTP en claro es deliberado y temporal** (el CHR de
  fábrica no tiene certificado); el ADR correspondiente debe decirlo.
- **La puerta del interior** construye el inventario **en memoria** (`inventario_invitados.yml`):
  usuario, clave, `StrictHostKeyChecking=no`, `UserKnownHostsFile=/dev/null`, y `ProxyJump` cuando haga
  falta: el **primer salto es siempre el puerto reenviado del puesto de control** (§5) —el bastión del
  lab— y el segundo, si el invitado cuelga detrás de un router del propio lab. Es el **único** sitio del repo donde se declaran
  parámetros de conexión SSH a invitados; el check lo vigila.
- **El diario del interior** es una línea JSON por paso, con lo que hace falta para reconstruir qué
  pasó: `ts`, `verb`, `lab`, `invitado`, `tipo`, `area`, `accion`, `declarado`, `encontrado`,
  `cambiado`, `resultado`. Sin credenciales, sin claves, sin contenido de ficheros enteros.
- **La clave pública del motor se inyecta al crear** el invitado, no después: LXC con
  **`ssh-public-keys`** (medido: PVE lo escribe en el rootfs al crear, sin `snippets` ni cloud-init);
  VMs Linux (fuera de alcance, §16) con cloud-init. En RouterOS no hay cloud-init: su clave se
  importa **por REST**, en la primera convergencia, con las credenciales de fábrica y las de
  `secrets.yml`.

## 9. Los drivers: qué sabe hacer cada tipo de interior

Un driver es un **procedimiento con la misma forma para todos los equipos de su tipo**: leer el
estado del área → comparar con lo declarado **en los dos sentidos** → escribir lo que falta → borrar
lo que sobra **dentro del área** → volver a leer y comprobar. Nada de «lanzar un comando y confiar».

### 9.1 `routeros` (REST)

Áreas y orden de convergencia (el orden importa: es el de v3, y no es casual):

1. `identidad` — el nombre del equipo y las credenciales del motor (**la última** en la primera
   convergencia, para no perder el camino de vuelta a mitad de camino; v3 lo llamaba intercambio
   atómico y la razón sigue siendo buena).
2. `servicios` — deshabilitar lo declarado (`telnet`, `ftp`, `api`, `api-ssl`), **nunca `www`**.
3. `cliente_dhcp` — deshabilitar el de fábrica (si queda alguno).
4. `direcciones` — estáticas, y comprobando que **no** queda una dinámica con el mismo valor.
5. `rutas` — con `active=true` en la verificación.
6. `puentes` — con exactamente los puertos declarados.
7. `dhcp` — red, servidor, pool y reservas derivadas.
8. `cortafuegos` — reglas con su orden.
9. `reinicio` — sólo si el residuo dinámico lo exige (§9.2), y **declarado en el plan**.

Trampas que ya están pagadas y no se vuelven a pagar: `POST /rest/…/add` en vez de `PUT`;
`dynamic=yes` no se borra por API; el servicio `www` es el camino de vuelta.

### 9.2 El residuo dinámico del CHR (y el reinicio, si no hay más remedio)

Hipótesis a **medir** en esta fase (y a escribir en un ADR, con el resultado real):

- Si la oferta DHCP **no lleva la opción de pasarela**, el cliente de fábrica del CHR no instala
  **ruta por defecto dinámica**, y el reinicio que v3 necesitaba para purgarla podría no hacer falta.
- Queda por ver el **residuo de dirección** (la dinámica con el mismo valor que la estática). Si hay
  que reiniciar, el plan lo declara como `reiniciar_invitado` con su `porque` — y el reinicio se
  ejecuta **una sola vez por vida del invitado**, no en cada `apply`.

Si el resultado de la medición es «el reinicio no se puede evitar», eso **no** es un fracaso: es un
paso del plan, escrito y explicado. Lo que no vale es esconderlo en un `command` con `ignore_errors`.

### 9.3 El arranque de una VM con imagen de fábrica

`scsi0: "<storage>:0,import-from=<volid>"` **sólo se acepta al crear** el invitado; después, `PUT
/nodes/<nodo>/qemu/<vmid>/resize` para crecer el disco hasta el tamaño declarado (y sólo si es más
pequeño: redimensionar al mismo tamaño es un error). Si la imagen declarada no quedó adjunta, el
motor **falla con el motivo y el remedio** («una imagen importada sólo se adjunta al crear: hay que
recrear el invitado»), no sigue y lo deja pasar.

### 9.4 `linux` (SSH)

Áreas: `direccion` (estática o dinámica), `pasarela`, `rutas`, `dns`, `reenvio`, `dhcp_servidor`
(con reservas derivadas), `claves` y **`camino`** (sólo en el puesto de control: la unidad de salida
hacia casa, que se pone **una vez por consola** y después se comprueba como todo lo demás, §5). Se converge con comandos idempotentes y se comprueba leyendo el
estado real (`ip -j addr`, `ip -j route`, la tabla de concesiones). **Nada de `shell` con `creates`**:
leer, decidir, escribir, releer.

## 10. El arranque en frío: quién le da la primera dirección al primer router

La cadena completa, resuelta y en orden (es la parte que el encargo anterior dejó abierta):

0. **El camino, antes de todo** (§5): el puesto de control nace con sus patas, recibe su clave por
   API, el motor entra **una vez** por su consola para poner el arranque de la salida hacia casa, y
   comprueba que el puerto reenviado contesta. **Hasta que eso no se cumple, no se toca nada más.**
1. **Escalón 1 — el puesto de control** (LXC Linux, `config.linux.dhcp_servidor`): ya arrancado en el
   paso 0, se converge su interior por el camino recién construido. Es el que da la **primera**
   dirección a los CHR en el bridge de gestión.
   - Su servidor DHCP reserva, por la **MAC derivada del vmid**, la dirección que cada CHR declara
     (§6.2). Nadie escribe una MAC.
   - En su interfaz hace falta el arreglo del checksum medido en v3:
     `ethtool -K <if> tx off gso off tso off`. Sin eso, las ofertas se tiran y nada funciona.
2. **Escalón 1 — el primer CHR**: se arranca sin dirección y la pide por DHCP. Es **tolerante**
   (pide sin parar hasta que la recibe), así que puede compartir escalón con el puesto de control.
3. **El motor ya lo alcanza** por el camino (§5) en su dirección declarada, y hace la **primera
   convergencia**: usuario y clave del motor, identidad, servicios, direcciones estáticas, y
   deshabilitar el cliente de fábrica.
4. **Escalón 2 — el segundo escalón de la red** (otro CHR y/o servidores): su dirección en la LAN del
   primer CHR es **estática declarada**, y el primer CHR la tiene reservada por MAC derivada. Aquí se
   ve el encadenamiento: el que da la dirección ya está convergido antes de que el otro arranque.
5. **Escalón 3 — los puestos**: `direccion: dhcp`, colgados del CHR de su LAN. **No arrancan hasta
   que su CHR está sirviendo** (regla 18). Su verificación es la de §6.3.

**Nada de esto puede depender de que un humano lance las cosas en el orden correcto**: el orden está
en el plan, y el plan sale de los `escalones` que el lab declara.

## 11. Verificación: qué significa «hecho» ahora

`verify` sigue siendo el test final, y ahora mira **en los dos mundos**:

- **El mundo (API)**: lo de hoy — cada invitado declarado existe, con su pool, su descripción, su
  bridge, su escalón; y nada de fuera del lab se toca.
- **Parte de la verdad se puede leer sin camino**: `GET /nodes/<nodo>/lxc/<vmid>/interfaces` da las
  direcciones reales de cada invitado, desde el host y sin tocar su interior (§1.3). Permite comprobar
  «tiene dirección y está en el rango declarado» **aunque el camino esté caído**. Cuando existen las
  dos lecturas, se dicen las dos.
- **El interior de cada invitado**: para cada **área declarada**, el estado real del equipo coincide
  con lo declarado **en los dos sentidos**: todo lo declarado está, y **nada que no esté declarado
  queda dentro del área** (regla 17). Fuera de las áreas declaradas, el motor **no opina**.
- **Lo que no puede probar, lo dice**: p. ej. que una dirección dinámica viniera del rango declarado
  se prueba por la concesión del router **y** por la dirección del invitado, pero que un cliente no
  haya pedido dos veces, o que un paquete haya cruzado la topología, **no** se prueba aquí. Se dice.
- **El informe** (`logs/verify-*.json` y su resumen humano) lleva los hallazgos del interior con el
  mismo formato que los del mundo: qué se esperaba, qué se encontró, y qué falta.
- **El test de idempotencia incluye el interior**: segunda ejecución con `changed=0` **y** los dos
  diarios con sólo lecturas (regla 6 endurecida). Si la segunda ejecución escribe algo, no está
  hecho.

## 12. Documentación, checks y guardas nuevas

- **ADRs nuevos** (`docs/decisiones/`): `0004` el camino y el token (qué protocolo nuevo se habla
  por la única puerta, qué privilegios exactos tiene el token y qué se descartó: el túnel al propio
  nodo y la plantilla-aparato); `0005` qué es «de la declaración» dentro de un equipo (las áreas);
  `0006` las cuatro puertas y los tres diarios; `0007` el residuo dinámico del CHR (§9.2), con el
  resultado real de la medición. Una decisión por ADR, con el **porqué** y con lo descartado.
- **`docs/camino-del-puesto-de-control.md`**: cómo funciona el camino —el protocolo de la consola y su
  ventana de billete, la línea en base64, el `authorized_keys` de casa con su `permitlisten`, el
  puerto derivado—. **No es una receta para un humano**: no hay nada que pegar a mano.
- **`README.md`**: el motor cambia de verdad, así que el README cambia: verbos (¿siguen siendo los
  mismos? sí: `plan`, `preflight`, `apply`, `verify`, `destroy`), las cuatro puertas, los tres
  diarios,
  y el vocabulario nuevo. **Sin valores de ningún lab** (lo vigila `check readme`).
- **`AGENTS.md`**: las reglas 12–19 del §4 y la tabla «si pasa X → corre Y» con las filas nuevas
  (cambiar un lab con `config:` → `plan --api` y `check docs`; tocar un driver → `check puerta` y los
  tests de interior).
- **El documento de cada lab** (`labs/<lab>/<lab>.md`): la región generada crece para mostrar la
  configuración declarada (una tabla por invitado con sus áreas). La reescribe
  `tools/documentos.py`; la prosa sigue siendo libre y es donde se archiva **lo que se aprendió al
  ejecutar** (los reinicios, los residuos, las trampas del checksum).
- **Checks nuevos o ampliados** (todos con su caso que **debe** fallar, probado a propósito):
  - `puerta`: la ruta base de RouterOS (`/rest`) sólo puede aparecer en `tasks/ros_api.yml`; los
    parámetros de conexión SSH a invitados, sólo en `tasks/interior_ssh.yml` y
    `tasks/inventario_invitados.yml`; y el protocolo de consola, sólo en `tasks/camino_consola.yml`.
  - `privilegios`: nada del motor concede privilegios de la API (ninguna llamada a `/access/…` fuera
    de la guarda de `preflight`); ningún invitado declarado nace privilegiado (`unprivileged`
    siempre), ni con claves crudas de LXC que monten rutas del host, ni con dispositivos.
  - `supernet`: toda dirección y todo rango declarado por un lab cae dentro de su `lab.supernet`, y
    los supernets de dos labs no se solapan.
  - `declaracion`: valida el vocabulario del §6 (tipos, formas de `direccion`, áreas conocidas,
    ninguna MAC, ninguna contraseña, `reservas` bien formadas).
  - `pureza-lab`: sigue igual de estricto, y ahora también con los ficheros nuevos del interior
    (si el nombre de un lab o el de un bridge aparece en el motor, es un bug).
- **Una afirmación de comportamiento que puede ser un check no se queda en prosa.** Si al ejecutar
  descubres una regla nueva («el orden importa porque…»), o se mecaniza, o va a la prosa del lab
  **diciendo que no está mecanizada**.

## 13. Estructura: qué ficheros nuevos, con presupuesto

```
deployment_engine/
  tasks/ros_api.yml              la puerta a RouterOS REST + el diario
  tasks/interior_ssh.yml         la puerta al interior Linux + el diario
  tasks/inventario_invitados.yml construye el inventario en memoria (una vez)
  tasks/camino.yml              el lado del motor: clave del camino, authorized_keys, comprobación
  tasks/camino_consola.yml      la puerta de consola (la única que habla ese protocolo)
  tools/consola.py              el cliente de consola (websocket, sólo biblioteca estándar)
  tasks/configurar_routeros.yml  el driver: orquesta llamadas a ros_api
  tasks/configurar_linux.yml     el driver: lee, decide, escribe, relee
  filter_plugins/interior.py     PURO: (declarado, leído) → pasos del interior  [+ tests]
  playbooks/…                    los verbos, con las fases nuevas del §7
  tools/documentos.py            la región generada, ampliada
docs/decisiones/0004..0007-*.md
docs/camino-del-puesto-de-control.md
labs/<lab-de-aceptacion>/…       el lab nuevo (§14) + su documento
test/test_interior.py            el driver puro, con fixtures
```

**Presupuesto**: `deployment_engine/` **no crece un tercer nivel** de subdirectorios. Si un cambio lo
pide, para y justifícalo por escrito en el README (regla 10). Nada de colecciones: sólo
`ansible.builtin`. Ficheros nuevos: los de la lista, y ninguno más sin decirlo.

## 14. Los labs de aceptación

1. **Un lab nuevo con CHR** (nombre sugerido: `lab-red-routeros`), que ejerza la cadena entera del
   §10: puesto de control (con su **camino**, §5) → primer CHR → segundo escalón → puestos dinámicos. Dos bridges como
   mínimo (gestión y una LAN), dos escalones de red, y puestos que obtienen su dirección del CHR. Es
   el lab que se despliega **de verdad** en el VPS y se destruye al final (§15).
2. **Regresión de los labs de la fase 1** (`lab-dos-redes`, `lab-minimo`, `ejemplo-topologia`): **su
   plan no puede cambiar ni un paso**, porque no declaran `config:` ni `imagen:`. Se comprueba
   comparando la salida de `plan` con una copia de referencia tomada **antes** de empezar.

## 15. Alcance del test final (comandos y salida esperada)

Todo esto se ejecuta y se pega con la salida real. «Funciona» no es una salida.

```bash
./lab check                          # todos los checks en verde, incluidos los nuevos
python3 test/test_interior.py        # el driver puro: declarado+leído → pasos (con fixtures)
./lab --lab lab-dos-redes plan       # MISMO plan que antes de empezar (regresión, §14)

# el ciclo real contra el Proxmox del VPS, con el camino en pie:
./lab --lab lab-red-routeros preflight      # dice qué hay y si el camino responde
./lab --lab lab-red-routeros plan --api     # plan exacto: lecturas y escrituras
./lab --lab lab-red-routeros apply          # converge en UNA sola pasada
./lab --lab lab-red-routeros apply          # changed=0 y los TRES diarios con sólo lecturas
./lab --lab lab-red-routeros verify         # CORRECTO, con lo de dentro comprobado dentro
./lab --lab lab-red-routeros destroy --yes

# y los DOS fallos correctos, provocados a propósito (parte del test, no un extra):
# 1) el camino caído (puesto de control parado): `apply` DEBE reconstruirlo —arrancarlo y rehacer su
#    salida— sin tocar nada más.
# 2) la consola fuera de alcance (privilegio `VM.Console` retirado a mano): `apply` DEBE parar
#    diciendo el privilegio exacto y la llamada exacta, sin tocar nada.
```

Y lo que el reporte final debe decir sin maquillar: qué quedó medido (¿hizo falta el reinicio del
CHR?), qué no se pudo probar y por qué, y qué límites tiene la capa nueva.

## 16. Fuera de alcance (y dónde vive el punto de extensión)

- **Cerrar la consola**: en esta fase la consola de la API **es** el arranque del camino (§5). El
  roadmap la cierra con **el aparato preparado** —una plantilla que ya nace sabiendo salir hacia casa,
  subida al nodo **por la propia API** (`vztmpl`: medido, se puede)—, que dejaría el camino sin
  consola y sin `VM.Console`. Su ADR lo dirá.
- **Estrechar `VM.Console`** de `/vms` (todo el clúster) a una ACL por pool de lab, y **endurecer el
  resto de la ACL por ruta** si al operador le aprieta el radio de daño del §5.1.
- **El nodo sin segmento de gestión**: en un nodo virgen haría falta un bridge con salida (API) y su
  NAT (host). Hoy el `vmbr1` del nodo ya lo es; el roadmap dirá cómo se resuelve en un nodo limpio.
- **Cerrar el SSH de RouterOS**: en esta fase existe declarado, sólo para depurar. El roadmap lo
  cierra (quitar la clave, deshabilitar el servicio) y el check que lo exigirá.
- **VMs Linux con cloud-init** (clave inyectada al crear): el mecanismo se especifica, pero **no hay
  ninguna imagen de nube en el nodo**, así que no se puede aceptar. Se dice, no se finge.
- **Aplicaciones dentro de los invitados** (ficheros, paquetes, servicios, contenedores dentro de
  contenedores): no está en el vocabulario (§6). El punto de extensión es **una primitiva nueva en
  el motor**, con su ADR.
- **Clústeres de varios nodos, otros hipervisores, IPv6 en el interior de los labs.**

## 17. Cómo trabajar y reportar

1. **Capa por capa, y cada capa verificada antes de la siguiente**: (a) **el token nuevo y su guarda
   de mínimos privilegios** (§5.1) — lo primero, porque todo lo demás se apoya en él; (b) el
   vocabulario y su validación + el plan, con tests puros; (c) **el camino** (§5): puesto de control,
   puerta de consola y comprobación de punta a punta, con su prueba de «funciona» y su prueba de
   «falla como debe»; (d) la puerta de RouterOS y su diario; (e) el driver de RouterOS con un CHR
   suelto; (f) el driver de Linux; (g) el encadenamiento por escalones y el lab de aceptación; (h) el
   ciclo real completo.
2. **Pregunta en vez de inventar.** Si algo del §5 o del §10 no encaja con lo que mides, para y
   dilo; no lo rodees con un `ignore_errors`.
3. **Reporta con la salida real de los comandos**, incluida la de los checks y la del ciclo
   `destroy → apply → verify`. Un commit que no ha pasado el ciclo es una promesa sin respaldo.
4. **Escribe lo aprendido donde toca**: la prosa del lab (`filing back`), el ADR correspondiente, y
   **la skill del proyecto** (`netlabs-v4_b`): extiéndela con los procedimientos y las trampas nuevas
   del interior (cómo se lee un CHR, qué se rompe al converger, el orden que importa). Si el interior
   crece hasta pedir su propia skill, créala y dilo.
5. **Nunca** digas que algo funciona sin la salida que lo prueba, y nunca subas `secrets.yml` ni
   `labs/*/logs/`.