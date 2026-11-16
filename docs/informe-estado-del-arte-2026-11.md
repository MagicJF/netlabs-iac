# Estado del arte (noviembre 2026): desplegar topologías RouterOS/CHR en Proxmox de forma idempotente

Informe de investigación encargado el 16-nov-2026. Contrasta el motor de `netlabs-iac`
con lo que hay publicado y propone qué copiar. **No es documentación del motor**: es
un documento de trabajo; cuando se citen sus conclusiones, pásense a un ADR.

> Fecha de corte: 16-nov-2026. Todo lo que se afirma de terceros va con su fuente al
> final. Lo que es mi lectura (y no un hecho publicado) va marcado como **[lectura]**.

---

## 0. Veredicto en una línea

**No estás reinventando toda la rueda, pero sí has reconstruido varias partes que otros
tienen resueltas** —y has construido, en un eje muy concreto, algo que prácticamente
nadie tiene: convergencia **idempotente y verificable del interior de un RouterOS**, sobre
**Proxmox nativo**, **solo por API**, con identidad derivada y documentación verificada.

La forma útil de partir la pregunta es en **dos mitades**:

- **Mitad A — «el mundo»**: crear VMs, contenedores LXC, bridges, pools, discos, arrancar,
  esperar. **Esta mitad está comoditizada.** Hay providers de Terraform, colecciones de
  Ansible y herramientas de lab que la hacen completa y madura. Aquí sí reinventas.
- **Mitad B — «el interior»**: entrar en cada RouterOS/Linux, leerlo, compararlo con lo
  declarado, escribir la diferencia, releerlo y verificar en los dos sentidos, sin estado
  guardado. **Esta mitad es tu foso**, y el ecosistema la tiene en pañales: el mejor
  competidor (netlab) da a RouterOS un soporte «minimal» y ni siquiera apunta a Proxmox.

Dicho de otro modo: **lo que casi nadie hace es exactamente lo que tú haces bien; lo que
casi todos hacen, tú lo haces a mano.** El informe ordena las recomendaciones por eso.

---

## 1. El mapa del ecosistema (seis familias)

### 1.1 Orquestadores de laboratorio basados en contenedores

- **containerlab** (srl-labs) — el líder de facto. Topología en YAML, `deploy/destroy`,
  cableado virtual, captura de paquetes, *link impairments* con `netem` (delay, jitter,
  loss, MTU), integración con CI, y extensiones a Kubernetes con **clabernetes (c9s)** para
  labs de cientos de nodos. Corre sobre Docker en un host Linux (a menudo un contenedor/VM
  dentro de Proxmox). Soporta MikroTik con **dos** kinds:
  - `mikrotik_chr` — la imagen **oficial** `mikrotik/chr` de Docker Hub (amd64/arm64), sin
    build de vrnetlab; listón de conexión con 7.24.5/7.23.8/7.25rc2. Arranca la CHR en
    QEMU dentro del contenedor (KVM si hay `/dev/kvm`, si no TCG).
  - `mikrotik_ros` — CHR desde una imagen que construyes con **vrnetlab**.
  - Detalles que te interesan: `startup-config` importa un `.rsc` **una vez al arrancar** por
    REST; hay **`healthcheck`** y *readiness* (`chr-launch: RouterOS ready`) que habilitan
    `stages`/`wait-for: healthy`; credenciales por env creando usuario en grupo `full` y
    **deshabilitando el `admin` de fábrica**; y la convención de interfaces `ethN` ↔
    `ether(N+1)` (con huecos) que **coincide con tu regla de numeración por orden de bridges**.
- **Kathará** — emulación ligera sobre Docker, sucesor espiritual de Netkit. Escenarios
  `lab.conf` + ficheros `*.startup` por dispositivo; backend Docker o Kubernetes
  (**Megalos**). Fuerte en docencia; configuración por fichero de arranque, no por
  convergencia idempotente.
- **netlab** (ipSpace / Ivan Pepelnjak) — ver 1.4, es su propia categoría.

### 1.2 Emuladores de VM con GUI

- **GNS3**, **EVE-NG**, **Cisco CML**, **PNetLab**. Importas la imagen CHR y cableas con
  ratón. Cómodos para estudio, malos para CI y para "infraestructura como código".
  Conclusión de los comparativos de 2026: containerlab para "topology-as-code"; GNS3/EVE-NG
  para labs gráficos offline.

### 1.3 Empaquetado de VMs de router en contenedores

- **vrnetlab** (y su fork **srl-labs/vrnetlab**, que es el que usa containerlab) — mete una
  VM (QEMU/KVM) dentro de un contenedor para reutilizar la orquestación de contenedores.
  Cablea los NICs de la VM con `tap` + `tc`/mirroring. Es la pieza que hace que
  containerlab pueda tener routers que solo existen como VM.

### 1.4 Generadores de topología de alto nivel (intención, no detalle)

- **netlab** — el más ambicioso. Escribes la **intención** en YAML (nodos, enlaces,
  módulos: `ospf`, `bgp`, `vlan`, `vrf`, `vxlan`…) y netlab **deriva**: plan de
  direccionamiento IPv4/IPv6 (pools, loopbacks, /31 P2P, LANs), diseño de encaminamiento,
  plantillas de configuración **Jinja2** para 20+ plataformas, inventario de Ansible, y los
  ficheros de Vagrant/containerlab. Comandos: `create`, `up`, `down`, `initial`, `config`,
  `collect`, `connect`, `capture`, `exec`, `tc`, **`validate`**.
  - **Providers**: `libvirt` (Vagrant/KVM), `clab` (containerlab), `virtualbox`
    (deprecado), `external` (hardware). Puede combinar providers (VMs y contenedores en el
    mismo lab). **Está *sunsetting* libvirt y va a por containerlab como único provider.**
  - **MikroTik RouterOS 6 y 7**: tipo de dispositivo `routeros`/`routeros7`, **nivel
    `minimal`**, y **solo con el provider libvirt** (no está soportado en clab — ver su
    tabla de combinaciones). Su box libvirt de RouterOS 7 existe y funciona. **No apunta a
    Proxmox.**

