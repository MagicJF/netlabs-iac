# Los mapas L2 automáticos: qué hace falta, medido

**Pregunta.** Poder ver mapas de topología de capa 2 automáticos en el servidor de
vigilancia (NetXMS) de un lab de este motor. Esta respuesta es de medidas, no de
opiniones: qué entrega cada equipo, qué construye NetXMS con eso y qué falta.

## Qué construye NetXMS, y con qué

De su documentación: arma el modelo de red con la **caché ARP**, las **tablas de rutas** y
la **tabla de conmutación (FDB)** de los equipos que gestiona, más los protocolos **CDP,
LLDP y NDP** para los enlaces entre conmutadores. Tres reglas suyas ordenan todo lo demás:

- De la FDB sólo valen los puertos donde hay **una sola MAC**: eso es un equipo conectado
  directamente.
- Ese equipo tiene que ser **conocido** por NetXMS: agente, SNMP, o un IP-MAC en la ARP de
  un equipo gestionado.
- Cada interfaz de un nodo lleva una columna *Peer Discovery Protocol* que dice por qué vía
  se descubrió cada vecino.

## Qué entrega cada equipo, medido

`nxsnmpwalk` contra los equipos del lab 08, y contra un CHR de un lab de medición
configurado para **conmutar** (un bridge de RouterOS uniendo dos de sus patas, con dos
invitados Linux hablando a través):

| se le pregunta por | CHR que sólo enruta | CHR que conmuta |
| --- | --- | --- |
| ARP (`ipNetToMediaTable`) | sí | sí |
| rutas (`ipRouteTable`) | sí (64 filas) | sí |
| MIB base de conmutación (`dot1d`) | responde: 3 puertos | responde: 2 puertos |
| **tabla de conmutación (FDB)** | **vacía** | **4 MAC en 2 puertos** |
| **LLDP (vecinos)** | nada | local sí, **vecinos no** |

La FDB del que conmuta traía las dos MAC de los invitados —derivables de sus vmids, una en
cada puerto— más las dos interfaces del propio CHR. Es decir: **el equipo sí publica lo que
NetXMS necesita para un enlace L2**, pero sólo cuando conmuta de verdad. Un equipo que sólo
enruta no publica nada, porque no tiene nada que publicar.

## Y sin embargo, el mapa no se dibujó

En ese mismo experimento NetXMS acabó con `peer_proto = 0` en todas las interfaces: no
descubrió **ni un vecino**. El motivo no es el equipo, es la otra mitad: la FDB da
MAC ↔ puerto, y NetXMS necesita **casar esa MAC con un objeto que conozca**. Allí sólo
conocía al propio CHR y al vigilante: los dos Linux no eran nodos (ni agente ni SNMP). Sin
esa mitad no hay enlace que dibujar.

Y LLDP no salva la papeleta: los vecinos de un equipo en este motor son **bridges de Linux
del nodo Proxmox** y Linux pelados, y ninguno habla LLDP.

## Conclusión

Un mapa L2 automático en un lab de este motor **es posible, y necesita dos mitades**:

1. **Un equipo que conmute de verdad** y publique su FDB (medido: RouterOS lo hace).
2. **Que los extremos sean conocidos** (agente o SNMP dentro de ellos).

Hoy no hay ninguna de las dos. El conmutador real de los labs es el **bridge de Linux del
nodo**, y al nodo no se le sondea: no tiene SNMP. Y los invitados Linux entran como nodos
pelados, sin agente.

## Opciones, por coste

| # | qué | coste | qué da |
| --- | --- | --- | --- |
| 1 | agente SNMP dentro de los invitados Linux (primitiva nueva del driver, con ADR) | medio | nodos con métricas; **por sí sola no da L2** |
| 2 | una caja que conmute: el `sw` del vocabulario (hoy en `AREAS_PENDIENTES`, el validador lo rechaza) | alto: necesita ADR propio (qué es conmutar aquí y cómo se declara) | la FDB ya está medida; daría los enlaces de lo que cuelgue de ella |
| 3 | las dos | — | el mapa L2 completo |

Recomendación: **1 primero** (vale por sí sola: métricas) y **2 con su ADR** si de verdad se
quiere el dibujo L2, sabiendo que el L2 de un lab virtualizado vive en el hipervisor, y que
el hipervisor no habla SNMP.

## Lo que NO se puede

- El L2 del bridge de Proxmox: invisible para el vigilante, y lo seguirá siendo mientras el
  nodo no exponga SNMP.
- Un mapa L2 hecho sólo con equipos que enrutan: sin conmutación no hay FDB ni vecinos.

## Método y estado

- El experimento vive en `labs/11_l2-research/`: un CHR `rt-l2` con tres patas, un `ctl`
  con la vigilancia y dos `ws` hablando a través del bridge. El bridge de RouterOS se
  configuró **a mano por la REST del CHR** —es diagnóstico, y se tira con el lab— porque el
  motor todavía no tiene la primitiva `bridges` de RouterOS.
- Comandos de medida: `nxsnmpwalk -v2c -c netlabs <equipo> .1.3.6.1.2.1.17.4.3.1.1` (las MAC
  de la FDB), `.1.3.6.1.2.1.17.4.3.1.2` (el puerto de cada MAC), `.1.3.6.1.2.1.17.1.4.1.2`
  (puerto ↔ interfaz), `.1.0.8802.1.1.2.1.4.1.1` (vecinos LLDP), `.1.3.6.1.2.1.4.22.1.2`
  (ARP).
- Estado del lab de medición: **su `apply` no llegó a converger** en la primera pasada (el
  CHR no contestó en su puerto 80 dentro de la espera declarada, un arranque lento ya
  conocido), así que las medidas se tomaron sobre el CHR ya en pie. Es material de partida
  para el ADR del `sw`, no un lab verde.
