# 0029 — Un servidor de VIGILANCIA: el área `snmp` de RouterOS, el área `monitorizacion` de Linux, y dónde vive quien mira

*Fecha: 17-nov-2026 — Estado: aceptada y aplicada — Ámbito: el vocabulario del interior (dos
áreas nuevas), la pata de gestión del plan (deja de ser exclusiva del bastión) y la colocación
de un servidor de vigilancia dentro de un lab*

## El problema

El lab `08_dunder-mifflin-con-fw` quiere **mirar su propia red**: un NetXMS que pregunte a los
cinco equipos de red (un `rt` y cuatro `fw`) por SNMP, dibuje la topología y enseñe sus datos.
El motor ya sabe instalar y servir NetXMS (ADR 0028), pero un NetXMS recién servido **no mira a
nadie**: su árbol de nodos queda vacío. Para que mire hacen falta tres cosas que el motor no
tenía, y una decisión de colocación que el lab no puede tomar sola:

1. **Los equipos tienen que CONTESTAR.** Un RouterOS nace con su agente SNMP APAGADO (`/snmp`
   es `no` de fábrica): sin encenderlo, el vigilante pregunta y no le responde nadie. Eso es
   una primitiva nueva del interior de RouterOS.
2. **El servidor tiene que SABER a quién mira.** NetXMS descubre en dos formas: **pasiva**
   (lee el ARP y las rutas de nodos que YA vigila) y **activa** (ronda un rango de
   direcciones, y con sonda SNMP añade lo que contesta). La pasiva necesita un nodo de
   partida que nadie le ha dado; la activa, un rango que nadie le ha dicho. Es una primitiva
   nueva del interior de Linux.
3. **La web tiene que poder ENTRARSE y el invitado tiene que poder salir.** NetXMS se instala
   bajando su repositorio de internet y se mira por su web. Ninguna de las dos cosas la tiene
   un invitado cualquiera del lab: hacen falta por la misma pata que usa el bastión.

Y la pregunta de fondo que no es de vocabulario sino de **sitio**: ¿dónde vive quien mira?

## Los escenarios de colocación (medidos contra la topología del lab 08)

El lab es una sede con **zonas** (`oficina`, `almacén`, `DMZ`), un **router de troncal** que
enruta y sale, **cuatro cortafuegos** uno por zona más el de borde, y una **red de gestión**
(`vmb_fw_gestion`, `10.44.0.0/24`) por la que el motor despliega. Se consideran cinco sitios:

**(a) Dentro de una zona (oficina, almacén, DMZ).** El vigilante vería a su propia zona y a
nadie más: para llegar a otra zona tendría que atravesar el cortafuegos que la protege, y esas
reglas **no** dan acceso desde dentro de una zona a las demás (es justo lo que el lab enseña a
filtrar). Habría que abrir un boquete por zona. **Descartado**: el vigilante acabaría siendo la
excepción que deshace el ejercicio.

**(b) Detrás del router de borde.** Es una red de tránsito de dos direcciones; ahí no vive un
servidor. **Descartado**: no es un sitio, es un cable.

**(c) Entre cortafuegos (el troncal).** Igual: es tránsito. Además pondría al vigilante a ver
el tráfico que pasa y no a los equipos. **Descartado.**

**(d) En la red de GESTIÓN, compartiendo red con los equipos.** Es la **única red que los cinco
equipos comparten** — cada uno tiene ahí su `ether1` de gestión — y es la red que su tabla de
entrada **ya da por buena** (`accept src-address=10.44.0.0/24`, la primera regla de entrada de
cada `fw`): el vigilante ve a los cinco por SNMP **sin abrir una sola regla nueva** y sin
depender de ningún router del lab. **Elegido.**

**(e) Sacarlo del lab (un invitado fuera de la topología).** No vería las direcciones de
gestión (están en un bridge del lab), y para llegar tendría que entrar por un router. Mismo
problema que (a), más un invitado que no es del lab. **Descartado.**

**La elección, en una frase: el vigilante va donde va el que despliega — a la red de gestión —
porque mirar no es un privilegio de una zona, es una función de la operación.**

## La segunda mitad: ¿el puesto de control, o un invitado aparte?

El invitado que tiene la pata de gestión (red de gestión **y** salida por el puente del nodo)
hoy es **el bastión** — el `ctl-1` del lab 08, que además da DHCP y DNS a la gestión. Dos
caminos:

- **(A) Ampliar el bastión** con el servicio. Más barato (ya tiene la pata y la red), pero
  mete un servidor con PostgreSQL, un JVM y Tomcat en el **único invitado del que cuelga todo
  lo demás**: si se queda sin memoria o un `apt upgrade` lo reinicia, se cae el túnel, que es
  la forma de entrar del motor (regla 16, ADR 0004). El bastión es una pieza **del motor**, no
  un servidor de aplicaciones.
- **(B) Un invitado APARTE** (`ctl-2`) que publica el servicio y no toca el túnel. Separa
  responsabilidades (el bastión sigue siendo la forma de entrar) y es el patrón que ya usan los
  labs 09 y 10, donde el servicio tiene su propio invitado.