### 1.5 IaC de aprovisionamiento (la "mitad A")

- **Terraform/OpenTofu `bpg/proxmox`** — el provider de Proxmox sano y mantenido (fork del
  difunto `danitso`, supera al viejo Telmate). Cubre **Proxmox VE 9.x**, VMs **y LXC**,
  `import_from` para discos **por API** (sin SSH), **cloud-init**, discos, redes, pools.
  Modelo `plan/apply/destroy` con **fichero de estado**.
- **Terraform/OpenTofu `terraform-routeros/routeros`** (Gnewi) — configuración **declarativa
  de RouterOS por su REST**, con recursos para casi todo el árbol de menús (ip address,
  route, dhcp-server, interface bridge, firewall filter/nat/mangle, wireguard, bgp, ospf…).
  **Es la mejor fuente pública para el *vocabulario* de tus áreas.**
- **Ansible `community.routeros`** — módulos `api`, `api_modify`, `api_find_and_modify`,
  `api_info` sobre el API de RouterOS. El módulo `api_find_and_modify` existe **justo**
  porque «RouterOS no es idempotente» (busca y modifica por `.id`). Soporte `check_mode` y
  `diff_mode` completos.
- **`community.general.proxmox_kvm`** y similares — Ansible puro para crear VMs en Proxmox
  (lo que tú has evitado a propósito con tu vía de acceso REST).

### 1.6 Fuente de verdad / IPAM / validación

- **NetBox / Nautobot** — fuente de verdad de red (NSoT) e IPAM. Nautobot es el fork
  extensible orientado a automatización (Jobs, GraphQL, apps).
- **Validación funcional**: **`netlab validate`** (tests declarados en la topología, con
  `wait`/`retry`, pensados para CI), **pyATS/Genie**, **Batfish** (análisis de config
  offline), **pytest-for-networking / netpicker**, **SuzieQ** (observabilidad).

### 1.7 Productos comerciales (el ángulo "agente IA")

- **NetPilot** — labs preconstruidos con la imagen `mikrotik/chr`, y **un agente de IA que
  construye el lab desde un *prompt* en ~2 minutos**. Es lo comercialmente más cercano a
  tu idea de "Ansible como arnés de agentes IA". **[lectura]** No es idempotente ni
  verificado como lo tuyo; es "genera y ya".

---

## 2. Comparación pieza a pieza con `netlabs-iac`

| Capacidad | Quién la tiene resuelta | Tú |
| --- | --- | --- |
| Declarar topología en YAML versionado | containerlab, netlab, Kathará | **Sí** (`labs/<lab>/<lab>.yml`) |
| Crear VMs/LXC/bridges/pools | bpg/Telmate (TF), `proxmox_kvm` (Ansible) | **Sí, a mano, por API REST** |
| Idempotencia con estado | Terraform (fichero de estado) | **Sí, sin estado** (re-deriva del clúster) — *mejor propiedad* |
| Carga de imagen de fábrica (CHR) al crear | containerlab/vrnetlab, bpg (`import_from`) | **Sí** (`import-from`, ADR propios) |
| Cableado explícito entre nodos | containerlab (links), netlab | **Parcial** (bridges del nodo; sin "links" de 1ª clase) |
| Entrar en el interior de un router y **convergerlo** | **casi nadie** (netlab routeros7 = minimal; containerlab importa `.rsc` una vez) | **Sí** — tu foso |
| Driver Linux idempotente (leer→decidir→escribir→releer) | netlab (plantillas + Ansible), tú | **Sí** |
| Verificación declarado↔real en los dos sentidos | Terraform (drift), tú | **Sí** (incluye "sobra algo = fallo") |
| Verificación **funcional** (¿hay conectividad? ¿convergió OSPF?) | **`netlab validate`**, pyATS, Batfish | **No** — y lo dices |
| Readiness / healthcheck por nodo | containerlab (`wait-for`, healthcheck) | **Sí, implícito** (sonda por etapa) |
| Captura de paquetes | containerlab (`capture`) | **No** |
| *Link impairment* (delay/loss/jitter/MTU) | containerlab (`netem`) | **No** |
| Diagrama de topología autogenerado | netlab (`--graph`) | **No** (solo tabla markdown) |
| Plan de direccionamiento **derivado** de pools | **netlab** (lo hace entero) | **Parcial** (`static_leases: derived`; las IPs se escriben a mano) |
| CI de verdad (GitHub Actions) | containerlab, netlab (tests de integración por dispositivo) | **No** (fuera de alcance) |
| Secretos cifrados | Ansible Vault, sops/age | **No** (texto plano, decidido) |
| Concurrencia / escala horizontal | clabernetes, netlab multi-provider | **No** (documentas que es en serie) |
| Arnés para agentes IA | NetPilot (comercial) | **Sí** (AGENTS.md + reglas + checks) — diferencial |
| Documentación con dos regiones y refs selladas | nadie, exactamente | **Sí** — diferencial |

---

## 3. Dónde NO reinventas la rueda (tu foso real)

1. **Convergencia idempotente del interior de RouterOS/RouterOS-CLI.** El mercado o importa
   un `.rsc` una vez (containerlab) o da soporte «minimal» (netlab). Tú lees el estado por
   REST, decides el diff y escribes **solo lo que cambia**, y lo pruebas por relectura.
   Eso no lo tiene nadie empaquetado como tú.
2. **Idempotencia sin fichero de estado.** Terraform necesita estado (y sufre *drift* de
   estado). Tú re-derivas de la fuente de verdad de verdad (el clúster) + marcas de
   propiedad (pool, descripción, `comments`). Es una propiedad superior para un nodo único,
   y no la tiene ni Terraform.
3. **La frontera de propiedad** (pool + descripción + marca de bridge) que permite
   convivencia de labs sin estado. Original y sólido.
4. **Documentación verificable** (dos regiones, punteros vivos, sellado por hash, check que
   se ha visto gritar). Ningún proyecto de lab de red hace esto.
5. **`AGENTS.md` como contrato inyectable y checks que vigilan el propio motor.** El "Ansible
   como arnés de agentes IA con idempotencia garantizada por relectura" es un diferencial
   real frente al "agente genera y reza" de NetPilot.

