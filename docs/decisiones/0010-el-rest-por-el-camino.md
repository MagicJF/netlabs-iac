# ADR 0010 — El REST por el camino: el motor llama, el puesto hace de camino

<!-- PROPÓSITO: dejar escrito por qué la puerta de RouterOS dejó de DELEGAR la llamada en
     el puesto de control y pasó a hacerla el motor en su propia máquina, con el puesto
     reenviando el puerto 80 de cada router por el mismo túnel que ya usaba para la
     consola. Nace de una MEDIDA: la llamada delegada costaba 4,39 s por petición --y el
     45 % del tiempo de `apply`--, mientras que la misma llamada hecha en el motor cuesta
     0,50 s. No es una optimización de red (el TCP al router era 3 ms): es el coste de
     copiar e invocar Python por SSH en cada petición.
     INVARIANTES: el motor NO usa `delegate_to` en ningún sitio: hay un solo lugar donde
     se ejecutan las llamadas, y es la máquina donde corre Ansible. La puerta sigue siendo
     `tasks/ros_api.yml` y sigue escribiendo una línea por petición en `logs/api.jsonl`
     (regla 12). El puerto local por el que se llega a cada router es hermandad del puerto
     del camino y sale del vmid: NADA derivado se guarda (regla 11). Lo que se diariza y lo
     que se lee en los errores sigue siendo la dirección del INVITADO; el puerto es sólo el
     transporte. Un túnel que no reenvíe esos puertos se declara CAÍDO y el plan lo
     reconstruye: el cambio se auto-repara en el siguiente `apply`.
     LÍMITES: esto NO cambia cómo se configura un Linux: su interior sigue entrando por SSH
     (regla 12), y ahí la conexión termina en el invitado porque ése ES el diseño. El
     reenvío sólo se abre para los equipos que la DECLARACIÓN declara con
     `config.routeros`: el vocabulario es cerrado y no se abre un puerto de más. El HTTP
     sigue en claro (el CHR de fábrica no trae certificado, ADR 0006). Y sólo reenvía el
     puerto 80: si algún día un RouterOS se configurara por 443, esto se para y se pregunta.
     VER: deployment_engine/tasks/ros_api.yml (la puerta),
     deployment_engine/tasks/configurar_routeros.yml (el driver),
     deployment_engine/tasks/camino.yml (el túnel y la línea autorizada),
     deployment_engine/tasks/camino_mundo.yml (la sonda que lo repara),
     deployment_engine/filter_plugins/interior.py (puerto_rest_camino,
     patas_rest_del_puesto_control, guion_camino), docs/camino-del-puesto-de-control.md,
     informe-rendimiento-despliegue.md -->

**Estado:** aceptada; medida contra el VPS (lab de aceptación `04_lab-red-routeros`, ciclo
`destroy → apply → apply → verify` en verde con `changed=0` en la segunda pasada). Las 99
llamadas REST del `apply` pasan de **4,39 s** a **0,50 s** de media (mediana 465 ms): la
puerta baja de **434,5 s a 49,7 s** y el `apply` entero, de **1.028,7 s a 650 s**.

**Contexto.** El motor no llega solo a la red del lab: desde la máquina donde corre Ansible
no hay ruta a `10.40.x.x`, que son redes internas del hipervisor. La solución del ADR 0004
fue el **camino**: el puesto de control abre un túnel inverso hacia casa y el motor entra en
el lab por él. Pero para hablar con el **REST** de un RouterOS —que es la única puerta a un
CHR (regla 13)— la primera versión **delegaba** la llamada en el puesto (`add_host` +
`delegate_to`), porque es el único que tiene una pata en cada bridge del lab.

Eso funcionaba, pero medido (informe-rendimiento-despliegue.md) costaba **4,39 s por
petición**, y un `apply` del lab de aceptación hace 99 peticiones: **434,5 s, el 45 % del
tiempo total**. El diagnóstico fue claro: la red no tenía la culpa (3 ms de TCP al CHR;
0,15 s haciendo la misma petición con `urllib` en Python desde el motor). El coste era el
**transporte**: cada llamada obligaba a copiar e invocar un intérprete de Python por SSH en
el puesto. Y, además, dejaba las llamadas repartidas en dos máquinas, que es justo lo que no
se quiere: **un solo sitio donde ocurren las cosas**.

**Decisión.** El motor hace **todas** las llamadas, en su propia máquina, y el puesto de
control **sólo hace de camino**. Concretamente:

1. **El túnel del camino reenvía, además de su propio sshd, el puerto 80 de cada router.**
   El guion que el puesto levanta (`guion_camino`) gana un `-R` por equipo:
   `-R 21102:10.40.0.11:80`. Es el MISMO túnel, la MISMA conexión y la MISMA clave: no hay
   un segundo mecanismo que mantener, ni un agente dentro del router.

