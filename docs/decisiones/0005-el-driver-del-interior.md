# ADR 0005 — El driver del interior: leer, decidir, escribir y releer

<!-- PROPÓSITO: dejar escritas las decisiones del DRIVER que configura el interior de un
     invitado Linux: qué forma tiene (cuatro tiempos, y el último es releer), dónde vive
     la decisión (funciones puras, no plantillas), cómo se distingue «no llegué» de «eso
     no está», con qué clave se entra, y qué se hace cuando la imagen base no trae lo que
     el área declarada necesita.
     INVARIANTES: el interior se toca SÓLO por la vía de acceso (`interior_ssh.yml`, que diariza
     en `logs/interior.jsonl`); la decisión es una función pura de (declarado, leído); un
     invitado al día produce CERO escrituras (regla 6); lo que no se puede leer PARa, no
     se adivina (regla 16); el vocabulario del lab no gana ni un paquete (regla 15).
     LÍMITES: este ADR cubre el driver de Linux. RouterOS (su REST, su imagen de fábrica)
     va aparte y no está implementado. Lo que aquí no está probado, se dice abajo.
     VER: deployment_engine/tasks/{interior_ssh,inventario_invitados,configurar_linux}.yml,
     deployment_engine/filter_plugins/interior.py, test/test_interior.py,
     labs/04_lab-red-routeros/04_lab-red-routeros.md -->

**Estado:** aceptada (implementada y probada de punta a punta contra el Proxmox real; el
driver de RouterOS, en construcción).

**Contexto.** La fase 2 hace que el motor **entre** en cada invitado. Un invitado Linux de
un lab es un contenedor que sirve de servidor o de puesto: lleva dirección, reenvío y —si
es el bastión— el servidor DHCP de la red a la que está colgado. Eso hay que
ponerlo, comprobarlo **leyéndolo desde dentro** y saber **quitar lo que sobra**.

El motor de la fase 1 tiene una regla que manda sobre cómo se escribe todo esto: la
decisión de qué hacer es una **función pura** de (declaración, estado del mundo), y el
verbo ejecuta *ese mismo* plan. Un driver que decidiera dentro de un playbook (con un
`when` que compara la salida de un comando) tendría su lógica repartida en Jinja, sin
pruebas y sin poder planificarse sin credenciales. Así que el driver se parte en dos:

1. **La decisión** — `filter_plugins/interior.py`, funciones puras: *(declaración, lo
   leído) → operaciones*. Se prueba con `test/test_interior.py`, sin red y sin Proxmox.
2. **La ejecución** — `tasks/configurar_linux.yml` + `tasks/interior_ssh.yml`: pide, escribe
   y comprueba. No decide nada.

## Decisión 1 — La forma: leer, decidir, escribir, RELEER

El driver siempre hace los mismos cuatro tiempos, y el cuarto es el que no se puede saltar:

```
leer dentro  ->  decidir (los DOS sentidos)  ->  escribir lo que falta  ->  RELEER y comprobar
```

El cuarto tiempo es el que hace verdad la promesa: al final **se vuelve a leer lo mismo** y
se decide otra vez. Si queda alguna operación por hacer, el paso FALLA con su nombre. «El
comando no dio error» no es convergencia; «el estado real coincide con lo declarado» sí.
Sin este tiempo, un `apt-get` que no llegó a instalar dejaría un invitado a medias con el
motor diciendo que está listo.

## Decisión 2 — «No llegué» no es «eso no está»

La vía de acceso deja en el diario el código de salida de cada comando. El driver lo lee así:

| `rc` del comando | Qué significa | Qué hace el motor |
| --- | --- | --- |
| `0` | contestó | se compara con lo declarado |
| `1` (o cualquier otro normal) | **contesta que eso no está** | es un estado: se escribe lo que falte |
| `255` | `ssh` no consiguió entrar | **PARA**: no se sigue a ciegas (regla 16) |

Confundir los dos últimos es el error que convierte un motor en una máquina de escribir a
ciegas: con un `255` tratado como «no está», el driver intentaría poner una dirección en un
invitado al que no llega — y probablemente diría que lo ha hecho. El 255 se distingue en
`leido_de_lecturas()` (función pura, probada), no en el playbook.

## Decisión 3 — Una clave por lab, para los DOS sentidos

La clave del túnel (`~/.ssh/netlabs_tunnel_<lab>_ed25519`) es la misma en los dos sentidos:
el motor la inyecta en el invitado al crearlo (`ssh-public-keys`, para poder ENTRAR) y el
invitado la usa para salir hacia casa (su línea de `authorized_keys` con `permitlisten`,
que sólo restringe lo que esa clave puede hacer **en el nodo de control**).

No es una clave compartida por todos los labs porque OpenSSH, en `authorized_keys`, usa la
**primera** línea cuya clave casa: con una clave común y una línea por lab, el segundo lab
se queda mudo. Medido en la fase del túnel (§5 del encargo).

