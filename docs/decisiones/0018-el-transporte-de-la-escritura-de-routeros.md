# 0018 — El transporte de la escritura de un RouterOS: el mismo cálculo, en un solo guion

*Fecha: 15-nov-2026 — Estado: aceptada y aplicada — Ámbito: CÓMO se manda una escritura a un
RouterOS (el transporte), no lo que se decide*

## El problema

Convergir el interior de un RouterOS cuesta **N llamadas REST**: el driver lee las 6 áreas
declaradas (11-13 lecturas), decide el diff y luego **pide cada cambio por separado** —una
llamada por objeto, con su `POST /…/add` o `POST /…/set`— y RELEE. Medido en el lab
`07_dunder-mifflin`: una convergencia FRÍA del router son **51 llamadas (30 GET + 21 POST),
~25 s** de punta a punta por el túnel.

Cada una de esas 21 escrituras es:

- un **punto de fallo de transporte** con su propio timeout (una llamada que se pierde no
  pierde las demás, pero hay 21 formas de perder una);
- una línea del diario (bueno para trazar, caro en número);
- y, sobre todo, **una vuelta de reloj** —0,13 s medidos por llamada sobre este túnel, más
  lo que tarda el propio RouterOS en aplicar—.

La pregunta que abrió esto: *¿y si en vez de pedir los cambios uno a uno se le manda al
router, de una vez, un guion con todo lo decidido?* RouterOS ya se usa así para una cosa
(el intercambio de la dirección de gestión, ADR 0006): **un `POST /execute` con un script que
el router corre dentro**. La idea es generalizarlo.

## Las dos cosas que se confunden (y sólo una vale)

**A) Una plantilla / un `export`.** RouterOS sabe volcar su configuración entera
(`/export`, medido: 44 líneas, ~2,6 s) y sabe reimportarla (`/import`, y el `.auto.rsc` por
FTP). Tienta meter ese volcado como «plantilla del estado deseado» en cuanto el equipo es
alcanzable. **No vale, y por cuatro razones medidas:**

1. **No es la intención, es el estado.** El `/export` real de este router trae
   `add address=10.43.0.11/24 interface=ether1` —una dirección que **deriva el motor**— y
   `set [ find default-name=ether1 ] disable-running-check=no`, que el motor no gestiona.
   Volcarlo en el lab sería **colar valores derivados y de entorno dentro de la
   declaración** (rompe reglas 7 y 11).
2. **No es idempotente**: son `add` a ciegas. Reimportar sobre un equipo ya configurado
   duplica objetos (la regla 6 —«la 2ª pasada sólo lee»— muere).
3. **Se lleva por delante la propiedad de área** («lo que no se declara, se quita», regla
   17): un blob no sabe qué sobra.
4. **`show-sensitive` filtra la credencial.** La contraseña del `admin` acabaría en claro.
   Eso nunca puede estar ni en el repo ni en el diario.

Además, la doctrina del repo ya lo decía: *«Añadirlas es un driver y un ADR, **nunca una
plantilla más**»* (`interior.py`, sobre las áreas pendientes).

**B) El mismo cálculo, otro transporte.** La capa pura ya emite la lista EXACTA de
llamadas que hay que hacer (`escrituras_routeros`). En vez de mandarlas como N peticiones,
se **serializan en las líneas de consola equivalentes** y se mandan en UNA sola llamada a
`/execute`. Esto es lo que ya se hace con el intercambio de la dirección de gestión —sólo
que aplicado al resto de las escrituras—. **Es lo que se adopta.**

## La decisión

**1. La decisión no cambia; cambia el TRANSPORTE.** El diff sigue decidiendo QUÉ hay que
cambiar. Lo único nuevo es un pliegue puro: `guion_routeros(llamadas, activado)` funde cada
**tramo contiguo de escrituras SIN credencial** en UNA llamada a `POST /execute` cuyo
`cuerpo.script` es la lista de líneas de consola, **en el mismo orden**. La traducción es
mecánica y sin tabla: `/ip/dhcp-server/network/set` es la consola `/ip dhcp-server network
set`, `numbers` va posicional (a QUIÉN) y el resto `clave=valor`. Un `/execute` (el guion del
intercambio) ya era consola: se copia tal cual.

