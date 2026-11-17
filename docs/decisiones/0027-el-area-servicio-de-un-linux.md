# 0027 — Un Linux declara un `servicio`, y el motor lo instala y lo deja SIRVIENDO

*Fecha: 17-nov-2026 — Estado: aceptada y aplicada — Ámbito: una primitiva NUEVA del interior
Linux: el área `servicio`, que instala un paquete declarado, lo configura y comprueba que sirve*

## El problema

El vocabulario del interior Linux sabía tocar **la red** del equipo (`tunnel`, `address`,
`addresses`, `ip_forward`, `dhcp_server`) y nada más. Un lab que quisiera un servicio dentro
—un `lab` que enseñe «un contenedor, y algo vivo dentro»— no podía declararlo: no había
palabra para decirlo (regla 15: el vocabulario es **cerrado**, un lab no inventa primitivas).
El lab `09_lxc-caddy` se desplegaba y el motor entraba por SSH, pero **no había área que
instalara nada**: lo decía su propia prosa, y esa prosa era verdad.

## La decisión

**1. Un área nueva de Linux: `servicio`.** Se declara en `config.linux` junto a las de siempre
(`tunnel`, `address`, …). Su **VALOR es el NOMBRE de un servicio** de un **vocabulario cerrado**:

```yaml
config:
  linux:
    servicio: caddy     # el ÚNICO miembro hoy
```

No es un mapa: el valor **ya es** el dato (a diferencia de `dhcp_server`, que necesita varias
piezas). Un nombre que no esté en el vocabulario se **rechaza** al leer la declaración, con su
motivo y la lista de los que hay — no se acepta y se ignora. El vocabulario vive en el motor
(`interior.SERVICIOS_LINUX`), no en el lab.

**2. El área hace TODO lo que hace falta para que el servicio SIRVA**, no sólo para que el
paquete esté. Para `caddy`, en una sola pasada:

- **instala** el paquete y, con él, `curl` (que la relectura necesita y la imagen base no trae);
- **escribe** la configuración mínima que sirve una página (su `Caddyfile`, en
  `/etc/caddy/Caddyfile`) y la **página de relleno** (`/var/www/html/index.html`) — porque un
  servidor web que no sirve nada no cumple nada;
- **habilita y arranca** la unidad de systemd del servicio;
- y lo **comprueba SIRVIÉNDOLO**: un `curl -fsS http://127.0.0.1/` **desde dentro** del invitado
  (por la vía de acceso de siempre, `interior_ssh.yml`).

**3. La configuración y la página son del MOTOR, no del lab.** El lab declara el **nombre** del
servicio; **por dónde** sirve, **qué** sirve y **cómo** se configura es vocabulario del motor
(regla 7). Eso hace que el área sea una primitiva, no un fichero suelto que cada lab escriba a
su manera.

**4. El área gobierna un conjunto ACOTADO — y lo que no está declarado, aquí, no es «bórralo».**
La regla 17 dice que dentro de un área declarada lo que no está se quita. Aplicado a `servicio`,
eso significa: **el área gobierna el paquete, la unidad y la configuración que el motor escribe**
de ESE servicio. **No** borra paquetes ni servicios ajenos (el motor no desinstala media
imagen base por declarar un servicio), y **si un lab no declara `servicio`, no se toca nada**
(fuera de las áreas declaradas no se opina). Se dice aquí porque es una decisión, no un olvido.

**5. Idempotencia, como el resto del interior: un invitado ya convergido produce CERO
operaciones.** El comparador del motor (`_servicio_canonico`) mira lo LEÍDO y decide en los dos
sentidos; si no falta nada, no hay paso. Es la misma promesa de la regla 6, y es la que un
servicio podría romper con facilidad (ver *la trampa*).

## La trampa

**La relectura no puede fiarse de «hay algo».** El paquete de Debian **trae su propio
`Caddyfile`** y ya sirve algo de fábrica. Si la relectura diera por puesta la configuración sólo
porque el fichero existe, el área **no gobernaría nada**: el motor no escribiría nunca la suya.
Por eso el motor escribe una **MARCA** (`# netlabs-servicio`) en su configuración: distingue el
fichero del motor del de fábrica y hace legible el diario.

**Pero la marca NO es la prueba — y aquí la revisión tenía razón.** Una configuración **editada a
mano conserva la marca**, así que «la marca está» daba el área por buena con el fichero cambiado;
y una **página borrada** no se reponía nunca (nadie volvía a escribirla). El comparador
**compara el CONTENIDO ENTERO de los DOS ficheros** que el área gobierna contra lo que el motor
escribiría, y reescribe si difieren. La marca se queda por lo que sí es: una firma para leer el
diario, no una prueba de convergencia. (Hallazgo del PR #12, reproducido con su caso en
`test_interior.py`.)

