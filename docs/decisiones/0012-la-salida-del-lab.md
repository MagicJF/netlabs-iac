# ADR 0012 — La salida del lab: un router que es la vía de acceso, y la interfaz de fuera como valor de entorno

<!-- PROPÓSITO: dejar escrito por qué un RouterOS puede declarar `uplink` (que ES la
     salida del lab a internet) y por qué eso NO mete ni una dirección de casa en el lab.
     Nace de la necesidad de un lab con salida real: el lab de aceptación
     (`04_lab-red-routeros`) demuestra que cada invitado toma su dirección del router que le
     toca, pero nada sale de él -- y para que salga, alguien tiene que traducir y alguien
     tiene que saber por dónde se sale.
     INVARIANTES:
       * `uplink` es una MARCA, sin opciones. La interfaz de fuera la tiende el PLAN, la
         ÚLTIMA y sin dirección, sobre `pve_bridge_gestion` (valor de ENTORNO, en
         secrets.yml; nunca un valor de lab, regla 7). La interfaz del router se DERIVA
         (`ether<interfaces declaradas + 1>`): el lab no nombra lo que no declaró.
       * La DIRECCIÓN de esa interfaz, su PASARELA y su DNS los DERIVA el motor del estado, con
         la misma regla que la interfaz del bastión en ese mismo bridge: la vía de acceso es
         la dirección del bridge por el que sale el nodo, y la del invitado se cuenta por
         arriba entre las libres. El lab no declara ni una dirección de casa.
       * Lo que el motor configura son CUATRO cosas y ninguna se supone: la dirección
         (derivada), la ruta por defecto por la pasarela de fuera (derivada), MASQUERADE por
         esa interfaz, y el resolutor DNS encendido y apuntando a esa misma vía de acceso (donde este
         nodo sirve el DNS de su red). Lo que no es del motor no se toca (regla 17).
       * Se probó a pedirlo por DHCP -- lo natural para una interfaz de fuera -- y en este
         entorno NO puede ser, medido con captura: las ofertas del bridge de salida salen
         con el checksum UDP mal formado, un CHR las descarta y su cliente se queda en
         `searching...` indefinidamente (nunca llega a pedir). Por eso la numeración es del
         motor y no del bridge. Queda escrito para que nadie lo reintente a ciegas.
       * Un router de salida NO declara ruta por defecto: la pone el motor por la vía de acceso de
         fuera. Si la declara, se avisa con el consejo `exterior-con-ruta` (dos rutas
         compitiendo por el mismo destino), y el lab tendría que saberse la pasarela de
         casa -- que es exactamente lo que esta área evita.
       * La interfaz de fuera NO cuenta como el cliente de fábrica del router (el de las interfaces
         DEL LAB). Si contara, el motor la quitaría --y con ella la salida-- en la primera
         pasada.
     LÍMITES: `uplink` es "esta caja es la vía de acceso", no "escríbeme reglas". El área
     `firewall` de RouterOS es OTRA cosa y tiene su ADR (0019: la tabla de filtrado entera,
     que converge después de todo); aquí el masquerade es la consecuencia de ser la salida,
     no una primitiva de cortafuegos: `uplink` no filtra entradas, no admite servicios de
     fuera y no publica nada hacia dentro. El motor tampoco sabe LEER el interior de un LXC
     (las rutas y los DNS que el cliente aplica de verdad): el driver de Linux no tiene esa
     área todavía, así que la salida del contenedor se comprueba por lo que el router
     dice que repartió -- y lo que no se puede medir se dice, no se maquilla.
     VER: deployment_engine/filter_plugins/interior.py (área `uplink`, `interfaz_exterior`,
     `MARCA_EXTERIOR`), deployment_engine/tools/plan.py (`_interfaz_de_fuera`),
     deployment_engine/filter_plugins/declaracion.py (consejos `exterior-sin-dns` y
     `exterior-con-ruta`), labs/06_conectividad-exterior/06_conectividad-exterior.md (la medida),
     docs/crear-un-lab.md (la decisión, en su sitio) -->

**Estado:** aceptada; convergida y verificada en el lab `06_conectividad-exterior` (VPS,
CHR 7.25.1) con el ciclo `destroy → apply → verify`.

**Contexto.** El motor despliega labs cerrados: cada invitado toma su dirección del router
que le toca y se queda ahí. Un lab que necesite **salir** a internet se topa con dos
preguntas que el lab no puede contestar: por dónde se sale, y quién traduce.

Las dos respuestas fáciles son malas por la misma razón --meten la casa dentro del lab--:

1. **Declarar la pasarela y los DNS de casa en el YAML del lab.** Es lo obvio, y es una
   violación de la regla 7 (el lab no lleva valores que no sean suyos) y de la regla 8 (el
   lab no es asunto del entorno). Además envejece fatal: cambia la red de casa y el lab
   que sale por ella deja de salir, sin que nadie haya tocado el lab.
