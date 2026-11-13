<!-- PROPÓSITO:   el documento del lab `lab-dos-redes`. Dos regiones: la generada
     (datos derivados de la declaración) y la prosa (lo que el YAML no puede decir).
     INVARIANTES: dentro de los marcadores no se escribe a mano; `./lab check docs`
     falla si difiere del render. Fuera, ningún check opina.
     LÍMITES:     la prosa no repite valores que ya están en la tabla: los cita.
     VER:         AGENTS.md §Documentación; README.md §Documentación -->
# lab-dos-redes

La topología que sube un escalón respecto al lab de tres dispositivos: **dos redes
separadas —perímetro y núcleo—, cinco invitados en tres escalones de arranque, dos
de ellos VMs**. Donde el lab de tres dispositivos tenía un bridge, dos escalones y
una sola VM, aquí hay dos bridges, tres escalones y dos VMs, repartidos en las dos
ramas del motor (QEMU y LXC) y en dos redes que no comparten direccionamiento.

Sirve para lo que un lab de un solo segmento no puede enseñar: que el orden de
arranque **atraviesa** la topología (el borde primero, el núcleo después, los
extremos al final), que un mismo plan convive con varias redes declaradas a la vez,
y que el motor no sabe nada de ninguna de las dos —el reparto entre `perimetro` y
`nucleo` vive entero en la declaración, no en el código—.

<!-- generado:inicio -->
_Datos derivados de `lab-dos-redes.yml`. Los reescribe `./lab check docs --actualizar`;
si los editas a mano, `./lab check docs` falla._

## Invitados declarados

| rol | tipo | escalón | cores | memoria (MB) | disco (GB) | bridge | dirección |
| --- | --- | --- | --- | --- | --- | --- | --- |
| borde | VM (qemu) | 1 | 2 | 512 | 8 | vmb_perimetro | 203.0.113.2/24 |
| nucleo | VM (qemu) | 2 | 2 | 1024 | 8 | vmb_nucleo | 203.0.113.130/24 |
| puesto-1 | LXC | 3 | 1 | 512 | 4 | vmb_nucleo | 203.0.113.131/24 |
| puesto-2 | LXC | 3 | 1 | 512 | 4 | vmb_nucleo | 203.0.113.132/24 |
| servidor | LXC | 3 | 1 | 512 | 6 | vmb_perimetro | 203.0.113.21/24 |

## Bridges del lab

| bridge | dirección del bridge |
| --- | --- |
| vmb_perimetro | 203.0.113.1/24 |
| vmb_nucleo | 203.0.113.129/24 |

## Orden de arranque (escalones)

| escalón | roles |
| --- | --- |
| 1 | borde |
| 2 | nucleo |
| 3 | puesto-1, puesto-2, servidor |

## Identidad: la deriva el motor, no la declara el lab

| rol | tipo | nombre canónico | vmid | MAC |
| --- | --- | --- | --- | --- |
| borde | VM (qemu) | lab-dos-redes-borde | — | — |
| nucleo | VM (qemu) | lab-dos-redes-nucleo | — | — |
| puesto-1 | LXC | lab-dos-redes-puesto-1 | — | — |
| puesto-2 | LXC | lab-dos-redes-puesto-2 | — | — |
| servidor | LXC | lab-dos-redes-servidor | — | — |

El **vmid** (el menor libre de *todo* el clúster) y la **MAC** (`BC:24:11` + los
bytes del vmid) los asigna `apply` leyendo el estado de Proxmox: no se declaran aquí y
no se guardan en ningún fichero del repositorio. Por eso estas dos columnas son un
guion hasta que exista un despliegue real.
<!-- generado:fin -->

## Cómo llevarlo a un Proxmox real

Los pasos, en orden. Este lab **se ha desplegado y verificado contra un Proxmox
real**; más abajo queda anotado lo que se aprendió al hacerlo.

1. **Rellena las credenciales** (no se versionan):
   ```
   cp deployment_engine/secrets.yml.example deployment_engine/secrets.yml
   chmod 600 deployment_engine/secrets.yml
   $EDITOR deployment_engine/secrets.yml
   ```
   Hay que sustituir `pve_nodo` (el host de la API), `pve_nombre_nodo` (el nombre
   con el que Proxmox conoce al nodo, el de `/nodes/<nombre>/...`), `pve_token_id` y
   `pve_token_secreto`. El puerto por defecto de Proxmox es 8006.

