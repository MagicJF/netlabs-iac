<!-- PROPÓSITO:   el documento del lab. Dos regiones, dos escritores.
     INVARIANTES: la región generada (entre los marcadores) la reescribe
                  `./lab check docs --actualizar`; `./lab check docs` falla si el
                  fichero difiere de su render. La prosa de fuera NO la toca
                  ningún check: escribe lo que el YAML no puede decir.
     LÍMITES:     la prosa no repite valores que ya están en la tabla; los cita.
     VER:         AGENTS.md §Documentación; README.md §Documentación;
                  docs/crear-un-lab.md (la guía de campo: las decisiones, en orden) -->

# 07_dunder-mifflin

La red de una empresa pequeña, en su forma mínima: una sede, una salida a internet,
dos áreas (la oficina y el almacén), un servidor de ficheros y tres puestos. Lo que
este lab añade a los anteriores no son invitados --son seis, como los de antes-- sino
que **un solo router sirve dos redes a la vez**, con dos ámbitos DHCP, y que hay un
cliente dinámico en cada área: eso es lo que prueba que el router no se confunde de
red. Los labs anteriores daban una red por router, así que esto no se había podido
enseñar.

<!-- generado:inicio -->
_Datos derivados de `07_dunder-mifflin.yml`. Los reescribe `./lab check docs --actualizar`;
si los editas a mano, `./lab check docs` falla._

## Invitados declarados

| rol | tipo | escalón | cores | memoria (MB) | disco (GB) | bridge | dirección |
| --- | --- | --- | --- | --- | --- | --- | --- |
| borde | VM (qemu) | 1 | 2 | 512 | 1 | vmb_dm_gestion + vmb_dm_oficina + vmb_dm_almacen | 10.43.0.11/24 |
| control | LXC | 1 | 1 | 512 | 4 | vmb_dm_gestion | 10.43.0.10/24 |
| ficheros | LXC | 2 | 1 | 512 | 8 | vmb_dm_oficina | 10.43.1.10/24 |
| puesto-1 | LXC | 3 | 1 | 512 | 4 | vmb_dm_oficina | dhcp |
| puesto-2 | LXC | 3 | 1 | 512 | 4 | vmb_dm_oficina | dhcp |
| puesto-3 | LXC | 3 | 1 | 512 | 4 | vmb_dm_almacen | dhcp |

## Bridges del lab

| bridge | dirección del bridge |
| --- | --- |
| vmb_dm_gestion | 10.43.0.1/24 |
| vmb_dm_oficina | 10.43.1.1/24 |
| vmb_dm_almacen | 10.43.2.1/24 |

## Orden de arranque (escalones)

| escalón | roles |
| --- | --- |
| 1 | borde, control |
| 2 | ficheros |
| 3 | puesto-1, puesto-2, puesto-3 |

## Identidad: la deriva el motor, no la declara el lab

| rol | tipo | nombre canónico | vmid | MAC |
| --- | --- | --- | --- | --- |
| borde | VM (qemu) | {equipo}-{alias} | — | — |
| control | LXC | {equipo}-{alias} | — | — |
| ficheros | LXC | {equipo}-{alias} | — | — |
| puesto-1 | LXC | {equipo}-{alias} | — | — |
| puesto-2 | LXC | {equipo}-{alias} | — | — |
| puesto-3 | LXC | {equipo}-{alias} | — | — |

El **vmid** (el menor libre de *todo* el clúster) y la **MAC** (`BC:24:11` + los
bytes del vmid) los asigna `apply` leyendo el estado de Proxmox: no se declaran aquí y
no se guardan en ningún fichero del repositorio. Por eso estas dos columnas son un
guion hasta que exista un despliegue real.
<!-- generado:fin -->

## Por qué así

**Una sede, no una cadena de routers.** Los labs 04 y 06 encadenaban dos CHR para
llegar a la segunda red. Una empresa pequeña no tiene eso: tiene un cortafuegos y un
conmutador, y lo que hay que demostrar aquí es que el MISMO equipo sirve dos redes sin
confundirse. De ahí las dos direcciones y los dos ámbitos DHCP en un solo router, cada
uno con su red declarada -- porque es la red la que dice de quién es cada reserva
derivada, y por eso el ámbito del almacén, donde hoy no hay nada fijo, no reserva nada
y el de la oficina sí. Si el motor se confundiera de ámbito, `puesto-3` no tendría
dirección; es la comprobación que hace que este lab valga la pena.

**El servidor lleva la dirección a mano, y los puestos la piden.** Es la regla de
ADR 0013 y se ve entera en esta tabla: el servidor de ficheros declara dirección y
puerta y no pregunta nada, y los puestos declaran `dhcp`. Así la sede no depende de que
el DHCP funcione para todo, que es como está montado un rack de verdad. El servidor no
declara `config:` -- no se entra en él: su dirección la escribe el motor al nacer, en
la cadena de red del contenedor, que es donde Proxmox la pone.

