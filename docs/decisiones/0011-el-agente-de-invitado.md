# ADR 0011 — El agente de invitado: lo que el motor puede LEER, y lo que sigue sin poder

<!-- PROPÓSITO: dejar escrito por qué el motor enciende el agente de invitado de Proxmox
     (`agent: 1`) en TODA VM que crea, y por qué el privilegio `VM.GuestAgent.Audit`
     sale de la lista de VEDADOS. Nace de una medida del lab `research` (labs/05_research/):
     un CHR de RouterOS trae el agente de FÁBRICA --agente 2.10.50, 21 comandos-- y
     contesta en cuanto la VM nace con la opción puesta. Dentro del router no se instala
     nada, y el interruptor es una línea de la config de la VM.
     INVARIANTES: al motor se le concede `VM.GuestAgent.Audit`, y SÓLO eso. Medido en el
     código de PVE del propio nodo (`/usr/share/perl5/PVE/API2/Qemu/Agent.pm`), `Audit`
     cubre lecturas --`network-get-interfaces`, `get-osinfo`, `get-host-name`, `get-time`,
     `info`, `ping`--; `exec` pide `VM.GuestAgent.Unrestricted` y los ficheros, `FileRead`
     /`FileWrite`. Esos cuatro SIGUEN VEDADOS: son la vía de acceso al interior que la regla 12 no
     permite. Toda lectura del agente pasa por la PUERTA (`tasks/pve_api.yml`) y deja su
     línea en `logs/api.jsonl`: si no se puede leer por la vía de acceso, no se lee. El agente se
     enciende al NACER, nunca se cambia en caliente: el canal aparece al arrancar y añadirlo
     a una VM viva obligaría a reiniciarla (misma razón que la consola serie y el bus del
     disco). Una lectura que falla --sin privilegio en la ACL del nodo, o una VM que no nació
     con agente-- se TOLERA y se dice en el informe: el motor sigue a ciegas como antes, pero
     no finge ver.
     LÍMITES: esto alcanza a las VMs QEMU. Un contenedor LXC ya declara sus interfaces por
     `GET /nodes/<n>/lxc/<vmid>/interfaces` y no necesita agente. Una VM nacida ANTES de este
     cambio no lo tiene y no se le puede poner sin reiniciarla: su dirección sigue siendo
     invisible hasta que se rehaga (`destroy` + `apply`). La REGLA de elección de la dirección
     de gestión (contar por ARRIBA, `.254`…) NO cambia: con el conjunto de direcciones usadas
     completo, contar por arriba ya es correcto, y cambiarlo movería la dirección de los
     bastiones que ya existen. Y `POST /agent/shutdown` (que no pide `Audit` sino
     `VM.PowerMgmt`, ya concedido) NO se usa: un apagado limpio es otra decisión.
     VER: deployment_engine/tools/plan.py (el nacimiento), deployment_engine/vars/engine.yml
     (los privilegios), deployment_engine/tasks/addresses.yml (la lectura),
     deployment_engine/filter_plugins/estado.py (estado_con_direcciones),
     labs/05_research/05_research.md (la medida), docs/decisiones/0004-*.md (la guarda),
     ./lab check privilegios -->

**Estado:** aceptada; medida en el lab `research` (VPS, CHR 7.25.1) con su A/B, y pasada
por el ciclo `destroy → apply → verify` del lab de aceptación `04_lab-red-routeros`.

**Contexto.** El motor elige la dirección de la interfaz de gestión del bastión
preguntándole al nodo qué direcciones están ya en uso. Para eso le pregunta a cada
**contenedor** del clúster (`GET /nodes/<n>/lxc/<vmid>/interfaces`), y lo dice por escrito en
tres sitios (`filter_plugins/estado.py` dos veces, `tasks/addresses.yml` una): **la
dirección de una VM QEMU no se puede saber por API**. Su config no lleva `ip=` --lo configura
el invitado por dentro-- y no hay endpoint de interfaces para VMs. Por eso, cuando hay que
elegir una dirección libre, el motor cuenta **por arriba** (`.254`, `.253`…) *a ciegas*: es
una apuesta a que las VMs ajenas no estén arriba. Está escrito en el propio código: *«haría
falta el agente de invitado, que aquí no está»*.

