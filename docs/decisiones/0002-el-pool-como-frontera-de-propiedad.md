# ADR 0002 — El pool es la frontera de propiedad, y la identidad se deriva

<!-- PROPÓSITO: por qué no hay un fichero de asignaciones y cómo se sabe qué
     invitado es de qué lab.
     INVARIANTES: la identidad nunca se declara ni se guarda; se re-deriva leyendo
     el estado del sistema.
     LÍMITES: no decide cómo se elige el vmid, sólo de dónde sale esa decisión.
     VER: README.md §Identidad; AGENTS.md §Identidad -->

**Estado:** aceptada.

**Contexto.** Si el motor no conoce las topologías, ¿cómo sabe a qué invitado
pertenece un vmid, o cuál está libre? La tentación es un fichero de asignaciones en
el repositorio, o una banda de vmids reservada por lab.

**Decisión.** El **pool de Proxmox** es la frontera de propiedad: lo que está en el
pool es de este lab. Su nombre lo **deriva el motor** de la carpeta del lab, con su
prefijo: `lab_<carpeta>` (`identidad_pool`). El prefijo no es decoración: Proxmox exige
que un poolid **empiece por letra**, y la carpeta de un lab empieza por su número de
antigüedad (ADR 0016). La **descripción** de cada invitado, que escribe el propio motor,
lleva `lab=` y `rol=`. Con esas dos cosas, y leyendo la API, cada verbo reconstruye el
mapa rol→vmid. No hay fichero de estado, y tampoco hay bandas: el vmid es **el menor
libre de todo el clúster**.

**Por qué.** Un rango de vmids por lab se solapa en cuanto hay dos labs, y ese fue
exactamente el origen de los conflictos en el intento anterior. El pool es una
frontera que el propio hipervisor mantiene, y mirar todo el clúster (no sólo el pool)
hace que dos labs no puedan chocar de vmid **por construcción**, no por disciplina.

**Y se compara con el nombre derivado, no con el de la carpeta.** Medido: cuando la
comparación de la frontera se hacía contra el nombre de la carpeta, **ningún** invitado
propio se reconocía —todos caían del lado de «no es de nadie»—, así que el plan los veía
como ausentes y volvía a crear la topología entera con vmids nuevos en cada pasada: el
motor duplicaba el lab y dejaba de ser idempotente (regla 6), sin un solo error en el
diario. Una frontera que se lee con dos nombres distintos no es una frontera. Hoy la
deriva `identidad_pool` en un solo sitio y **la usan todos** los que preguntan de quién
es algo: el estado, el asignador, el plan y `destroy`. La prueba está en
`test/test_identidad.py` (caso 8: la forma CRUDA de `/cluster/resources` → estado →
identidad, y el invitado propio conserva su vmid).

**El hueco: los bridges.** Un pool contiene **invitados**, no interfaces de red, así
que la frontera de propiedad no dice nada de un bridge. Y el plan crea un bridge
**sólo si falta**, de modo que un lab puede encontrarse uno que ya estaba en el nodo:
por el nombre declarado no se puede saber quién lo creó. Por eso el plan escribe en el
`comments` de cada bridge que **crea él** la marca `lab=<lab> gestionado por
netlabs_v4_b`, y `destroy` exige **las dos** pruebas: esa marca, y que ningún invitado
de fuera del lab lo esté usando —mirando **todas** sus interfaces, y conservando el
bridge si la config de alguno no se pudo leer—. Un bridge sin marca no se adopta: se
conserva y se dice por qué. Es la misma regla de siempre, aplicada a lo que no cabe en
un pool: **en la duda, el lado que no rompe nada**.

**Consecuencia.** Un invitado borrado a mano no se recupera del repositorio: se
declara como falta y `apply` lo recrea. La disjunción de vmids no se puede probar sin
credenciales; la de lo declarado (bridges, direcciones) sí, y la vigila el check
`colisiones`. Las dos cosas se dicen, y no se maquillan.

**Traducción al código:** la frontera de propiedad y la reconstrucción de rol→vmid se
leen en [deployment_engine/filter_plugins/estado.py](../../deployment_engine/filter_plugins/estado.py),
y el asignador puro en
[deployment_engine/filter_plugins/identidad.py](../../deployment_engine/filter_plugins/identidad.py).
