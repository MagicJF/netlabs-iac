# lab-red-routeros

El lab de aceptación de la capa de configuración: **dos routers RouterOS (CHR)
encadenados y un puesto de control**, con servidores y puestos como contenedores.
Es el lab que hace medir de verdad lo que el encargo de la fase 2 promete: que el
motor **entra** en cada equipo, lo **converge** y sabe **quitar lo que sobra**, sin
que nadie más toque el hipervisor ni la red del lab.

<!-- generado:inicio -->
_Datos derivados de `lab-red-routeros.yml`. Los reescribe `./lab check docs --actualizar`;
si los editas a mano, `./lab check docs` falla._

## Invitados declarados

| rol | tipo | escalón | cores | memoria (MB) | disco (GB) | bridge | dirección |
| --- | --- | --- | --- | --- | --- | --- | --- |
| borde | VM (qemu) | 1 | 2 | 512 | 1 | vmb_gestion | 10.40.0.11/24 |
| control | LXC | 1 | 1 | 512 | 4 | vmb_gestion | 10.40.0.10/24 |
| nucleo | VM (qemu) | 2 | 1 | 512 | 1 | vmb_lan1 | 10.40.1.11/24 |
| servidor | LXC | 2 | 1 | 512 | 4 | vmb_lan1 | dhcp |
| puesto-1 | LXC | 3 | 1 | 512 | 4 | vmb_lan1 | dhcp |
| puesto-2 | LXC | 3 | 1 | 512 | 4 | vmb_lan2 | dhcp |

## Bridges del lab

| bridge | dirección del bridge |
| --- | --- |
| vmb_gestion | 10.40.0.1/24 |
| vmb_lan1 | 10.40.1.1/24 |
| vmb_lan2 | 10.40.2.1/24 |

## Orden de arranque (escalones)

| escalón | roles |
| --- | --- |
| 1 | borde, control |
| 2 | nucleo, servidor |
| 3 | puesto-1, puesto-2 |

## Identidad: la deriva el motor, no la declara el lab

| rol | tipo | nombre canónico | vmid | MAC |
| --- | --- | --- | --- | --- |
| borde | VM (qemu) | lab-red-routeros-borde | — | — |
| control | LXC | lab-red-routeros-control | — | — |
| nucleo | VM (qemu) | lab-red-routeros-nucleo | — | — |
| servidor | LXC | lab-red-routeros-servidor | — | — |
| puesto-1 | LXC | lab-red-routeros-puesto-1 | — | — |
| puesto-2 | LXC | lab-red-routeros-puesto-2 | — | — |

El **vmid** (el menor libre de *todo* el clúster) y la **MAC** (`BC:24:11` + los
bytes del vmid) los asigna `apply` leyendo el estado de Proxmox: no se declaran aquí y
no se guardan en ningún fichero del repositorio. Por eso estas dos columnas son un
guion hasta que exista un despliegue real.
<!-- generado:fin -->

## Por qué así

### El arranque en frío, en orden (y por qué el orden es el diseño)

El problema que este lab resuelve de verdad no es «configurar un router»: es **cómo
se le da una dirección al primer equipo**, cuando todavía no hay nadie dentro que
pueda configurar nada. La cadena, tal como queda:

1. **El puesto de control nace completo**: una pata en el bridge de gestión del nodo
   (por donde sale hacia casa) y una por cada bridge del lab -- la declaración tiene
   `vmb_gestion`, `vmb_lan1` y `vmb_lan2`, así que nace con cuatro patas. **Nace**
   con todas, no se le añaden después: cambiarle las patas a un invitado en marcha
   obliga a reiniciarlo, y aquí no se reinicia la máquina que está trabajando.
2. **El motor le deja su clave al crearlo** (`ssh-public-keys` en la API de creación
   de un LXC: Proxmox la escribe en el rootfs, sin `snippets` ni cloud-init).
3. **El motor entra UNA vez por su consola** y le manda UNA línea (en base64) que
   levanta el túnel hacia el nodo de control. A partir de ahí el puesto de control es
   el bastión del lab: Ansible llega a todo lo que cuelgue de sus bridges.
4. **El puesto de control configura su servidor DHCP** y reserva, por la **MAC
   derivada del vmid** de cada CHR, la dirección que ese CHR declara. Nadie escribe
   una MAC en ningún sitio.
