# Rendimiento del motor: dónde se va el tiempo y qué se ha recortado

Medición hecha sobre `lab-red-routeros` (2 CHR + 1 LXC de puesto de control + 3 LXC),
en el nodo Proxmox `54.36.168.83`, el 15-nov-2026. **Todo lo que aparece como "medido"
sale de una ejecución real**; lo que es estimación va marcado como tal.

## Cómo se ha medido (y por qué así)

Ansible no dice cuánto tarda cada tarea. En vez de meter un callback o un plugin (el
motor sólo usa `ansible.builtin`), se perfila **por fuera**: un envoltorio que sella
cada línea de salida con un `date +%s.%3N`, y luego se calcula el hueco entre
cabeceras `TASK [...]`. El sello de tiempo no toca el motor.

- Perfilador: `perfilar.sh` (en el directorio de trabajo del agente, no en el repo).
- Analizador: `analizar_perfil.py`.
- Cruce con la verdad de la API: `labs/<lab>/logs/api.jsonl` (`duration_ms` por llamada).

Lo que Ansible NO imprime (las vueltas de bucle que se saltan) se midió aparte, con
**bancos mínimos** fuera del repo: el mismo patrón, aislado, cronometrado.

## Ciclo de DESTRUIDO: 224 s (3 min 44 s)

6 invitados (2 VM + 4 LXC) parados y borrados, más la red.

| familia | seg | % | qué es |
| --- | ---: | ---: | --- |
| **esperas de tarea (UPID)** | **183,3** | **82 %** | los 13 bucles de sondeo a Proxmox |
| llamadas a la API | 43,5 | 19 % | 65 llamadas (48 GET, 17 de escritura) |
| resto (arranque, inventario, tareas sueltas) | ~41 | 18 % | ~2.400 evaluaciones de tarea |

Dentro de esas 13 esperas:

- **~140 s son sobrecarga del motor**, no trabajo de Proxmox. La API de verdad, dentro
  de las esperas, es ~43 s.
