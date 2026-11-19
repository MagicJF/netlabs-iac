# 0032 — El rango de vigilancia se deriva de las rutas (y se escribe donde NetXMS lo lee)

Fecha: 2026-11-18
Estado: aceptada
Relacionada: ADR 0028 (el área `servicio` aprende NetXMS), ADR 0029 (el servidor de
vigilancia), ADR 0030 (el vigilante alcanza las zonas), ADR 0031 (el latido), reglas 7, 8,
15 y 17

## El problema, medido

El vigilante del lab 08 (`monitor`, 10.44.0.20, en el bridge de gestión) **no veía a los
invitados de las zonas**. Consultada su base con el lab desplegado:

```
$ psql -h 127.0.0.1 -U netxms -d netxms -tAc "SELECT primary_ip, uname FROM nodes ORDER BY 1;"
10.10.10.1|
10.10.10.2|
10.44.0.10|
10.44.0.11|RouterOS CHR 7.25.1
10.44.0.12|RouterOS CHR 7.25.1
10.44.0.13|RouterOS CHR 7.25.1
10.44.0.14|RouterOS CHR 7.25.1
10.44.0.15|RouterOS CHR 7.25.1
127.0.0.1|
```

Nueve nodos: los cinco equipos de RED (los CHR), el bastión, el propio servidor y dos
direcciones del nodo anfitrión. **Ningún invitado de zona** (`ficheros`, los tres `puesto`,
`web`), aunque su subred sí aparece como objeto (el vigilante la lee de las tablas de los
routers). El latido (ADR 0031) los deja en la caché ARP de su cortafuegos, pero **un nodo no
entra por estar en una caché ajena**: el descubrimiento activo sondea un RANGO y añade lo que
responde.

Y el rango que el `preparar` creía declarar **no se estaba usando**:

```
$ psql -h 127.0.0.1 -U netxms -d netxms -tAc "SELECT * FROM address_lists;"
(vacío)
```

Medido sobre la fuente de NetXMS 7.0 (el servidor que instala el área `servicio`):
`NetworkDiscovery.ActiveDiscovery.AddressRange` **no aparece en ningún fichero del código** —
se escribía con `nxdbmgr set` y no lo lee nadie. Tampoco
`NetworkDiscovery.ActiveDiscovery.Enabled`. El descubrimiento activo toma sus objetivos de la
tabla **`address_lists`** con `list_type = 1` (`discovery.cpp`:
`s_activeDiscoveryRanges = LoadServerAddressList(1)`, releído en cada ronda). Por eso los
nueve nodos entraban igual: venían del descubrimiento **pasivo** (las tablas ARP y de rutas
de los equipos SNMP), no de la ronda.

## La decisión

**1. El rango se ESCRIBE donde NetXMS lo lee: la tabla `address_lists` (`list_type = 1`).**
Cada red a vigilar es **una FILA** (`addr_type = 0`, `addr1` = red, `addr2` = máscara en CIDR,
`community_id`/`zone_uin`/`proxy_id` = 0, un `comments` con la marca `netlabs: …`). Son varias
redes y varias caben porque son varias filas — la variable de configuración, en cambio, no
tenía dónde ponerlas (y no se leía). El `preparar` **borra las filas de `list_type = 1` y
escribe las que el motor declara**: repetirlo deja el mismo estado (regla 17 aplicada a la
tabla, y regla 6).

**2. Las redes a vigilar se DERIVAN, no se escriben.** Son **dos fuentes, las dos leídas del
propio equipo**: (a) su red de gestión, derivada de su interfaz (`eth0`); y (b) **el destino
de cada ruta estática que el invitado tiene puesta** (`ip -4 route show`, las que puso el área
`routes`). El motor no conoce ninguna topología (regla 8): lee lo que el invitado declara de
sí mismo. El lab sólo **declara el camino** (las `routes`); el rango que ese camino abre sale
de ahí.

**3. `NetworkDiscovery.ActiveDiscovery.Interval` va en SEGUNDOS.** El sembrado escribía `1`
creyendo que eran horas, y en NetXMS 7.0 eran **un segundo** — una ronda por segundo. Se deja
en `3600` (una hora), que es lo que se quería decir. Se quitan, además, las dos variables
muertas (`AddressRange`, `Enabled`): escribir ajustes que nadie lee es una promesa sin
respaldo.

