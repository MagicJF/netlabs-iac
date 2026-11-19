# 0030 — Que el vigilante alcance los equipos, y que los Linux cuenten lo suyo

Fecha: 2026-11-18
Estado: aceptada
Relacionada: ADR 0029 (el servidor de vigilancia), ADR 0026 (el tipo manda), reglas 15 y 17

## El problema, medido

El vigilante del lab 08 descubre **solo su propia red**: el motor le declara como rango
`<base>.0/24` derivado de su interfaz, y ahí solo viven los cinco equipos de red (su `ether1`) y el
bastión. Los invitados de las zonas —`ficheros`, `puesto-1/2/3`, `web`— **no aparecen**, y no es
porque estén en silencio:

- **No hay camino.** Medido en el vigilante: `default via 10.10.10.1` (su pata de gestión) y solo
  `10.44.0.0/24` por `eth0`; **ninguna ruta** a `10.44.1/2/3.0/24`. Ampliar el rango, por tanto,
  sondea hacia la nada.
- **Y no contestan.** Los `fw` tienen `input`/`forward` en `drop` salvo lo declarado, así que un
  ping del vigilante a una zona **no vuelve**.
- **Y no tienen con qué contar nada.** Ningún invitado Linux lleva agente SNMP (solo los RouterOS
  declaran el área `snmp`). Aunque llegara, un Linux sin agente es, como mucho, **un nodo pelado**:
  una IP y poco más — sin sistema operativo, sin interfaces, sin sitio real en la topología.

Y una pieza que faltaba para poder pedirlo: **esos cinco invitados no declaran `config:`**, es
decir, el motor **no entra en ellos** (`ready: {tipo: ninguno}`, por diseño del lab). Sin entrada no
hay forma de instalarles nada.

## La decisión

### 1. Que un Linux pueda responder por SNMP: área `snmp`

El vocabulario del interior es cerrado (regla 15): el lab no inventa primitivas. Se añade al driver
Linux el **gemelo** del área `snmp` que ya existe para RouterOS:

- **Lo que hace**: instala `snmpd` (net-snmp, del repo de la distro), fija `agentaddress udp:161`
  (Debian lo deja escuchando solo en `127.0.0.1`, medido) y pone **una** comunidad **de solo
  lectura**, la constante del motor (`COMUNIDAD_SNMP`, la misma con la que el vigilante pregunta y
  la misma que ya declaran los equipos de red). **No toca** ninguna otra directiva: lo que no está
  en el área, no se configura (regla 17).
- **Cómo se lee**: `estado` = el demonio vivo **y** contesta a un GET de `sysDescr` hecho **contra
  sí mismo** (`127.0.0.1`), que es la única prueba de que la comunidad y la dirección de escucha
  valen. Igual que en RouterOS: no basta con que el paquete esté, hay que **poder preguntarle**.
- **Por qué `snmpd` y no el agente de NetXMS**: `snmpd` es **el estándar** y no ata el invitado a
  este servidor; el agente de NetXMS da más (inventario, rendimiento) pero solo tiene sentido si el
  lab entero se casa con NetXMS. Para «ver la topología y la info», `snmpd` es la pieza justa. El
  agente propio queda como posible ADR futuro, no se descarta: se aparca.

### 2. Que el vigilante llegue: área `routes` para Linux

El CHR ya declara `routes:`; el Linux no tenía esa área. Se añade, **idéntica en forma y en
semántica** (`dst_address` + `gateway`, se aplican y se leen), para que el lab pueda dar al
vigilante el camino a las zonas **por los routers del lab** (nunca por una vía que rodee la
topología: regla 16). El motor no elige la ruta: la declara el lab.

### 3. Que el rango se declare: `monitorizacion.redes`

Hoy el rango de descubrimiento es **derivado** (la red del propio invitado), y está bien: es el caso
general. Pero cuando el vigilante tiene camino a más redes, el lab debe poder decirlo, porque **el
motor no conoce la topología** (regla 8) y no puede adivinar a dónde llega. Por eso el área
`monitorizacion` admite una lista **opcional** de redes a vigilar:

```yaml
monitorizacion: {redes: [10.44.1.0/24, 10.44.2.0/24, 10.44.3.0/24]}
```

Sin `redes`, el comportamiento de hoy no cambia (la red del propio invitado). Con `redes`, se
declaran esas **y** la suya. Siguen siendo **valores del lab** (en el fichero del lab, nunca en el
motor).

### 4. Los permisos no son código

Que el vigilante pueda hablar con cada zona es **declaración del `filter`** de su `fw` (primitiva que
ya existe: `chain`, `action`, `protocol`, `src_address`, `dst_address`, `dst_port`). El motor no
abre nada por su cuenta; el lab dice a quién deja preguntar.

## Lo que NO cambia

- El motor **no conoce** ninguna de estas redes, ni elige rutas, ni decide quién vigila a quién: todo
  eso es declaración (reglas 7 y 8).
- El vigilante sigue **fuera** de los cortafuegos y en el bridge de gestión (ADR 0029).
- Un invitado que no declare `config.linux.snmp` sigue **sin** agente: el motor no lo toca.

## Consecuencia que hay que decir en voz alta

Para que estos cinco aparezcan **con información**, el lab tiene que **entrar en ellos** (declararles
`config:`), y hoy no lo hace: hoy son hosts que el lab deja vivir sin gestionar. Este ADR **no**
decide ese cambio del lab — solo abre las primitivas para que, si el lab lo pide, el motor sepa
hacerlo. La decisión de gestionar esos cinco es del lab, y va con sus permisos y sus rutas.

## Cómo se sabrá que funciona

- Una prueba por primitiva, con el mismo patrón que las existentes (diff canónico + `estado`), sin
  Proxmox: el área `snmp` y el área `routes` del driver Linux, con sus casos.
- Contra el nodo real: `./lab --lab 08_dunder-mifflin-con-fw plan --api` (converge los cinco), y
  `python3 test/test_interior.py`.
- Y la prueba de punta a punta que importa: `snmpget` **desde el vigilante** a la IP de un invitado
  de zona, y ese invitado apareciendo en la topología **con sus interfaces**.