---

## 4. Dónde SÍ reinventas (y qué copiar exactamente)

### 4.1 La "mitad A" (el mundo) está resuelta — **estúdiala, no necesariamente la cambies**

Tu capa de crear/actualizar/borrar objetos de Proxmox es manual. El ecosistema la tiene
madura. **No te digo que te pases a Terraform** (te costaría tu ADR 0001 y tu diario), pero:

- **Minar el provider `bpg/proxmox`** para saber qué cubre el dominio de recursos
  (VMs, LXC, `import_from`, cloud-init, discos, pools, SDN) y **compararlo con lo que
  implementas a mano**. Si algo que haces está resuelto ahí, mejoras tus defaults y evitas
  bugs de esquema.
- **Nota importante**: `bpg` documenta que **con token API no-PAM** algunas operaciones de
  **LXC privilegiado / `arch`** fallan (piden `root@pam`), y que **snippets/backups**
  necesitan SSH con cuenta PAM. Tú ya evitás eso (nada de snippets, `unprivileged`, etc.).
  Es un **argumento a favor de tu diseño**, no en contra: confirma que "solo API" tiene
  bordes que tu motor ya esquiva.

### 4.2 El vocabulario de RouterOS ya está inventariado por otros

- **`terraform-routeros/routeros`** (Gnewi) es, en la práctica, **el esquema completo de lo
  que un RouterOS declara** (por recurso, con atributos). Úsalo como **checklist** para
  extender tus áreas cerradas (`bridges`, `queues`, `wireguard`, `bgp`, `ospf`, `mangle`…)
  con confianza, sin inventar nombres.
- **`community.routeros.api_find_and_modify`** resuelve el mismo problema que tu driver
  (buscar por `.id` y modificar en vez de añadir duplicados). Es **prior art directo** de tu
  bucle leer→decidir→escribir; su doc y sus `extended_query`/`where` son una fuente de ideas
  para el matching de tus áreas.

### 4.3 La abstracción "intención vs proveedor" (lección de netlab)

netlab separa **topología (intención)** de **provider (dónde se ejecuta)**. Tu `lab.yml`
**mezcla** ambas: declara intención (`roles`, `address`) **y** acoplamiento a Proxmox
(`bridges`, `image`, `uplink`, `pools`). Para un solo hipervisor está bien; el precio es que
tu motor **no sobrevive a un cambio de sustrato** (otro hipervisor, contenedores, hardware).
No es urgente, pero **es la lección arquitectónica más importante del sector** y conviene
tenerla escrita como límite consciente (o plan).

### 4.4 El "derivado" de netlab aplicado al direccionamiento (tu `static_leases: derived` es el patrón)

netlab **deriva el plan de direccionamiento entero** de unos pools + la topología. Tú haces
esto **solo** para las reservas DHCP. **Es tu propia idea llevada a la mitad de su
potencial**: podrías derivar también direcciones de bridge, bucles, y rangos de servidores
DHCP desde `lab.address_space`. Es el apartado 6.1.

---

## 5. Lo que te falta y el mercado da por supuesto

1. **Verificación funcional (behavioral).** `netlab validate`, pyATS, Batfish: no solo "¿existe
   lo declarado?", sino "¿h1 llega a h2? ¿está `active=true` la ruta? ¿convergió el protocolo?".
   Tú lo dices explícitamente en el README («que un paquete haya cruzado la topología, no se
   prueba aquí»). **Es el hueco más grande y el más alineado con tu filosofía.**
2. **Readiness declarativo y a nivel de nodo.** containerlab lo hace de primera clase
   (`wait-for: healthy`, healthcheck por kind). Tu sonda existe pero está acoplada a la
   etapa; el sector lo expone como **predicado declarado por nodo con su timeout**.
3. **Captura e impairment de enlaces.** Estándar en containerlab (`capture`, `tc`/netem).
   Tú no tienes ni lo uno ni lo otro. **Se puede reconducir a tu modelo** (ver 6.4).
4. **CI.** containerlab y netlab lo consideran básico. Tú lo tienes fuera de alcance —pero tu
   `plan` funciona **offline con fixtures**, así que un CI que no necesita Proxmox es barato.
5. **Secretos cifrados.** Vault/sops son el estándar. Tu "texto plano 0600" es una decisión
   consciente y **reversible sin romper tu arquitectura** (ver 6.6).
6. **Concurrencia/escala.** clabernetes resuelve el paralelismo con k8s. Tú documentas que
   aplicar en paralelo es inseguro (misma lectura → mismo vmid). Hay un arreglo pequeño (6.7).
7. **Diagrama autogenerado.** netlab genera grafos de la topología. Tú generas tablas. Un
   diagrama derivado encaja **exactamente** en tu "región generada".

---

## 6. Recomendaciones priorizadas

> Todas están pensadas para **encajar en tu arquitectura**, no para cambiarla. Las P0 son
> baratas y de alto retorno; las P2 son estratégicas.

### P0 — baratas, alineadas con tu filosofía, alto retorno

> **Estas cuatro NO se quedaron en el papel.** Se implementaron y se midieron desplegando
> labs de verdad el 16 de noviembre de 2026, y lo que se cuenta debajo de cada una es lo
> que salió: lo que aportan, lo que **no** hacen, y los errores que sólo aparecen cuando
> el motor se enfrenta a Proxmox. El veredicto junto está al final del apartado.

**6.1 Asignador de direcciones (IPAM) derivado del `address_space`.**
Ya tienes `lab.address_space` y el check que lo vigila, y ya derivas reservas DHCP. Da el
paso natural: un **asignador puro** `(declaración, estado) → direcciones` que reparta rangos
y direcciones de pools declarados, igual que `identidad.py` reparte vmids y MACs.
- Extiende **la misma idea** (`static_leases: derived`) a `bridge.address`, LANs y pools DHCP.
- Mantén el escape: `address: 10.x.y.z/24` explícita sigue ganando (como el `nombre:` corto).
- **Beneficio**: menos YAML, menos errores humanos, y `check address_space` pasa a probar la
  **asignación**, no solo el encuadre.
