# 0015 — El nombre del invitado dice qué es, no de quién es

*Fecha: 15-nov-2026 — Estado: aceptada y aplicada — Ámbito: la identidad de los invitados
(`deployment_engine/filter_plugins/identidad.py`, `declaracion.py`, `vars/engine.yml`),
la declaración de un lab y `./lab new`*

## El problema

El nombre canónico de un invitado era `<lab>-<rol>`: `conectividad-exterior-borde`,
`conectividad-exterior-servidor`. En Proxmox, que es donde se leen esos nombres, el resultado
es que **el nombre dice de quién es el invitado y no qué es**, gasta la primera mitad en algo
que ya está dicho dos veces por otra vía (el pool y la descripción `lab=… rol=…`), y hace que
dos labs con la misma forma —que es lo normal: casi todos tienen un router y un par de
puestos— tengan seis nombres distintos por una razón que no aporta nada al leer la lista.

Quien mira el nodo quiere saber **qué es cada máquina**, no de qué carpeta salió: `rt-borde`
dice «router, el que hace de pasarela»; `conectividad-exterior-borde` dice «de este lab, y el
rol» — y para saber que es un router hay que saberse el rol de memoria.

Y hay un segundo problema, del mismo sitio: el nombre era **la única** prueba de pertenencia
que un humano podía leer. Si el nombre deja de llevar el lab, ¿cómo se sabe de quién es cada
`ws-1`? La respuesta ya estaba en el motor y no se estaba usando: el **pool** (una frontera de
Proxmox, que es lo que el motor consulta para decidir qué es suyo) y la **descripción** del
invitado (`lab=<lab> rol=<rol> gestionado por netlabs_v4_b`), que el motor escribe al crear y
lee para adoptar. La pertenencia estaba resuelta; lo que sobraba era pedirle al nombre que
también la contara.

## La decisión

**1. El nombre se compone de dos mitades declaradas por el lab: `tipo` y alias.**

- `tipo:` — **obligatorio** en cada invitado, de un vocabulario **cerrado** (regla 15):
  `rt` (router, un CHR), `srv` (servidor), `ws` (puesto de trabajo), `sw` (conmutador o
  equipo sin dirección), `ctl` (bastión, el bastión). Un equipo que no quepa en
  ninguno pide su tipo al motor **con su ADR**, no se inventa en un YAML.
- `nombre:` — **opcional**: el alias corto. Si no está, el alias es el `rol`. Admite número
  (`nombre: 2` -> `ws-2`), que es lo natural para numerar.

Y el nombre es `tipo` + `-` + alias: `rt-borde`, `rt-nucleo`, `srv-1`, `ws-1`, `ws-2`,
`ctl-1`, `sw-1`. La plantilla vive en `vars/engine.yml` (`engine_plantilla_nombre:
"{equipo}-{alias}"`), así que sigue siendo **forma del motor y no valor de ningún lab** (regla
7): el motor no sabe que existe `rt-borde`, sabe componer el nombre a partir de lo que el lab
declara.

**2. El rol NO desaparece: cambia de sitio.**

El `rol` sigue siendo lo que declara el lab (`workstation-1`, `chr-agente`, `puesto-2`) y sigue
mandando en todo lo que no es el nombre: la descripción del invitado, los diarios, los informes
y la adopción (un invitado se reconoce por el rol que lleva su descripción, dentro del pool del
lab). El nombre corto es para leer el nodo; el rol es la identidad de trabajo. Por eso el alias
es opcional: si un lab no quiere pensar en nombres, el invitado se llama `tipo-rol` y ya está.

**3. Dos labs pueden repetir nombre, y no pasa nada.**

`rt-nucleo` puede existir en tres labs a la vez: el pool dice de quién es cada uno y la
descripción, qué rol cumple. Lo que **no** se puede repetir es el nombre **dentro** de un lab:
dos invitados del mismo lab que compongan el mismo nombre son una declaración incoherente, y el
validador lo rechaza con el nombre y los dos roles que chocan.

Esto cambia una comprobación que existía: `test_identidad.py` exigía que los nombres de dos
labs disjuntos **no** chocaran. Ahora exige lo contrario —que el nombre se repita a propósito—
y que lo que no se repita sea la descripción. Es exactamente la propiedad que hay que
demostrar, y la que se comprobó: sometida a un clúster con `rt-nucleo` en otro pool, la
adopción sigue discriminando por pool.

**4. Lo que se mira para vigilar que sigue siendo verdad.**

- `declaracion.py` rechaza un invitado sin `tipo:`, un `tipo:` fuera del vocabulario, un alias
  con caracteres que Proxmox leería mal, y dos invitados del mismo lab con el mismo nombre
  derivado. Cuatro errores distintos, cada uno diciendo qué hacer.
- La descripción y el pool llevan el lab entero, así que **la propiedad no depende del nombre**
  ni un bit: es lo que ya hacía `destroy`, `estado` y la adopción, que no leen el nombre para
  decidir.

## Lo que esto rompe, y por qué se acepta

Un invitado **ya desplegado** con el nombre viejo no se renombra solo: la declaración dirá
`rt-borde` y en el nodo habrá `conectividad-exterior-borde`. El motor lo dirá como una
diferencia (no la esconde) y el túnel es el honesto: `destroy` y `apply`, que es lo que se
hizo con los labs del repositorio el mismo día de esta decisión (se destruyeron todos y se
volvieron a desplegar con los nombres nuevos). Un renombrado en caliente no existe como tal en
la API de Proxmox para un invitado en marcha, y no se inventa aquí.

## Cómo se comprueba

- `python3 test/test_identidad.py` — los dos labs del fixture declaran el mismo rol con el mismo
  tipo y **comparten nombre** (`rt-nucleo`), y lo que no comparten es la descripción.
- `python3 test/test_declaracion.py` — el lab de aceptación es coherente con `tipo:` en sus seis
  invitados; y los casos negativos del validador (sin tipo, tipo inventado, alias imposible,
  nombre repetido en el mismo lab) fallan como tienen que fallar.
- `./lab --lab 01_ejemplo-topologia plan` — la identidad derivada y el `name`/`hostname` de cada
  invitado salen como `sw-1`, `ws-1` y `ws-2`; el poolid, como `01_ejemplo-topologia`.
- `python3 test/test_regresion_planes.py` — el plan de la fase 1 cambia **sólo** en la forma del
  nombre y del pool; ni un paso, ni un orden, ni un parámetro distinto. La referencia se
  regeneró a mano y el test dice por qué.
- `./lab check` en verde, y el ciclo `destroy → apply → verify` de un lab con CHR, verde.
