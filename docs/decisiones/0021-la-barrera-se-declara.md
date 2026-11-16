# 0021 — La barrera de un invitado se declara, y es un tope DURO

*Fecha: 16-nov-2026 — Estado: aceptada y aplicada — Ámbito: CUÁNTO se le espera a un invitado
antes de configurar lo que va detrás (`ready:`)*

## El problema

El motor ya sabía **cuánto** esperar a cada equipo (la sonda que prueba su puerto antes de
seguir), pero lo sabía **por dentro**: la ventana era un número del motor y el tipo de equipo lo
insinuaba el motor a partir de su interior. Dos agujeros:

- Un invitado **sin `config:`** (media docena en estos labs: puestos, servidores) **no tenía
  barrera ninguna y no había forma de pedirla**. El motor decidía, y decidía «ninguna».
- El lab no podía decir «a éste espérale más, que en frío tarda», ni «a éste no le esperes».

## La decisión

**1. `ready:` se declara por invitado**, con vocabulario cerrado y dos campos:
`ready: {tipo: ssh|routeros_rest|ninguno, espera: <segundos>}`. El `tipo` dice **por dónde** se le
pregunta (ssh → su 22; `routeros_rest` → su 80); `ninguno` dice «a éste no le esperes», que es
una afirmación, no un silencio.

**2. La espera va en SEGUNDOS, no en intentos.** Los intentos son un detalle del compás del motor
(`intentos = espera / engine_sonda_espera + pausa`); el lab escribe tiempo, que es lo que sabe.

**3. Sin `ready:`, todo se comporta EXACTAMENTE como antes.** La barrera que el motor insinuaba
por el tipo no se toca, así que ninguno de los labs que ya existen cambia por declarar esto.

**4. La barrera del lab manda sobre la insinuada.** Si el lab declara `ready:`, esa es la
ventana; el motor no la alarga ni la recorta.

**5. `ninguno` sobre un invitado con DHCP se ADMITE** (y esto necesitó una excepción explícita
en el validador): no hay dirección que sondear, y decir «a este no le esperes» es justo lo más
informativo precisamente ahí.

## La trampa

**Es un tope DURO, y puede volver el lab más FRÁGIL que antes.** Una `espera:` más corta que la
del motor (24 intentos × (2 s + 5 s) = **168 s**) hace que un lab que hoy despliega, mañana no —
y quien escribe el lab no sabe cuánto tarda su bastión en frío. Se declara con margen, no con lo
justo.

Y una segunda, que costó un `apply` en frío: **la ventana declarada no llegaba a la sonda**.
`None` no dispara el `default` de Jinja (sólo sustituye lo *indefinido*), así que el tope se
renderizaba VACÍO y el comando que viajaba al invitado quedaba en `while [ $i -lt  ]` — un error
de shell: la barrera no podía pasar NUNCA, tardara lo que tardara el equipo. Se arregla con
`default(..., true)` en las dos puntas (`paso.yml` y `sonda.yml`). El fallo sólo existe **dentro
del invitado**: ninguna lectura del código lo ve.

## Qué NO se toca

- **La sonda**: sigue siendo la misma (un puerto, intentos, pausa) y sigue leyendo, no
  configurando.
- **Los tipos que no sean los tres**: lo que no esté en el vocabulario se rechaza con su motivo,
  como el resto del interior.
- **Los labs existentes**: ninguno declara `ready:` y ninguno cambia.

## Cómo se comprueba

- **`test/test_interior.py`**: la ventana declarada se traduce a intentos y manda sobre la
  insinuada; `ninguno` no genera sonda; un invitado sin `config:` **sí** puede declarar barrera.
- **`test/test_declaracion.py`**: un `tipo` fuera del vocabulario, una `espera` que no es un
  entero positivo y un `ready` con DHCP (que ahora admite `ninguno`).
- **El ciclo real** (informe §6.3): el lab 08 declara cinco barreras y despliega con ellas; y el
  primer POST del 06 parado en esta barrera fue, en realidad, la caza del tope vacío.

## VER

- [deployment_engine/filter_plugins/interior.py](../../deployment_engine/filter_plugins/interior.py)
  (`espera_de_servicio`, `SONDA_SEGUNDOS_POR_INTENTO`)
- [deployment_engine/filter_plugins/declaracion.py](../../deployment_engine/filter_plugins/declaracion.py)
  (`ready` en el vocabulario y su validación)
- [deployment_engine/tasks/paso.yml](../../deployment_engine/tasks/paso.yml) y
  [sonda.yml](../../deployment_engine/tasks/sonda.yml) (la propagación y el `default(..., true)`)
- [docs/informe-estado-del-arte-2026-11.md](../informe-estado-del-arte-2026-11.md) (§6.3, medido)
