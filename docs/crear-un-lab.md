# Crear un lab: las decisiones, en orden

<!-- PROPÓSITO: la guía de campo para escribir un lab. NO es una plantilla que se pega: es el
     orden en que se TOMA cada decisión, con su valor por defecto, su trampa y el check que la
     vigila. La plantilla que sí se copia es `labs/.plantilla/` (`./lab new <nombre>`); esto es
     el porqué de lo que hay dentro.
     INVARIANTES: nada de lo que aquí se decide pertenece al motor. Un lab nuevo no toca ni un
     fichero de `deployment_engine/` (regla 7); si necesita una primitiva que no existe, la pide
     al motor con un ADR (regla 15), no la inventa en su YAML.
     LÍMITES: esto describe el vocabulario de HOY. Lo que está declarado como pendiente
     (puentes y cortafuegos de RouterOS; pasarela, rutas, dns y claves de Linux) se nombra aquí
     para que no lo busques: no está implementado.
     VER: AGENTS.md; README.md; deployment_engine/filter_plugins/declaracion.py;
     labs/04_lab-red-routeros/ (el ejemplo trabajado); ./lab check declaracion -->

## La forma de un lab, en tres piezas

```
labs/NN_<lab>/            el NN es la antigüedad: lo pone `./lab new`, no tú
├── NN_<lab>.yml    el estado deseado. Es la FUENTE DE VERDAD: lo que no está aquí no existe
├── NN_<lab>.md     el documento. Dos regiones: la tabla la escribe el motor, la prosa la escribes tú
└── logs/           lo que dejó el motor (api.jsonl, interior.jsonl, console.jsonl). Nunca a mano
```

`./lab new <lab>` scaffoldea las dos primeras desde `labs/.plantilla/`, con el nombre del lab
ya numerado. A partir de ahí el lab es tuyo: no se hereda de ningún sitio ni se genera solo.
**Lo que se escribe una vez es lo que se lee después**, así que el orden de abajo importa.

## 1. Qué quieres poder demostrar

Antes de escribir nada: ¿qué tiene que pasar para que este lab valga? De esa respuesta sale la
forma, y **la forma más pequeña que demuestre eso es la correcta**. Los labs del repo son, en
orden de tamaño, el catálogo de formas que ya existen:

- **un invitado y nada más** — que el motor crea, identifica y entra en un Linux.
- **dos redes y un router** — que el motor construye un túnel entre dos L2 y enruta.
- **una red de routers** — que el motor encadena equipos, reparte direcciones y converge por etapas.
- **algo que aún no se sabe** — un lab de investigación: mide, y luego se decide.

Regla de crecimiento: **una pieza nueva por lab, y sólo cuando la anterior está verde**. Un lab
que hace cinco cosas nuevas a la vez te dice que algo falla, pero no cuál.

## 2. El nombre

En minúsculas y con guiones (`mi-lab`). **El número de antigüedad lo pone el wrapper**:
`./lab new mi-lab` crea `labs/07_mi-lab/` con el siguiente número libre, porque los labs se
ordenan por antigüedad y la carpeta lo dice (ADR 0016); `ls labs/` se lee de arriba abajo en
orden histórico. Se puede pedir uno concreto (`./lab new 09_mi-lab`) para insertar algo donde
corresponde, y dos labs nunca comparten prefijo.

El nombre no es decorativo: de él salen la carpeta, el pool de Proxmox (que se llama como la
carpeta) y la frontera de propiedad. Cámbialo después y `destroy` ya no sabe qué es tuyo.

Ojo: el nombre del **lab** no es el de los **invitados**. Un invitado se llama por lo que ES
(`rt-borde`, `srv-1`, `ws-2`) y el lab se ve en su pool y en su descripción, así que dos labs
pueden repetir `rt-nucleo` sin confundirse (ADR 0015).

## 3. El espacio de direcciones