- Fuente: patrón de pools de netlab.

**MEDIDO (16-nov-2026).** Implementado como `direcciones_resolver` en
`filter_plugins/identidad.py`: un asignador puro `declaración → declaración`, sin estado,
idempotente, que resuelve `derived` en los bridges del lab, la dirección de cada invitado,
las patas de los CHR, el `network`/`pool.rango` de su DHCP y las reservas estáticas. Un
valor explícito siempre gana.

La prueba de fuego: se cogió el lab `06_conectividad-exterior`, que tiene **21 direcciones
escritas a mano**, se marcaron todas como `derived` y se comparó lo que el IPAM deriva con
lo que el lab decía. El resultado no es el que el informe suponía:

- **9 el IPAM deriva EXACTAMENTE la misma dirección.** Los tres bridges del lab y, en cada
  CHR, su pata de dentro, la red de su DHCP y la pasarela de esa red. Es justo el sitio
  donde más se copia y pega un lab, así que ahí el valor es real: `derived` no cambia nada
  y quita de en medio el error humano.
- **4 el IPAM deriva OTRA dirección.** Los dos CHR y los dos contenedores se **intercambian
  el `.10` y el `.11`**: el IPAM numera los routers primero y los contenedores después, y
  el lab los numeraba al revés. No rompe nada, pero deja claro que `derived` **no es un
  no-op en todas partes: adoptarlo renumera el lab**. Y un lab ya desplegado no se renumera
  gratis: cambia la dirección de un equipo que ya está en servicio.
- **8 no las cubre**: las rutas (`dst_address` y `gateway`), el `dns` que anuncia el DHCP de
  cada CHR, la pasarela declarada de un invitado, la dirección de la pata Linux del bastión
  y el rango del DHCP de Linux. Ahí `derived` se queda en `derived` y el validador lo dice
  (no se resuelve a medias en silencio).

El caso del `dns` merece un renglón, porque enseña el límite de la idea: el IPAM deriva
como resolutor la pasarela del bridge, y este lab quiere anunciar el router de **salida**
(el único que resuelve). Eso el motor no lo puede adivinar. La recomendación del informe
(«menos YAML») es cierta en el 43 % de los valores de este lab y falsa en el resto.

- **2ª conclusión, y es la que más costó**: un asignador puro que **muta una copia** de la
  declaración es invisible dentro de Ansible. Ansible no le pasa al filtro un `dict`: le pasa
  un `_AnsibleLazyTemplateDict`, un mapa perezoso que vuelve a plantillar desde el original
  en cada lectura. El IPAM resolvía sobre su copia y el validador leía el original, así que
  el motor se negaba a desplegar un lab perfectamente coherente con 16 errores fantasma
  («los `derived` se salen del espacio de direcciones», «el lab no declara `address_space`»).
  Lo arregla una función de veinte líneas (`_plano`, en `declaracion.py`) que convierte la
  entrada en Python de verdad antes de tocarla. **Sin eso, la recomendación no se puede
  implementar, y con eso se implementa entera.**

**6.2 `./lab test` — verificación funcional declarada en el lab.**
Un bloque `tests:` en `lab.yml` (del tipo: `ping`, `traceroute`, `ruta activa`, `vecino`,
`servicio`), ejecutado **por los drivers que ya tienes** (REST del router, SSH del Linux),
con salida en un diario y un veredicto. Es **literalmente tu propia regla** («una afirmación
de comportamiento que puede ser un check, no se queda en prosa»): hoy "el paquete cruza" es
prosa; con esto pasa a ser un test.
- Inspírate en `netlab validate` (tests + `wait`/`retry` + exit code para CI) y en
  pytest-for-networking (aserciones legibles).
- No metas colecciones ni dependencias nuevas: se ejecuta **dentro de los invitados** que ya
  alcanzas, con las herramientas que ya tienen.
- **Beneficio**: cierras el hueco nº1 del sector y refuerzas tu diferencial.

**MEDIDO (16-nov-2026).** Implementado como bloque `tests:` del lab (vocabulario cerrado:
`ping`, `servicio`, `dns`, y nada más por ahora), verbo `./lab test`, un playbook que lo
lanza por SSH en el invitado y consolida veredictos, y **tres códigos de salida**: `0` OK,
`1` KO, `3` OMITIDA. El `3` no es un adorno: es lo que evita que el entorno se confunda con
el lab. Tres cosas que sólo se aprenden ejecutándolo:

- **Dentro de un `bash -c '...'` no puede haber NI UNA comilla simple.** El comando de la
  prueba de `dns` llevaba un `cut -d' '`, y esa comilla cerraba el `bash -c` antes de
  tiempo: la prueba decía «falla» cuando lo que fallaba era el entrecomillado. Hay un test
  que lo vigila (`count("'") == 2`).
- **`ping` necesita `CAP_NET_RAW`.** En una imagen de contenedor sin privilegios devuelve
  «Operation not permitted», que no es un fallo del lab sino del entorno: ahora la prueba
  comprueba antes si puede emitir paquetes y sale con `3` (OMITIDA) en vez de con `1`.
- **Una prueba `dns` necesita un nombre que EXISTA — y el ejemplo del propio informe no lo
  hacía.** El informe proponía `{tipo: dns, hacia: ejemplo.test}`; medido en el mismo instante
  y por el mismo camino, `nacsira.com` resuelve (104.21.65.222) y `ejemplo.test` no existe. La
  prueba no fallaba por el lab: fallaba porque el nombre no está. El motor no puede inventar
  nombres — si un lab quiere probar un nombre SUYO, tendrá que declararlo (dnsmasq/hosts), y
  ese vocabulario todavía no existe. Es el segundo hueco que sólo aparece al ejecutar (el
  primero: no se puede esperar un fallo).
- **Las pruebas sólo se pueden lanzar desde un invitado al que el motor llegue** — o sea,
  desde el bastión, que es el único con túnel. En un lab donde los equipos interesantes son
  contenedores planos a los que sólo se llega por la red del lab (`ws-1`, `srv-1`), no se
  puede entrar en ellos a probar. **La recomendación promete «verificación funcional del
  lab» y eso es lo que da; no promete verificar cada invitado por dentro, y no lo hace.**

