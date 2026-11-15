# ADR 0006 — Escribir en RouterOS: la forma, las trampas y el orden

<!-- PROPÓSITO: dejar escritas las tres cosas que costaron una tarde de medida al
     conectar el driver de RouterOS con un CHR real: (1) con qué forma se ESCRIBE por
     REST, (2) las dos trampas del transporte que no dan un error sino un timeout, y
     (3) por qué el orden de las áreas lo manda el motor y no el lab.
     INVARIANTES: toda escritura va por `ros_api.yml` (la única puerta a RouterOS, con
     diario `api: routeros` en `logs/api.jsonl`); en una lectura no se declara el formato
     del cuerpo; la dirección de gestión de un equipo cuyo cliente de fábrica aún la tiene
     la pone el propio router, con un guion que se le manda ENTERO (`POST /execute`),
     porque a pasos desde fuera el equipo se queda sin dirección (§5); no se toca
     `www` nunca; el orden de las áreas vive en `AREAS` (`interior.py`) y no en la
     declaración.
     LÍMITES: esto es RouterOS 7.25.1 sobre un CHR en QEMU. Nada de lo de aquí se puede
     afirmar de otra versión ni de hardware MikroTik sin volver a medirlo. La API de
     Proxmox no se toca en este ADR.
     VER: deployment_engine/tasks/ros_api.yml, tasks/configurar_routeros.yml,
     filter_plugins/interior.py (AREAS), test/test_routeros.py,
     labs/lab-red-routeros/logs/api.jsonl -->

**Estado:** aceptada; medida contra un CHR real (RouterOS 7.25.1, QEMU en el Proxmox del
VPS). La pregunta abierta que queda se dice al final.

**Contexto.** El lab `lab-red-routeros` tiene un CHR de MikroTik (`borde`) al que el motor
tiene que configurar por REST: identidad, servicios, cliente DHCP de fábrica, direcciones,
rutas y el servidor DHCP de la LAN. RouterOS **no tiene SSH por API** y su REST no se puede
llamar desde el nodo de control (no hay ruta al otro lado del router): la puerta
`deployment_engine/tasks/ros_api.yml` llama **en la máquina del motor** y el **puesto de
control le hace de camino**, reenviando el puerto 80 de cada router por el túnel del camino
(ADR 0010; la primera versión le **delegaba** la llamada, y costaba 4,4 s por petición). Cada
llamada queda diarizada en `logs/api.jsonl` con `api: routeros`. Lo que sigue se aprendió
llamando de verdad a ese CHR.

## 1. Cómo se escribe (y cómo no)

RouterOS expone su CLI por REST: cualquier comando se puede enviar como `POST` a la ruta
de la tabla. Medido en el CHR:

| Forma | Resultado medido |
| --- | --- |
| `POST /rest/ip/service/set` con `{"numbers": "<id>", "disabled": "yes"}` | **200** (×4: api, api-ssl, ftp, telnet) |
| `POST /rest/ip/dhcp-client/set` con `{"numbers": "*1", "disabled": "yes"}` | sin respuesta: la conexión murió (ver §3) |
| `PUT` a la ruta de una tabla | `400` «no such command» |

Es decir: **se escribe con `POST /rest/<tabla>/set` y el `.id` leído**, no con `PUT` sobre
la ruta. El `.id` que se manda es el que devolvió la lectura (`*1`, `*3`…): no se inventa ni
se deduce del orden.

## 2. Trampa: un GET con formato de cuerpo deja al CHR mudo

`ansible.builtin.uri` con `body_format: json` y el cuerpo omitido —que es exactamente lo
que hace una lectura— **no recibe respuesta**: la llamada muere por timeout a los 30 s,
igual que si el equipo no estuviera encendido. Bisecado en tres variantes contra el mismo
CHR y la misma ruta:

| Variante | Resultado |
| --- | --- |
| A · lo mínimo (`uri` a `/rest/system/identity`, con credenciales) | **200** (14 bytes) |
| B · A + `status_code` explícito | **200** |
| C · B + `body_format: json` y `body: omit` | **-1**, «Connection failure: timed out» |

Regla que sale de aquí: **el formato del cuerpo sólo se declara al escribir**. En
`ros_api.yml` es una expresión, no una constante:

```yaml
body: "{{ ros_cuerpo | default(omit) }}"
body_format: "{{ 'json' if (ros_metodo | upper in ['POST', 'PUT']) else omit }}"
```

Y el diario lo prueba: las lecturas del ciclo real son `GET` con 200; las escrituras,
`POST` con 200.

## 3. Trampa: apagar el cliente DHCP de fábrica se lleva la dirección (y el camino)

`borde` no tiene dirección propia: la recibe del cliente DHCP de fábrica que trae RouterOS,
y el puesto de control la tiene reservada por la MAC derivada del vmid. Al deshabilitar ese
cliente, RouterOS **se lleva la dirección que ese cliente instaló** —y con ella el REST—.
No da un error: da un timeout, porque la escritura llega, el equipo se queda sin dirección y
la conexión se muere antes de responder.