Y no estaba por una decisión, no por un olvido: `VM.GuestAgent.*` figuraba en
`engine_privilegios_vedados`, con esta razón: *«sería un túnel al interior que no pasa por
las vías de acceso del motor (regla 12)»*.

**La medida (lab `research`).** Un CHR 7.25.1, nacido del motor. Con `agent: 0` --como nace
hoy toda VM-- el nodo no tiene ni el socket del agente (`/var/run/qemu-server/<vmid>.qga`) y
nadie contesta. Con `agent: 1` el socket existe y **RouterOS contesta**: `guest-get-osinfo`
→ `{"id":"routeros","variant":"CHR","machine":"x86_64"}`; `guest-get-host-name` → el nombre
que le puso el motor; `guest-network-get-interfaces` → `ether1`, con su MAC derivada y
`10.41.0.11/24` -- **exactamente el dato que el motor decía no poder leer**. No se instaló
nada dentro del router: el agente viene de fábrica en la imagen.

**La decisión, en cuatro partes.**

1. **Toda VM nace con `agent: 1`.** Es una decisión de nacimiento --el canal aparece al
   arrancar-- y una regla genérica del motor, no un valor de ningún lab (regla 7). El motor
   no pregunta si el invitado lo va a saber usar: un invitado sin agente simplemente no
   contesta, y eso se tolera.

2. **`VM.GuestAgent.Audit` sale de los VEDADOS y entra en el rol de `/vms`.** Porque la razón
   por la que estaba vedado --«un túnel al interior que no pasa por las vías de acceso»-- no se
   sostiene para `Audit`: las llamadas a `/agent/*` SE HACEN a la API de Proxmox, pasan por
   `tasks/pve_api.yml` y dejan su línea en el diario. Y porque lo que concede es corto y
   está medido en el código del nodo: **lecturas y `ping`**. `exec` exige
   `VM.GuestAgent.Unrestricted` y los ficheros `FileRead`/`FileWrite`
   (o `Unrestricted`): esos cuatro **siguen vedados**, que es lo que mantiene la regla 12 en
   pie. `shutdown` no pide `Audit` sino `VM.PowerMgmt`, que el rol ya tiene: queda disponible,
   pero no se usa (ver LÍMITES).

3. **`addresses.yml` lee también las VMs**, por el agente, con el error TOLERADO. Así
   `direcciones_usadas` deja de estar cojo. Con el privilegio en la ACL del nodo, el motor
   ve por fin lo que antes sólo podía esquivar; sin él, cada lectura diaria un error y el
   motor se queda como estaba -- más pobre, pero igual de honesto.

4. **La regla de elección NO cambia.** Se sigue contando por arriba. Lo que cambia es que
   ahora se sabe qué direcciones están ocupadas, así que contar por arriba es correcto por sí
   solo. Cambiar la regla movería la dirección de los bastiones ya desplegados, y eso
   es tocar el mundo por una preferencia estética.

**Lo que esto NO es.** No es un túnel nuevo al interior: el motor no puede leer ni escribir
un fichero dentro de un invitado, ni ejecutar nada (salvo que alguien conceda
`Unrestricted`, y la guarda lo impediría). Es un canal de **lectura** que el hipervisor ya
tenía y que el motor estaba ignorando; configurarlo todo sigue siendo por su pasarela
(REST del router, SSH del Linux).

**Cómo se aplica, y en qué orden.** El privilegio se declara en el repo (`vars/engine.yml`,
en el rol `NetlabsMotorVms`) **y** se concede en el nodo, porque un mínimo que no se prueba
es una intención:

```sh
pveum role modify NetlabsMotorVms --privs VM.GuestAgent.Audit --append
```

Es aditivo y no abre ninguna ventana: el rol ya está puesto en `/vms` (para el usuario y
para el token) y sólo se le suma una capacidad. Al revés que cuando se recorta un privilegio,
aquí no hay que crear el nuevo antes de quitar el viejo. `./lab check` compara después la
declaración con el nodo; si divergen, lo dice. Lo único que el motor NO puede hacer por sí
mismo es esto de aquí: su token no administra permisos a propósito (`Permissions.Modify` y
`Sys.Console` están vetados), así que el `pveum` lo corre una persona con root en el nodo.
