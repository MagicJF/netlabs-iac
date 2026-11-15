# 0016 — Los labs se numeran por antigüedad, y el número lo pone el wrapper

*Fecha: 15-nov-2026 — Estado: aceptada y aplicada — Ámbito: `labs/` y el wrapper `./lab`
(`orden_new`), no el motor*

## El problema

Los labs se llamaban por lo que eran (`conectividad-exterior`, `lab-dos-redes`) y nada decía
**cuándo** se hicieron. En una carpeta con seis labs, el orden alfabético no es el orden en que
se aprendió nada: `research` cae en medio, y dos labs de la misma semana quedan separados por
una letra. Quien llega nuevo al repositorio —o quien vuelve seis meses después— no puede leer
la historia en `ls labs/`.

Y hay una segunda mitad: si el prefijo se pone a mano, el día que se crea un lab «entre medias»
alguien reutiliza un número o deja un hueco sin querer, y el orden deja de significar nada.

## La decisión

**1. La carpeta del lab lleva delante su número de antigüedad: `NN_<nombre>`.**

`01_ejemplo-topologia`, `02_lab-minimo`, `03_lab-dos-redes`, `04_lab-red-routeros`,
`05_research`, `06_conectividad-exterior` — en el orden en que se crearon de verdad (medido con
`git log --diff-filter=A` sobre cada carpeta, no recordado). El número va **delante** de todo lo
demás, así que `ls labs/` se lee de arriba abajo en orden histórico.

El nombre del lab **es** el de la carpeta (el pool de Proxmox se llama como la carpeta: es la
frontera de propiedad), así que el `lab.nombre` del YAML y los ficheros de dentro cambian con
ella: `labs/06_conectividad-exterior/06_conectividad-exterior.{yml,md}`.

**2. El número lo pone `./lab new`, no la mano de quien escribe.**

`./lab new <nombre>` scaffoldea `labs/NN_<nombre>/`, donde `NN` es **el mayor que ya hay, más
uno**. Se mira el mayor y no la cuenta a propósito: si un lab se renombra o su carpeta
desaparece, su número **no se reutiliza** y el orden histórico no se falsea. Se puede pedir un
número concreto escribiéndolo (`./lab new 07_lo-que-sea`) para el caso legítimo de insertar algo
donde corresponde; lo que no se puede es dejar que dos labs compartan prefijo, porque el wrapper
lo comprueba antes de crear nada.

Esto no es una regla del **motor** (que sigue sin saber que existe `labs/`: regla 8), y por eso
vive en el wrapper: el prefijo es una propiedad del **repositorio**, no del lab.

## Lo que esto NO cambia

- Nada del motor: ni una línea de `deployment_engine/` sabe que los labs están numerados.
- La identidad de los invitados: el nombre de cada invitado ya no lleva el lab (ADR 0015), así
  que renumerar no toca ni un nombre de invitado.
- Los diarios: `labs/NN_<lab>/logs/` viaja con la carpeta; lo que ya estaba escrito, escrito
  queda (es la prueba de lo que pasó, y no se reescribe: regla 5).

## Cómo se comprueba

- `./lab list` enumera los seis labs en orden, con su carpeta.
- `./lab new prueba-numeracion` crea `labs/07_prueba-numeracion/` y lo dice; `rm -rf` de la
  carpeta lo deshace (no se sube nada a Proxmox).
- `python3 test/test_regresion_planes.py` y el resto de la suite, en verde: la referencia de los
  planes de la fase 1 se regeneró a mano por este cambio (y lo dice en su cabecera).
- `./lab check` en verde: los checks leen `labs/` por lo que es, no por cómo se llame.
