# El camino del puesto de control

<!-- PROPÓSITO: explicar CÓMO el motor entra en la red de un lab. No es una receta para un
     humano: no hay nada que pegar a mano. El camino lo construye, lo arranca y lo comprueba
     el motor (tasks/camino.yml + tasks/camino_consola.yml + tools/consola.py).
     INVARIANTES: el motor no toca el hipervisor (ni rutas, ni NAT, ni ficheros suyos) y no
     abre ninguna puerta que no sea la suya. El túnel sale del INVITADO hacia casa, no al
     revés. La comprobación es de punta a punta: sólo vale si el puerto reenviado del nodo de
     control contesta.
     LÍMITES: la consola no devuelve código de salida (se reconoce una MARCA en el eco); el
     billete de consola vive 40 s (medido en PVE 9.2); el invitado tiene que existir, estar
     arrancado y tener dirección en el bridge de gestión del nodo, o el túnel no sale.
     VER: docs/decisiones/0004-el-camino-y-el-token.md; deployment_engine/tasks/camino.yml;
     deployment_engine/tasks/camino_consola.yml; deployment_engine/tasks/camino_mundo.yml;
     deployment_engine/tools/consola.py;
     ./lab check puerta -->

## El problema

El motor corre **en casa**; el lab vive en un **VPS**. Entre los dos hay internet, y del lado
del nodo no hay ninguna puerta hacia las redes internas del lab. La API de Proxmox no ayuda a
ejecutar nada dentro de un invitado: `POST /nodes/<n>/lxc/<vmid>/exec` es **501** en PVE 9.x, y
el resto de métodos no saben hablarle a la shell de nadie. Configurar el interior de un
invitado exige, por tanto, una puerta **de verdad**: una dirección a la que conectar y un
camino de ida y vuelta.

## La pieza: un puesto de control por lab

Cada lab declara un invitado con **`rol: control`**: un LXC Linux como cualquier otro, pero con
dos cosas que ningún otro tiene.

- **Sus patas**: una por cada bridge del lab más una en el bridge de **gestión** del nodo (esta
  ÚLTIMA, porque es la única con puerta por defecto y es por donde sale hacia casa). Las decide
  el motor, no la declaración (`patas_del_puesto_control`).
- **Su `camino`**: un área declarada (`config.linux.camino`) que le dice al motor que este
  invitado es la unidad de salida del lab y que hay que construirle el túnel.

Este puesto **sale hacia casa con `ssh -R` por el 443 público** del nodo de control, y deja
reenviado un puerto local. A partir de ahí el motor entra en el lab por ese puerto, usando el
puesto como **bastión** (`ProxyJump`): el primer salto de cualquier conexión al interior es
siempre `localhost:<puerto>` en la máquina del motor. Se descartó el túnel al propio nodo de
Proxmox y la plantilla-aparato (el porqué, en ADR 0004).

## El puerto se deriva, no se guarda

El puerto local del nodo de control que el invitado deja reenviado es
**`engine_camino_puerto_base` + el vmid** del puesto (p. ej. base `20000` y vmid `200` →
`20200`). No se guarda en ningún sitio: se re-deriva, como el resto de la identidad. Si el
invitado se rehace, cambia de vmid y por tanto de puerto — y el `authorized_keys` de casa hay
que rehacerlo (ver «lo que mordió»).

## El camino, paso a paso

`pasos_del_camino` (en `filter_plugins/interior.py`) emite hasta dos pasos, y su orden importa:

### 1. `construir_camino` — el arranque

Tiene tres piezas, en este orden:

1. **La clave pública del motor se deja DENTRO del invitado al CREARLO** (`ssh-public-keys` en
   el `POST /lxc`): por ahí entra Ansible después. Es una decisión de **nacimiento**: una vez
   creado el invitado ya no se puede meter, y uno que nació sin ella **se rehace**. El motor
   necesita saber su clave pública **antes** de calcular el plan (`camino_solo_clave: true`,
   que `apply` llama antes de `plan` y que `plan`/`preflight` no pueden generar: mirar qué haría
   el motor no debe crear ficheros).