2. **Sustituye las direcciones del lab.** Este lab declara direcciones en
   `203.0.113.0/24`, que es un rango reservado para documentación (RFC 5737) y no
   existe en ninguna red real. Edita `lab-dos-redes.yml` y pon las tuyas. Ojo: hoy
   esas direcciones son el **plan de direccionamiento** del lab, no algo que el
   motor escriba en el invitado ni en el bridge (ver «Un límite que se ve al leer
   la topología»). Los dos nombres de bridge ya cumplen el formato que el núcleo
   exige (sin guiones, 2 a 15 caracteres): el motor rechaza los que no lo cumplen
   antes de tocar la API.

3. **Mira el plan** (no toca nada):
   ```
   ./lab --lab lab-dos-redes plan --api
   ```
   Sin `--api`, `plan` usa un clúster vacío simulado y sirve igual para revisar el
   orden de las llamadas.

4. **Pregunta qué hay y qué falta**, sólo lectura:
   ```
   ./lab --lab lab-dos-redes preflight
   ```

5. **Converge**:
   ```
   ./lab --lab lab-dos-redes apply
   ```
   `apply` ejecuta exactamente el plan que acabas de ver: crea el pool, crea los
   bridges que falten y recarga la red del nodo una sola vez, crea o ajusta cada
   invitado y los arranca por escalones.

6. **Verifica** contra la API, que es el único test que no se cree a sí mismo:
   ```
   ./lab --lab lab-dos-redes verify
   ```

7. **Destruye** cuando ya no lo quieras (borra los invitados del lab y, al final,
   su pool si ha quedado vacío):
   ```
   ./lab --lab lab-dos-redes destroy
   ```
   Los bridges **no** se borran: son del nodo, no del lab. Si querías que
   desaparecieran, se quitan a mano en Proxmox (y con la red recargada después).

## Por qué así

### Dos redes y no una

Un lab de un solo segmento no distingue «el bridge del lab» de «la red del lab»:
con un bridge, la pregunta no se plantea. Con dos, el motor tiene que crear **los
que falten** (los bridges son del nodo, no del pool: Proxmox no los mete en
ningún pool) y recargar la red del nodo **una vez** para que los dos entren en
vigor, no una vez por bridge. Eso es lo que se ve en el plan: dos `POST` a
`/nodes/<nodo>/network` y un único `PUT` de recarga al final.

### Tres escalones y no dos

El orden de arranque es parte de la declaración, no del código: el motor sólo sabe
«arranca el escalón 1, luego el 2, luego el 3», y no hay ni un nombre de rol dentro
de `deployment_engine/`. Aquí el orden tiene sentido físico —primero la puerta,
después el conmutador que da red al segundo segmento, y sólo entonces los extremos—
y ese orden se lee entero en el YAML.

### Dos VMs y tres contenedores

El lab de tres dispositivos ejercita las dos ramas del motor una vez. Aquí la rama
QEMU aparece dos veces y en escalones distintos, que es donde se nota si el motor
trata igual a los dos tipos: la red de una VM se declara `virtio=<mac>` y la de un
contenedor `name=eth0,bridge=...,hwaddr=<mac>`, y esa diferencia está en un solo
sitio (`tools/plan.py`), no repartida por los playbooks.

### Un límite que se ve al leer la topología

Cada invitado declara **un** bridge y **una** dirección. Este lab, por tanto, no
puede declarar un cortafuegos con una pata en cada red: la interconexión entre
perímetro y núcleo **no se declara**, y las dos redes quedan aisladas entre sí. No
es un olvido de esta declaración, es la forma que tiene hoy el esquema: admitir
varias interfaces por invitado es un cambio del motor, no de un lab. Se dice aquí
en vez de maquillarlo con una topología que aparente lo que no hay.

Otros límites, los mismos de cualquier lab de este repositorio, y uno de este que
conviene tener delante:

