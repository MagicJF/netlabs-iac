# 0035 · El terminal SSH del vigilante: lo abre un agente, no el servidor

- **Fecha:** 20-nov-2026
- **Estado:** aceptada
- **Contexto:** un lab con **dos o más RoutersOS** tiene algo que enseñar en una
  sola consola: las dos cajas. NetXMS 7.0 trae el **terminal SSH embebido** en su
  consola (`Tools > SSH terminal`), y el lab 04 es el primero con dos `rt`. Lo
  pide el lab, no el motor: `terminal: {}` va en el `config.linux` del equipo que
  hace de vigilante.

## La decisión

1. **El área `terminal` es del vocabulario del interior Linux, y su valor es
   vacío** — como `tunnel`: lo que hay lo dice la **clave**. El área exige
   `servicio: netxms` en el mismo equipo y la validación lo comprueba **antes de
   tocar nada**: un terminal sin vigilante es una consola que no existe.
2. **El terminal lo presta un AGENTE, y el motor lo deja cargado.** La sesión SSH
   la abre el agente del propio invitado con el subagente `ssh.nsm`; el servidor
   sólo transporta bytes. Se escribe `/etc/nxagentd.conf` con
   `SubAgent = ssh.nsm` **en la sección `[CORE]`** (arriba del fichero) — al final
   del fichero la línea cae en `[FILEMGR]` y el subagente no se carga.
3. **El nodo del vigilante lleva la capacidad de agente, y eso se escribe a
   mano.** `Node::createAgentConnection` exige `NC_IS_NATIVE_AGENT` (`0x2`); sin
   ese bit devuelve nulo y el API contesta **502 «Cannot connect to SSH proxy
   agent»** con el agente vivo y escuchando. `NC_IS_SSH` (`0x80`) es lo que la
   interfaz lee para ofrecer el terminal. El motor hace `OR` sobre el nodo que ya
   tiene `NC_IS_LOCAL_MGMT` (`0x10`, el del propio vigilante): **no pisa** nada, y
   no depende del nombre que le puso el instalador.
4. **Cada router vigilado es un NODO con su credencial y `ssh_proxy = 0`.** El
   nodo se crea por el API (`POST /v1/objects`, `class: Node`, `parentId: 2`) y la
   credencial (`ssh_login`, `ssh_password`, `ssh_port`) se escribe en su fila:
   `ssh_proxy = 0` significa «el agente del propio servidor». El nombre del nodo
   es del vocabulario del motor (`rt-<alias>`), y el nodo se busca por su IP
   primaria, no por el nombre: dos labs pueden repetir `rt-nucleo`.
5. **La credencial no viaja en la línea de órdenes.** Va a
   `/etc/netlabs/terminal.env` (0600) y el paso que lo escribe lleva
   `comando_diario`: el diario cuenta lo que se hizo y **no guarda el blob**. El
   diario es sagrado (regla 5), y un secreto en base64 dentro de un comando
   acabaría escrito en `interior.jsonl`.
6. **Un reinicio, y sólo cuando hay algo que cambiar.** Capacidades y
   credenciales se leen **al arrancar**: la escritura termina reiniciando
   `netxms-server` y esperando a que el API vuelva a entrar (no un tiempo fijo).
   La segunda pasada no escribe: la lectura ya coincide y el área no genera paso.
7. **El agente abre la conexión: `EnableTCPProxy = 1`** (añadido al medirlo en
   vivo el 20-nov-2026). Con los tres hechos anteriores puestos, `Tools > SSH
   terminal` abría la ventana y la cerraba con **«TCP proxy function is
   disabled»**: la sesión es una conexión TCP que nace en el agente, y sin la
   bandera `AF_ENABLE_TCP_PROXY` el agente la rechaza
   (`src/agent/core/session.cpp`). El área lo comprueba **en marcha** —el proceso
   del agente tiene que ser posterior al fichero, porque las banderas se leen al
   arrancar— y la escritura sólo reescribe si el contenido cambia, reiniciando el
   agente en ese mismo paso.
