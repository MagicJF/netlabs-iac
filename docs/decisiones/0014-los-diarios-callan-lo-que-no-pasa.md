# 0014 — Los diarios callan lo que no pasa, y el humano lee un resumen

*Fecha: 15-nov-2026 — Estado: aceptada en parte (aplicados los puntos 1, 3 y 5; los puntos 2 y 4,
decididos y pendientes) — Ámbito: la salida del motor y los ficheros que deja (`ansible.cfg`,
`./lab`, `deployment_engine/tools/`)*

## El problema

Desplegar seis invitados deja **28.000 líneas** de consola, con miles de `ok` y miles de
`skipped`, y **15 ficheros** en `labs/<lab>/logs/`. Casi todo eso es correcto y casi nada es
información: el motor hace cientos de tareas pequeñas —una por invitado, por área y por
llamada— y Ansible cuenta cada una que no cambia nada. Un humano no puede leer eso; y cuando
algo falla, lo que falla se pierde entre lo que no pasó.

Lo que sí funciona es el **reporte nativo**: el `PLAY RECAP` con los totales y las tareas
`changed`/`failed` señaladas. El problema no es cómo reporta Ansible, es **cuántas tareas hay y
cuánto canta cada una**.

## La decisión

**1. La consola cuenta lo que pasa, no lo que no pasa. Aplicado.**

`ansible.cfg` pasa a `display_ok_hosts = False` (con `display_skipped_hosts = False`, que ya
estaba). La consola **deja de cantar cada tarea que no cambia nada**, y sigue enseñando el
`PLAY RECAP` -- los totales, el reporte nativo que nos gusta.

Medido, no supuesto: el `apply` de `06_conectividad-exterior` (seis invitados) pasó de **1.563
líneas a 819**, y el `destroy`, a 896. La mitad del ruido, de golpe y sin tocar una tarea. Pero
**la mitad del ruido no es el ruido**: lo que queda son las cabeceras `TASK [...]`, una por
tarea, y ésas no las quita un ajuste de salida. El detalle de cada paso **no se pierde**: sigue
entero, llamada a llamada, en los diarios del lab, que es donde se depura de verdad. Para verlo
en la consola, `ansible-playbook -v`.

Y el número que de verdad hay que bajar no es de líneas: es el `skipped=1818 ok=1178` del
recap. Eso no se arregla callando: se arregla haciendo **menos tareas** (punto 4).

Esto es todo lo que cambia ahora. Lo de abajo está decidido pero **no hecho**, y se dice para
que nadie lo dé por bueno.

**2. Un solo diario por lab, con la vía de acceso etiquetada. Pendiente.**

Hoy son cuatro ficheros que cuentan **la misma ejecución**: `api.jsonl`, `interior.jsonl`,
`console.jsonl` y `ansible.log`. Repartidos por vía de acceso, el orden cronológico se pierde, que es
justo lo que se necesita para depurar («¿qué pasó antes de esto?»). Lo que se decide es
`logs/diario.jsonl`, una línea por paso, con `gateway: proxmox | routeros | interior | túnel`,
`ts`, `lab`, `rol` y el resultado. Es lo mismo que ya se escribe, junto y en orden.

Ojo: esto toca la **regla 12** de `AGENTS.md` («cuatro vías de acceso, tres diarios») y el check
`gateway`, así que se hace con su cambio de regla explícito, no por la vía de acceso de atrás.

**3. Un resumen que se lee, renderizado del diario. Hecho.**

`deployment_engine/tools/resumen.py` lee los diarios de un lab y escribe **`logs/resumen.md`**:
la pasada que hay en el diario, cuántas llamadas hizo cada vía de acceso y si alguna no respondió 200,
**qué se escribió** con la explicación que el propio motor dio al ordenarlo, y qué áreas se
convergieron dentro de cada invitado. Es la página que se mira al terminar; el diario es la que
se mira cuando algo va mal.

