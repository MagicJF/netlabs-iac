# Registro de cambios

Lo que ha entrado en cada versión, de la más nueva a la más vieja. El formato es
[Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/) y el versionado
[SemVer](https://semver.org/lang/es/): `MAYOR.MENOR.PARCHE`.

Mientras la versión MAYOR sea `0`, el motor está **en desarrollo**: la declaración de un
lab y los verbos todavía pueden cambiar, y cualquier versión MENOR puede traer un cambio
que rompa. Es la regla de SemVer para la serie 0.x, y es la razón de que la primera
entrega sea `0.1.0` y no `1.0.0`: no hay nada estable que prometer todavía. La `1.0.0` se
publicará cuando lo haya —una declaración de lab que no queramos volver a tocar y
terceros usándola—.

El fichero `VERSION` lleva la **última versión publicada**, el tag `vX.Y.Z` la marca y
aquí está su entrada; los tres tienen que contar lo mismo, y eso es lo que vigila
`./lab check version`. Lo que entra en `main` sin publicarse se apunta bajo
`[No publicado]`, y se convierte en una versión el día que se publica.

## [No publicado]

### Añadido

- **CI offline** (`.github/workflows/ci.yml`, informe §6.5): en cada push a `main` y en cada pull
  request corren las pruebas del motor, `./lab check`, `ansible-lint` y `yamllint` **sin
  credenciales y sin tocar Proxmox**.
- **Los secretos pueden ir cifrados** (ADR 0025, informe §6.6): `deployment_engine/secrets.sops.yml`
  vive versionado y cifrado con sops/age, y el wrapper lo descifra al `secrets.yml` de siempre antes
  de lanzar nada. La clave se pasa con `--age-key-file` (bandera, no variable), así que el motor
  sigue sin leer el entorno.
- **El choque de vmid converge** (informe §6.7): si dos `apply` en paralelo eligen el mismo vmid, el
  motor re-lee el mundo, recalcula el plan y lo reintenta una vez — sin guardar estado en disco.
- **El diagrama de la topología, autogenerado** (informe §6.8): la región generada de cada lab lleva
  ahora un **Mermaid** derivado de la declaración (bridges como segmentos, invitados por tipo).
- **`./lab check secretos`** (ADR 0024): el candado de lo que abre el **nodo**. Caza en lo
  versionado el token de la API con su valor, un ticket de sesión, una clave privada y el propio
  `secrets.yml`, y se cierra en el hook de pre-commit mirando el **índice** —lo que va a entrar en
  el commit, no el árbol de trabajo—. Las credenciales de los labs se siguen citando en claro: la
  política es asimétrica, y ahora está escrita y vigilada en vez de confiada.

### Cambiado

- **La raíz en su sitio.** `informe-rendimiento-despliegue.md` se fue a `docs/`,
  `GOAL-capa-de-configuracion.md` a `docs/encargo-capa-de-configuracion.md`, y `analizar_perfil.py` y
  `perfilar.sh` a `scripts/` (herramientas de DESARROLLO). El mapa del README y de AGENTS.md ya
  mencionan `scripts/`, y las referencias internas están actualizadas.
- **El candado de los secretos, más fino.** Cierra las formas escurridizas que destaparon las
  revisiones: nombres de fichero no ASCII, claves entrecomilladas o en JSON, valores en la línea
  siguiente, valores entrecomillados con coma, comentarios entre comillas — y no bloquea un binario
  ni un fichero limpio con una línea hermana.
- **Fuera la configuración muerta.** Se fueron las claves `pve_ssh_usuario`/`pve_ssh_password`
  (ningún fichero del motor las leía, y el nodo no acepta contraseña), `engine_clave_tunnel` (la
  clave vive en el vocabulario del interior, no en una variable) y quince alias viejos del registro
  de filtros, más dos funciones que ya no llamaba nadie. Nada de eso se ejecutaba: por eso ningún
  lab cambia de comportamiento.

## [0.2.0] - 2026-11-16

### Añadido

- **El área `firewall` de RouterOS** (ADR 0019): un lab puede declarar la **tabla de
  filtrado entera**, en orden, con vocabulario cerrado (`chain`, `action`, `protocol`,
  `src_address`/`dst_address`, `src_port`/`dst_port`, `in_interface`/`out_interface`,
  `connection_state`, `comment`, `disabled`). Es la única área que converge **después de la
  credencial**, porque es la única capaz de dejar al motor fuera de su propio equipo; y el
  validador **rechaza** un `drop` de `input` sin un `accept` de `input` antes, que es
  exactamente esa situación.
- **El tipo de equipo `fw`** (`tipo: fw` → `fw-oficina`): una máquina cuya responsabilidad es
  filtrar, que es lo que permite repartir una topología en «1 máquina = 1 responsabilidad».
- **El lab `08_dunder-mifflin-con-fw`**: la versión con zonas del lab 07 — un router que
  enruta y sale, tres cortafuegos que filtran (uno por zona), ninguno con dos
  responsabilidades.
- **La tabla de accesos en el documento de cada lab** incluye, además del usuario y el
  método, el **valor** de la credencial con la que se entra y **de dónde sale**
  (`secrets.yml`). Es una decisión explícita para labs efímeros de aprendizaje: se citan
  para poder entrar, no porque el secreto importe.
- **`derived` en una dirección** (ADR 0020): el lab escribe la marca y el motor calcula el
  valor repartiendo en orden desde `lab.address_space` (la pasarela de cada bridge primero,
  los routers antes que los puestos). Un valor explícito manda. Es opcional y aditivo: donde
  no se declara, nada cambia.
- **`ready:` por invitado** (ADR 0021): el lab declara cuánto se le espera antes de
  configurar lo que va detrás —`tipo: ssh|routeros_rest|ninguno` y `espera:` en segundos—, y
  ahora también un invitado **sin `config:`** puede declarar su barrera (antes no podía
  ninguna). Sin `ready:`, cada invitado se comporta exactamente como antes.
- **`./lab test`** (ADR 0022): las **pruebas funcionales** que declara el lab (`tests:`, con
  `ping`, `servicio` y `dns`). Contesta lo que `verify` no puede —«¿el lab HACE lo que
  promete?»— con tres salidas: `0` OK, `1` KO y **`3` OMITIDA** cuando el entorno no puede
  comprobar algo (un `ping` sin privilegios no es un lab roto). Deja evidencia por prueba en
  `labs/<lab>/logs/`. Sólo prueba desde donde el motor llega (el bastión).
- **`./lab capture` y `./lab impair`** (ADR 0023): mirar el tráfico de un bridge y estropearlo
  desde el bastión, **acotado** (se aplica, se espera y se retira en el mismo comando, así que
  no queda un `netem` huérfano). Son experimentos: `apply` no los toca. Ojo a lo que hace el
  impairment: estropea el tráfico **del bastión**, no el del bridge.
- **El informe de estado del arte** (`docs/informe-estado-del-arte-2026-11.md`), con las cuatro
  P0 **medidas sobre labs reales**: lo que aporta cada una, lo que no hace, y el A/B en frío de
  un lab mínimo (665 s antes, 662 s después: no cuestan despliegue).

### Cambiado

- **El repositorio se llama `netlabs-iac`** (antes `netlabs_v4_b`): la versión y la
  variante salen del nombre, que era un sitio del que ya no podían salir nunca. El URL
  viejo de GitHub redirige. **El motor sigue escribiendo su marca `netlabs_v4_b`** en la
  descripción de cada invitado y en el comentario de cada bridge: esa marca es estado ya
  desplegado —de ella depende la propiedad de los bridges y la idempotencia—, así que
  cambiarla tiene su propia migración, y no va en este cambio.

### Arreglado

- **Una escritura que converge DESPUÉS del cambio de credencial viajaba con la de fábrica**,
  y RouterOS contestaba 401 a media convergencia (medido en el lab 08, ADR 0018). Ahora la
  capa pura marca cada llamada con la credencial que le toca (`credencial: motor`) y el
  driver la obedece.
- **`./lab plan` sin credenciales fallaba en cualquier lab con salida**: el fixture offline
  no modelaba la dirección del bridge de gestión del nodo.
- Un aviso de plantilla en `tasks/tunnel.yml`: una tarea hablaba de un rol que no existía en
  esa pasada.

## [0.1.0] - 2026-11-15

Primera entrega. Recoge lo que el motor es hoy, después de siete labs: un motor IaC en
Ansible que despliega topologías —VMs QEMU y contenedores LXC— en un nodo Proxmox **sólo
por su API REST**, pone él mismo la identidad de cada invitado, **configura el interior**
de cada equipo (RouterOS por su REST, Linux por SSH) y lo documenta.

### Añadido

**La declaración**
- Una carpeta por topología (`labs/NN_<nombre>/`) con su declaración, su documento y sus
  diarios. El motor **no conoce ninguna topología**: el lab es siempre un parámetro.
- El lab declara roles, el tipo de equipo (`rt`/`srv`/`ws`/`sw`/`ctl`), bridges,
  direcciones, etapas de arranque, recursos y —si quiere que el motor entre dentro— qué
  configurar y con qué imagen. **Nunca** declara vmids ni MACs.

**La identidad, derivada**
- vmid (el menor libre de todo el clúster), nombre `<tipo>-<alias>`, MAC `f(vmid)`,
  descripción y pool del lab. **Sin fichero de estado**: se re-deriva leyendo la API.

**Los verbos**
- `plan` (ordena y explica cada llamada REST que haría), `preflight` (sólo lectura: qué
  hay, qué falta, qué difiere), `apply` (converge y verifica), `verify` (¿existe de verdad
  lo declarado?) y `destroy` (el único que borra, y sólo lo que él creó).
- El plan es una **explicación**: dice por qué cada llamada, no sólo cuál.

**Las cuatro vías de acceso y los tres diarios**
- API de Proxmox y REST de RouterOS, siempre con `ansible.builtin.uri`, y cada llamada
  deja su línea en `logs/api.jsonl` (`api: proxmox` | `routeros`).
- El interior de un Linux, sólo por SSH, con una línea por paso en `logs/interior.jsonl`.
- La consola de la API —el único protocolo no-REST— para una sola cosa: el arranque del
  bastión. Su diario es `logs/console.jsonl`. Ninguna credencial se escribe en un diario.

**El interior de un invitado**
- Un driver por familia (RouterOS por REST, Linux por SSH) con la misma forma: leer dentro
  → decidir la diferencia en los dos sentidos → escribir lo que falta → releer y comprobar.
- DHCP con reservas derivadas de la MAC del invitado, direcciones estáticas por interfaz,
  rutas, cortafuegos, identidad y servicios. Dentro de un área declarada, lo que no está en
  la declaración se quita; fuera de las áreas declaradas no se toca nada.

**El túnel**
- Lo construye el motor y lo comprueba de punta a punta antes de seguir. Por él van el REST
  de RouterOS y el SSH al interior: el motor no necesita llegar solo a la red del lab.

**La red y el orden de arranque**
- Los bridges los crea el plan si faltan, con su marca de propiedad; `destroy` sólo borra
  los que llevan esa marca y no están usando invitados de fuera del lab.
- Cada etapa arranca sólo cuando la anterior está convergida y sirviendo: la carrera del
  DHCP que mató a la fase anterior se evita por construcción, no por suerte.
- El agente de invitado en toda VM, para poder LEER direcciones que la API no expone.

**Los checks y la documentación**
- Checks mecánicos (`./lab check`), sin credenciales y sin Proxmox, cada uno diciendo el
  fichero y el comando que lo arregla.
- El documento de un lab tiene dos regiones: la generada (nadie la escribe a mano) y la
  prosa libre. Los documentos que citan el motor se sellan por hash y **caducan avisando**.
- ADRs para lo que no se quiere re-litigar, un pre-commit que vigila docs↔código, y una
  suite de pruebas con fixtures para el asignador: el asignador se prueba sin Proxmox.
