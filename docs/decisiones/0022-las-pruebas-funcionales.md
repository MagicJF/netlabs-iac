# 0022 — Las pruebas funcionales: un verbo, un vocabulario cerrado y TRES salidas

*Fecha: 16-nov-2026 — Estado: aceptada y aplicada — Ámbito: CÓMO se comprueba que un lab HACE lo
que promete (verbo `test`)*

## El problema

`verify` contesta «¿existe de verdad lo declarado?» leyendo el mundo, área por área. Es una
comprobación enorme y necesaria, y **no contesta** la otra pregunta: ¿el lab *funciona*? Un
cortafuegos puede estar declarado regla a regla y aun así cortar lo que no debe (o dejar pasar lo
que no debe). Es el hueco nº1 del sector, y el motor no tenía forma de cerrarlo.

## La decisión

**1. Un verbo nuevo, `./lab test`**, con las pruebas **declaradas por el lab** en `tests:`. No hay
pruebas del motor: lo que se prueba es lo que el lab dice de sí mismo.

**2. El vocabulario es CERRADO y pequeño**: `ping` (¿contesta?), `servicio` (¿acepta conexiones
en su puerto?) y `dns` (¿resuelve un nombre?). Lo que no esté no se puede pedir.

**3. Tres salidas, y la tercera es la que lo hace honesto**: `0` (todas pasan), `1` (alguna
falla) y **`3` (OMITIDA)**, para cuando el ENTORNO no puede comprobar algo — `ping` sin
`CAP_NET_RAW`, un binario que no está. Sin el 3, un entorno pobre se disfrazaría de lab roto.

**4. Las pruebas se lanzan desde un invitado al que el motor LLEGA** (el bastión, el único con
túnel), y por eso se declara `desde:`. Es verificación funcional DEL LAB, no de cada invitado por
dentro.

**5. La ventana es corta por diseño** (`engine_prueba_intentos: 6`): una prueba **no** es una
barrera — si el lab hace lo que dice, pasa al primer intento, y si hace falta declarar `espera:`
en una prueba es que había una barrera que faltaba antes.

**6. Se deja evidencia**: un JSON por prueba en `labs/<lab>/logs/`, y un resumen en
`logs/ultimo-test.txt`.

## La trampa

- **Dentro de un `bash -c '...'` no puede haber NI UNA comilla simple.** Un `cut -d' '` en un
  comando cerraba el `bash -c` antes de tiempo y la prueba decía «falla» cuando lo que fallaba
  era el entrecomillado. Hay una prueba que lo vigila (`count("'") == 2`).
- **Una prueba `dns` necesita un nombre que EXISTA.** El ejemplo que traía el informe
  (`hacia: ejemplo.test`) falla, y no por el lab: medido en el mismo instante y por el mismo
  camino, `nacsira.com` resuelve y `ejemplo.test` no existe. El motor no inventa nombres; si un
  lab quiere probar un nombre SUYO, tendrá que declararlo (dnsmasq/hosts), vocabulario que
  todavía no está.
- **Y falta un tipo que espere un FALLO.** Hoy el vocabulario espera éxito, así que en un lab con
  cortafuegos **no se puede probar que lo que DEBE caer, cae** — que es la mitad del valor. Hace
  falta un `bloqueado`, y este ADR lo deja dicho: es lo primero que se ensancha cuando un lab lo
  pida.

## Qué NO se toca

- **`verify`**: sigue siendo el test final de lo declarado. `test` es OTRA pregunta, y no lo
  sustituye ni lo adelanta.
- **El interior de los invitados**: `test` mide, no configura. No escribe nada.
- **La confianza del código**: no se prueban implementaciones, se prueban contratos observables
  (un puerto, una conexión, una resolución).

## Cómo se comprueba

- **`test/test_interior.py`**: cada tipo se traduce a su comando, los códigos de salida, y el
  caso de la comilla.
- **`test/test_declaracion.py`**: un tipo fuera del vocabulario, un `desde` que no es un invitado
  del lab y una prueba que no dice `hacia`.
- **El ciclo real** (informe §6.2): 5 de 5 en el lab 06 y 5 de 5 en el 08 — este último probando
  el plano de gestión de cuatro CHR **con tres cortafuegos en medio**.

## VER

- [deployment_engine/filter_plugins/interior.py](../../deployment_engine/filter_plugins/interior.py)
  (`pruebas_de` y el vocabulario)
- [deployment_engine/tasks/prueba.yml](../../deployment_engine/tasks/prueba.yml) y
  [playbooks/test.yml](../../deployment_engine/playbooks/test.yml)
- [deployment_engine/vars/engine.yml](../../deployment_engine/vars/engine.yml)
  (`engine_prueba_intentos`)
- [docs/informe-estado-del-arte-2026-11.md](../informe-estado-del-arte-2026-11.md) (§6.2, medido)