2. **En casa se añade UNA línea al `authorized_keys` del nodo de control** con
   `restrict,port-forwarding,permitlisten="<puerto>"`. La clave **no da shell**: sólo autoriza
   ese reenvío, y sólo en ese puerto. La clave es **UNA POR LAB**
   (`~/.ssh/netlabs_camino_<lab>_ed25519`): el comentario de la línea es
   `netlabs_v4_b-camino-<lab>-<puerto>`, y al rehacer se quitan **sólo** las líneas viejas de
   **ese** lab (filtradas por el comentario, nunca por descarte: ese `authorized_keys` no es del
   motor, también tiene la clave personal del usuario).
3. **Por la consola del invitado se manda UNA línea, en base64**, que levanta el túnel
   (`ssh -R <puerto>:127.0.0.1:22` hacia el nodo de control). El invitado **todavía no tiene
   ninguna red por la que recibirla** — ése es justo el motivo de usar la consola: existe desde
   que el invitado arranca. La línea va en base64 para que lo que viaja sea **una palabra** sin
   espacios ni comillas; lo que el invitado ejecuta lo decide el **guion**, no la shell de
   nadie. El guion es **idempotente** (reescribe una unidad de systemd y la reinicia), así que
   reintentar no hace daño.

### 2. `comprobar_camino` — la prueba de punta a punta

El motor sondea `localhost:<puerto>` en su propia máquina y exige que conteste. Eso demuestra
la cadena **entera** (casa → 443 → puesto → vuelta), no una parte. Si el camino **ya**
responde, la mitad 1 **no se emite** (reconstruir un túnel que funciona en cada `apply` sería
el error que este plan evita); la comprobación, en cambio, se emite **siempre**: es una lectura
y `apply` tiene que poder decir que el camino está en pie **ahora**, no que lo estuvo. Quién
decide que «ya responde» es `tasks/camino_mundo.yml`: un sondeo **local** (un `wait_for` a
127.0.0.1:<puerto>) que se hace **antes de planificar** y deja el resultado en el estado del
mundo (`estado.camino.responde`), porque un puerto que contesta no se puede fingir.

## La consola: el único fichero que habla ese protocolo

La consola de Proxmox (`termproxy` + `vncwebsocket`, la misma del navegador del nodo) vive en
`tasks/camino_consola.yml`, y el protocolo en `tools/consola.py` (websocket con la biblioteca
**estándar**, sin dependencias). Reglas que no se aflojan:

- Es **la única** puerta que habla ese protocolo (`./lab check puerta` lo vigila). Exige el
  privilegio **`VM.Console`** (sin él: `403 Permission check failed (/vms/<vmid>, VM.Console)`).
- El **billete vive 40 segundos** (medido en PVE 9.2): pedirlo y abrir el websocket son **el
  mismo paso**, dentro de `consola.py`.
- **La consola no devuelve código de salida.** Se reconoce el **eco** del terminal. Por eso el
  guion termina imprimiendo una **MARCA** de éxito/fallo, y el motor la busca en el eco: si no
  lee ninguna marca, **no se da por bueno**, para y lo dice. Y la marca **no puede aparecer en
  el texto tecleado** (el eco de entrada la imprimiría antes de que el comando corra, falso
  positivo): la genera el propio guion.
- **Una llamada = una línea** en `logs/camino.jsonl`, salga bien o mal. El token **nunca** se
  escribe en el diario (va con `no_log`).

## Lo que mordió, medido

- **Un LXC nace con `cmode: tty`** y su consola pide usuario y contraseña. El plan manda
  `cmode=shell` **al crear** (después no se puede: `cmode` no se arregla en marcha).
- **Recién arrancado, la consola todavía no da shell**: la primera línea se pierde y hay que
  **reintentarla**. Como el guion es idempotente, reintentar no hace daño.
- **La clave por lab no es un capricho**: en `authorized_keys` OpenSSH usa la **PRIMERA** línea
  cuya clave case, así que una sola clave con una línea por lab deja **mudos a todos los labs
  menos al primero**, y sin dar error (`Remote: port forwarding refused`, apuntando al
  `permitlisten` de la línea que sí casó).
- **Filtrar el `authorized_keys` por el comentario del motor, siempre**: «todo lo que no sea
  mío» borra la clave personal del usuario (pasó; había copia).
- **La pata de gestión va la ÚLTIMA** (es la única con puerta por defecto) y las del lab van
  primero, para que `eth0` signifique lo mismo en cualquier nodo.

## Qué se descartó

El **túnel al propio nodo de Proxmox** y la **plantilla-aparato**. El razonamiento y las
medidas que los descartaron están en **ADR 0004** (`docs/decisiones/0004-el-camino-y-el-token.md`).
