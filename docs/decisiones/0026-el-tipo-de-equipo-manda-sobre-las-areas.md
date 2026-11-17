# 0026 — El tipo de equipo manda sobre las áreas: un equipo, una responsabilidad

*Fecha: 17-nov-2026 — Estado: aceptada y aplicada — Ámbito: QUÉ puede declarar cada `tipo`
de equipo (y por qué el validador lo caza antes de tocar nada)*

## El problema

La regla «**1 equipo = 1 responsabilidad**» estaba en el encargo desde el principio, y
escrita en la prosa de los labs: el `07` dice que sus routers no filtran, el `08` que su
router enruta y sale «y nada más». Pero **no la comprobaba nadie**. El vocabulario de áreas
es por INTERIOR (`AREAS["routeros"]`), no por tipo de equipo, así que un `rt` podía declarar
una tabla de filtrado entera y el validador la aceptaba tan contento.

Y pasó. `08_dunder-mifflin-con-fw` la llevaba: `rt-nucleo` declaraba `firewall` con una
tabla defensiva, justificada en su propio comentario («no es su trabajo, pero un equipo con
una pata en internet NO se queda abierto»). El argumento se sostiene solo; el problema es
que **un router que además filtra es exactamente el router con dos trabajos que la regla
prohíbe**, y mientras la regla viva sólo en la prosa, el siguiente lab la vuelve a romper
con otro buen argumento.

La misma grieta vale para el otro eje que el encargo pidió separar: **conmutar no es
enrutar**. El área `bridges` (RouterOS puenteando) está en `AREAS_PENDIENTES`, así que hoy
nadie puede declararla — pero el día que llegue, sin regla, un `rt` podría ponerse a
conmutar y nadie diría nada.

## La decisión

**1. El `tipo` de un invitado manda sobre las áreas de su `config:`.** Un equipo hace UNA
cosa, y el tipo es la declaración de cuál. El criterio, palabra por palabra el de
`TIPOS_DE_EQUIPO`:

- **filtrar no es enrutar** → `firewall` es de un `fw`, y de nadie más.
- **salir no es filtrar** → `uplink` (cliente DHCP de la pata de fuera + traducción +
  resolutor, ADR 0012) es de un `rt`.
- **repartir no es filtrar** → `dhcp_server` no vive en un `fw`.
- **conmutar no es enrutar** → un `sw` no enruta (`routes`), no filtra (`firewall`), no
  traduce (`uplink`) y no reparte (`dhcp_server`). (`dhcp_client` no está en la lista a
  propósito: esa área sólo **apaga** el cliente de fábrica de un CHR recién nacido —es
  higiene, no una función— y prohibirla sería prohibir la higiene.)

**2. Se declara en NEGATIVO, y con el motivo.** `AREAS_QUE_NO_LE_TOCAN` dice lo que cada
tipo **no** puede pedir, no lo que puede. La lista de lo permitido ya está en `AREAS`, y una
regla en positivo se quedaría corta en silencio el día que el motor gane un área nueva —
justo cuando más falta hace que muerda. En negativo, un área nueva nace permitida para
todos y prohibida sólo donde alguien lo escriba a conciencia.

**3. El motivo viaja con el error, y nombra al equipo que SÍ puede.** «Un `rt` que filtra es
un router con dos trabajos: filtrar es de un `fw`» se arregla; «no puedes declarar
`firewall`» no. Cada prohibición lleva su porqué y a quién le toca.

**4. El orden de la validación es el de la pregunta.** Primero se dice si el área EXISTE en
el vocabulario (y si está pendiente); sólo después, si existe, se discute si le toca a ese
equipo. Al revés, un área inventada en un `rt` daría dos motivos y el de verdad se perdería
entre el ruido.

**5. Un `fw` SÍ reenvía, y eso no es enrutar.** Es la precisión que faltaba: la definición
de `fw` decía «no enruta», y un cortafuegos **en línea** reenvía el paquete que deja pasar —
si no lo reenviara no sería un cortafuegos, sería un adorno. Lo que un `fw` no hace es
decidir el camino de la red (no es la vía de acceso de nadie), ni traducir, ni repartir. La
definición del tipo se corrige en el motor para decir eso exactamente.

## Lo que esto NO es

- **No es un tipo por área.** No se prohíbe declarar áreas: se prohíbe declararlas en el
  equipo al que no le tocan. La misma tabla, en un `fw`, pasa sin una queja — y hay una
  prueba que lo exige, porque una regla que sólo sabe decir «no» es otra regla.
- **No toca el vocabulario del interior**: `AREAS`, `AREAS_PENDIENTES`, los drivers y las
  lecturas siguen igual. Esto es una regla de COHERENCIA entre dos cosas que el lab ya
  declaraba por separado.
- **No arregla el diseño del lab 08 por su cuenta**: que el borde tenga que ir por dentro
  del router es una consecuencia de que la vía de acceso sea una primitiva cerrada (ADR
  0012), y eso está contado en el documento del lab, con su precio medido.

## Cómo se comprueba

- **`test/test_declaracion.py`** §«EL TIPO DE EQUIPO MANDA SOBRE LAS ÁREAS»: un `rt` con
  `firewall` se caza y el motivo nombra al `fw`; **el mismo equipo declarado `fw`, con la
  misma tabla, pasa** (la regla es del tipo, no del área); un `fw` con `uplink` o con
  `dhcp_server` se caza; y un `sw` con `routes` se caza.
- **La batería del cortafuegos** de ese mismo fichero declara ahora su CHR como `fw`, que es
  lo que le toca: sin el tipo, cada prueba de forma saldría además con el motivo del tipo y
  no se leería nada.
- **`./lab check declaracion`** sobre los ocho labs del repo, sin credenciales: ninguno
  declara hoy un área que no le toque.

## VER

- [deployment_engine/filter_plugins/declaracion.py](../../deployment_engine/filter_plugins/declaracion.py)
  (`TIPOS_DE_EQUIPO`, `AREAS_QUE_NO_LE_TOCAN`, `_validar_interior`)
- [deployment_engine/filter_plugins/interior.py](../../deployment_engine/filter_plugins/interior.py)
  (`AREAS`, `AREAS_PENDIENTES`)
- [docs/decisiones/0019-el-area-firewall-de-routeros.md](0019-el-area-firewall-de-routeros.md)
  (el área `firewall`, y por qué converge la última)
- [docs/decisiones/0012-la-salida-del-lab.md](0012-la-salida-del-lab.md) (qué compra `uplink`)
- [docs/decisiones/0015-el-nombre-dice-que-es-el-equipo.md](0015-el-nombre-dice-que-es-el-equipo.md) (el `tipo` en el nombre)
- [labs/08_dunder-mifflin-con-fw/08_dunder-mifflin-con-fw.md](../../labs/08_dunder-mifflin-con-fw/08_dunder-mifflin-con-fw.md)
  (el lab que lo destapó, y el cortafuegos de borde que lo repara)