**1bis. Las escrituras CON credencial NO se funden.** La clave SSH y la contraseña del motor
se quedan como llamadas sueltas, en su sitio, síncronas — como estaban. **Esto no es una
preferencia: es una trampa MEDIDA** (ver «La trampa que destapó el A/B», abajo).

**2. Se enciende con `engine_routeros_guion` (en `vars/engine.yml`), no con un lab.** Es un
parámetro del MOTOR, no un valor de entorno: el motor no sabe de ningún lab. `false` es el
transporte viejo (una llamada por operación), que se conserva como red de seguridad y para
el A/B.

**3. La convergencia la prueba la RELECTURA, nunca el silencio.** `/execute` es ASÍNCRONA:
devuelve un job id en ~0,13 s y NO devuelve la salida del script (medido). Quien prueba que
el mundo cambió es volver a leer y volver a decidir —exactamente lo que ya hacía el driver—.
Por eso el guion hereda `tolerar_sin_respuesta` si CUALQUIERA de sus escrituras lo declaraba.

**4. El diario lleva el guion TAPADO.** El guion real lleva la contraseña DENTRO del texto
del script, y `sin_secretos` tapa por NOMBRE de campo (no por contenido). Así que la llamada
del guion trae además un `cuerpo_diario` —el mismo guion con los campos de credencial
sustituidos por `···`— y la vía de acceso (`ros_api.yml`) diariza ESE. La regla «la
contraseña no se escribe nunca» sigue en pie, ahora también para el guion.

**5. El guion va por la MISMA vía de acceso.** No se abre una puerta nueva: es un
`POST /execute` más por `tasks/ros_api.yml`, diarizado igual. `verify` sigue funcionando sin
tocar nada (su modo `solo_leer` ya prohíbe cualquier cosa que no sea GET).

## Ramificaciones (asumidas y dichas)

- **Diagnóstico más grueso.** El transporte viejo daba una línea de diario y un error por
  operación. El guion da UNA línea (con el guion dentro) y un solo resultado: si algo falla,
  se ve en la RELECTURA qué quedó pendiente, no en qué línea. Se mitiga guardando el guion
  entero en el diario (tapado): se puede reproducir a mano. Es el precio, y es menor que el
  que se paga hoy en 21 puntos de fallo.
- **Un fallo a mitad de guion aborta el resto** (RouterOS para el script en el primer
  error). El desenlace es el MISMO que con el transporte viejo —que también se para en la
  llamada que falla—: el equipo queda a medias igual, y lo caza la misma relectura.
- **El orden se conserva entero**, con dos consecuencias ya blindadas por test: el guion del
  intercambio va justo antes de la credencial, y la credencial sigue siendo la ÚLTIMA línea
  (ninguna escritura posterior depende ya de la credencial de fábrica, ADR 0006).

## Lo que esto NO cambia

- La **decisión** (`pasos_de_convergencia`), el **vocabulario** de los labs y la
  **validación**.
- La **vía de acceso** y el **diario** (una línea por llamada; ahora una llamada es un guion).
- El **guest agent**: es un canal de LECTURA (lo único que sabe leer las direcciones de una
  VM QEMU); el guion es de ESCRITURA. Son ortogonales — el guion no jubila al agente.
- Los labs, que no se tocan ni una coma.

## Cómo se comprueba

- **`test/test_routeros.py`** (sección 1bis): sin activar devuelve las llamadas TAL CUAL (y
  un `"false"` de texto no enciende el guion: se lee con un reconocedor de literales); activado
  funde cada tramo sin credencial en UNA llamada a `/execute` y BAJA el número de llamadas;
  el orden se conserva (la clave SSH y la credencial quedan sueltas, la credencial la última);
  `www` fuera; y el `cuerpo_diario` pasa el tamiz de secretos.
- **El ciclo** `destroy → apply → verify` contra el Proxmox real, que es la única prueba de
  que el guion converge de verdad (la relectura decide).

## La trampa que destapó el A/B (medida)

