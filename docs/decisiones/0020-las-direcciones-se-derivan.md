# 0020 — Las direcciones se derivan repartiendo, en una función pura, y lo que el lab escribe gana

*Fecha: 16-nov-2026 — Estado: aceptada y aplicada — Ámbito: CÓMO se resuelve una `address` que
no es una dirección, y qué NO se puede derivar nunca*

## El problema

Escribir las direcciones a mano es donde más se copia y pega un error: una subred repetida, un
`.10` que era un `.11`, una pasarela que no es la del bridge. El motor ya derivaba cosas por su
cuenta, pero cada una por su lado y en sitios distintos. El lab `08_dunder-mifflin-con-fw` tenía
21 direcciones escritas a mano que se calculan solas.

## La decisión

**1. `derived` es una MARCA, no una dirección.** El lab la escribe donde quiera que el motor
calcule el valor, y **un valor explícito manda siempre** sobre la marca: el lab declara, y el
motor no adivina lo que el lab ya sabía.

**2. La derivación es una FUNCIÓN PURA**: `direcciones_resolver(declaración) → declaración`, sin
estado, sin API y **idempotente**, en `filter_plugins/identidad.py` — donde se prueba sin
Proxmox. Corre **antes** de validar y **antes** de normalizar, para que lo que se valide y lo
que se despliegue sean los valores ya resueltos.

**3. Se deriva repartiendo, en ORDEN, desde `lab.address_space`**: primero la pasarela de cada
bridge (el `.1` de su subred) y luego los invitados, con los **routers antes que los puestos**.
Adoptarlo en un lab ya desplegado **renumera** (es un cambio de direcciones, no cosmético).

**4. Lo que NO se deriva, y se dice en voz alta**: las rutas (`dst_address`, `gateway` — el motor
no sabe a quién se enruta), un `dns` anunciado (el lab puede querer anunciar el router de
**salida**, y eso no se adivina), la pata Linux del bastión y el interior de Linux. Ahí `derived`
se queda como está y la validación lo dice, en vez de resolver a medias en silencio.

## La trampa (y por qué `_plano` existe)

**Ansible no le pasa al filtro un `dict`**: le pasa un `_AnsibleLazyTemplateDict`, un mapa
perezoso que re-plantilla desde el original **en cada lectura**. Un asignador que copie y mute la
declaración es INVISIBLE: el IPAM resolvía sobre su copia, el validador leía el original, y el
motor rechazaba un lab perfectamente coherente con **16 errores fantasma** («los `derived` se
salen del espacio», «el lab no declara `address_space`»). Por eso `_plano()` materializa la
entrada en tipos nativos (`dict`/`list`) antes de tocarla. Sin eso, esta decisión no se puede
implementar.

## Qué NO se toca

- **Ninguna dirección de un lab que no diga `derived`**: donde no hay marcas, la función no-op.
- **El `08` NO adopta `derived`**, y es una decisión medida: su direccionamiento es un PLAN (el
  troncal en `.10.x`, la DMZ en `.3.x`) y sus rutas apuntan a direcciones concretas de ese plan.
  Derivarlo renumeraría las subredes y dejaría las rutas (que sí se quedan escritas) colgando.
- **El motor no conoce ningún valor de ningún lab**: sólo reparte dentro del `address_space` que
  el lab declara.

## Cómo se comprueba

- **`test/test_identidad.py`**: el reparto en orden, el espacio que se agota, y que un valor
  explícito gana a la marca.
- **`test/test_declaracion.py`**: un `derived` fuera de sitio y un `address_space` que no da para
  las subredes declaradas (con su motivo, no con un volcado).
- **El ciclo real** (informe §6.1): las 21 direcciones del lab 06 marcadas como `derived` y
  comparadas — 9 exactas, 4 renumeradas, 8 fuera del alcance del IPAM. Es la medida que acota
  esta decisión: aporta en el trozo mecánico (bridges y el DHCP de los CHR), no en «menos YAML».

## VER

- [deployment_engine/filter_plugins/identidad.py](../../deployment_engine/filter_plugins/identidad.py)
  (`direcciones_resolver` y sus ayudantes)
- [deployment_engine/filter_plugins/declaracion.py](../../deployment_engine/filter_plugins/declaracion.py)
  (`_plano`, el orden de llamada y `derived` en la validación)
- [docs/informe-estado-del-arte-2026-11.md](../informe-estado-del-arte-2026-11.md) (§6.1, medido)