5. **El primer CHR** (escalón 1) arranca sin dirección y la pide por DHCP. Es
   **tolerante**: pide sin parar hasta que le contestan, así que puede compartir
   escalón con el puesto de control.
6. **El motor ya lo alcanza** en su dirección declarada y hace la primera
   convergencia: identidad, servicios, direcciones y su propio servidor DHCP.
7. **El segundo escalón** (el otro CHR y el servidor) cuelga del primero, y su
   dirección está reservada por él. Aquí se ve el encadenamiento: el que da la
   dirección ya está convergido antes de que el otro arranque.
8. **Los puestos**, en el tercer escalón, con `direccion: dhcp`: no arrancan hasta
   que su CHR está sirviendo.

Nada de esto depende de que un humano lance las cosas en el orden correcto: el orden
está en los `escalones` de la declaración, y el plan lo respeta (regla 18).

### Lo que se aprendió ejecutando

<!-- Esta sección es para lo MEDIDO, no para lo previsto. Lo que no se haya medido
     de verdad contra el VPS no se escribe aquí: se dice que falta. -->

- **El bug de la supernet, cazado por este lab.** El validador daba por buena la
  supernet con una comparación de prefijo mal hecha: decía que `10.40.0.1/24` **no**
  caía dentro de `10.40.0.0/16`. Ningún lab anterior declaraba supernet --los tres de
  la fase 1 no tienen interior-- así que la comprobación no se había ejercitado
  nunca. Lo cazó este lab, y ahora tiene sus casos en `test/test_declaracion.py`.
- **Las áreas que el motor todavía no converge se rechazan, no se ignoran.** El
  encargo nombra `puentes` y `cortafuegos` (RouterOS) y `pasarela`, `rutas`, `dns` y
  `claves` (Linux) como áreas del vocabulario; el motor aún no las sabe converger, así
  que están declaradas como **pendientes** y la validación las rechaza con su motivo.
  Este lab no las declara: aquí no se finge una configuración que no se aplica.
- **El motor entra de verdad en el invitado, y se ve en el diario.** El 14-nov-2026, con
  el puesto de control recreado, las cuatro lecturas del driver salen `rc=0` en
  `logs/interior.jsonl` (`camino=active`, `direccion=10.40.0.10/24`, `reenvio=1`). Antes
  de recrearlo salían `rc=255`: la clave que el invitado tenía dentro era la genérica
  vieja. La lección es la clave **por lab** y **para los dos sentidos** (entrar y salir),
  porque un invitado creado con otra clave da `Permission denied` y el motor no lo puede
  adivinar: lo dice y para.
- **La imagen base no trae servidor DHCP ni `ethtool`, y `ip link` no los sustituye.**
  Medido dentro del invitado: sin `dnsmasq` ni `ethtool` en `/usr/sbin`, y
  `ip link set dev eth0 tx off / gso off / tso off` rechazado por iproute2. El motor los
  instala **en su aparato** (el puesto de control) y escribe la configuración con la
  reserva derivada del vmid: quedó medido dentro, `dhcp-host=BC:24:11:00:00:6C,10.40.0.11`
  (el CHR `borde` es el vmid 108), `dnsmasq` escuchando en `eth0:67` y los tres offloads
  en `off`.
- **La segunda pasada del interior no escribe NADA.** El 14-nov-2026, `apply` dos veces
  seguidas: la segunda dejó en el diario del interior **cuatro lecturas y cero
  escrituras**. Es la prueba de la idempotencia que la regla 6 pide, hecha sobre el
  invitado de verdad y no sobre el plan. Costó encontrarla: el motor pedía reescribir el
  fichero del DHCP y recargar el servicio en cada pasada porque no leía el estado del
  servicio ni normalizaba el rango declarado contra el que escribe dnsmasq (ver ADR 0005).
- **Lo que falta, dicho en voz alta.** Este lab no llega todavía al final del camino: el
  `apply` para a propósito en el **primer escalón de RouterOS** («el rol 'borde' es un
  interior de tipo routeros y el plan no ha leído dentro»), porque su driver (su REST y su
  imagen de fábrica) no está implementado; y la **sonda** que comprueba que un escalón
  sirve antes de tocar el siguiente tampoco. Los escalones 2 y 3 quedan **parados** en el
  hipervisor, que es exactamente la barrera que el lab quiere demostrar: no se arranca lo
  siguiente hasta que lo anterior esté convergido y sirviendo.
