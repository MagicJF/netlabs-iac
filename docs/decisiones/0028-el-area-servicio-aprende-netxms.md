# 0028 — El área `servicio` aprende un segundo miembro: NetXMS (con su base y su web)

*Fecha: 17-nov-2026 — Estado: aceptada y aplicada — Ámbito: el vocabulario del área `servicio`
de Linux, que deja de ser «el servicio de un fichero» y pasa a gobernar un servicio con
dependencias (base de datos y contenedor de servlets)*

## El problema

El ADR 0027 dejó el área `servicio` con **un solo miembro** (`caddy`) y una forma muy
concreta: dos ficheros, una unidad de systemd y un `curl` a 127.0.0.1. El lab `10_lxc-netxms`
pide un servicio que **no cabe en esa forma**: NetXMS necesita un **repositorio APT ajeno** a
Debian, un **motor de base de datos** con su usuario y su esquema (creado por `nxdbmgr init`,
no por el paquete), y una **aplicación web** (el WAR `nxmc`) dentro de un **contenedor de
servlets** que no es su unidad. Con la forma del 0027 el motor instalaría el paquete y se
creería convergido con el servidor sin base de datos y sin web.

Dos caminos: (a) un área nueva `netxms`, o (b) **el área `servicio` deja de tener la forma de
`caddy` y pasa a tener la forma de un SERVICIO**, con lo que cada miembro declara sus piezas.
Se elige (b): el laboratorio no gana una palabra por cada producto (regla 15 es un vocabulario
**cerrado**, no un catálogo de aplicaciones).

## La decisión

**1. `SERVICIOS_LINUX` pasa a tener dos miembros: `caddy` y `netxms`.** El laboratorio sigue
declarando **el NOMBRE** y nada más:

```yaml
config:
  linux:
    servicio: netxms
```

**2. El motor aprende la forma GENERAL de un servicio, no la de cada uno.** Cada miembro del
vocabulario declara en `SERVICIOS_LINUX_OPCIONES`:

- **`paquetes`** — lo que instala, incluido lo que la relectura necesita (`curl`);
- **`herramientas`** — los ejecutables cuya AUSENCIA prueba que falta el paquete;
- **`unidad`** — la unidad de systemd del servicio;
- **`ficheros`** — los ficheros que el motor gobierna, **en orden**: su contenido se compara
  **entero** contra lo que el motor escribiría (la marca `# netlabs-servicio` sigue siendo una
  firma para leer el diario, nunca una prueba);
- **`sirve`** — el comando que comprueba que el servicio **de verdad sirve**;
- **`extra`** — una lectura MÁS, opcional, que el servicio necesita para decidir (para NetXMS:
  si la base ya tiene su esquema **y** el WAR de la web está desplegado — las dos cosas que
  tienen que existir antes de arrancar);
- **`preparar`** — comandos idempotentes que dejan el servicio en estado de poder arrancar
  (para NetXMS: base, usuario, esquema y WAR);
- **`preparar_paquetes`** — lo que hay que hacer ANTES de instalar (para NetXMS: añadir su
  repositorio APT).

**3. La relectura es la MISMA para todos: siete bloques en un viaje.** herramientas, `is-active`,
`is-enabled`, un bloque por fichero gobernado, `sirve` y `extra`. Los dos últimos van SIEMPRE
(con `na` cuando el servicio no tiene `extra`), de modo que el analizador no necesita saber de
qué servicio se trata: por eso `leido_linux` sigue siendo una función de (texto) → datos, sin
el nombre del servicio dentro.

**4. Una operación nueva: `prepare_service`.** Se pide cuando la lectura `extra` no coincide
con lo esperado y se ejecuta **después** de escribir los ficheros y **antes** de arrancar la
unidad — el orden importa: `nxdbmgr init` necesita `/etc/netxmsd.conf` y el servidor no
arranca sin esquema. Es la pieza que el 0027 no tenía porque `caddy` no la necesitaba.

## La trampa

**`is-active` de la unidad del servicio no dice nada de la base ni de la web.** Un
`netxms-server` vivo con PostgreSQL caído se cae en cuanto habla con la base; y una web sin
desplegar no se nota mirando la unidad del servidor. Por eso el `extra` de NetXMS **pregunta a
PostgreSQL** por el número de tablas del esquema, y el `sirve` **pide la página** a Tomcat
(`curl` a `127.0.0.1:8080/nxmc/`), no al puerto del servidor: lo que el laboratorio promete es
que se puede **entrar** al servidor desde el navegador.

**La web tarda.** Un WAR de 53 MB desplegado por Tomcat no está listo en dos segundos: el
`sirve` reintenta acotado (sin reintentos, la primera pasada pediría recargar para siempre) y
la espera tras arrancar es mayor que la de Caddy. El reintento vive en el COMANDO de la
lectura, no en el motor: una lectura que espera es una lectura que mide, no que supone.

**El repositorio de NetXMS no está en Debian.** Se añade con su paquete `netxms-release`
(descargado de `packages.netxms.org`), y sólo si `dpkg -s netxms-release` no lo ve: la
comprobación es de estado, no de «ya lo intenté». Sin `apt-get update` después de añadirlo, el
`install` no ve los paquetes (es el mismo fallo medido en 0027 con las listas de la imagen).

