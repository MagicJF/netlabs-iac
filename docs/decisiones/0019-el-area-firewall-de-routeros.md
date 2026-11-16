# 0019 — El área `firewall` de RouterOS: la tabla de filtrado entera, y la última en converger

*Fecha: 16-nov-2026 — Estado: aceptada y aplicada — Ámbito: QUÉ se declara del cortafuegos de
un RouterOS y CÓMO converge (un área nueva del vocabulario cerrado)*

## El problema

El motor sabía montar un router (direcciones, rutas, DHCP, salida con NAT, servicios) pero **no
sabía filtrar**: `firewall` estaba en `AREAS_PENDIENTES` con `bridges`, y la validación
**rechazaba** declararlo con un motivo legible en vez de aceptarlo y no hacer nada. Un lab que
quiera un **cortafuegos de verdad** —no un router con NAT, sino una máquina cuya única
responsabilidad sea decidir qué pasa y qué no— no se podía declarar. Este ADR añade el área.

## La decisión

**1. La tabla declarada ES la tabla entera, y el ORDEN es la semántica.** RouterOS aplica la
**primera** regla que casa y para: el orden no es presentación, es la política. Así que
`firewall:` es una **lista ordenada** y el área entera es del lab (regla 17): una regla que no
se declara **se quita**. No hay «añadir una regla suelta»: se declara la política.

**2. El vocabulario es CERRADO y está en `CAMPOS_FILTRO`** (`interior.py`): `chain`, `action`,
`protocol`, `src_address`, `dst_address`, `src_port`, `dst_port`, `in_interface`,
`out_interface`, `connection_state`, `comment`, `disabled`. A la izquierda el nombre que escribe
el lab (snake_case, como el resto del vocabulario); a la derecha el objeto de RouterOS
(`src-address`). Lo que no esté ahí **no se puede pedir**, y se caza antes de tocar nada.

**3. `chain` ∈ {input, forward, output} y `action` ∈ {accept, drop, reject}.** Es lo que hace
un cortafuegos: permitir, tirar, o rechazar. Se deja fuera lo que no se ha pensado (saltos a
cadenas, `jump`, marcado, `log`) — el vocabulario se ensancha cuando haya un lab que lo pida,
no antes.

**4. La convergencia es RECONSTRUIR, no parchear.** Si la tabla leída ya coincide (comparando
la lista **en orden**, campo a campo), no hay operación y la 2ª pasada **sólo lee**. Si no
coincide, se quitan **todas** las reglas leídas —con su `.id`, que es lo único con lo que
RouterOS deja borrar una regla— y se ponen las declaradas **en orden**. Es más grueso que un
diff fino, y es a propósito: conservar el ORDEN regla a regla exigiría `move`, que por REST no
es razonable; la reconstrucción lo garantiza de una vez. El precio, dicho: entre el `remove` y
el `add` hay un instante sin filtro (y con el transporte por guion, ADR 0018, todo el
`remove`+`add` es **una sola llamada**).

**5. Converge la ÚLTIMA, después incluso de la credencial.** Es la única área capaz de **dejar
al motor fuera de su propio equipo**: su túnel de vuelta es una conexión de **ENTRADA**. Así que
se cierra la puerta con todo lo demás ya puesto y probado, y con la credencial del motor ya
cambiada — no con la de fábrica. Es la misma doctrina que ya estaba escrita en el orden de
áreas («no se cierra una vía de acceso antes de haber pasado por ella»).

## La trampa (y la guarda que la caza antes de tocarte el router)

Un `drop` en la cadena `input` que no deje pasar la red de gestión **corta el túnel**: el equipo
deja de obedecer y hay que recuperarlo **por consola**. No es hipotético: es la primera regla que
escribe cualquiera que endurezca un router, y con este motor significa brickear el lab.

Por eso la validación (`declaracion.py`) **no** se limita a la forma: caza una regla
`input`+`drop`/`reject` que llegue **sin un `accept` de `input` ANTES** en la lista, y la rechaza
con el motivo. La excepción de gestión es **obligatoria y explícita**: el lab la declara, no la
adivina el motor. (En el lab `dunder-mifflin-con-fw` son las reglas que abren `input` para la
red de gestión y para `established,related`.)

## Qué NO se toca

- **Nada del cálculo de las otras áreas**: el diff, el orden de las áreas, el diario, la
  relectura y el `verify` (que sigue leyendo, y ahora lee también `/ip/firewall/filter`).
- **Ni un valor de lab en el motor**: el área no conoce ninguna red concreta; sólo traduce el
  vocabulario cerrado.
- **`bridges` sigue PENDIENTE**: una máquina «switch» (un RouterOS puenteando) es OTRA área y
  OTRO ADR. Este ADR es sólo el filtrado.

## Cómo se comprueba

- **`test/test_routeros.py`** (§5): la tabla declarada entera y en orden; el cortafuegos es lo
  ÚLTIMO (después de la credencial); los cuerpos usan los nombres de RouterOS; en el guion cada
  regla es su línea de consola **con el comentario entre comillas**; la 2ª pasada no escribe
  nada; y con una regla de más se reconstruye con los `.id` leídos.
- **`test/test_declaracion.py`**: un campo fuera del vocabulario, una cadena o acción que no
  existen, un `firewall` que no es lista, y —lo que importa— el `drop` de entrada sin `accept`
  previo, cada uno con su motivo.
- **El ciclo real** contra el VPS, en el lab `dunder-mifflin-con-fw` (ver su documento): la
  prueba de que la tabla converge de verdad la da la relectura, no este ADR.

## VER

- [deployment_engine/filter_plugins/interior.py](../../deployment_engine/filter_plugins/interior.py)
  (`CAMPOS_FILTRO`, `_firewall_canonico`, `LECTURAS_ROUTEROS["firewall"]`, el orden en
  `pasos_de_convergencia` y las dos operaciones en `escrituras_routeros`)
- [deployment_engine/filter_plugins/declaracion.py](../../deployment_engine/filter_plugins/declaracion.py)
  (la forma cerrada, la guarda de supervivencia y el tipo de equipo `fw`)
- [deployment_engine/tasks/configurar_routeros.yml](../../deployment_engine/tasks/configurar_routeros.yml)
- [deployment_engine/tasks/ros_api.yml](../../deployment_engine/tasks/ros_api.yml)
- [docs/decisiones/0006-escribir-en-routeros.md](0006-escribir-en-routeros.md) (el orden de
  escritura y la credencial al final)
- [docs/decisiones/0018-el-transporte-de-la-escritura-de-routeros.md](0018-el-transporte-de-la-escritura-de-routeros.md)
  (el guion, que es como viaja esta tabla)
- [labs/08_dunder-mifflin-con-fw/08_dunder-mifflin-con-fw.md](../../labs/08_dunder-mifflin-con-fw/08_dunder-mifflin-con-fw.md)