- **La dirección IP declarada de cada rol no es verificable por API**: vive dentro
  del invitado y la configuración del hipervisor no la guarda. `verify` compara el
  bridge y la MAC (que sí están en la config) y lo dice en voz alta en lugar de dar
  por bueno lo que no ha mirado. Es más: el motor no la escribe tampoco —no
  configura el interior de los invitados—, así que es el plan de direccionamiento,
  no una dirección puesta.
- **La dirección del bridge se declara y no se envía**: el `POST` que crea un
  bridge manda `iface`, `type` y `autostart`, y nada de `address`/`cidr`. Los dos
  bridges de este lab existen, están activos y arrancan solos, pero salen con
  `method=manual` y **sin** dirección: la del YAML es intención documentada.
- **`disco` se declara y se valida, pero la API no recibe ninguna orden de disco**:
  el plan no inventa recursos que la API no da, y una plantilla de disco es uno de
  ellos (`tools/plan.py` lo deja escrito). Los tres contenedores se crean con el
  tamaño por defecto de la plantilla, también el que declara más de lo que la
  plantilla da.

Ninguno de los tres lo detecta `verify`: compara existencia, nombre, cores,
memoria, bridge, MAC y descripción, que es lo que la API guarda. El hueco está
dicho aquí, que es el único sitio donde cabe decirlo.

### Lo que se aprendió al desplegarlo de verdad

*(Archivo de lo ejecutado, no de lo previsto: esto no son hipótesis, es lo que
pasó al correrlo contra el Proxmox real.)*

- **El plan y lo que pasa cuadran, y eso se puede comprobar.** El plan anunció 14
  llamadas REST (crear pool, dos bridges, una recarga, cinco invitados, cinco
  arranques) y el primer `apply` terminó con `changed=14`. Un segundo `apply`
  seguido no hizo ni una escritura: `changed=0` y el diario de la API de esa
  corrida no tiene ni un método que no sea `GET`. Es la prueba de idempotencia que
  el motor se puede hacer a sí mismo sin creerse.
- **El asignador toma el menor vmid libre de TODO el clúster, no del pool.** Si el
  nodo ya tiene invitados sueltos fuera de cualquier pool, los vmids del lab salen
  salteados: no son un rango contiguo ni el orden de creación. Se ve al mirar la
  tabla de identidad de un despliegue real, y es el motivo de que esa tabla no se
  rellene a mano.
- **Los bridges sobreviven al lab.** `destroy` borra los invitados y el pool, pero
  no los bridges: son del nodo. Un lab que se despliega y se destruye varias veces
  deja bridges huérfanos si nadie los limpia; conviene saberlo antes de crear el
  quinto.
- **La recarga de red es el paso que más tarda y el único que toca el nodo.** Los
  `POST`/`DELETE` de invitados van contra el pool del lab; el `PUT` de recarga
  reescribe `/etc/network/interfaces` del nodo y corre `ifreload -a`. Si esa
  recarga falla, el bridge queda creado en el fichero pero sin activar, y el
  invitado que lo use se queda sin red: merece la pena mirar la respuesta antes de
  dar el despliegue por bueno.
- **La creación es asíncrona y el motor la espera.** Cada `POST` devuelve un UPID y
  el motor sondea `GET /nodes/<n>/tasks/<upid>/status` hasta que la tarea deja de
  estar en marcha; sin esa espera, el `start` choca con el bloqueo de la creación y
  `verify` ve invitados «parados» que en realidad están arrancando.

## Ver también (punteros al código)

- La puerta única a la API y el diario de cada llamada:
  [deployment_engine/tasks/pve_api.yml](../../deployment_engine/tasks/pve_api.yml)
- El asignador de identidad (vmid, nombre canónico, MAC):
  [deployment_engine/filter_plugins/identidad.py](../../deployment_engine/filter_plugins/identidad.py)
- El cálculo del plan ordenado (bridges, escalones y las dos formas de `net0`):
  [deployment_engine/tools/plan.py](../../deployment_engine/tools/plan.py)
- Los checks del motor, incluido `colisiones`:
  [deployment_engine/tools/framework_check.py](../../deployment_engine/tools/framework_check.py)
- Por qué el pool es la frontera de propiedad:
  [docs/decisiones/0002-el-pool-como-frontera-de-propiedad.md](../../docs/decisiones/0002-el-pool-como-frontera-de-propiedad.md)