**«Vivo» no es «habilitado» (`is-active` no es `is-enabled`).** Un servicio **vivo pero
deshabilitado** no arranca al reiniciar el invitado — que es justo lo que el área promete
gobernar. La lectura pregunta las DOS cosas y el comparador pide habilitar cuando falta
cualquiera de ellas. (También medido por la revisión.)

**Y no puede pedir `reload` cuando ya sirve.** Si la relectura no comprobara de verdad que el
servicio **responde** (el `curl`), pediría «recargar» en **cada** pasada: idempotencia rota por
un restaurante de más. La lectura tiene que **medir** que sirve, no suponerlo; por eso la ÚLTIMA
cosa que se pregunta al invitado es exactamente esa (y no se pregunta nada más de lo que la
decisión usa).

**El orden importa.** La configuración se escribe **antes** de arrancar (si la unidad arrancara
con la de fábrica, se recargaría igual), y cuando la configuración **cambia** sobre un servicio
ya vivo hace falta un `restart` para que la coja. Se arranca con `enable --now` y, si hay que
recargar, con `restart` (idempotente), con un `sleep` corto antes de que la relectura haga el
`curl` — porque el `curl` no reintenta y la unidad tarda un instante en volver a escuchar.

**Las listas de apt de la imagen base están ENVEJECIDAS.** El primer `apply` real lo destapó: un
`apt-get install` a secas sale con **rc=100** porque las listas de la imagen apuntan a versiones
que el espejo de Debian ya no tiene (`404 Not Found`, medido). El `install` del área hace
`apt-get update -qq` **antes** de instalar, y sólo cuando de verdad falta algo — así que el coste
se paga una vez y la convergencia sigue siendo idempotente.

## Qué NO se toca

- **Las otras áreas de Linux**: ninguna cambia. Un lab que no declara `servicio` no ve
  diferencia alguna.
- **`secrets.yml` / el diario**: la instalación escribe en `interior.jsonl` como cualquier paso
  (va por `interior_ssh.yml`); nada nuevo que esconder.
- **La propiedad**: el paquete y la unidad son de este invitado; el área no adopta ni borra
  nada de fuera.

## Cómo se comprueba

- **`test/test_interior.py`**: la relectura de un invitado fresco lo ve todo por poner y el diff
  pide las cuatro operaciones; la de un invitado convergido **no pide ninguna** (idempotencia);
  una configuración **con la marca pero cambiada** se reescribe —y una **página borrada**
  también—; un servicio **vivo pero deshabilitado** pide habilitarse; un nombre fuera del
  vocabulario no produce decisión; y el camino entero (`pasos_de_convergencia` →
  `escrituras_linux`) traduce las cuatro operaciones a comandos, sin dejar ninguna
  `pendiente_de_driver`.
- **`test/test_declaracion.py`**: `servicio: caddy` pasa; un nombre que no está en el vocabulario
  se **rechaza** con su nombre y con los que hay; y ni una forma que no es un nombre (un mapa) ni
  una clave **presente pero vacía** (`servicio:` sin valor, o en blanco) cuelan: declarar el área
  y no decir qué servicio no puede pasar en silencio.
- **El ciclo real** del lab `09_lxc-caddy` (`destroy → apply → verify`): el motor instala Caddy
  dentro, lo deja sirviendo y `verify` da **CORRECTO** — con la relectura viendo `servido` y
  `changed=0` en la segunda pasada.

## VER

- [deployment_engine/filter_plugins/interior.py](../../deployment_engine/filter_plugins/interior.py)
  (`SERVICIOS_LINUX`, `configuracion_servicio`, `pagina_servicio`, `_servicio_canonico`,
  `lecturas_linux`, `leido_linux`, `escrituras_linux`, `pendiente_de_driver`)
- [deployment_engine/filter_plugins/declaracion.py](../../deployment_engine/filter_plugins/declaracion.py)
  (`servicio` en el vocabulario del interior y su validación)
- [deployment_engine/tasks/configurar_linux.yml](../../deployment_engine/tasks/configurar_linux.yml)
  (el driver: leer → decidir → escribir → RELEER) y
  [tasks/interior_ssh.yml](../../deployment_engine/tasks/interior_ssh.yml) (la única vía al interior)
- [labs/09_lxc-caddy/09_lxc-caddy.yml](../../labs/09_lxc-caddy/09_lxc-caddy.yml) (el lab que lo declara)