Lo que quedó en el diario de esa ejecución (no es interpretación, es la línea):

```
POST /ip/service/set        -> 200    4752 ms   deshabilitar el servicio 'api'
POST /ip/service/set        -> 200    4730 ms   deshabilitar el servicio 'api-ssl'
POST /ip/service/set        -> 200    4662 ms   deshabilitar el servicio 'ftp'
POST /ip/service/set        -> 200    4637 ms   deshabilitar el servicio 'telnet'
POST /ip/dhcp-client/set    ->  -1   34685 ms   deshabilitar el cliente DHCP de fábrica de ether1
```

Y desde el puesto de control: `ping KO` y `10.40.0.11 dev eth0 INCOMPLETE`. El equipo se
quedó sin dirección hasta rehacer el lab. De paso: **RouterOS tarda ~4,7 s por escritura**,
dato que hay que tener en cuenta al dimensionar los timeouts del motor.

**Decisión.** El orden de las áreas lo manda `AREAS` en
`deployment_engine/filter_plugins/interior.py`, no el orden en que el lab las escriba:

```python
"routeros": ("identidad", "direcciones", "servicios", "cliente_dhcp", "rutas", "dhcp"),
```

Lo que la medida corrigió es **quién da el orden dentro de `direcciones`**: la dirección de
gestión no se puede escribir mientras el cliente de fábrica la tenga, y apagarlo desde fuera
se lleva el camino antes de que nadie pueda escribir nada más. Por eso ese intercambio no se
da a pasos desde fuera: lo ejecuta el router, entero y de una vez, en un guion (§5). No se
dedujo: se midió (el intento «natural» se comió un `400 already have such address`, y el
intento «a pasos» se comió una llamada sin respuesta).

Lo que sí vale sin matices es la razón de que el orden lo mande el motor y no el lab:
cualquier fallo posterior deja al invitado alcanzable; al revés, el primer fallo deja al
motor fuera y sin forma de volver. Lo blinda `test/test_routeros.py`, que compara la lista
de operaciones completa y —en el caso del choque de direcciones— la lista de llamadas con su
orden, con el guion en su sitio y sin que ninguna de las escrituras que van dentro de él se
mande además por fuera.

La `identidad` sigue yendo la última en la primera convergencia (intercambio atómico):
primero se pone y se verifica lo nuevo, y sólo entonces se cambia el nombre y la credencial
del equipo, para no quedarse fuera con las credenciales viejas.

## 4. Lo que NO se hizo por SSH

Nada. Todo el camino se hizo por el REST del equipo, con la puerta diarizando cada llamada
(entonces la puerta le **delegaba** la llamada al puesto de control; hoy la hace el motor, con
el puesto de camino: ADR 0010).
Los dos diagnósticos que no se pudieron hacer por REST (ver la pantalla del CHR y recuperar
un equipo que se quedó sin dirección) se hicieron por la vía de depuración del `AGENTS.md`
—consola del hipervisor y reinicio por API— y se dice en el reporte, sin maquillar. El
motor no entró por SSH en ningún momento.

## 5. La dirección duplicada: el intercambio lo hace el ROUTER, entero y de una vez

Medido en el primer ciclo real (CHR recién creado, cliente de fábrica vivo con
`10.40.0.11/24` dinámica, el lab declarando la MISMA dirección como estática):

```
POST /ip/address/add  {"address":"10.40.0.11/24","interface":"ether1"}
  -> 400  Bad Request  failure: already have such address
```

Así que el orden `direcciones` → `cliente_dhcp` **no basta por sí solo**: la dirección de
gestión no se puede escribir mientras el cliente de fábrica la tenga, y el cliente no se
puede apagar antes porque se lleva la dirección (y con ella el REST, §3). Es un círculo.

**Decisión: el intercambio no se da a pasos desde fuera --se le manda al router ENTERO y de
una vez, como un guion (`POST /execute`)--.** Una sola llamada cuyo cuerpo es lo que el
equipo ejecuta DENTRO, sin que nadie tenga que acertar el momento entre paso y paso:

```
/ip dhcp-client remove [find interface=ether1];
/ip address add address=10.40.0.11/24 interface=ether1
```

Lo que se ejecuta, en su orden:

| # | Llamada REST | Por dónde se habla | Qué garantiza |
| --- | --- | --- | --- |
| 1 | …todo lo demás (la otra pata, servicios, rutas, DHCP, y el nombre y la clave del equipo)… | la declarada (la dinámica contesta: es la misma dirección) | se aprovecha que el camino existe |
| 2 | `POST /execute` con el guion: quitar el cliente + poner la estática | la declarada, **sin exigir respuesta** | el equipo no se queda sin dirección a medias: las dos cosas pasan dentro, o ninguna |
| 3 | `POST /user/set` (la credencial del motor) | la declarada | lo último que se toca es la credencial (§6) |