8. **Va en su propio invitado, no en el bastión** (corregido el 20-nov-2026, el
   mismo día). El área se declara en el invitado que hace de vigilante, y ese
   invitado **no es el bastión**: el ADR 0029 ya eligió separarlos («el bastión es
   una pieza del motor, no un servidor de aplicaciones»), y meter ahí el JVM, el
   PostgreSQL y el Tomcat pone la forma de entrar del motor a merced de un `apt
   upgrade` o del OOM killer. En el lab 04 se hizo al revés durante un día, con el
   argumento de que el bastión era el único que alcanzaba las dos redes — el mismo
   argumento que 0029 resolvió generalizando la pata de gestión: un invitado que
   publica un servicio lleva **sus** interfaces y la salida, así que `ctl-2` llega a la
   LAN del CHR por lo que es una red: una **ruta** por el router que la sirve
   (`routes: 10.40.1.0/24 via 10.40.0.11`), no una dirección de esa red puesta en su
   tarjeta de salida — declarar ahí una `addresses` la dejaba en `eth1` (vmbr1), una red
   en la que el invitado no está (medido el 20-nov: el terminal abría y no alcanzaba
   `rt-nucleo`). El bastión se queda con su túnel, su DHCP y su `ip_forward`.

## Por qué así

- **Porque el servidor no tiene cliente SSH.** La documentación de SSH Monitoring
  lo dice sin rodeos: *«all SSH operations are executed by an agent with the
  ssh.nsm subagent loaded»*. El terminal embebido no es una capacidad nueva del
  servidor, sino la tubería de las DCIs de origen SSH puesta a servir una shell.
  De ahí que las dos formas del diálogo (relay por el agente, o TCP proxy directo)
  necesiten **agente**: el proxy TCP vive en el agente, no en `netxmsd`.
- **Porque el fallo se vio tal cual y se ahorró a quien venga detrás.** La
  primera versión daba 502 y parecía un problema de red. No lo era: `capabilities`
  del nodo del vigilante tenía `0x10` y le faltaba `0x2`. Se comprobó en la
  fuente (`src/server/core/node.cpp`) antes de tocar nada, y por eso esta ADR cita
  el bit y no «había que activar algo».
- **Porque el equipo que lo declara tiene que alcanzar a los routers.** En el 04
  ese equipo es `ctl-1`: es el único que tiene interfaz en la red de gestión
  (`eth0`) **y** en la del primer CHR (`eth1`). El vigilante abre las sesiones por
  su cuenta; no se le pide al operador que tenga ruta a las LANs del lab.
- **Frente a la alternativa de que el motor lo despliegue solo** (cada lab con
  dos `rt` recibe un vigilante sin declararlo): se descarta. El motor no conoce
  topologías ni inventa invitados (reglas 7, 8 y 11); un invitado que aparece
  porque sí no está en la declaración y `destroy` no sabría de quién es. El lab
  lo declara en una línea, y el validador impide declararlo mal.

## Límites, dichos

- **Modo relay**: el tráfico pasa por `netxmsd`, que ve las credenciales y los
  comandos. El modo «directo» (cifrado extremo a extremo) exige `EnableTCPProxy`
  en el agente y que la consola de escritorio salga por él; **no** se configura
  aquí, y esta ADR no lo promete.
- **La credencial del equipo queda en la base de NetXMS** (en claro, como la de
  su propia base): es lo que el producto necesita para abrir la sesión. Por eso
  el API vive **sólo en loopback** (ADR 0034) y se entra por túnel.
- **El alta de nodos usa `psql`** para los campos `ssh_*`, porque el API REST no
  los documenta. Es la misma vía que ya se usa para la clave del administrador
  (ADR 0033): se mide, se escribe y se lee de vuelta con la lectura del área.

## Lo que se corrigió al mirarlo de cerca

Cuatro cosas que la primera versión daba por buenas y no lo eran; las cuatro las
enseñó la revisión (Greptile, PR #20) y las cuatro se reprodujeron antes de tocar
nada:

- **La credencial se cargaba con `.` y sin comillas.** Una clave con `$` o con
  comillas se expandía al cargar el fichero y el agente recibía **otra** cosa. Ahora
  los valores van entre comillas simples, con las internas cerradas y reabiertas.
- **El SQL de la credencial pasaba por `/tmp/netlabs-terminal.sql`.** Previsible y
  creado con la máscara del sistema (022). Ahora nace 0600 y con nombre único.
- **La lectura no pedía puerto, proxy ni la clave.** Con la dirección y el login
  buenos, un nodo con el puerto mal o la clave vieja pasaba por «al día» y el
  terminal no abría. Ahora se comparan los cuatro campos, y la clave se contesta
  como un sí/no en la propia base: el diario no lleva credenciales.
- **`cmp -s` no bastaba para reiniciar el agente.** Sus banderas se leen al arrancar:
  si el fichero ya estaba bien pero el proceso era **anterior**, el paso no lo
  reiniciaba y el área repetía el fallo en cada pasada. Ahora se reinicia también
  en ese caso (`ps -o etimes` contra la fecha del fichero).