**El switch no es un invitado: es el bridge.** Un bridge de Linux es un conmutador
--aprende MACs y conmuta entre sus patas--, así que la oficina ya tiene el suyo y no
cuesta un invitado. Declarar aquí un contenedor de tipo `sw` sería declarar una caja
que no conmuta: el vocabulario del interior no tiene `puentes`, y la validación lo
rechaza con su motivo. El switch está donde tiene que estar, en el nodo, y por eso lo
crea el motor (marcado, para que `destroy` sepa que es suyo).

**Tres escalones, y el del medio no es un capricho.** El 1 es el puesto de control y el
router --el que da y el que pide la primera dirección, que es el círculo que cierra el
arranque en frío--; el 2 es el servidor, que no pregunta nada pero necesita la puerta
ya sirviendo para salir; y el 3 son los puestos dinámicos, que sin DHCP no serían nada.
El orden no es estético: es lo que mata la carrera del DHCP por construcción (regla 18).

**Un solo resolutor, y en la puerta.** Los dos ámbitos anuncian el propio router como
DNS, y es el router quien resuelve porque `exterior` le enciende el resolutor. Un lab
con dos redes no necesita dos DNS: necesita uno que sepa salir.

**El puesto de control no lleva dirección en las patas de dentro.** Nace con una pata
en cada bridge del lab --y una en el del nodo, derivada--, pero sólo declara la de
gestión. No es un olvido: el único invitado en el que el motor entra es el router, y el
router está en el bridge de gestión, que es donde el puesto ya tiene su dirección. Las
patas de dentro son para mirar y para el día en que haya que entrar en algo que hoy no
se toca.

**`dm`, y no `dunder-mifflin`, en los bridges.** Una interfaz del kernel no pasa de 15
caracteres (IFNAMSIZ) y el nombre del lab, entero, no cabe. `vmb_07_dunder_m` --lo que
derivaría el wrapper-- tampoco dice nada; `dm` al menos se lee.

## Qué se rompió (y cómo se arregló)

**La primera pasada no convergió, y no era culpa del lab.** Murió con una operación
pendiente en el router: `[dhcp] quitar_reserva`. El ámbito del ALMACÉN quería quitar la
reserva de la oficina -- la del servidor de ficheros, que el otro ámbito acababa de
declarar en la misma pasada -- porque el motor comparaba las concesiones del router
ENTERO contra lo que declara cada ámbito. Con una sola LAN eso no se ve (todas las
concesiones son de ese ámbito); con dos, el segundo ámbito pide quitarle la reserva al
primero y el router no converge nunca, por muchas pasadas que se le den.

Es un fallo del MOTOR, no de este lab: el caso (un router sirviendo dos redes) es
legítimo, y el driver ya decía en su docstring que cada servidor tiene su ámbito -- lo
que no hacía era mirarlo al leer. Arreglado en
`deployment_engine/filter_plugins/interior.py` (`_reserva_es_de_este_servidor`): cada
ámbito mira SÓLO las concesiones que sirve su servidor (el campo `server` de la
concesión, que un CHR siempre escribe), y una concesión que no diga a quién sirve
(`all`, o sin `server`) se atribuye a la red en la que cae su dirección -- y a la única
del router si sólo declara una, que es lo que deja igual un router de una sola LAN. El
caso quedó en `test/test_routeros.py` (§2.b: dos ámbitos, cero operaciones al día, y lo
que sobra en el segundo ámbito sí se quita).

**Y el segundo fallo lo destapó la segunda pasada, y era más gordo.** Al reintentar
`apply` (la pasada había muerto a medias), el motor **creó la topología entera otra vez**
con vmids nuevos: `rt-borde` pasó a existir dos veces (102 y 109), y así los seis. La
causa no era el lab: la frontera de propiedad se comparaba con **dos nombres distintos**
--el estado y el asignador preguntaban por el pool *de la carpeta* (`07_dunder-mifflin`)
mientras el motor lo **crea** con su prefijo (`lab_07_dunder-mifflin`, que es lo que
Proxmox exige a un poolid)--, así que **ningún** invitado propio se reconocía: todos
caían del lado de «no es de nadie», el plan los veía ausentes y los volvía a crear. Sin
un solo error en el diario, y sin que `verify` se quejara: el motor duplicaba el lab y
dejaba de ser idempotente (regla 6). Arreglado en `estado.py` y en `identidad.py`
(comparar con `identidad_pool(lab)`, el nombre derivado), con el caso de punta a punta en
`test/test_identidad.py` (caso 8) y el ADR 0002 diciendo lo que faltaba decir.

Los seis invitados duplicados se borraron **a mano por la API** (parar y
`DELETE ...?purge=1`), que es lo que manda el propio mensaje de `destroy` cuando
encuentra en el pool algo que la declaración no reconoce: su `rol` sí estaba declarado,
así que el motor se negó -- con razón -- a tocar lo que no puede distinguir de un
invitado puesto a mano. Después, `destroy` limpió el lab de verdad (6 invitados, el pool
y los tres bridges) y el ciclo volvió a empezar de cero.

**Lo que este lab enseñó de paso, y no es poco:** el fixture del clúster vacío no tiene
puerta de casa, así que un lab con `exterior` no se puede planificar en seco (ver §Qué
queda fuera); y la reserva derivada sigue la RED que declara el servidor, no el bridge,
que es la forma que hace falta en cuanto un router sirve dos redes.