**MEDIDO EN EL LAB COMPLEJO (`08_dunder-mifflin-con-fw`, `apply` en frío rc=0 en 913 s):** las
cinco pruebas —el plano de gestión de los cuatro CHR, con **tres cortafuegos de RouterOS en
medio**— **pasan las cinco al primer intento** (`pasan=5 fallan=0 omitidas=0`, 44 s). Es justo lo
que `verify` no puede decir: `verify` confirma que cada `firewall` declarado es lo que dice ser,
regla a regla; esto confirma que el filtrado **deja pasar lo que tiene que dejar pasar** (que el
motor se sigue pudiendo configurar por su túnel a través de equipos que filtran). Y aquí se ve
otra vez el límite del vocabulario: la mitad interesante de ese lab es lo que **no** debe pasar
(de la red de gestión a la oficina), y no hay forma de declarar «esto tiene que fallar».

**6.3 Readiness de primera clase por nodo.**
Saca la "sonda" a la declaración: `ready:` por invitado (p. ej. `ready: {routeros_rest: true}`,
`ready: {ssh: true}`, `ready: {dhcp_lease: true}`), con su timeout, y que `plan` lo trate como
un paso (`esperar_servicio`). Es el `wait-for: healthy` de containerlab, en tu vocabulario.
- **Beneficio**: hoy el readiness está **implícito en las etapas**; explicitarlo hace el
  contrato legible y comprobable, y desacopla "orden" de "listo".

**MEDIDO (16-nov-2026).** Implementado como `ready:` por invitado, con tres tipos
(`ssh`, `routeros_rest`, `ninguno`) y `espera:` en **segundos** (que el motor traduce a
intentos con el compás que ya tenía para la sonda). Un invitado sin `ready:` se comporta
exactamente como antes: la barrera que el motor insinuaba por el tipo no se toca, así que
los ocho labs que ya existen no cambian. Lo que salió al implementarlo:

- **El agujero que cierra es más grande de lo que el informe decía.** No era sólo
  «explicitar» una espera implícita: un invitado **sin `config:` declarado no tenía barrera
  ninguna, y no había forma de pedirla**. El motor decidía, y decidía «ninguna». Con `ready:`
  el lab dice «espérame por ssh 90 s» aunque el invitado no tenga interior que converger —
  que es el caso de media docena de invitados de estos labs. Ahí está el retorno de verdad.
- **`ninguno` necesitó una excepción explícita en el validador.** Estaba prohibido declarar
  `ready` sobre un invitado que toma su dirección por DHCP (no hay dirección que sondear), y
  esa regla hacía `ninguno` **inutilizable justo donde más sentido tiene**: decir «a este no
  le esperes» es una afirmación, y callarse es otra cosa (callarse es «decide el motor», y en
  un invitado con DHCP el motor ya no sondea). Ahora `ninguno` se admite y el resto de tipos
  siguen rechazándose con su motivo.
- **La ventana declarada no llegaba a la sonda, y lo cazó un `apply` en frío real.** El
  primer POST paró con «`'control' NO contesta en 10.42.0.10:22`». El invitado estaba
  perfectamente: lo que llegaba mal era el **tope de intentos**. Un `None` no dispara el
  `default` de Jinja — sólo sustituye lo *indefinido* —, así que el comando que se le mandaba
  al bastión quedaba en `while [ $i -lt  ]`: un error de shell, y la barrera **no podía pasar
  nunca**, tardara lo que tardara el equipo. Se arregla con `default(..., true)` en las dos
  puntas (`paso.yml` y `sonda.yml`). Es el fallo más instructivo de los siete: **el comando
  se genera perfecto y el error sólo existe dentro del shell del invitado**, así que no hay
  lectura del código que lo encuentre. Y deja el precio de `ready:` a la vista: como la
  barrera es un tope DURO, una `espera:` declarada **más corta** que la del motor
  (`engine_sonda_intentos` = 24 intentos × 7 s = 168 s) puede hacer que un lab que hoy
  despliega, mañana no despliegue.

**MEDIDO EN EL LAB COMPLEJO (08, `apply` en frío rc=0 en 913 s):** el 08 declara la barrera de
sus cuatro CHR (`routeros_rest`, 240 s), la del bastión (`ssh`, 120 s) y cinco `ninguno` (los
hosts), y el lab entero se desplegó con cada barrera cumpliéndose en el orden de su etapa. Es,
de hecho, el lab donde `ready:` más se nota: sus **cinco hosts no declaran `config:`** (no se
entra en ellos), así que sin `ready` habrían quedado **sin barrera y sin forma de pedirla** — que
es exactamente el agujero que esto cierra. Y confirma lo de arriba: 120 s SÍ bastan para un
bastión; el fallo del primer POST de 06 no era la espera, era el tope vacío.

**6.4 Captura y "impairment" como primitivas del **bastión**.**
containerlab da `capture` y `netem`. En Proxmox, `tc` en el host violaría tu ADR 0001 (SSH al
nodo). **Pero tu bastión ya tiene una pata en cada bridge del lab** y ya lo configuras por
SSH (tu vía de acceso). Por tanto:
- `capture: {bridge, filtro, segundos}` → `tcpdump` **en el bastión** (que ya controlas), con
  su línea en `interior.jsonl` y el pcap como artefacto del lab.
- `impairment: {bridge, retardo, pérdida, jitter}` → `tc`/`netem` **en el bastión** (es un
  Linux que tú ya convergés). El tráfico que cruza ese bridge se ve afectado.
- **Beneficio**: entras en la liga de containerlab **sin romper** "solo API al hipervisor".

**MEDIDO (16-nov-2026).** Implementado como bloque `capture:` (un `tcpdump` acotado en la
pata del bastión del bridge que el lab diga) y bloque `impairment:` (`tc netem` en esa
misma pata), cada uno con **su verbo** (`./lab capture`, `./lab impair`) porque no son estado
deseado: son experimentos. Y el impairment es **acotado por diseño**: se aplica, espera lo
que declare el lab y **se quita en el mismo comando**, así que ni un fallo del motor deja un
lab estropeado sin dueño. Un `netem` huérfano es peor que un lab sin impairment.