Un bloque por lab, distinto del de todos los demás: es lo que hace que dos labs no se pisen ni
al convivir en el mismo nodo. Sale de una decisión consciente, no de la comodidad. El check
`address_space` avisa si dos labs del repo se solapan, y `colisiones` si dos labs declaran lo mismo.

**Por defecto:** un `/16` libre. Los direccionamientos de los ejemplo de esta guía son de
documentación (`192.0.2.0/24`, TEST-NET-1): no los copies como si fueran de tu lab.

## 4. Los bridges

Se **declaran** en `lab.bridges`, con nombre y con su dirección. No hay bridges implícitos.

- El nombre es del lab (`vmb_<algo>` por convención del repo). Nada más mirarlo se sabe que no
  es un bridge del nodo.
- **Su dirección es la vía de acceso de esa red**: `192.0.2.1/24` quiere decir que quien cuelga de ese
  bridge tiene ahí su gateway. Por eso el bridge de gestión del lab y el router que lo atiende
  pueden compartir red (la dirección del bridge es de un extremo, la del router del otro).
- El motor **sólo crea el bridge si falta**, y le pone su marca (`lab=<lab>`); un bridge sin esa
  marca no se adopta y no se toca. `destroy` sólo borra lo que lleva su marca y no está en uso.

**Trampa:** declarar un bridge por el que luego no pasa nadie. Sale en el check y en el nodo, y
no sirve para nada.

## 5. Los invitados

Uno por rol, en `vms:` (QEMU) o `containers:` (LXC). Cada uno:

- **`rol`**: el nombre de la pieza en tu topología (`router-borde`, `puesto-1`). Es lo único que
  te identifica, y de él salen la descripción del invitado (`lab=… rol=…`) y el alias del nombre
  si no declaras uno.
- **`tipo`**: QUÉ EQUIPO es — `rt` (router), `srv` (servidor), `ws` (puesto de trabajo), `sw`
  (conmutador o equipo sin dirección), `ctl` (bastión, el bastión del lab).
  **Obligatorio**, y del vocabulario cerrado: con él y su alias se compone el nombre del invitado
  en Proxmox (`rt-borde`, `srv-1`, `ws-2`) — ADR 0015. Un equipo que no quepa en ninguno pide su
  tipo al motor, con su ADR; no se inventa aquí.
- **`nombre`**: opcional, el alias corto (`1`, `borde`, `salida`). Si no lo pones, el alias es el
  rol. Es la segunda mitad del nombre del invitado. Dos invitados del **mismo** lab no pueden
  componer el mismo nombre (el validador lo rechaza); dos labs distintos sí pueden repetirlo.
- **Qué es VM y qué es contenedor** se elige por la **sección**, no por un campo: en `vms:` si
  necesita su propio kernel (un CHR, una imagen de fábrica), en `containers:` si basta un Linux
  ligero (arranca en segundos).
- **`stage`**: el orden en que el motor enciende y converge. **Nadie arranca antes de que
  quien le da la dirección esté sirviendo** (regla 18: así la carrera del DHCP muere por
  construcción). Si te equivocas, el consejo `stages` te lo dice con el número que toca.
- **`bridges`/`bridge`**: sus interfaces. Una VM declara todas y el orden importa (`ether1` es la
  primera); un contenedor normalmente una.
- **`address`**: en la primera interfaz, `"dhcp"` o una dirección con máscara. **Es la
  diferencia entre una estación y un servidor, y se declara como se hace en la vida** (ADR
  0013):
  - `"dhcp"` — una **estación**: al conectar pide dirección, y el router de su red le da
    dirección, pasarela y DNS de una vez. No declares nada más: ése es el escenario.
  - `192.0.2.10/24` — una **máquina con dirección fija**: no pregunta nada. Necesita su
    **`gateway`** (`192.0.2.1`) para salir, y esa pasarela la declaras tú, como la pondrías en el
    equipo. La dirección estática va **fuera del rango del DHCP** (si no, un cliente dinámico
    puede pedirla antes: eso es el consejo `dhcp`).
  - sin declararla — si el invitado tiene interior, nace pidiendo dirección (`dhcp`), que es lo
    que hace cualquier equipo al enchufarle el cable. Un invitado **sin** interior no la lleva:
    es un esqueleto de topología, no una máquina que el motor vaya a configurar.
