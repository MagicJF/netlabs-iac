# 0013 — Una estación pregunta, un servidor dice

*Fecha: 15-nov-2026 — Estado: aceptada — Ámbito: la dirección de una interfaz y el interior del
invitado (`deployment_engine/tools/plan.py`, `deployment_engine/filter_plugins/declaracion.py`)*

## El problema

Las interfaces de un contenedor nacían **sin dirección**: la cadena de red era
`name=eth0,bridge=…,hwaddr=…`, y punto. Con un invitado que declara interior (`config:`) eso no
es una máquina: es un cable enchufado a nada. El motor no pedía dirección porque no declaraba
el `ip=`, y el contenedor nunca llegaba a preguntar: se quedaba con `eth0` vacío.

Un lab que quiere recrear un escenario real no puede permitirse eso, porque **en un escenario
real las cosas no funcionan así**:

- a un **puesto de trabajo** le enchufas el cable y **pide** dirección; el router de su red le
  devuelve dirección, pasarela y DNS en la misma respuesta, y sale a internet sin que nadie le
  toque la configuración;
- a un **servidor** le pones la dirección **a mano**, con su pasarela, y no pregunta nada —
  pero sale igual, porque sabe por dónde.

Las dos cosas son verdad a la vez, y son las que hacen que un lab se parezca a lo que el lab
quiere representar. Un esquema que obligue a declarar la dirección de un puesto pierde el DHCP,
que es *parte del escenario*: la mitad de las veces lo que se está probando es justamente el
repartidor.

## La decisión

**La dirección de una interfaz se declara como se declara en la vida: por lo que el equipo es.**

| lo que el lab declara | lo que nace | qué hace el equipo |
| --- | --- | --- |
| `address: dhcp` | `ip=dhcp` | pregunta: dirección, vía de acceso y DNS se los da el router de su red |
| `address: 10.42.1.10/24` + `gateway: 10.42.1.1` | `ip=…,gw=…` | no pregunta: lleva lo suyo puesto a mano |
| nada, con interior (`config:`) | `ip=dhcp` | lo que hace cualquier equipo al conectarlo |
| nada, sin interior | sin dirección | los invitados de la fase 1, que no se tocan |

`gateway` es **la vía de acceso de ese invitado**, y sólo tiene sentido con una dirección fija. El
motor **no la adivina ni la reparte**: la declara el lab, como la pondría una persona en el
equipo (regla 7: el motor no sabe qué dirección tiene la red de un lab). Y el valor se
normaliza (`invitado.vía de acceso`) para que `plan.py` lo use al crear y al actualizar: tenerlo en
dos sitios distintos es tener dos verdades.

**El DNS no se declara todavía, y se dice.** Un puesto lo recibe por DHCP (por eso funciona sin
declarar nada). Un servidor con dirección fija **no tiene forma de declarar su resolutor** en el
vocabulario de Linux: `dns` está en `AREAS_PENDIENTES`. Hoy hereda el del nodo que lo hospeda
—que es lo que hace un contenedor, y por eso *sale*—, pero no es lo mismo que un servidor que
le pregunta al DNS del lab. Se queda escrito aquí como lo siguiente, con su ADR, en vez de
aparentar que ya está.

## Por qué así, y no de otra forma

**No se inventa la dirección.** Habría sido fácil que el motor numerase los puestos por su
cuenta (como hace con la interfaz de fuera, 0012). Pero el DHCP **es el escenario**: si el lab
declara `dhcp`, lo que se quiere probar es que el router reparta. Numerar por dentro se lo
comería. Cada equipo recibe del mecanismo que le toca, y eso es lo que se comprueba.

**La vía de acceso no se deriva.** Para la interfaz de *gestión* del bastión el motor sí la
deriva (es del nodo, no del lab). Aquí no: la vía de acceso de un servidor de un lab la pone quien
monta el lab, y el motor sólo la escribe donde va. Derivarla sería que el motor supiera la
topología del lab, que es exactamente lo que la regla 7 prohíbe.

**Los labs viejos no se tocan.** Los invitados de la fase 1 no declaran interior, así que
siguen naciendo sin dirección: no hay `changed` en su próxima pasada por un cambio que no
pedían.

## Cómo se comprueba

- Un invitado con `address: dhcp` nace con `ip=dhcp`; uno con dirección y vía de acceso, con
  `ip=…,gw=…`; uno sin nada y con interior, con `ip=dhcp`.
- La lectura de dentro (`/interfaces`) enseña la dirección que el equipo **consiguió**, no la
  que el motor quería: si el CHR no reparte, no aparece, y eso es el fallo — no un verde.
- El conjunto entero: `labs/06_conectividad-exterior` con una estación por router y un servidor
  fijo, y la comprobación de que los tres salen a internet.
