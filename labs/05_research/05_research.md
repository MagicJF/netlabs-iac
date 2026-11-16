<!-- PROPÓSITO:   el documento del lab. Dos regiones, dos escritores.
     INVARIANTES: la región generada (entre los marcadores) la reescribe
                  `./lab check docs --actualizar`; `./lab check docs` falla si el
                  fichero difiere de su render. La prosa de fuera NO la toca
                  ningún check: escribe lo que el YAML no puede decir.
     LÍMITES:     la prosa no repite valores que ya están en la tabla; los cita.
     VER:         AGENTS.md §Documentación; README.md §Documentación -->

# research

El lab de investigación: un laboratorio MÍNIMO --un bastión y una VM-- para
medir cosas del motor y del nodo sin tocar el lab de aceptación. Nace con una pregunta
concreta y la responde aquí abajo: ¿se le puede poner el agente de invitado (QEMU guest
agent) de Proxmox a una VM CHR de RouterOS, y sirve de algo?

<!-- generado:inicio -->
_Datos derivados de `05_research.yml`. Los reescribe `./lab check docs --actualizar`;
si los editas a mano, `./lab check docs` falla._

## Invitados declarados

| rol | tipo | stage | cores | memory (MB) | disk (GB) | bridge | address |
| --- | --- | --- | --- | --- | --- | --- | --- |
| chr-agente | VM (qemu) | 1 | 1 | 512 | 1 | vmb_research | 10.41.0.11/24 |
| control | LXC | 1 | 1 | 512 | 4 | vmb_research | 10.41.0.10/24 |

## Bridges del lab

| bridge | dirección del bridge |
| --- | --- |
| vmb_research | 10.41.0.1/24 |

## Orden de arranque (etapas)

| stage | roles |
| --- | --- |
| 1 | chr-agente, control |

## Identidad: la deriva el motor, no la declara el lab

| rol | tipo | nombre canónico | vmid | MAC |
| --- | --- | --- | --- | --- |
| chr-agente | VM (qemu) | {equipo}-{alias} | — | — |
| control | LXC | {equipo}-{alias} | — | — |

El **vmid** (el menor libre de *todo* el clúster) y la **MAC** (`BC:24:11` + los
bytes del vmid) los asigna `apply` leyendo el estado de Proxmox: no se declaran aquí y
no se guardan en ningún fichero del repositorio. Por eso estas dos columnas son un
guion hasta que exista un despliegue real.

## Cómo se entra a cada equipo

| rol | tipo | usuario | credencial | forma de acceso |
| --- | --- | --- | --- | --- |
| chr-agente | VM (qemu) | admin | `admin` / `BORgAt4kRPsodoOsbm78ehg3` — de `secrets.yml` → `routeros_clave` (HTTP Basic) | REST por el túnel del bastión (`21000`+vmid); su consola, por la serial del nodo |
| control | LXC | root | clave del lab (`~/.ssh/netlabs_tunnel_05_research_ed25519`), sin contraseña | SSH a `127.0.0.1`:(`20000`+vmid): él ES el bastión, se entra directo por su túnel |

El **usuario**, la **credencial** (de dónde sale Y cuánto vale) y la **forma de acceso** se
derivan de la declaración, del motor y de `deployment_engine/secrets.yml`. **Este lab es de un
solo uso y la contraseña se escribe aquí a la vista a propósito** (decisión explícita del dueño
del repo): es un cuadro de acceso, no un secreto — en un lab efímero prima poder entrar. El
puerto sale del **vmid**, que no se conoce hasta `apply`: por eso va como fórmula (`base`+vmid)
y el número de verdad lo dice el despliegue. Un invitado sin `config:` no se toca, y su fila lo
dice en vez de fingir un acceso que no hay. (En un Linux la credencial **no es una contraseña**:
es el **fichero** de la clave del lab, y por eso se enseña su ruta, no un valor.)
<!-- generado:fin -->

## Por qué así

**La pregunta.** El motor decía por escrito, en tres sitios, que no podía ver las interfaces
de una VM QEMU: `deployment_engine/filter_plugins/estado.py` (dos veces) y
`deployment_engine/tasks/addresses.yml` (una). Por eso, cuando un lab necesita una
dirección que no venga ya declarada --la del bastión--, la elegía contando por
arriba (`.254`, `.253`…) a ciegas, con la esperanza de no pisar una VM que no puede ver. El
agente de invitado era justo el canal que faltaba: Proxmox lo publica como
`GET /nodes/<nodo>/qemu/<vmid>/agent/network-get-interfaces`.