El primer intento fundió **TODAS** las escrituras en un solo guion, credencial incluida. El
`apply` **falló** con UNA operación pendiente: `[identity] set_identity`. La causa, leída del
diario: `/execute` es **asíncrona** (devuelve el job y sigue), así que la RELECTURA arranca
mientras el guion aún corre. En el transporte viejo, `/user set` era una llamada **síncrona**
que TERMINABA antes de releer; dentro del guion, la credencial se aplicaba ~1-2 s MÁS TARDE,
y la primera relectura —que ya usa la credencial nueva— se adelantaba y recibía un **401**
(`GET /system/identity 401 Unauthorized` en el diario). Sin leer esa área, su operación salía
«pendiente». El equipo estaba bien; el que mintió fue el juicio, por adelantarse.

Por eso el pliegue es por **tramos contiguos sin credencial**: la credencial (y la clave SSH,
que lleva el campo `key`) se quedan sueltas y síncronas, en su sitio, y el ORDEN se conserva
entero. Con eso, el `apply` converge.

### La segunda vuelta de la misma tuerca (medida en el lab `08_dunder-mifflin-con-fw`)

Separar la credencial **no basta**: hay que mandar cada tramo **con la credencial que le toca**.
Con el área `firewall` convergiendo la última (ADR 0019), hay escrituras **detrás** del cambio
de credencial, y salían con la que el driver había **negociado al empezar** —la de fábrica—,
que a esa altura ya no valía:

```
POST /user/set   {"password":"<la del motor>"}                -> 400 Session closed  (tolerado, surte efecto)
POST /execute    {las reglas del cortafuegos, en un guion}    -> 401 Unauthorized
```

El arreglo es de la capa pura: `escrituras_routeros` marca cada llamada con la credencial con
la que hay que mandarla (`credencial: motor` a partir de `set_engine_credential`),
`guion_routeros` hereda la del primer miembro del tramo, y el driver obedece esa marca en vez
de la negociada. La lección, para el que venga: **un tramo sin credencial no es lo mismo que un
tramo sin cambio de credencial**, y el orden de las áreas puede crecer por detrás de
`identity` sin reabrir esta trampa.

## Medido (A/B, mismo lab, mismo nodo, mismo día)

Lab `07_dunder-mifflin`, nodo real, dos ciclos `destroy → apply → verify` seguidos: uno con el
transporte viejo (`engine_routeros_guion: false`) y otro con el guion (`true`). Mismo lab, mismo
nodo, mismas horas, único cambio: el transporte.

| | A — viejo | B — guion |
|---|---|---|
| Escrituras al RouterOS por convergencia (`POST`) | **21** | **4** |
| Llamadas RouterOS del `apply` | 66 | 49 |
| Tiempo RouterOS del `apply` | 31,7 s | 24,2 s |
| `verify` (sólo lectura) | 15 llam. / 7,4 s | 15 llam. / 6,9 s |
| `apply` completo (reloj) | 626 s | 610 s |
| Ciclo `destroy`+`apply`+`verify` | 829 s | 754 s |
| Resultado | rc=0 | rc=0 |

Lectura honesta: en **lo que es el router**, el guion baja las escrituras 5× y el tiempo del
área ~24 %, sin perder fiabilidad. En el **ciclo entero** apenas se nota (−2,5 % en el `apply`),
porque mandar al RouterOS es una rebanada pequeña del total: el grueso es Proxmox (crear las
VMs, copiar la imagen, recargar redes, esperar arranques). El guion NO es la palanca de la
velocidad del despliegue; es una mejora de **transporte** (menos puntos de fallo, menos diario)
que además deja la puerta abierta a bajar lecturas reusando lo que el guion ya sabe.

Lo que NO cambió: el `verify` (idéntico, sólo lectura), la decisión, el vocabulario, los labs.
Y lo que se pagó: el diagnóstico es más grueso (una línea de diario por tramo, en vez de una por
operación) y hay una trampa viva que ya está escrita en un test.

## Fuera de alcance

- **Plantilla / `export` / `.rsc` / `.auto.rsc` / cloud-init**: descartado arriba. Un
  cloud-init al crear (antes del primer arranque, por la API de Proxmox) se estudió y se
  descarta: no pasa por las vías de acceso ni por el diario (rompe la regla 12), y no está
  medido que el CHR lea el NoCloud de Proxmox.
- **Inyectar la config en el disco del CHR al crearlo**: no portable (habría que escribir
  en el sistema de ficheros de MikroTik desde el hipervisor).