2. **Poner la salida en cada router del lab** (traducir en todos). Funciona y no necesita
   que nada sepa de casa, pero convierte el lab en una pila de NAT encadenados: deja de
   demostrar lo que un lab de redes debe demostrar --que se **enruta**-- y cada traducción
   esconde un tramo que ya no se puede leer en un `traceroute`.

**La decisión: `uplink` es una MARCA, y la interfaz de fuera es del ENTORNO.**

Un RouterOS declara `uplink: {}` y con eso dice una sola cosa: **este router es la salida
del lab**. Nada más. La interfaz no se nombra --se deriva: es la siguiente a las interfaces que
el invitado declaró-- y la interfaz tampoco: la tiende el **plan** al nacer el invitado, la
**última**, sin dirección, sobre el bridge del nodo que tiene salida (`pve_bridge_gestion`
en `secrets.yml`, hoy `vmbr1`; si falta, el plan para con el motivo y con el remedio).

Al nacer y no en caliente, por la razón de siempre (§5): cambiarle las interfaces a un invitado
en marcha obliga a reiniciarlo, y aquí no se reinicia la máquina que trabaja.

**La dirección la deriva el motor, no la pide el lab ni el DHCP del bridge.** La primera
versión de esto pedía la dirección por DHCP --lo natural para una interfaz de fuera-- y **no
pudo ser, medido**: en este nodo las ofertas del bridge de salida salen con el checksum UDP
mal formado, un CHR las descarta y su cliente se queda en `searching...` para siempre (la
captura está en el documento del lab; del diálogo sólo se ve `DISCOVER → Offer` repetido:
nunca llega a `Request`). Así que la interfaz de fuera se numera con **la misma regla que la
interfaz del bastión en ese mismo bridge**: la dirección del bridge es la vía de acceso, la
dirección del invitado se cuenta por arriba entre las libres (para no caer dentro de un pool
que reparta un router del lab), y el DNS se toma también como la vía de acceso --que es donde este
nodo sirve el resolutor de esa red--. Las tres salen del **estado**, no del lab.

Las cuatro cosas, y ninguna se supone:

- **la dirección de la interfaz de fuera**, derivada (`poner_direccion`): el lab no la declara.
- **la ruta por defecto por la pasarela de fuera**, derivada (`poner_ruta`). Si el lab ya
  declaró una ruta por defecto, esa vale y el motor no añade otra: avisa el consejo.
- **MASQUERADE por esa interfaz**, con la marca `MARCA_EXTERIOR` en el `comment` para que el
  motor reconozca **su** regla (y no toque ninguna otra: regla 17).
- **el resolutor DNS encendido y apuntando a la vía de acceso** (`allow-remote-requests=yes`,
  `servers=<vía de acceso>`), para que los invitados que tienen a este router de pasarela puedan
  resolver nombres preguntándole a él, y él sepa a quién reenviar.

**Por qué la traducción se pone aunque en ESTE nodo sea redundante.** El bridge de salida
de este nodo ya traduce por su cuenta (tiene una regla de la casa para su LAN de gestión),
así que hoy la salida del lab funcionaría sin la regla del router. Se pone igual, y no es
por gusto: un lab no debe depender de un detalle de la casa. El día que la interfaz de fuera
sea una WAN de verdad (una ONT, un router de frontera), sin traducción en el router del lab
no vuelve nada -- y el lab seguiría diciendo que funciona. La regla se declara, se marca y
se comprueba; que además la casa traduzca es una coincidencia, no un cimiento.

**El lab de dentro no se toca.** El motor no configura los invitados que cuelgan del router
de salida: su dirección, su pasarela y sus DNS los reparte el DHCP del router, y eso --y
nada dentro de ellos-- es lo que les da salida. Un contenedor cliente no necesita ni una
línea de `config:` para tener internet: necesita que su red reparta pasarela y DNS. Por eso
el consejo `exterior-sin-dns` existe: el fallo que más veces se lee como "no tiene salida"
es "tiene salida y no resuelve un nombre".

**Una decisión de lab que este ADR NO toma: cuántos resolutores.** El lab de salida resuelve
en la vía de acceso y anuncia ESE resolutor a todas sus redes (una sola boca que resolver en el
lab), en vez de encender un resolutor en cada router. Es una decisión del lab, y está escrita
en su documento; el motor no la impone -- lo que hace es no estorbar para ninguna de las dos.

**Lo que esto NO es.** No es el área `firewall` de RouterOS (esa tiene su ADR, el 0019): aquí
no se escriben reglas de filtrado, no se filtran entradas y no se publica nada hacia dentro.
Es una primitiva cerrada con un nombre honesto: "esta caja es la vía de acceso". Si un lab
quiere un cortafuegos, declara `firewall` en un equipo cuya RESPONSABILIDAD sea filtrar.

**Cómo se comprueba.** Por las cuatro cosas que el motor sabe leer del equipo, y ninguna se
supone: la dirección en la interfaz de fuera (¿es la derivada?), la ruta por defecto (¿hay
alguna?), la regla de NAT con su marca, y el resolutor encendido apuntando a la vía de acceso. Y por
el túnel entero, que es lo que de verdad importa: que un invitado que cuelga de esas redes
llegue a internet.