- **`capture` funciona porque `tcpdump` pone la interfaz en modo promiscuo**: el bridge de
  Linux le entrega también el tráfico que no va dirigido a él. Eso es lo que hace útil a la
  pata del bastión — y es una propiedad del modo promiscuo, no del bridge.
- **Y hay un límite de dónde se puede medir, que el primer POST enseñó a golpes.** El
  informe daba por hecho que el bastión tiene «una pata en cada bridge»; **no la tiene**: su
  dotación es el bridge de gestión más los que declare en `bridges:`. Se declaró una captura
  en la LAN del lab 06 y el motor la rechazó al montarla («el bastión no tiene una interfaz
  en el bridge `vmb_ext_lan1`») — con el lab ya desplegado. Dos arreglos: el lab mira donde
  de verdad tiene pata, y **el validador lo comprueba al leer la declaración** (`check`), no
  al ejecutar el verbo. Medir DENTRO de una zona pide darle antes al bastión una pata ahí,
  que es una decisión de topología, no un detalle del verbo.
- **`impairment` NO hace lo que el informe prometía, y esto es lo importante.** El texto de
  arriba dice que el bastión tiene «una pata en cada bridge» y de ahí deduce que puede
  estropear «lo que cruza ese bridge». **No puede**: en un bridge de Linux cada invitado
  tiene su propia interfaz, y `netem` se pone en la del bastión, así que estropea **el
  tráfico del bastión** — el suyo — y no el de dos invitados que hablen entre ellos. Medido:
  el retardo se ve en el ping del bastión (de ~1 ms a ~200 ms) y no afecta a un tercero. Para
  estropear el tráfico de otros habría que tocar `tc` en el nodo, que es exactamente lo que
  prohíbe el ADR 0001.
- Conclusión: **`capture` es una primitiva de primera clase con una salvedad; `impairment`
  es útil para ensayar «y si el LAB se comunicara mal» (el bastión está dentro del lab), pero
  no como perturbador de red del bridge.** Si lo que se quiere es eso, hay que decirlo así en
  el informe y no venderlo como el `netem` de containerlab.

**MEDIDO EN EL LAB COMPLEJO:** `./lab capture` sobre el 08 terminó bien (**rc=0, 85 s**) y
`./lab impair` sobre el 06 también (**rc=0, 44 s**: el `netem` se aplicó, se esperó lo declarado y
se retiró), sin dejar nada puesto en ninguno de los dos. Sobre un lab de nueve invitados con tres
cortafuegos, el experimento se monta y se desmonta solo.

### Lo que sale de medirlas (16-nov-2026)

Las cuatro se implementaron de verdad y se probaron con **dos ciclos reales sobre el lab
mínimo** (`06_conectividad-exterior`: 6 invitados, dos CHR encadenados y salida a internet)
— uno con el motor tal como estaba (**PRE**) y otro con las cuatro puestas (**POST**), en
frío los dos — más el **lab complejo** (`08_dunder-mifflin-con-fw`, con cortafuegos de
RouterOS), para ver si aguantan donde el lab tiene de verdad que hacer cosas.

**El ciclo, medido (lab 06, en frío):**

- **PRE**: `destroy` del lab 08 para liberar el nodo → **163 s**; `apply` en frío del lab 06
  → **rc=0, 665 s** (11 min).
- **POST** (`destroy` del lab de gestión + `apply` en frío con las cuatro declaradas):
  **`apply` rc=0 en 662 s**; `verify` rc=0 (56 s); **`./lab test` rc=0 con 5 de 5 pruebas
  pasando** (53 s); `./lab capture` rc=0 (83 s); `./lab impair` rc=0 (45 s). Las cinco pruebas
  son el mismo plano que el lab promete: los dos routers de la cadena, la LAN que sirve el
  borde, su REST y la resolución de nombres por su resolutor.
- **Y el lab complejo, medido de verdad**: `08_dunder-mifflin-con-fw` (9 invitados, 4 CHR, tres
  cortafuegos) se desplegó en frío con las cuatro P0 declaradas en **913 s, rc=0**, con su
  `verify` en verde (76 s) y sus **cinco pruebas funcionales pasando al primer intento** (44 s).
  Ojo a la letra pequeña: de ese lab **no se midió un PRE** porque su `apply` nunca formó parte de
  la línea base (de la fase PRE sólo se midió su `destroy`, 163 s). Y no es un hueco que cambie la
  conclusión: **las P0 no añaden ni un paso al plan de un lab** —`ready:` sólo cambia la ventana de
  una barrera que ya existía, y `tests`/`capture`/`impairment` sólo los ejecutan verbos nuevos—,
  así que el tiempo de despliegue no es donde está su valor. Lo que había que probar del lab
  complejo no era cuánto tarda, sino **si aguanta con las cuatro puestas**; aguanta.
- **Lo que dice el A/B**: 665 s (PRE) frente a 662 s (POST) es, a efectos prácticos, el MISMO
  tiempo — Δ 3 s, un 0,5 %, dentro del ruido de que un nodo arranque una máquina un poco más
  lenta. Confirma lo que se deducía del diseño: **las cuatro P0 no cuestan despliegue.** Su
  retorno no se mide en minutos de `apply`: se mide en errores que no se cometen y en cosas
  que antes no se podían decir.

**El veredicto, una por una:**

- **6.3 `ready:` → SÍ, y es la primera que se implementaría.** La más barata (un campo por
  invitado), no cambia ninguno de los ocho labs que ya existen (sin `ready:` todo se comporta
  igual), y cierra un agujero real que el informe no había visto: **un invitado sin `config:`
  no podía declarar barrera ninguna**. Añade vocabulario de dos valores (`ssh`,
  `routeros_rest`) y un «ninguno» que es tan informativo como los otros. Coste: bajo. Riesgo:
  bajo (una espera mal declarada se ve en el primer `apply`, no en silencio).