## La opción APARCADA (que no descartada para siempre): importar la config exportada

Lo que se investigó, en corto y medido:

- RouterOS sabe **volcar** su configuración (`/export` → un `.rsc`; medido en el CHR del lab
  07: **44 líneas, ~1.800 bytes, ~2,6 s**) y sabe **reimportarla** (`/import`, y el `.auto.rsc`
  que el equipo ejecuta solo al arrancar). El plan tentador: en cuanto el equipo es alcanzable,
  empujarle un `.rsc` con «cómo lo queremos» y dejar que él lo aplique de una vez.
- También se estudió el atajo de meterlo **al crear**, por la API de Proxmox (cloud-init /
  escribir el disco del CHR): descartado —no pasa por las vías de acceso ni por el diario
  (regla 12) y no está medido que el CHR lea el NoCloud de Proxmox—.

**Lo que COMPRARÍA** (y es mucho, en transporte): hoy una convergencia fría del RouterOS son
**30 GET + 21 POST** y ~25 s de punta a punta por el túnel (medido, §El problema). Un `.rsc` es
**1 o 2 llamadas** y el trabajo pesado lo hace el router dentro. Es, con diferencia, el mayor
ahorro de llamadas que se ha puesto sobre la mesa — más que el guion del ADR.

**Lo que COSTARÍA, y por lo que se aparca** (cada punto, medido o derivado de las reglas):

1. **Es asíncrona y TODO-O-NADA: se pierde la auditabilidad.** `/import` corre como un trabajo
   que no devuelve el resultado **operación a operación**. Hoy el diario deja **una línea por
   escritura**, con su `status`; con un import queda **una línea para todo el fichero** y, si
   algo falla a mitad, el equipo se queda a medias **sin decir en qué línea**. Es exactamente
   la clase de fallo silencioso que este repo persigue (regla 6, y el «no mentir» del diario).
2. **No es idempotente**: son `add` a ciegas. Reimportar sobre un equipo ya configurado
   **duplica objetos** → la 2ª pasada deja de «sólo leer» (regla 6 muere).
3. **No tiene propiedad de área** («lo que no se declara, se quita», regla 17): un blob no sabe
   qué sobra, así que no puede converger, sólo **añadir**.
4. **Cuela estado derivado y de entorno.** El `/export` real trae la dirección de gestión que
   **deriva el motor** (`add address=10.43.0.11/24 interface=ether1`) y MACs de ESE despliegue.
   En un equipo **nuevo** serían direcciones equivocadas: rompe las reglas 7 y 11 y los ADR
   0012/0013 (que compran justo que la salida y la identidad no las declare un humano).
5. **Filtra la credencial** (`show-sensitive`): la contraseña del `admin` acabaría en el blob,
   y eso no puede estar ni en el repo ni en el diario.

**Veredicto: aparcada, no enterrada.** Sería **implementable en un futuro** el día que se acepte
un **camino rápido con un modelo de garantías distinto** — y hay un sitio donde encajaría bien:
un tramo **estático, sin estado derivado y sin credenciales**, como las reglas de un firewall
(que es lo que el nuevo lab `dunder-mifflin-con-fw` trae, ver ADR del área `firewall`). Para
retomarla harían falta tres condiciones, ninguna negociable:

- **que el import deje rastro en el diario** (el `.rsc` enviado, guardado y tapado) — sin eso no
  hay auditoría posible;
- **que la relectura siga siendo el juez** (el import no se cree: se relee y se decide), y
- **que el tramo importado no lleve credenciales ni direcciones derivadas** — sólo lo que el
  motor podría declarar sin inventarse nada.

Mientras esas tres no se cumplan, el **guion** (§La decisión) captura ya la mayor parte del
ahorro **sin** perder la línea-a-línea del diario. Por eso se eligió el guion y no el import.

## VER

`deployment_engine/filter_plugins/interior.py` (`guion_routeros`, `_linea_de_llamada`);
`deployment_engine/vars/engine.yml` (`engine_routeros_guion`);
`deployment_engine/tasks/configurar_routeros.yml`; `deployment_engine/tasks/ros_api.yml`;
`test/test_routeros.py`; `docs/decisiones/0006-escribir-en-routeros.md`.