- **`gateway`**: la suya, y sólo tiene sentido con una dirección fija. El motor **no la adivina**:
  la declaras tú (regla 7). Es la dirección del router de esa red dentro del lab.
- **Recursos**: `cores`, `memory`, `disk`. El mínimo honesto que necesita la pieza. Los CHR
  van con lo justo; un contenedor Alpine, con menos todavía.
- **`image`** (VMs): de fábrica, la del fabricante. La imagen sólo se puede adjuntar **al crear**
  la máquina: sin ella, nace sin disco y no arranca nada (el consejo `image` lo recuerda).

**Lo que NO se declara nunca:** ni vmids ni MACs. El motor los deriva (el menor vmid libre del
clúster, la MAC como función del vmid) y las reservas DHCP se derivan de ahí. Si ves una MAC en
un YAML, es un bug.

## 6. El interior: `config:`

Un invitado, por defecto, es un aparato vacío que el motor enciende. `config:` le dice que
además **hay que entrar en él y configurarlo**, con el vocabulario **cerrado** de su driver:

- **RouterOS** (`config.routeros`): `identity`, `addresses`, `ip_services`, `dhcp_client`,
  `rutas`, `dhcp`, `uplink`. Se configura **por su REST**, a través del túnel (ADR 0010).
- **Linux** (`config.linux`): `tunnel`, `address`, `addresses`, `ip_forward`, `dhcp_server`.
  Se entra **por SSH**, y sólo desde `tasks/interior_ssh.yml`.
- **Pendiente, y se nota que lo está**: `puentes` y `cortafuegos` (RouterOS); `gateway`,
  `rutas`, `dns` y `claves` (Linux). **No están implementadas y el validador las rechaza.**

### `uplink`: que el lab salga a internet

Un RouterOS declara `uplink: {}` para decir que **ese router es la salida del lab**. Es una
**marca**, sin opciones: la interfaz de fuera la tiende el motor al nacer —la última, sin
dirección— sobre el bridge del nodo que tiene salida (`pve_bridge_gestion`, un valor de
entorno), y su dirección, su pasarela y su DNS los **deriva el motor** del estado, con la misma
regla que la interfaz del bastión en ese bridge (la dirección del bridge es la vía de acceso;
la del invitado se cuenta por arriba entre las libres). Las tres las propone el motor, no el
lab: por eso **el lab no declara ni una dirección de casa** y por eso, si declaras opciones en
`uplink`, el validador te para (ADR 0012).

Con la marca, el motor configura cuatro cosas: la dirección de la interfaz de fuera (derivada), la
ruta por defecto por la pasarela de fuera (derivada), MASQUERADE por esa interfaz, y el resolutor
DNS encendido apuntando a esa pasarela.

Dos tropiezos que ya están cazados, para que no los repitas:

- **Un router de salida NO declara ruta por defecto.** La pone el motor por la vía de acceso de
  fuera. Si la declaras, salta el consejo `exterior-con-ruta` (dos rutas compitiendo) y además
  obligas al lab a saberse la pasarela de casa, que es justo lo que `uplink` evita.
- **Sus redes tienen que anunciar DNS.** Si ningún servidor DHCP del lab anuncia DNS, el lab
  sale a internet y no resuelve un solo nombre: salta `exterior-sin-dns`. El DNS que anuncies
  tiene que ser alguien que resuelva de verdad (el router de salida lo hace, porque
  `uplink` le enciende el resolutor).

Y los clientes **no se configuran por dentro**: su pasarela y su DNS los reparte el DHCP del
router. Un contenedor con su red bien servida tiene internet sin una línea de `config:`.

El ejemplo trabajado está en `labs/06_conectividad-exterior/`.

El lab **no puede inventarse una primitiva**. Si necesitas algo que no está, se le pide al motor
—con su ADR, su driver, su lectura de vuelta y sus pruebas— y luego se declara. Es la regla que
mantiene el motor genérico.

