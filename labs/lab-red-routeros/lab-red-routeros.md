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