**Y ya no hay que creérselo: está implementado.** Lo que sigue es la MEDIDA --el agente
existe, contesta y da el dato--, hecha en este lab a mano; lo que el motor decidió con ella
está en `docs/decisiones/0011-el-agente-de-invitado.md`.

**El método.** Se desplegó el lab (`apply` en una sola pasada, con `verify` CORRECTO) y,
sobre el CHR ya vivo, se encendió el interruptor que Proxmox guarda en la config de la
VM --`agent: 1`-- y se reinició. Antes y después se interrogó al canal del agente
directamente **en el nodo**, porque la API no llega: con el token del motor,
`GET .../agent/get-osinfo` responde **403 `VM.GuestAgent.Audit`**, y
`GET /access/permissions` también da 403 (`Sys.Audit`). Por API se intentó primero
--cada método y cada ruta de la documentación--; el SSH al nodo es el último recurso que
AGENTS.md permite, se usó **sólo para diagnosticar** (una clave `netlabs_v4b_debug`, que
resulta ser la única autorizada: el nodo no acepta contraseña) y no cambió nada de su
configuración.

**Lo que contesta el CHR.** A todo:

- `guest-get-osinfo` → `{"id":"routeros","name":"RouterOS","pretty-name":"RouterOS 7.25.1","variant":"CHR","variant-id":"chr","machine":"x86_64","kernel-release":"5.6.3-64"}`.
- `guest-get-host-name` → `rt-agente`: el nombre que le puso el motor.
- `guest-network-get-interfaces` → `ether1`, `bc:24:11:00:00:6d`, `10.41.0.11/24`. Es
  exactamente el dato que el motor dice que no puede leer.
- `guest-info` → agente **2.10.50**, **21 comandos** (`guest-exec`, `guest-file-*`,
  `guest-fsfreeze-*`, `guest-shutdown`, `guest-set-time`...).

**El interruptor, y lo que NO hace falta.** El A/B lo cierra: con `agent=1` el nodo tiene
`/var/run/qemu-server/<vmid>.qga` y RouterOS contesta; con `agent=0` el socket **ni
existe** y nadie contesta. Dentro del router no se instala ni se configura **nada**: el
soporte viene de fábrica en la imagen, y no depende de que el lab haya declarado nada
--CHR es `machine: x86_64` sobre KVM, que es la combinación que MikroTik implementa.

**Lo que NO sirve.** `guest-exec` **hace** pero no **devuelve**: un script RouterOS corre
(exit 0) y la salida llega vacía, con `path` + `input-data` y con `:put`. Es una vía para
*actuar* desde el host, no para *leer*: para leer RouterOS sigue mandando su REST.

**Lo que le costaría al motor, si se implementa** (no se ha implementado: esto es la
investigación que lo decide):

1. Un primitivo nuevo en el vocabulario (`config`... declarar el agente en una VM), y el
   vocabulario es CERRADO: pide ADR (regla 15).
2. Es una decisión de **nacimiento**, no de convergencia: `agent` se puede cambiar en
   caliente, pero el canal sólo aparece al arrancar, así que nacer sin él es nacer con un
   reinicio pendiente.
3. El privilegio `VM.GuestAgent.Audit` en el token del motor. Sin él la API sigue sin
   poder leerlo, por mucho que el invitado conteste.
4. Lo que compraría, en corto: dejar de adivinar las direcciones de las VMs QEMU,
   apagados limpios, `fsfreeze` para copias consistentes, y `guest-exec` como atajo de
   diagnóstico. La convergencia de RouterOS no cambia: sigue siendo sólo por REST
   (regla 13).

**Lo que se dejó como estaba.** El CHR quedó con `agent: 1` (el estado que se midió), y
desde entonces el motor lo enciende por su cuenta en TODA VM que crea, así que aquí ya no
queda nada excepcional (ADR 0011). Del nodo no se tocó nada *para medir*, y lo único que
cambió luego, ya con la decisión tomada, fue el rol `NetlabsMotorVms` --se le añadió
`VM.GuestAgent.Audit`, la misma línea que declara `vars/engine.yml`, y que `./lab check`
vigila--.