Nació sabiendo cosas que no sabíamos, que es la prueba de que hacía falta: enseñó tres llamadas
que no responden 200 (dos `GET` que preguntan si la credencial del motor ya vale —y un 401 es la
medida, no el fallo—, y un `POST /user/set` que se queda sin sesión justo cuando cambia la
credencial), y enseñó que el diario **no marca dónde empieza cada ejecución**, así que «lo de
esta pasada» es hoy «todas las pasadas de ese verbo que hay en el diario». Eso último es
exactamente el punto 2.

**4. Menos tareas, mismo resultado. Pendiente.**

El ruido de fondo no es la salida: son las **tareas**. El motor ya calcula listas de llamadas
con funciones puras (`interior_escrituras_routeros` devuelve N llamadas, con su cuerpo y su
explicación). Se pueden **ejecutar en una tarea que recorre la lista**, en vez de una tarea por
llamada: cientos de tareas pasan a unas pocas, el `ok=` del recap baja con ellas, y el diario
queda idéntico. Es el «montarlo de otro modo» que se pedía, y encaja con cómo está hecho el
motor: lo que decide ya está separado de lo que ejecuta.

**5. Menos ficheros, y los que quedan con nombre. Aplicado.**

Un lab dejaba **15 ficheros**, y la mayoría no los abría nadie: nueve `verify-<sello>.json`
acumulados (retención de 10, y el humano no relee ninguno) y un `apply-ultimo-plan.txt` que se
escribía **y no lo leía ni el propio `./lab`** (el plan ya se escribe en `plan.txt` cuando se
pide un plan). Ahora:

- **`resumen.md`** — lo que se lee. Todo lo demás es para la máquina.
- `api.jsonl`, `interior.jsonl`, `console.jsonl` — los diarios. No se leen a mano: son la
  fuente del resumen y la prueba de lo que pasó (regla 5).
- `ultimo-verify.txt` — el veredicto suelto, en un folio. Lo imprime `./lab` al terminar.
- `plan.txt` — qué haría un `plan`, sin tocar nada. Lo imprime `./lab plan`.
- `verify-<sello>.json` — **sólo el último** (`engine_retencion_informes: 1`): la evidencia
  congelada de la última comprobación. La historia entera está en el diario.
- `ansible.log` — el rastro crudo, para cuando el resumen no basta.

Y el resumen dejó de ser un volcado: va **en tablas con cabecera**, dice **a qué equipo** (con
su vmid y su rol, derivados del propio diario) se le tocó cada cosa, **en el orden del plan**, y
lo que no respondió 2xx tiene su propia sección en vez de perderse entre lo que fue bien.

## Por qué no se hace todo de golpe

Cada punto toca la vía de acceso por la que se habla con un equipo, y el ciclo `destroy → apply →
verify` es lo único que dice que no se ha roto. Se aplica por partes, cada una con su ciclo: la
1 es de salida y no puede romper nada; la 2 toca la regla 12 y necesita su cambio de ley; la 4
reescribe la ejecución de las cuatro vías de acceso. Meter las cuatro a la vez es pedir que un fallo de
formato parezca un fallo de red.

## Cómo se comprueba

- La consola de un `apply` de un lab de seis invitados baja de 1.563 a 819 líneas, y sigue
  enseñando el `PLAY RECAP` con los totales. Lo que queda son cabeceras de tarea: el número que
  hay que bajar de verdad es el `skipped`, y baja cuando bajen las tareas (punto 4).
- `python3 deployment_engine/tools/resumen.py labs/<lab>` cuenta la ejecución en un folio y deja
  `logs/resumen.md`. Cada escritura que aparece lleva la explicación que el motor dio al
  ordenarla, y ninguna llamada que no responda 200 se queda sin decir.
- Los diarios siguen teniendo **una línea por paso**, con el mismo contenido que antes.
- `./lab check` en verde: los checks no dependen de cómo se pinte la salida.