**El servidor no lee la configuración por su cuenta.** La unidad de Debian arranca
`netxmsd -S` sin `-c`, y el binario NO cae en `/etc/netxmsd.conf`: arranca con una base
SQLite local y el laboratorio se cree convergido con la base equivocada (medido). El motor
escribe un `drop-in` de systemd que vacía `ExecStart` y lo redefine con `-c`; vaciarlo no es
estético — systemd ACUMULA las líneas de `ExecStart`, y sin el vaciado el servidor arrancaría
dos veces, una de ellas sin configuración. `nxdbmgr` tiene la misma trampa y se le pasa `-c`
explícito **y el tipo** (`init pgsql`): con la configuración delante, `init` a secas sigue
contestando «Cannot determine database type from driver name» (medido con las dos formas).

**Un paquete puede traer un servicio que el lab no ha pedido.** `netxms-server` arrastra
`netxms-agent`, que se queda con el puerto 4700. El preparador lo deshabilita: el motor no
deja procesos que nadie ha declarado.

**El esquema no lo pone el paquete.** `nxdbmgr init` se ejecuta SÓLO si la base tiene cero
tablas: lanzarlo sobre una base ya inicializada es un error, y no lanzarlo deja un servidor que
no arranca. Es exactamente lo que lee `extra` — junto con el WAR: si la preparación sólo
mirara la base, un WAR que no llegó a descargarse no se volvería a pedir **nunca** (la base ya
está), y la web no serviría jamás: el motor pediría recargar para siempre.

## Qué NO se toca

- **`caddy`**: su contrato no cambia (mismos paquetes, mismos ficheros, mismo `curl` a 80);
  sólo cambia **dónde** vive su forma (en la tabla por servicio, no en el código).
- **Los ficheros son del MOTOR** (regla 7): el laboratorio no escribe configuración de NetXMS,
  ni la contraseña de su base, ni la URL de su WAR.
- **Nada de fuera del área**: no se borran paquetes ajenos, y un Linux sin `servicio` no ve
  diferencia alguna.

## Lo que la relectura cambió (y por qué)

- **Instalar el servicio NO enciende la vigilancia.** Los ajustes de descubrimiento se movieron
  detrás del área `monitorizacion`: un lab que sólo declara `servicio: netxms` —el 10— instala
  el servidor y **no** empieza a peinar su red cada hora.
- **Una caída de la API ya no puede borrar la base.** Si el login no responde o contesta un 5xx,
  eso **no** es un rechazo de credenciales: se distingue (`si` / `rechaza` / `no-contesta`) y
  `preparar` aborta sin `DROP DATABASE`. La inicialización automática queda para una base nueva
  o un esquema vacío **de verdad**: una consulta que falla no es un esquema vacío. Y la marca de
  sembrado exige un recuento válido y mayor que cero — una consulta rota no cierra el área.
- **Las rutas que el invitado necesita sobreviven al reinicio** (se persisten además de
  aplicarse), las rutas a un host se comparan normalizadas (con y sin `/32`, y `default` con
  `0.0.0.0/0`), y una comunidad SNMP se repara **por sus permisos** —no por su nombre— si lleva
  la marca del motor.
- **Y el rechazo de credenciales dejó de ser una condena** (medido, y costó medio día verlo):
  reponer la clave buena escribía la contraseña **corrupta**, porque el hash lleva `$`
  (`$argon2id$v=19$…`) y viajaba dentro de la cadena de `como_postgres` — que es `su postgres -c`,
  un **segundo shell**—: ahí `$argon2id` se expandía a vacío. El login no se recuperaba nunca, así
  que el `DROP DATABASE` acababa siendo la salida de todos los días, con el descubrimiento dentro
  (de 9 equipos vigilados a 3). Ahora el valor no viaja dentro de ninguna orden —`printf` a un
  fichero que psql lee con `-f`— y la base sólo se rehace cuando de verdad hay que rehacerla. Ojo
  con el fichero que guarda la clave: si es de una pasada vieja, reponerlo repone basura y no
  arregla nada; por eso se refresca al rehacer la base.

## Cómo se comprueba

- **`test/test_interior.py`**: el contrato del 0027 sigue verde para `caddy` (fresco → cuatro
  operaciones; al día → cero), y se añade el de `netxms`: herramienta ausente → instalar;
  base sin esquema → `prepare_service`; esquema y web al día → **cero operaciones**; el `sirve`
  se mide con la página web y el `extra` con el esquema.
- **`test/test_declaracion.py`**: `servicio: netxms` pasa; sigue rechazándose un nombre fuera
  del vocabulario, con la lista de los que hay.
- **El ciclo real** del lab `10_lxc-netxms`: `destroy → apply → verify` con la web respondiendo
  y `changed=0` en la segunda pasada.

## VER

- [deployment_engine/filter_plugins/interior.py](../../deployment_engine/filter_plugins/interior.py)
  (`SERVICIOS_LINUX`, `SERVICIOS_LINUX_OPCIONES`, `_ficheros_servicio`, `lectura_servicio`,
  `_servicio_canonico`, `leido_linux`, `escrituras_linux`)
- [labs/10_lxc-netxms/10_lxc-netxms.yml](../../labs/10_lxc-netxms/10_lxc-netxms.yml)
- [docs/decisiones/0027-el-area-servicio-de-un-linux.md](0027-el-area-servicio-de-un-linux.md)