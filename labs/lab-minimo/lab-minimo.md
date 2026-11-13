<!-- PROPÓSITO:   el documento del lab `lab-minimo`.
     INVARIANTES: la región generada la reescribe `documentos.py`; la prosa es libre.
     LÍMITES:     no repite los valores de la tabla; los cita.
     VER:         AGENTS.md §Documentación -->
# lab-minimo

La topología más pequeña que el motor puede converger: **un bridge y un
contenedor**.

<!-- generado:inicio -->
_Datos derivados de `lab-minimo.yml`. Los reescribe `./lab check docs --actualizar`;
si los editas a mano, `./lab check docs` falla._

## Invitados declarados

| rol | tipo | escalón | cores | memoria (MB) | disco (GB) | bridge | dirección |
| --- | --- | --- | --- | --- | --- | --- | --- |
| workstation-1 | LXC | 1 | 1 | 256 | 4 | vmb-lab-minimo | 198.51.100.11/24 |

## Bridges del lab

| bridge | dirección del bridge |
| --- | --- |
| vmb-lab-minimo | 198.51.100.1/24 |

## Orden de arranque (escalones)

| escalón | roles |
| --- | --- |
| 1 | workstation-1 |

## Identidad: la deriva el motor, no la declara el lab

| rol | tipo | nombre canónico | vmid | MAC |
| --- | --- | --- | --- | --- |
| workstation-1 | LXC | lab-minimo-workstation-1 | — | — |

El **vmid** (el menor libre de *todo* el clúster) y la **MAC** (`BC:24:11` + los
bytes del vmid) los asigna `apply` leyendo el estado de Proxmox: no se declaran aquí y
no se guardan en ningún fichero del repositorio. Por eso estas dos columnas son un
guion hasta que exista un despliegue real.
<!-- generado:fin -->

## Por qué existe este lab

No es decorativo. Es la única forma de probar, **sin credenciales y sin Proxmox**,
que el motor no conoce ningún lab:

1. Los **mismos verbos**, sin tocar una línea de `deployment_engine/`, producen un
   plan **distinto** al del otro lab de ejemplo. Si el motor tuviera una lista de
   labs, o una banda de vmids por lab, este plan saldría de esa lista y no de la
   declaración.
2. Los conjuntos declarados por los dos labs (bridges, direcciones, nombres
   canónicos) son **disjuntos**: `./lab check colisiones` lo exige y falla si
   alguien duplica un bridge en dos labs.
3. Usa el **mismo vocabulario de roles** que cualquier otro lab. Un rol se llama
   igual en los dos labs a propósito: el nombre canónico lo desambigua el motor
   (`<lab>-<rol>`), que es exactamente el mecanismo que hay que demostrar.

## Cómo llevarlo a un Proxmox real

Igual que cualquier otro lab: rellenar `deployment_engine/secrets.yml`, sustituir
las direcciones (están en `198.51.100.0/24`, rango reservado para documentación por
la RFC 5737, inexistente en la realidad) y entonces
`./lab --lab lab-minimo plan --api`, `preflight`, `apply`, `verify`.

## Por qué así

Un solo escalón: no hay nada que esperar antes del contenedor. No hay VM, así que
este lab no ejercita la rama QEMU del plan; para eso está el otro ejemplo.

- **Lo verificado aquí:** el plan derivado de esta declaración es distinto del de
  `ejemplo-topologia` y no menciona ningún recurso que no esté declarado aquí.
- **Lo no verificado:** todo lo que exige un Proxmox alcanzable.

## Ver también (punteros al código)

- El asignador de identidad:
  [deployment_engine/filter_plugins/identidad.py](../../deployment_engine/filter_plugins/identidad.py)
- La comprobación de colisiones entre labs (este lab es su caso de prueba):
  [deployment_engine/tools/framework_check.py](../../deployment_engine/tools/framework_check.py)
- Una sola puerta a la API:
  [deployment_engine/tasks/pve_api.yml](../../deployment_engine/tasks/pve_api.yml)
