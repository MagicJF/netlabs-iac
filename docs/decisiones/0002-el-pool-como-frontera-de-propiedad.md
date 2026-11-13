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

**Decisión.** El **pool de Proxmox**, llamado como la carpeta del lab, es la frontera
de propiedad: lo que está en el pool es de este lab. La **descripción** de cada
invitado, que escribe el propio motor, lleva `lab=` y `rol=`. Con esas dos cosas, y
leyendo la API, cada verbo reconstruye el mapa rol→vmid. No hay fichero de estado, y
tampoco hay bandas: el vmid es **el menor libre de todo el clúster**.

**Por qué.** Un rango de vmids por lab se solapa en cuanto hay dos labs, y ese fue
exactamente el origen de los conflictos en el intento anterior. El pool es una
frontera que el propio hipervisor mantiene, y mirar todo el clúster (no sólo el pool)
hace que dos labs no puedan chocar de vmid **por construcción**, no por disciplina.

**Consecuencia.** Un invitado borrado a mano no se recupera del repositorio: se
declara como falta y `apply` lo recrea. La disjunción de vmids no se puede probar sin
credenciales; la de lo declarado (bridges, direcciones) sí, y la vigila el check
`colisiones`. Las dos cosas se dicen, y no se maquillan.

**Traducción al código:** la frontera de propiedad y la reconstrucción de rol→vmid se
leen en [deployment_engine/filter_plugins/estado.py](../../deployment_engine/filter_plugins/estado.py),
y el asignador puro en
[deployment_engine/filter_plugins/identidad.py](../../deployment_engine/filter_plugins/identidad.py).