- **6.2 `./lab test` → SÍ, con el límite dicho en voz alta.** Aporta lo que `verify` no puede
  dar (que el lab *haga* lo que promete, no sólo que *sea* lo declarado), y el código `3`
  (OMITIDA) es lo que lo mantiene honesto cuando el entorno no puede comprobar algo. Su
  límite: **sólo puede probar desde un invitado al que el motor llegue** (el bastión), así que
  no sustituye a probar dentro de cada equipo. Con eso claro, es retorno directo.
- **6.1 IPAM `derived` → SÍ, pero acotado y sin prometer lo que no da.** En el lab medido
  resuelve bien el 43 % de los valores escritos a mano (bridges y el bloque DHCP de los CHR,
  que es donde de verdad se copian y pegan errores), renumera el lab en otro 19 %, y no cubre
  el 38 % restante (rutas, `dns` de intención, pasarelas, interior de Linux). **El valor está
  en el trozo mecánico, no en «menos YAML».** Adoptarlo en un lab ya desplegado es un cambio
  real de direcciones, no cosmético. Y hay una condición técnica que no se puede saltar: **el
  asignador tiene que convertir lo que le da Ansible en Python de verdad antes de tocar nada**
  (`_plano`) — sin eso el motor se niega a desplegar un lab coherente con 16 errores fantasma.
- **6.4 `capture` / `impairment` → `capture` sí (con salvedad), `impairment` NO como está
  propuesto.** `capture` es una primitiva útil y barata (el bastión ya está, y el modo
  promiscuo hace el trabajo). `impairment` estropea **al bastión**, no al bridge: no es el
  `netem` de containerlab que el apartado insinúa, y venderlo como tal sería prometer algo que
  no cumple. La parte que **sí** vale de ambos es el diseño acotado: el experimento se apaga
  solo, así que no deja el lab roto.

**Los errores que sólo aparecen al desplegar.** Ésta es, con diferencia, la parte más
aprovechable de haberlo implementado en vez de escribirlo: ninguno de estos siete se ve
leyendo el código, y seis de ellos habrían pasado a `main` sin la prueba con Proxmox delante.

0. **El tope de la sonda llegaba vacío: la barrera no podía pasar nunca.** El comando que se
   le manda al invitado quedaba en `while [ $i -lt  ]` (un error de shell) porque `None` no
   dispara el `default` de Jinja: sólo sustituye lo *indefinido*, y `None` está definido. El
   síntoma fue un `apply` en frío parado en «`'control' NO contesta`» con el invitado
   funcionando. Se arregla con `default(..., true)` en `paso.yml` y en `sonda.yml`. Es el que
   más enseña: **el comando se genera perfecto y el error sólo vive dentro del shell del
   invitado**.
1. **`_AnsibleLazyTemplateDict`.** Ansible no pasa el YAML al filtro: pasa un mapa perezoso
   que re-plantilla desde el original en cada lectura. Todo asignador puro que **copie y
   mute** la declaración es invisible: el IPAM resolvía sobre su copia y el validador leía el
   original. El síntoma fue el peor posible — 16 errores que acusaban al lab de incoherente,
   con mensajes ciertos sobre datos falsos. Arreglado con `_plano()`.
2. **La normalización se comía lo nuevo.** `declaracion_normalizar` construye una declaración
   nueva con las claves que conoce; al no incluir `tests`, `capture` ni `impairment`, los
   verbos nuevos habrían recibido una declaración **sin nada que ejecutar**. Un verbo que
   existe y no ve lo que declara el lab.
3. **Dos formas de leer la declaración.** La cruda trae `vms`/`containers`; la normalizada,
   `guests`. El validador ve una y el driver ve la otra: código que leía `containers` se
   quedaba en blanco al recibir `guests` (`_invitados_de` lee las dos).
4. **Un `__pycache__` viejo.** El motor llegó a validar con lógica que ya no estaba en el
   fuente: un `.pyc` se recompiló después del fuente y Python lo dio por bueno. El primer
   intento de POST falló con errores que el código actual no produce. Un `rm -rf __pycache__`
   lo aclaró — y es una trampa silenciosa que merece quedar escrita.
5. **Un `/24` no da para dos bridges.** Con `derived` en dos bridges y un espacio `/24`, el
   segundo bloque se salía del espacio. Ahora no se deriva y el validador lo dice con el
   motivo correcto, en vez de mandar a mirar el sitio equivocado.
6. **`ping` sin privilegios.** Una imagen de contenedor sin `CAP_NET_RAW` devuelve
   «Operation not permitted»: un falso KO del lab cuando el que no puede es el entorno. Es
   exactamente lo que justifica el código `3`.

### P1 — robustez operativa, coste medio

**6.5 CI en GitHub Actions (offline).**
`./lab check` + `ansible-lint` + `yamllint` + los `test/*.py` **no necesitan Proxmox** (ya lo
documentas). Un workflow que corra en cada push a `main` y en cada PR. Opcionalmente,
`./lab --lab <lab> plan` de referencia contra fixtures para **regresión de planes** (ya tienes
`test_regresion_planes.py`). containerlab y netlab lo dan por supuesto; a ti te falta.
- **Beneficio**: `main` siempre verde de forma **mecánica**, no por disciplina. Cierra tu
  propio criterio "un commit que no ha pasado el ciclo es una promesa sin respaldo", al menos
  en la parte offline.

**6.6 Secretos cifrados con **sops/age** (sin variables de entorno).**
Tu regla 3 prohíbe `os.environ`; tu decisión consciente es texto plano. **sops+age respeta
ambas**: el fichero **sigue siendo un fichero** (`secrets.sops.yml`), se descifra a un
`secrets.yml` efímero en tiempo de ejecución (o lo lee el wrapper), y **se versiona cifrado**.
No rompe "no env", no rompe "un fichero", y quita el riesgo nº1 de tu MVP.
- Alternativa si no quieres herramienta nueva: mantener texto plano pero **documentar el
  procedimiento de rotación** del token (que equivale a root y no caduca — ya lo dices).

**6.7 Serializar la asignación de vmid (cierra tu límite documentado).**
Hoy dos `apply` en paralelo proponen el mismo vmid libre (lo mediste). El sector lo resuelve
con un **lock** (clúster) o **reintento del paso**. Para tu escala, lo más baratoy limpio:
- Un **lock lógico** en el propio Proxmox (p. ej. un pool/objeto centinela, o el `lock` del
  guest) adquirido por el plan antes de asignar identidad, con expiración; o