- La causa: `engine_tarea_intentos` valía **150** y Ansible **no sabe cortar un bucle**
  (`break_when` y `until` sobre `include_tasks` están prohibidos en este ansible-core —
  comprobado con un banco: *"conflicting action statements"* / *"`retries` is not a
  valid attribute for a TaskInclude"*). Así que cuando la tarea terminaba en el primer
  sondeo, las **149 vueltas restantes se recorrían igual**, saltándose el cuerpo.

Medido con una copia fiel del cuerpo real del sondeo (`esperar_paso.yml`), con el
cuerpo ya saltado, que es el caso normal:

| vueltas del bucle | tiempo |
| ---: | ---: |
| 40 | 3,28 s |
| 150 | **10,19 s** |

→ **~63 ms por vuelta saltada**. Con 13 esperas: **~90 s tirados** por ciclo.

## Ciclo de DESPLIEGUE: 1.166 s (19 min 26 s)

| familia | seg | % | qué es |
| --- | ---: | ---: | --- |
| **PUERTA ROUTEROS** | **540,0** | **46 %** | 363 tareas = 99 llamadas REST a los CHR, **delegadas al puesto de control** |
| esperas de tarea (UPID) | 282,6 | 24 % | 13 esperas, la mayor de **50 s** (crear una VM) |
| PUERTA (Proxmox) | 118,6 | 10 % | creación, arranque, red |
| CONSOLA | 65,5 | 6 % | 13 usos; uno de **46,1 s** (arranque del puesto de control) |
| INTERIOR (SSH) | 55,7 | 5 % | incluye 39,4 s de "ejecutar en `control`" |
| INVENTARIO | 33,5 | 3 % | incluye 23,2 s de "las opciones de conexión a `control`" |
| DIARIO | 33,3 | 3 % | escritura de las líneas de diario |

La API, según su propio diario: **231 llamadas, 597,7 s (51 % del total)**.

| puerta | llamadas | suma | media | máx |
| --- | ---: | ---: | ---: | ---: |
| routeros | 99 | 511,6 s | **5,17 s** | 6,87 s |
| proxmox | 132 | 86,1 s | 0,65 s | 1,86 s |

**El 44 % del despliegue son 99 llamadas REST a un CHR a 5,2 s cada una.**

## ¿El CHR es lento? No. Es Ansible.

Medido por piezas, desde el nodo:

| pieza | medido |
| --- | ---: |
| TCP del puesto de control al CHR (`/dev/tcp`, puerto 80) | **3 ms** |
| `python3` + `urllib` DENTRO del puesto de control, con autenticación | **0,15 s** |
| `ssh` al puesto de control (1ª vez / siguientes) | 1,88 s / **0,92 s** |
| **10 llamadas `uri` (sin auth) vía `delegate_to`** | **51,2 s → 5,1 s/llamada** |
| las mismas 10 con `pipelining` | **39,4 s → 3,9 s/llamada** |
| las mismas 10 con `ControlPersist` explícito | 50,0 s (no mejora) |

Dos conclusiones que importan:

1. Una llamada **sin** autenticación (un 401, respuesta inmediata) cuesta lo mismo que
   una real (5,1 s vs 5,17 s medidos en producción). El CHR no aporta el coste: lo
   aporta la maquinaria de Ansible alrededor de cada tarea delegada.
2. El suelo real es ~1,1 s (0,92 de SSH + 0,15 de Python). Todo lo que pase de ahí es
   Ansible copiando el módulo al invitado y recogiendo el resultado.

## Lo que se ha recortado (2 cambios, medidos por separado)

### 1. `pipelining = True` en `ansible.cfg` — 5,1 s → 3,9 s por llamada delegada

El módulo viaja por el mismo canal SSH en vez de copiarse a un fichero temporal en el
invitado (mkdir + sftp + ejecutar + borrar: tres viajes de ida y vuelta por tarea).
No hay riesgo de `requiretty`: el motor sólo entra como `root` con la clave del camino,
sin `sudo` por medio.

**Medido después** (99 llamadas reales del mismo `apply`): 5,17 s → **4,39 s** por
llamada, **−0,78 s cada una** (−15 %). El banco, con llamadas sin autenticar, daba
−1,2 s: con autenticación real el ahorro es algo menor. Se pone el medido, no el del
banco.

### 2. El bucle de espera: 150 vueltas → 40, con espera creciente

`engine_tarea_intentos: 150 → 40`, y el intervalo ya no es fijo: **crece** con la
vuelta (`2s, 3s, 4s...` hasta `engine_tarea_intervalo_max: 15s`). Los primeros sondeos
siguen yendo seguidos —una tarea corta se detecta igual de rápido que antes— y los
últimos se espacian. Efecto:

- El tope total **sube** de 300 s a ~340 s (más margen, no menos).
- Las vueltas de más bajan de ~149 a ~39: **−6,9 s por espera** (medido en el banco).
- Con 13 esperas por ciclo. Medido en la familia ESPERA del `apply`: **283 s → 221 s**;
  y los `skipped` del verbo, de **6.683 a 2.379**.

## Resultado medido: antes y después

Ciclo completo real (`destroy → apply → verify`) contra el nodo, con el mismo lab:

| verbo | antes | después | delta |
| --- | ---: | ---: | ---: |
| `destroy` | 224,1 s | **142,8 s** | **−81,3 s (−36 %)** |
| `apply` | 1.166,2 s | **1.028,7 s** | **−137,5 s (−12 %)** |
| `verify` | — | 141,9 s | — |
| **ciclo** | ~1.532 s (25,5 min) | **1.313 s (21,9 min)** | **−219 s (−14 %)** |

El veredicto del `verify` fue **CORRECTO** (6 invitados) con `changed=0`, así que el
ciclo sigue siendo idempotente.

De dónde viene el ahorro del `apply` (medido por familias):

| familia | antes | después | delta |
| --- | ---: | ---: | ---: |
| PUERTA ROUTEROS | 540,0 s | 462,5 s | **−77,5 s** |
| ESPERA (bucles) | 282,6 s | 221,1 s | **−61,5 s** |
| PUERTA (Proxmox) | 118,6 s | 105,6 s | −13,0 s |

Las llamadas REST a RouterOS del `apply`: 5.167 ms → **4.389 ms** de media (99 llamadas,
511,6 s → 434,5 s).

Lo que **no** se ha movido: `CONSOLA` (65,5 s) e `INTERIOR` (56 s). Son esperas de
arranque reales; para bajarlas hay que atacar el punto 1 del margen que queda.


## Lo que NO se ha tocado, y por qué

- **El trabajo real de Proxmox** (crear una VM tarda lo que tarda; la espera mayor
  medida es de 50 s). Recortar aquí sería correr contra el hardware.
- **La espera entre sondeos de la sonda de escalón** (24 intentos × 5 s): su tiempo es
  un CHR arrancando de verdad, no un `sleep` de más. Se comprobó que sale por éxito
  temprano, así que un equipo que contesta rápido no la paga.
- **El intervalo entre sondeos de Proxmox** (antes 2 s fijos): bajarlo a 1 s no sale a
  cuenta —cada sondeo es una llamada de ~0,6 s— y recortaría la detección de tareas
  cortas sin ganar nada. De ahí que el cambio sea *creciente* y no simplemente menor.

## Margen que queda (no implementado; necesita decisión)

Por orden de tamaño:

1. **Las llamadas a RouterOS por `delegate_to` (el mayor, ~350 s ≈ 30 % del
   despliegue).** Aun con pipelining, cada llamada cuesta 3,9 s y el suelo medido es
   ~1,1 s. La causa es que la llamada se ejecuta *dentro* del puesto de control, y a
   ese invitado se llega por SSH. Si el **camino reenviara el puerto REST del CHR**
   (como ya reenvía el 22 del puesto de control), el motor haría `uri` **desde su
   propio nodo**, sin SSH por medio: ~0,15-0,30 s por llamada. Es un cambio en el
   camino (una pata más) y necesita su ADR; no se ha tocado.
2. **El arranque del puesto de control por consola (46 s en una sola tarea).** Es una
   espera de arranque real, pero el reintento está a 12 s fijos; con una rampa como la
   del punto 2 se afinaría.
3. **El suelo de Ansible (~12-23 ms por tarea × ~4.000 tareas ≈ 50-90 s).** Sólo baja
   haciendo menos tareas (un diario por llamada cuesta 5 tareas por llamada).

## Cómo repetir esta medición

```sh
# perfil de un verbo (no toca el motor)
perfilar.sh /tmp/perfil.tsv --lab lab-red-routeros apply
python3 analizar_perfil.py /tmp/perfil.tsv

# la verdad de la API, en paralelo
python3 - <<'EOF'
import json, collections
a=[json.loads(l) for l in open('labs/lab-red-routeros/logs/api.jsonl') if l.strip()]
por=collections.defaultdict(list)
for f in a: por[f.get('api','?')].append(f.get('duration_ms',0))
for k,v in por.items(): print(k, len(v), f"{sum(v)/1000:.1f}s", f"media {sum(v)/len(v):.0f}ms")
EOF
```

> El perfilador y el analizador van con el informe, en la raíz: son herramientas de quien
> diagnostica, no del motor, y por eso no las usa ningún play.