- **Por qué NO a pasos desde fuera** (que es lo que había antes): cada paso intermedio deja
  al equipo en un estado que sólo sirve si el siguiente llega. Se probó con una dirección
  prestada —cuatro llamadas, una de ellas muriendo por construcción— y la medida del segundo
  escalón fue un `POST /ip/address/add` **sin respuesta** (`status: -1`, 34,6 s) con el MISMO
  cuerpo que en el primer CHR contesta 200. Con el guion, ese corte ya no deja el trabajo a
  medias: o el equipo lo ejecutó —y lo dice la relectura— o no lo ejecutó, y entonces la
  operación sigue pendiente y el paso falla con su razón.
- **«Sin exigir respuesta» se declara, no se esconde**: la capa pura marca esa llamada
  (`tolerar_sin_respuesta`) y el driver la traduce a `ros_tolerar_error` sólo en ella. No es
  seguir a ciegas: quien prueba la convergencia es la **relectura** del final.
- **Un respiro dentro, si hay residuo**: cuando el cliente ya no está y su entrada dinámica
  sigue puesta, el guion la suelta (`[find address=… dynamic=yes]`), espera `:delay 2s` y
  pone la estática. Ese respiro no abre ninguna ventana hacia fuera: corre dentro.
- **Lo que a RouterOS NO se le puede pedir dentro del guion**, y por eso no se le pide:
  borrar la RUTA dinámica heredada del cliente (`cannot modify dynamic route created by a
  different owner`, medido; intentarlo deja al equipo sin dirección). Eso lo purga el
  reinicio del residuo, que es un paso aparte del plan.
- **El baile es sólo de la boca de gestión**: la otra pata (`ether2`) se escribe como
  siempre, por la dirección declarada. Y `www` no se toca: es el REST, o sea el camino de
  vuelta.
- **Las dos listas no se suman**: el guion SUSTITUYE a las llamadas de fuera, no se añade a
  ellas. Es trampa ya pagada —en v3 el guion emitía su `add` y la lista normal el suyo: dos
  veces la misma escritura— y aquí la blinda `test_routeros`: la estática de gestión no puede
  salir también por fuera.

### Procedencia

El camino del guion no se inventó aquí: el experimento anterior (`ansible-netlabs-v3`) ya lo
había medido y escrito —`POST /execute` con un guion, «the swap goes LAST and inside ONE
script», y el `:delay` entre quitar y poner—. Se cita como procedencia del CONOCIMIENTO, que
es lo aprovechable; no se copió ni código ni estructura (lo prohíbe el `AGENTS.md`): el guion
lo decide la capa pura de este motor (`_intercambio_de_la_gestion`), lo traduce su puerta
(`ros_api.yml`, con diario) y lo prueba su suite.

Lo que queda demostrado por el diario de ese ciclo: las **11 lecturas** de las seis áreas
declaradas vuelven 200 (identidad, usuarios, claves, direcciones, servicios, cliente DHCP,
rutas, servidores DHCP, rangos, redes y concesiones), y la elección de credencial funciona
(401 con la del motor, 200 con la de fábrica, y el motor elige con cuál converger).

## 6. La credencial se cambia AL FINAL (medido, y costó un paso parado)

El área `identidad` escribe tres cosas: el nombre del equipo, la clave pública del motor y
la credencial del motor (la contraseña de su usuario). El orden NO es indiferente, y el
primero que probó el motor estaba mal:

```
17:18:34  POST /system/identity/set   {"name": "rt-borde"}             -> 200
17:18:39  POST /user/set              {"numbers":"admin","password"}   -> 200
17:18:44  POST /user/ssh-keys/add     {"user":"admin","key":"<clave del motor>"} -> 401
```

Al cambiar la contraseña, la de fábrica (con la que el driver estaba hablando) deja de valer
**en el acto**, y la escritura siguiente se queda sin credencial. El equipo acaba a medias
--nombre puesto, contraseña cambiada, clave sin llegar-- y el verbo se para con el 401.

**Decisión: `nombre` -> `clave` -> `credencial`.** La clave se importa mientras la credencial
vieja aún vale, y la contraseña es la ÚLTIMA escritura de todo el interior: así ninguna
escritura posterior depende de una credencial que acaba de dejar de existir. Lo que deja al
motor dentro es la CLAVE; la contraseña se cambia como última medida de higiene, cuando ya
no hace falta la de fábrica para nada.

Y esa última escritura **se queda sin respuesta a propósito**: cambiar la contraseña del
usuario con el que se está hablando cierra la sesión, y RouterOS contesta

```
POST /user/set  {"numbers":"admin","password":"<la del motor>"}
    -> 400 Bad Request Session closed
```

aunque el cambio haya surtido efecto (medido). Es un corte por diseño, de la misma familia
que apagar el cliente DHCP, así que la operación lleva `tolerar_sin_respuesta` y el verbo no
se para: **la convergencia la dice la REELECTURA**, que ya entra con la credencial nueva.

Lo blinda `test/test_routeros.py`: compara la lista de operaciones entera, exige que la
última sea `poner_credencial_motor`, y que esa operación --y su llamada-- toleren el corte.