Y no se entra en el invitado con el usuario del túnel: el usuario del túnel es el de la
máquina donde corre el motor (`túnel_usuario`), mientras que dentro del invitado se entra
como `root` (`engine_usuario_invitado`). Confundirlos da
`root@127.0.0.1: Permission denied (publickey,password)` — que es exactamente lo que pasó.

## Decisión 4 — El aparato lo pone el motor, el vocabulario no crece

El área `dhcp_server` de un Linux necesita un servidor DHCP dentro. **Medido** el
14-nov-2026 en el contenedor del bastión (Debian 13):

| lo que se midió | resultado |
| --- | --- |
| `dnsmasq` y `ethtool` en la imagen base | **no están** (`/usr/sbin` sin ningún servidor DHCP) |
| `ip link set dev X tx off / gso off / tso off` | **rechazado** por iproute2 (`Invalid txqueuelen value`) |
| `systemd-networkd` | presente pero **deshabilitado**, sin `/etc/systemd/network` |
| `apt-get` + salida a internet desde el invitado | **funciona** (`deb.debian.org` resuelve) |

Así que el motor **pone en su aparato** lo que el área necesita: `apt-get install -y
dnsmasq ethtool` en el **bastión**, que es del motor, no un equipo del lab. El
vocabulario del lab sigue sin tener paquetes (regla 15): el lab declara *que hay un
servidor DHCP y en qué rango*, no con qué software.

El porqué de `ethtool`: sin apagar los offloads de la interfaz que envía, las ofertas DHCP
salen con el checksum UDP sin resolver y el kernel del CHR las tira (medido en v3; en esta
fase se vuelve a medir). Y `port=0` en dnsmasq a propósito: ahí se sirve DHCP, no DNS — el
DNS de la red lo declara el router que la sirve (`red.dns`), y montar un DNS aquí sería una
primitiva que nadie ha declarado.

## Decisión 5 — La idempotencia se pierde en los detalles, y hay que probarla

Cinco trampas encontradas al encender el driver, todas del mismo tipo: **el motor pedía
escribir algo que ya estaba bien escrito**, lo que rompe la regla 6 en silencio (la segunda
pasada no da `changed=0`). Cada una tiene su prueba en `test/test_interior.py`:

| trampa | por qué pasaba |
| --- | --- |
| el rango del `dhcp-range` | dnsmasq lo guarda `inicio,fin,mascara,tiempo` y la declaración dice `inicio-fin`: sin normalizar, el fichero se reescribía siempre |
| el prefijo de la reserva | la reserva derivada lleva `/24` y dnsmasq guarda la dirección pelada: se compara por dirección |
| el servicio | sin leer si `dnsmasq` está **vivo**, `recargar` se pedía en cada pasada |
| el marcador de escritura | buscar `dnsmasq.conf` no encuentra `/etc/dnsmasq.d/netlabs.conf`: la ruta se declara una vez (`RUTA_DNSMASQ`) y se usa entera |
| el orden de las operaciones | instalar antes de usar: sin `dnsmasq` no hay servidor y sin `ethtool` no se apagan los offloads |

La prueba que las caza a todas es una sola: **un invitado al día produce CERO operaciones**.
Cualquier campo que el analizador no sepa leer hace que su área «no coincida» y el motor
escriba; por eso la prueba compara la lista de operaciones con `[]` y no con «algo parecido».

## Decisión 6 — Lo que el driver no sabe hacer, lo dice (no lo ignora)

El plan puede pedir una operación que el driver todavía no traduce (hoy:
`mandar_linea_consola`, que quiere decir «el túnel no está en pie» — eso lo pone la vía de acceso
del túnel por la consola del hipervisor, no el interior). El driver **para antes de
escribir** con el nombre de la operación en la mano. Una operación sin traducir que se cae de
la lista es la forma más silenciosa de mentir: el motor diría «convergido» habiendo ignorado
algo.

## Consecuencias

- El interior de un Linux se converge **por áreas declaradas**: fuera de lo declarado, el
  motor no opina ni pregunta (regla 17).
- El diario del interior (`logs/interior.jsonl`) tiene una línea por paso, con el `rc` y lo
  leído: se puede reconstruir qué se preguntó, qué se escribió y qué contestó el invitado.
- Añadir un tipo de invitado es añadir un driver (`tasks/configurar_<tipo>.yml`) y declararlo
  en `DRIVERS` (`interior.py`): `test/test_interior.py` comprueba que la lista y los ficheros
  cuadran, y `apply` avisa de lo que aún no sabe hacer sin mentir.
- El driver de RouterOS (su REST, su imagen de fábrica) sigue pendiente, y se dirá igual:
  qué se intentó, qué se midió y qué falta.