2. **El puerto local sale del vmid del invitado** (`puerto_rest_camino` = `21000 + vmid`),
   igual que el puerto del camino (`20000 + vmid`). Derivado, no guardado (regla 11), y en
   una banda distinta para que las dos no se pisen.

3. **Quién recibe pata lo dice la declaración**: los equipos con `config.routeros`
   (`patas_rest_del_puesto_control`). No se abre el REST a un Linux ni a un invitado sin
   interior: el vocabulario es cerrado y un puerto abierto de más es un puerto de más. Un
   equipo sin dirección declarada (o en `dhcp`) no entra: no hay a dónde reenviar, y
   fingirlo en el guion sería mentir.

4. **La línea de `authorized_keys` autoriza los puertos del túnel, no uno**: con una opción
   `permitlisten` **repetida** por cada puerto
   (`permitlisten="20103",permitlisten="21102"`), y la clave del camino sigue sin dar shell
   ni ejecutar comandos. La FORMA importa: con una lista dentro de una sola opción
   (`permitlisten="20103,21102"`) sshd **no encuentra la clave** y contesta
   `Permission denied (publickey)` — un error que señala a la clave, no al `authorized_keys`
   (se comió una pasada entera del ciclo de aceptación). Los puertos los calcula UNA vez
   `camino.yml` (`interior_permitlisten`) y los usan los dos sitios que tienen que decir lo
   mismo (la línea autorizada y el guion); el plan pinta esa misma forma, así que lo que se
   lee y lo que se escribe no se pueden separar.

5. **La sonda del camino mira también los puertos de REST** de los routers que YA existen
   (`camino_mundo.yml`). Es lo que hace el cambio **auto-reparable**: un túnel construido
   antes de este cambio está en pie pero no reenvía los REST, así que el camino se declara
   caído, el plan reemite `construir_camino` y el túnel se rehace solo. Sólo se sondean los
   routers que existen (en la primera pasada no hay ninguno y no se fuerza nada), y la sonda
   mira si el **reenvío** está puesto —no si el router contesta—, así que un router parado
   no dispara una reconstrucción por nada.

6. **La puerta no cambia de forma**: sigue siendo `tasks/ros_api.yml`, sigue dejando una
   línea por petición en `api.jsonl` con su `api: routeros` y su rol, y sigue tapando las
   credenciales por su nombre. Lo único que cambia es a qué URL llama
   (`http://127.0.0.1:<puerto>/rest...`) y que ya no lleva `delegate_to`. Si no hay puerto,
   la puerta **para** y dice el remedio (regla 16), en vez de fallar con un error de
   conexión que no explica nada.

**Lo que se descartó, y por qué.**

- **Un SOCKS/`-D` dinámico**: obligaría a que `uri` supiera usar un proxy. El módulo no lo
  soporta, y meter un proxy por variables de entorno choca con la regla 3 (sin entorno, by
  design).
- **Reenviar el REST de todos los invitados** (no sólo los routers): serían puertos abiertos
  de más, y un Linux se configura por SSH, no por REST.
- **Dejar el `delegate_to`**: es el coste medido que este ADR viene a quitar, y reparte las
  llamadas en dos máquinas.
- **Rebanar el túnel en cada `apply` para "refrescarlo"**: reconstruir un túnel que funciona
  es exactamente el error que el plan del camino viene a evitar (usa la consola, que es
  cara). La sonda de los puertos consigue lo mismo sin tocar nada cuando ya está bien.

**Consecuencias.**

- Las llamadas pasan de **4,39 s a 0,50 s** de media (99 llamadas del `apply`: 434,5 s →
  49,7 s de suma; el `apply` entero, de 1.028,7 s a **650 s**). El grueso del tiempo de
  `apply` deja de estar en RouterOS.
- El motor no tiene **ningún** `delegate_to`: hay un solo sitio donde se ejecutan las
  llamadas, que era el objetivo.
- El túnel pasa a ser algo más que "la consola del puesto": es **la puerta de red del lab**,
  y su sonda comprueba las dos cosas que sirve.
- Un lab sin `config.routeros` no cambia en nada: sin patas de REST, el guion es el de
  antes, byte a byte.
- **Lo que mordió, para que no vuelva**: `permitlisten` se REPITE, no se lista dentro de una
  opción. La forma mala no rompe nada de forma ruidosa —sshd contesta `Permission denied` y el
  motor se queda sin camino—, así que hay un test que mira la FORMA del texto, no sólo que
  estén los números.
- Si un día el REST de un RouterOS dejara de ir en el puerto 80, hay que tocar
  `PUERTO_REST_ROUTEROS` en un solo sitio (`interior.py`) y volver a medir: la constante
  existe para que no haya dos números iguales que se puedan separar.