- **reintentar `crear_guest`** una vez si la API rechaza por vmid ocupado, **re-derivando** el
  vmid. Esto convierte el fallo en convergencia y no rompe "sin fichero de estado".
- **Beneficio**: dejas de tener que aplicar "uno y luego el otro", y honestamente o lo
  arreglas o lo mantienes como límite — pero hoy ya sabes cómo se cierra.

**6.8 Diagrama de topología autogenerado.**
En la **región generada** del `.md`, además de las tablas, un **Mermaid** (o Graphviz) derivado
de la declaración: nodos (por `tipo`), bridges como segmentos, direcciones como etiquetas.
- Encaja **literalmente** en tu modelo de dos regiones (lo genera `documentos.py`, lo vigila
  `check docs`). netlab lo hace (`--graph`); tú no, y es casi gratis.
- **Beneficio**: el documento de un lab se lee de un vistazo; refuerza tu diferencial de
  documentación.

### P2 — estratégicas (decidir, no necesariamente hacer ya)

**6.9 Separar "intención" de "provider" (lección de netlab).**
Reconoce explícitamente que `lab.yml` mezcla topología y acoplamiento a Proxmox. No hay que
refactorizarlo hoy, pero **escríbelo como límite consciente** con su ADR: "este motor es
Proxmox-native por decisión; migrar de sustrato exigiría separar intención de binding".
Si algún día quieres otro hipervisor, este es el punto de extensión.

**6.10 Evaluar delegar la "mitad A" al provider `bpg/proxmox`.**
Estratégico: ¿merece la pena mantener a mano crear VMs/LXC/pools/bridges/`import_from`,
cuando hay un provider maduro? **Contra**: pierdes tu diario de API, tu "sin estado" y tu
check `gateway`. **A favor**: menos superficie de bugs de esquema. **[lectura]** Mi
recomendación: **no** cambiarlo, pero **robarlo como referencia** para defaults y bordes
(snippets/PAM, LXC privilegiado, `arch`), y **citarlo** en el ADR 0001 como prior art
verificado.

**6.11 Fuente de verdad externa (NetBox/Nautobot) — para el futuro multi-nodo.**
Hoy tu "sin estado, re-derivado del clúster" es **mejor** que NetBox para un nodo. NetBox
tiene sentido **cuando haya clúster, multi-tenant o IPAM compartido entre labs**. Anótalo como
roadmap, no lo adoptes ahora.

**6.12 Escala horizontal (clabernetes) — fuera de alcance, pero lee el patrón.**
clabernetes demuestra la solución al paralelismo: **separar la definición del lab del
sustrato de ejecución** para que muchos *workers* corran labs. Es el "techo" de tu línea
"concurrencia en serie". Con 6.7 y un sustrato abstracto (6.9), tu motor podría escalar sin
rediseño conceptual.

---

## 7. Cosas que tu diseño hace **mejor** que el mercado (no las toques)

- **Idempotencia sin estado** — superior a Terraform en este caso de uso.
- **Verificación en los dos sentidos** ("sobra algo = fallo") — Terraform lo llama *drift* y
  necesita estado; tú lo derivas.
- **Frontera de propiedad por pool+descripción+marca** — única y elegante.
- **Diarios como prueba** ("si no dejó diario, no ocurrió") — nivel auditoría que ningún lab
  de red tiene.
- **Documentación verificada con sellado por hash** — sin parangón.
- **Checks que vigilan el propio motor** (`gateway`, `pureza-lab`, `privilegios` con operación
  nula) — más estricto que "linters".
- **Arnés de agentes IA con contrato inyectable** — frente al "prompt → lab" de NetPilot, tú
  tienes **idempotencia + verificación**. Ese es el argumento comercial si algún día lo abres.

---

## 8. Fuentes (nov-2026)

- containerlab, kind `mikrotik_chr`: https://containerlab.dev/manual/kinds/mikrotik_chr/
- containerlab, vrnetlab (integración de VMs): https://containerlab.dev/manual/vrnetlab/
- containerlab, impairments (netem): https://containerlab.dev/manual/impairments/
- containerlab, clabernetes: https://containerlab.dev/manual/clabernetes/
- containerlab 0.82 (release del kind oficial): https://containerlab.dev/rn/0.82/
- netlab (ipspace): https://github.com/ipspace/netlab y https://netlab.tools/
- netlab, plataformas soportadas (RouterOS 7 = minimal, libvirt): https://netlab.tools/platforms/
- netlab, box libvirt de RouterOS 7: https://netlab.tools/labs/routeros7/
- netlab, `validate` (tests en la topología): https://netlab.tools/topology/validate/
- vrnetlab: https://github.com/vrnetlab/vrnetlab
- Kathará: https://github.com/KatharaFramework/Kathara y https://www.kathara.org/
- Terraform provider bpg/proxmox: https://github.com/bpg/terraform-provider-proxmox
- bpg/proxmox, known issues (PAM/snippets/LXC): https://registry.terraform.io/providers/bpg/proxmox/latest/docs/guides/known-issues
- Terraform provider RouterOS (Gnewi): https://github.com/terraform-routeros/terraform-provider-routeros
- Ansible `community.routeros`: https://docs.ansible.com/projects/ansible/latest/collections/community/routeros/
- NetBox / Nautobot como NSoT (2026): https://netboxlabs.com/ y https://www.rogerperkin.co.uk/network-automation/netbox/nautobot-vs-netbox/
- NetPilot (labs con agente IA): https://www.netpilot.io/blog/mikrotik-chr-containerlab
- pyATS / pytest de redes: https://github.com/netpicker/pytests-for-networking
- Comparativas GNS3 vs EVE-NG vs containerlab (2026): https://www.netpilot.io/blog/gns3-vs-eve-ng-vs-containerlab-2026
- CHR en Proxmox (doc oficial MikroTik): https://manual.mikrotik.com/docs/getting-started/installation-and-upgrade/install/chr-installation/proxmox/