Se elige **(B)**. El precio es que un invitado que publica un servicio necesita **la misma pata
de gestión** que el bastión, y hasta hoy esa pata era exclusiva del túnel. Eso es lo que
generaliza esta decisión.

## La decisión

**1. Nueva área de RouterOS: `snmp`.** El lab la declara como una MARCA (`snmp: {}`) en un
equipo que debe dejarse vigilar. El motor enciende el agente (`/snmp/set enabled=yes`) y le
pone **una comunidad de LECTURA** con el nombre de una **constante del motor**
(`COMUNIDAD_SNMP = "netlabs"`), la misma que el vigilante usa por defecto
(`DefaultCommunityString`): el lab declara **que** un equipo se vigila; **cómo** se le pregunta
es del motor. La comunidad de fábrica (`public`) **no se toca** —el área manda dentro de lo que
declara (regla 17)— y la diferencia sólo **añade** lo que falta, así que un equipo ya vigilable
no produce ninguna operación (regla 6).

**2. Nueva área de Linux: `monitorizacion`.** También una MARCA (`monitorizacion: {}`), y sólo
tiene sentido junto a un `servicio` que **sepa vigilar** (hoy, `netxms`; el validador lo
rechaza con el motivo si no). Un comando del servicio dice si ya está **sembrado**; si no lo
está, el motor ejecuta **el sembrado**: el servicio **ronda la red del propio invitado** —
derivada de su interfaz, **no** un valor de lab — y NetXMS añade lo que contesta por SNMP. El
sembrado deja **una marca dentro del invitado**, y esa marca es lo que hace la operación
idempotente: la segunda pasada sólo lee.

**3. La pata de gestión deja de ser del bastión.** El plan gana un predicado
(`necesita_pata_de_gestion`): la pide **el bastión** (para el túnel hacia casa) **y el que
PUBLICA un servicio** (para entrar en su web y para alcanzar el repositorio). Un invitado que
publica un servicio lleva **sus** interfaces (las que el lab declara) **y la salida** — la
misma función que la del bastión (`_interfaz_de_salida`), pero **sin** una pata por cada bridge
del lab: el bastión está en todas las redes porque tiene que desplegarlas; un servidor
publicado está en la suya y sale por donde sale el nodo. La clave pública del motor también se
le deja al crearlo, porque el motor tiene que **entrar** a configurarlo (y lo alcanza por el
bastión, `tasks/guest_inventory.yml`).

**4. La web de NetXMS tiene ADMINISTRADOR conocido.** `nxdbmgr init` genera una clave al azar y
la imprime **una sola vez** si no se le da; una web a la que no se puede entrar no cumple nada.
El motor le **pone** una clave (`NETXMS_ADMIN`), como ya le pone la de su base
(`NETXMS_BD['clave']`). No abre nada del anfitrión: es la cuenta de la aplicación, dentro del
invitado.

## Lo que se midió al desplegar (y lo que obligó a cambiar)

La primera pasada de verdad contra el lab 08 enseñó tres cosas que el diseño no había visto, y
las tres se arreglaron **con su prueba** (no con un comentario):

1. **Dos invitados con pata en la MISMA pasada chocaban en el bridge del nodo.** La dirección de
   la pata de gestión se **deriva** de las que ya usa el nodo, y una pasada que crea al bastión Y
   al publicador mira el MISMO mundo los dos: los dos derivaron `10.10.10.254` y el bridge del
   nodo quedó con **dos máquinas contestando por una dirección** (además, la del propio nodo).
   Se midió en el invitado: `ip -4 -o addr` con la misma dirección que el bastión. **El plan
   ahora cuenta como usado lo que la propia pasada reparte** (`_direcciones_del_bloque_de_red`,
   leído de las MISMAS cadenas `net<n>` que recibe la API), así que el segundo invitado sale por
   otra dirección. Y no era cosmético: con el choque, el SSH del motor al publicador se caía a
   medias («Connection closed by UNKNOWN port 65535») y sin el choque converge a la primera.
2. **`nxdbmgr init` sin `-p` deja la web con una clave al azar.** La web quedaba **en pie y sin
   poder entrar**: el servidor arranca, Tomcat sirve el WAR… y el administrador tiene una clave
   que nadie leyó. La clave del administrador va **en el `init`** (`-p`, que es para eso).
3. **`set-user-password` NO se puede guionizar.** Pide la clave **por el terminal** y en un guion
   contesta «Cannot read password» (con un TTY de verdad sí funciona, pero un TTY no es algo que
   el motor deba necesitar para poner una clave). Y aunque se pudiera, **el paquete ARRANCA el
   servidor al instalarse**, deja la base **bloqueada** y `nxdbmgr` contesta «Database is locked
   by server …»: el motor **para el servidor antes de tocar la base** — pero la prueba de que se
   puede ENTRAR la hace con el servidor **todavía en marcha**, que es el único que sabe verificar
   una clave.
