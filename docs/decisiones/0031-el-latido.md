# 0031 — El latido: aparecer sin que nadie te pregunte

Fecha: 2026-11-18
Estado: aceptada
Relacionada: ADR 0029 (el servidor de vigilancia), ADR 0030 (el vigilante y las zonas), reglas 7, 15 y 17

## El problema, medido

Los invitados de las zonas del lab 08 (`ficheros`, los tres `puesto`, `web`) no aparecían en
la topología del vigilante. El camino «de verdad» para que aparezcan era que el vigilante
pudiera **preguntarles** —rutas declaradas y permiso en cada `fw`— y, para tener información
y no sólo el nodo, un agente SNMP dentro. Las dos cosas son caras: abren camino a través de
cortafuegos que hoy tiran lo no declarado, y obligan a entrar en invitados que el lab dejaba
vivir sin gestionar.

Y no había forma de pedir «haz que este equipo **se vea**»: el vocabulario del interior es
cerrado (regla 15), así que el lab no puede inventarse una primitiva.

Lo que **sí** se midió, en el código del vigilante (`discovery.cpp`):

- Su sondeo de descubrimiento **lee la caché ARP de cada equipo que sondea** y, por cada
  entrada, llama a `CheckPotentialNode(...)` con `DA_SRC_ARP_CACHE` y **encola el resultado
  como nodo nuevo** (`EnqueueDiscoveredAddress`).
- Y esa función **no exige que el equipo conteste**: pide que sea unicast válida, que esté
  en la **misma subred** que una interfaz del equipo sondeado, y que no sea broadcast.

Consecuencia directa: **para aparecer en la topología basta con estar en la tabla ARP del
propio cortafuegos**. Y ahí se está por el simple hecho de hablar con la pasarela: la
pregunta por su MAC sale **antes** de que nadie decida si el paquete pasa.

## La decisión

Se añade al driver Linux el área **`latido`**: una **marca** (`latido: {}`), con un valor
opcional (`cada`). El motor pone tres cosas —guion, unidad y temporizador— y el guion da un
toque a la pasarela cada `cada` (defecto **2 min**).

- **Por qué a la pasarela y no a internet**: el trabajo lo hace la pregunta por la MAC, y esa
  pregunta ocurre igual. Así el toque se queda **dentro de la red del lab** y no depende de
  que haya salida: medido, funciona con el cortafuegos en `drop` y sin internet.
- **Por qué 2 minutos**: quien lee esa caché es el vigilante, y lo hace cuando sondea cada
  equipo (cada cuarto de hora). Una entrada ARP dinámica vive minutos. El toque tiene que ser
  **más frecuente que la vida de la entrada** para que esté **siempre** ahí, no por suerte; si
  caducara entre dos lecturas, el equipo no se vería. La cadencia es un **valor del lab**
  (regla 7) y se cambia con `cada`.
- **Por qué se compara la marca y no sólo «está armado»**: un cambio de cadencia tiene que
  notarse. Mirando sólo que el temporizador esté `active`, el motor diría «convergido» con la
  cadencia vieja puesta. La marca (`# netlabs latido cada=…`, en el fichero del temporizador)
  es lo que lo hace converger.

## Lo que NO hace (y se dice en voz alta)

- **No promete que el equipo conteste a nadie.** Sólo que está en la tabla. El vigilante lo
  sondeará igual, y como hoy **no tiene camino hasta él**, saldrá en la topología **sin
  información** (una dirección, y poco más). Un agente SNMP —o el camino— es otra decisión
  (ADR 0030) y no se toma aquí.
- **No configura nada del equipo ni de la red**: no abre puertas, no pone interfaces, no añade
  rutas. El invariante del cortafuegos del lab se queda como estaba.
- **No sustituye a un agente**: sin agente no hay interfaces ni sistema.

## El coste, y por qué se acepta

- Un paquete cada 2 minutos por invitado, **dentro de su propia red**.
- Y nada más. Ni una ruta, ni una regla de cortafuegos, ni un boquete: **el bastión del lab ya
  tiene una pata en cada zona** (medido en el propio bastión: `10.44.1.254/24`, `10.44.2.254/24`
  y `10.44.3.254/24`, con las tres redes **directamente conectadas**), así que el motor entra en
  esos invitados por su propia pata y **sin cruzar ningún `fw`**. El latido se instala por un
  camino que ya existía; los cortafuegos del lab no se tocan.
  (Una versión anterior de esta decisión daba por hecho que había que declarar rutas al bastión
  y reglas en los `fw`; **medido, sobraban**, y se quitaron.)

## Cómo se sabrá que funciona

- Prueba de la primitiva, sin Proxmox: el diff canónico (nada ⇒ escribir y armar; armado con
  su marca ⇒ nada; cadencia distinta ⇒ reescribir).
- Contra el nodo real: `./lab --lab 08_dunder-mifflin-con-fw plan --api`, `apply` y `verify`.
- Y la prueba que importa: la entrada del invitado **en la tabla ARP de su cortafuegos**
  (`/rest/ip/arp`) y el invitado **en la topología**.