**4. El lab 08 declara lo que le faltaba a las DOS mitades del camino.** Al vigilante, las
`routes` a 10.44.1/2/3.0/24 por la pata de gestión de cada `fw` (10.44.0.12/13/14). Y en cada
`fw` de zona, en su `filter:` y **antes del `drop`**, un `accept` de **sólo ICMP** desde la red
de gestión hacia su zona: es el PERMISO para que la sonda atraviese el cortafuegos que, por
defecto, tira lo no declarado (regla 17 sin excepción: el permiso se declara, no se abre un
boquete a mano).

## Lo que NO hace (y se dice en voz alta)

- **No mete un agente en cada invitado.** Los de zona aparecen **como nodo** (una dirección,
  y lo que contesten a la sonda); para tener interfaces y sistema haría falta SNMP dentro de
  ellos, que es otra decisión (ADR 0030 §4) y no se toma aquí.
- **No se inventa vocabulario.** Esta decisión DESCARTA el `monitorizacion.redes` que proponía
  ADR 0030 §3: sería una **segunda** lista que puede separarse de las rutas y deja al motor
  adivinando (regla 8). Las rutas que el lab ya declara **son** la declaración de hasta dónde
  llega el vigilante; el rango es su consecuencia. (El área `routes` de Linux que ADR 0030 §2
  pidió ya existía; lo que faltaba era el lab usándola y el sembrado leyéndola.)
- **No toca los `fw` más de lo mínimo**: una regla por cortafuegos, ICMP, y del vigilante a su
  zona. Nada del tráfico entre zonas cambia.
- **No promete que NetXMS tarde un rato fijo**: la ronda corre **al arrancar** el servidor con
  las redes ya en la tabla; si el sembrado no ve hallazgos, **espera acotado** y se le da otra
  pasada.

## Las alternativas descartadas

- **Confiar en el latido (ADR 0031) solo.** Medido: deja al invitado en la caché ARP de su
  cortafuegos, pero **no lo vuelve un nodo** en esta puesta — los invitados de zona no
  aparecían. El latido sigue (es barato y no estorba); lo que se añade es el camino y la sonda.
- **`monitorizacion.redes` (ADR 0030 §3)**: una lista que el lab declara aparte de las rutas.
  Se descarta por redundante y propensa a divergir; el rango se deriva.
- **`NetworkDiscovery.ActiveDiscovery.AddressRange`**: se creía que era la palanca y **no
  existe en el código de NetXMS 7.0**. Se retira.
- **Un agente SNMP en cada invitado de zona** (ADR 0030 §4): no hace falta para que el nodo
  aparezca; queda para cuando se quiera información, no presencia.

## Cómo se sabrá que funciona

- **Prueba pura del motor** (`test/test_interior.py`): el sembrado ya no menciona
  `AddressRange`/`Enabled`, escribe la tabla `address_lists` con `list_type = 1`, y deriva las
  redes de `$base.0/24` más las rutas del propio equipo. Y que un `ctl` puede declarar `routes`
  con su Linux.
- **El ciclo real** del lab `08_dunder-mifflin-con-fw`: `destroy → apply → verify` en verde.
- **Y la prueba que importa**: entrando al invitado de vigilancia por el bastión y preguntando
  a su base, tienen que aparecer **las direcciones de zona** (10.44.1.10/.11/.12, 10.44.2.11,
  10.44.3.10) además de los equipos de red.

## VER

- [deployment_engine/filter_plugins/interior.py](../../deployment_engine/filter_plugins/interior.py)
  (`PLANTILLA_PREPARADOR_NETXMS`: `preparar` escribe `address_lists` y deriva las redes;
  `escrituras_linux`, área `routes` de Linux)
- [labs/08_dunder-mifflin-con-fw/08_dunder-mifflin-con-fw.yml](../../labs/08_dunder-mifflin-con-fw/08_dunder-mifflin-con-fw.yml)
  (las `routes` del `monitor` y el `accept` de ICMP en los tres `fw` de zona)
- [docs/decisiones/0030-el-vigilante-alcanza-las-zonas.md](0030-el-vigilante-alcanza-las-zonas.md)
- [docs/decisiones/0031-el-latido.md](0031-el-latido.md)