Dentro de un área declarada, **lo que no está en el YAML se quita del equipo**; fuera de las
áreas declaradas, el motor no toca nada. Declarar es tomar posesión.

## 7. El bastión: `lab.túnel`

Un lab puede declarar `lab.túnel`: eso pide un **bastión**, un LXC con `rol: control`
que construye el túnel hacia casa y por el que el motor entra en todos los demás (`ProxyJump`).
Hace falta cuando el motor tiene que configurar el interior de algo; no hace falta para que el
lab exista. El cómo está en [tunnel-del-bastion.md](tunnel-del-bastion.md).

**Trampa:** un lab con `config:` en algún invitado y **sin** bastión se despliega
igual, pero el trabajo del interior se queda **blando**: se declara, se avisa y se sigue. Si el
interior importa, el túnel no es opcional.

## 8. Quién da las direcciones

Dos sitios, y ninguno se improvisa:

- **El bastión** (`config.linux.dhcp_server`), con `static_leases: derived` para que el
  motor le ponga a un invitado la dirección que se deriva de su vmid. Es lo más cómodo para las
  interfaces de gestión.
- **Un RouterOS** (`config.routeros.dhcp`), para las redes que enruta.

**Un servidor DHCP por bridge.** Dos en la misma L2 es una carrera (consejo `dos-dhcp`). Y quien
pide por DHCP tiene que ir **después** de quien le contesta.

## 9. Y entonces, en este orden

| cuándo | qué |
| --- | --- |
| mientras escribes | `./lab check declaracion` — valida **y aconseja** |
| al terminar de escribir | `./lab check docs --actualizar` (regenera la tabla) y `./lab check docs` |
| antes de tocar el nodo | `./lab --lab <lab> preflight` — ¿el mundo es como crees? |
| para LEERLO antes de crearlo | `./lab --lab <lab> plan` — y con `config:`, `plan --api` |
| cuando el plan te convenza | `./lab --lab <lab> apply` — debe converger en UNA pasada |
| la segunda pasada | `./lab --lab <lab> apply` — debe dar `changed=0` y **sólo lecturas** |
| para saber si está | `./lab --lab <lab> verify` |
| antes de subirlo | `./lab check` (todo) y `ansible-lint` |
| para deshacerlo | `./lab --lab <lab> destroy --yes` |

**El plan se lee.** Un lab no se despliega «a ver qué pasa»: `plan` dice vmids, MACs, direcciones
y reservas **sin tocar el nodo**, y ahí se ven los errores que ningún check puede ver.

## 10. La prosa del documento

La tabla de `<lab>.md` la escribe el motor (`check docs --actualizar`). La prosa es tuya, y el
esqueleto nace con estos encabezados, en este orden:

- `## Por qué así` — qué topología es y por qué ésa y no otra.
- `## Qué se rompió (y cómo se arregló)` — lo que falló al desplegarla de verdad. Es lo que más
  vale del documento: nadie más va a tropezar donde tú tropezaste.
- `## Qué está verificado, y qué no` — qué comprobaste y con qué salida.
- `## Qué queda fuera` — los límites, dichos en claro.

Son un punto de partida, no una norma que ningún check vigile: los labs que ya existen tienen los
suyos, y su prosa no la reescribe nadie. Lo que sí es norma es lo de abajo.

**La prosa no repite valores de la tabla**: los cita. Si el dato no está en la tabla y hace
falta, se añade a la tabla (el esqueleto es rígido; el cuerpo es libre).

## 11. Lo que el motor no te va a perdonar

- Declarar un vmid, una MAC o un valor de casa (la vía de acceso de internet, el DNS de fuera, una ruta
  por defecto de verdad): **eso es del entorno, no del lab**.
- Copiar un fichero del motor para un lab, o un verbo para un lab.
- Escribir en `labs/<lab>/logs/`.
- Decir que funciona sin la salida del comando que lo prueba.