4. **«Hay esquema» no es «se puede entrar».** El paquete deja un esquema con una clave de
   administrador **al azar** que nadie leyó (medido: la web en pie, `/nxmc/` servido y la
   autenticación contestando `errorCode 61`). El motor ahora **no se conforma con el esquema**: si
   hay base y la autenticación no vale, **rehace la base** —está dentro de lo que el área declara
   (regla 17) y una base con una clave que nadie conoce no vale para nada— y la vuelve a
   inicializar con `-p`. Medido después del arreglo: `POST /v1/login` con
   `{"username":"admin","password":"netlabs"}` contesta **201 con un token de sesión**, y
   `nxadm -u admin -p netlabs` entra (el campo del cuerpo es `username`, no `login`: con `login`
   contesta 400).
5. **La consola de depuración ROMPÍA la clave del administrador.** Medido con el paso justo antes
   y justo después: el API contesta `201` con la clave aplicada; se ejecuta `nxadm -u admin -p …`
   (entra, rc=0); y el mismo login contesta `403 errorCode 61` acto seguido, sin recuperarse. Por
   eso la prueba de «se puede entrar» —y todo lo demás— va por el **API web**, que es la puerta
   por la que entra la interfaz. El motor no usa la consola para nada.
6. **El descubrimiento lo hace el SERVIDOR solo.** Ni `nxadm -c "scan …"` ni nada parecido: se le
   declaran la comunidad, el tipo, la sonda SNMP, la **red a vigilar** (la del propio invitado,
   derivada de su `eth0`) y el descubrimiento activo con su intervalo, y él añade los equipos por
   su cuenta (medido: 9 nodos sin que nadie lanzara una ronda). El sembrado sólo ESPERA —acotado—
   a que sus hallazgos estén en la base, y deja su marca; la topología aparece en la web según la
   encuentra.
7. **Y lo que NO controla la declaración, dicho en claro**: el paquete reescribe el hash del
   administrador a `argon2id` (al entrar con un hash viejo: `Password hash has to be recomputed`)
   y ese argon2id **no verifica**. Medido, determinista: con la base recién inicializada el API
   contesta `201` a los 20/40/60/80 s; a los ~100 s el hash ya es `$argon2id$…` (97 chars,
   canónico) y desde la siguiente recarga **todo login es `403 errorCode 61`**, con cualquier
   clave. Consecuencia honesta: **la web sólo se puede entrar en la ventana de ~1-2 minutos tras
   un `preparar`, y luego decae**; el motor no puede parchear el binario. Lo que sí hace: la
   sonda distingue `si` / `rechaza` / `no-contesta` (confundir «aún no contesta» con «no acepta la
   clave» costaba la base entera), un `rechaza` se cura **primero devolviendo el hash bueno que
   dejó `init`** —guarda sólo su hash, y sin tocar un dato— y sólo después se rehace, y no se
   reinicia el servidor «por si acaso» (un arranque de más vuelve a disparar el volcado).

También se midió que el **descubrimiento SNMP funciona** contra los equipos reales: el servidor,
con la red declarada y el descubrimiento activo encendido, añadió por su cuenta los cinco equipos
de red (los `10.44.0.11`–`10.44.0.15`) sondeándolos por **SNMP**, que es exactamente lo que el
área `snmp` puso a responder — y sin que nadie disparara una ronda desde la consola (hacerlo así
era, además, lo que rompía la clave: ver el punto 5).

## Los límites, dichos

- **La comunidad SNMP no se recorta por dirección.** El motor la pone con lectura y sin
  restricción de origen; quien limita quién llega a UDP 161 es **el cortafuegos del equipo**
  (los `fw` del lab sólo aceptan entrada de la red de gestión). En un equipo **sin** cortafuegos
  (el `rt` de este lab) el agente queda abierto a quien pueda alcanzar sus direcciones. Es un
  banco de pruebas y se dice; recortarlo por dirección es una línea que se puede añadir cuando
  haga falta, con su prueba.
- **El vigilante sólo alcanza los equipos por su dirección de gestión.** Vive en
  `10.44.0.0/24` y no tiene rutas hacia las zonas (`10.44.1.0/24`, `10.44.10.0/24`…): no las
  necesita para preguntar por SNMP, que va a la dirección de gestión. La topología que dibuje
  sale de las **tablas de rutas y de ARP** que lee de cada equipo (descubrimiento pasivo), no
  de alcanzar cada red.
- **La primera pasada del sembrado depende de que los equipos ya estén vivos y vigilables.**
  Por eso el invitado vigilante va en la **última etapa** del lab: cuando ronda la red, los
  cinco equipos ya tienen su área `snmp` convergida.

## Lo que NO se hace

- **No se añade un agente a los invitados** (`netxms-agent`): eso sería otra primitiva (un
  agente que se registra solo), y este ADR es sobre **preguntar** por SNMP, no sobre que los
  invitados se reporten.
- **No se copia `public` ni se reescribe la tabla de comunidades del equipo**: el área dice
  «este equipo se vigila», no «estas son TODAS tus comunidades».
- **No se publica la web con el Caddy del lab**: la entrada por HTTPS la da el **Caddy del
  NODO** (la pieza de gestión del anfitrión, ADR 0024), que reenvía al puerto de la pata de
  gestión del invitado. Lo que abre el anfitrión no se versiona en el lab.
