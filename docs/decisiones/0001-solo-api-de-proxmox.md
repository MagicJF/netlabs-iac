# ADR 0001 — Al hipervisor se le habla sólo por su API REST

<!-- PROPÓSITO: la decisión que no se quiere volver a discutir.
     INVARIANTES: ninguna vía de acceso al hipervisor que no sea la API.
     LÍMITES: no decide qué desplegar, sólo por dónde se le pide.
     VER: README.md §Las cuatro puertas, y un diario de cada una; AGENTS.md §Reglas duras -->

**Estado:** aceptada.

**Contexto.** Un motor de despliegue puede hablar con Proxmox de varias maneras:
SSH al nodo y `qm`/`pct`, `snippets` y `hookscripts` en el almacenamiento, o su API
REST. Las tres funcionan; sólo una es un contrato.

**Decisión.** Todo se hace con `https://<nodo>:<puerto>/api2/json`. La única puerta
es `deployment_engine/tasks/pve_api.yml`, con `ansible.builtin.uri`, y es a la vez
la que escribe el diario. El wrapper `./lab` no llama a la API: sólo lanza Ansible.

**Por qué.** SSH y los guiones de arranque son código que corre *dentro* del
hipervisor, con la versión de Proxmox como única interfaz: cambian sin avisar y no
dejan rastro consultable. La API es una interfaz estable, y cada llamada se puede
registrar. Y una sola puerta es lo que hace posible el check `puerta`: si hubiera
cinco sitios desde los que llamar, no habría ninguno del que fiarse.

**Consecuencia.** Lo que no se pueda hacer por API, se dice y se para; no se rodea.
La ausencia de `snippets`, `hookscripts`, `pct exec` y SSH al nodo es una regla, no
una casualidad del MVP.