## Qué está verificado, y qué no

**El ciclo, sobre el nodo de verdad** (`destroy` → `apply` → `verify`, sin nada en seco):

- **`apply`, una sola pasada**: `PLAY RECAP … changed=44 failed=0` y la verificación que
  el propio verbo corre al final: **CORRECTO** — `esperados=6 encontrados_en_el_pool=6`,
  los seis CONFORMES (existen, coinciden y están arrancados) y el interior **2/2** (los
  dos invitados en los que el motor entra: el router por su REST y el puesto de control
  por SSH).
- **Idempotencia (regla 6)**: segunda pasada `changed=0` (el `PLAY RECAP` lo dice), y los
  **tres diarios con sólo lecturas**: `api.jsonl` 66 líneas nuevas y todas `GET`,
  `interior.jsonl` 10 líneas y todas `leer`, y `camino.jsonl` **ni una** (la consola es
  para el arranque del puesto de control y no se vuelve a usar, regla 19).
- **El router sirvió cada red con SU ámbito**, que es lo que este lab venía a demostrar.
  Se lee en su tabla de concesiones, por su REST, en el diario de API: `ws-1` →
  `10.43.1.200` por `netlabs-ether2` (la oficina), `ws-2` → `10.43.1.199` por el mismo
  servidor, y `ws-3` → `10.43.2.200` por `netlabs-ether3` (el almacén). Las tres
  concesiones `bound`, cada una con la MAC derivada de su vmid. Y la reserva del servidor
  de ficheros (`10.43.1.10`, MAC derivada) esperando a su dueño en el ámbito de la
  oficina: `status: waiting`, que es exactamente lo que hace una reserva cuando el que la
  tiene no pregunta.
- **El router, leído por dentro** con el agente de invitado (ADR 0011): `ether1`
  10.43.0.11/24, `ether2` 10.43.1.1/24 y `ether3` 10.43.2.1/24 — las dos áreas con la
  dirección que les puso el motor, y la pata de fuera derivada del estado del nodo.

**Lo que NO se puede comprobar todavía, y se dice en claro:**

- La dirección **declarada** de cada rol no es verificable por API (lo dice el propio
  `verify`): vive dentro del invitado y la config del hipervisor no la guarda. Lo que sí
  se lee es el estado de la concesión en el router, que es de donde sale.
- El `verify` no entra en los tres puestos ni en el servidor de ficheros (no declaran
  `config:`, no hay nada que converger dentro): que tienen dirección se sabe por la
  concesión del router, no por ellos.
- No se ha probado **tráfico** entre las dos áreas ni hacia fuera desde los puestos (eso
  es `06_conectividad-exterior` y su verbo de camino, no este lab): aquí está demostrado
  que cada red recibe su dirección de su ámbito y que el router tiene las dos puertas.
- Las direcciones derivadas del puesto de control en las patas de dentro
  (`10.43.1.254` y `10.43.2.254`) **no se reservan** en el DHCP del router: quedan fuera
  del rango declarado, así que no chocan, pero un lab que declarara un rango que las
  cubriera tendría un problema -- y hoy el motor no lo avisa.

## Qué queda fuera

**No hay aplicaciones dentro de los invitados.** El vocabulario del interior llega a la
red del equipo, no a lo que corre encima: el servidor de ficheros no comparte nada
todavía, y llamarlo "de ficheros" es el papel que juega en la topología, no un servicio
declarado. Servir algo (NFS, Samba) sería una primitiva nueva, y pide ADR (regla 15).

**El almacén no tiene nada con dirección fija**, y por eso su ámbito no reserva nada. Si
el almacén necesitara su servidor, es una línea más aquí -- pero entonces conviene
preguntarse si no será otro lab.

**El router no declara puentes ni cortafuegos**, ni el Linux pasarela, rutas, DNS o
claves: son las áreas que el motor todavía no converge y están declaradas como
pendientes en `filter_plugins/interior.py`. Este lab no las finge: lo que no se puede
configurar, no se declara.

**El servidor de ficheros hereda el resolutor del nodo** que lo hospeda, porque un
contenedor lo hereda y el vocabulario todavía no sabe declarárselo (la última sección
de `docs/decisiones/0013-una-estacion-pregunta-un-servidor-dice.md`). No es un fallo de
este lab: es lo que el motor sabe hacer hoy.

**`plan` sin credenciales no puede planificar este lab.** El fixture del clúster vacío
no tiene la puerta de casa (`vmbr1` sin dirección), y un lab con `exterior` necesita
saberla para derivar la pata de fuera: `./lab --lab 07_dunder-mifflin plan` (sin
`--api`) **se para** con el motivo que ya sabe decir `estado_plan` --"el bridge de
gestión `vmbr1` no tiene dirección en este nodo: sin dirección no hay puerta por la que
salir hacia casa"--, en vez de inventarse una puerta. Se planifica con `--api`, que es
lo que lee el estado de verdad. (Los labs sin `exterior` sí se pueden planificar en
seco; el fixture del clúster vacío no tiene puerta de casa porque no la necesita.)
