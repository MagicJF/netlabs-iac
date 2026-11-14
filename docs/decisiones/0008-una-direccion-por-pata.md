# ADR 0008 — Una dirección por pata: el puesto de control declara dónde tiene que estar

<!-- PROPÓSITO: dejar escrito por qué el vocabulario del interior de un Linux tiene un área
     `direcciones` (una lista de `{interfaz, direccion}`) y por qué el puesto de control la
     usa para poner una dirección POR PATA en los bridges del lab. Nace de una pared medida:
     converger el segundo CHR de un lab de aceptación murió con `No route to host` a su
     dirección de LAN.
     INVARIANTES: la dirección de una pata es DECLARADA, no inventada por el motor (regla 7);
     el MOTOR no adivina: el plan ya da a cada pata extra una dirección libre del nodo
     (`direccion_libre`, una REGLA), y si el lab la declara, esa manda. El driver converge el
     área `direcciones` con el patrón de todas: leer, decidir en los dos sentidos, escribir
     (poner lo declarado que falta, quitar lo declarado que sobra) y RELEER. El orden de las
     patas es el de ADR 0007 (la declarada primero, la de gestión del nodo la ÚLTIMA).
     LÍMITES: esto no cubre la pasarela, las rutas ni el dns de un Linux (áreas declaradas
     como pendientes en `interior.py`, la validación las rechaza con su motivo), ni cambiar
     las patas de un invitado en marcha (se rehace: `destroy` de ese invitado y `apply`).
     LÍMITES: el área es del driver Linux; un CHR declara sus direcciones por la suya
     (`config.routeros.direcciones`, ADR 0005/0006).
     VER: deployment_engine/filter_plugins/interior.py (patas_del_puesto_control, el área
     `direcciones`, areas_que_piden_visita), deployment_engine/tools/plan.py
     (_red_del_invitado), docs/decisiones/0007-las-patas-se-declaran.md,
     docs/decisiones/0005-el-driver-del-interior.md,
     labs/lab-red-routeros/lab-red-routeros.yml -->

**Estado:** aceptada; medida contra el VPS (lab de aceptación, escalón 2, CHR `nucleo`).

**Contexto.** El puesto de control es el bastión del lab: nace con **una pata por cada bridge
del lab** más la de gestión del nodo (ADR 0007), y por ahí dentro entra el motor a configurar
lo que cuelga de cada LAN (`ProxyJump` al puerto reenviado del camino). Esas patas extra las
decide el motor (`patas_del_puesto_control`), no la declaración: a cada una le da una
dirección **libre** del nodo (`direccion_libre`, que evita lo que el lab ya declara en ese
bridge). Es una regla, no un valor: el motor no conoce la topología.

Pero el vocabulario no sabía decir «esta pata tiene ESTA dirección». El lab no podía **fijar**
la dirección del puesto en un bridge concreto; sólo la derivaba el motor. La primera pasada
completa del lab de aceptación se paró al converger el segundo CHR (`nucleo`, `10.40.1.11`):

```
DRIVER ROUTEROS · ¿ya vale la credencial del motor en 'nucleo'?
  -> No route to host  (10.40.1.11)
```

**Decisión.** El interior de un Linux gana un área más: `config.linux.direcciones`, una lista
de `{interfaz, direccion}`. El lab declara, pata por pata, dónde tiene que estar el puesto de
control:

```yaml
config:
  linux:
    camino: {}
    direcciones:
      - {interfaz: eth1, direccion: 10.40.1.2/24}
```

El driver la converge como cualquier otra área: **leer** las direcciones reales de cada
interfaz, **decidir** en los dos sentidos (`poner_direccion` lo declarado que falta,
`quitar_direccion` lo que sobra), **escribir** y **RELEER**. La pata extra sigue naciendo con
su dirección derivada (así nunca está muda al arrancar); la declarada la **fija**, y el driver
retira la derivada que ya no se declara.

**Por qué así.** Podría haberse dejado sólo la derivada, pero entonces la dirección del puesto
en cada LAN sería un número que el motor elige y el lab no puede ni leer en su declaración ni
fijar (útil para documentar, para no chocar con algo de fuera, o para que dos labs del mismo
nodo no se pisen en un bridge compartido). El motor sigue sin adivinar topología: da una
dirección libre cuando no se declara (una regla), y obedece cuando se declara (regla 7).

**Lo que la medida dijo de verdad.** El `No route to host` tenía DOS sospechosos y conviene no
confundirlos, porque el ADR es para no volver a pagarlos:

1. la dirección del puesto en esa LAN, y
2. el **tiempo de arranque** del invitado.

La medida (esta pasada, con el diario delante) resolvió que el muro decisivo era el (2): el
plan **convergía un invitado nada más arrancarlo**, y un CHR tarda en bootear y en pedir su
dirección por DHCP. La dirección derivada de la pata ya estaba puesta desde el nacimiento del
puesto, así que la pata no era el problema. El arreglo del (2) es del PLAN, no del vocabulario:
**la sonda del escalón (`esperar_servicio`) va DELANTE del interior de cada invitado**, no al
final — sólo se converge lo que ya contesta. Va en la prosa del lab y en la skill; aquí queda
anotado para que el (1) no tape al (2). El área `direcciones` se queda igual: es una primitiva
legítima (fijar la dirección de una pata) y su conversión está probada, pero no era la pared.

**Consecuencias.**

- El puesto de control declara `eth1: 10.40.1.2/24` y `./lab check declaracion` valida que la
  interfaz exista (N patas ⇒ hasta `ethN`, la misma regla que RouterOS: ADR 0007).
- El área `direcciones` es del driver Linux y se prueba con fixtures (`test/test_interior.py`),
  sin Proxmox: declarado + leído → operaciones, en los dos sentidos.
- El motor sigue sin saber nada de ningún lab: una dirección libre es una regla
  (`direccion_libre`), y un número concreto sólo aparece si el lab lo declara.
