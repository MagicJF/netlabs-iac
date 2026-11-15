# PROPÓSITO:   calcula el PLAN: la lista ORDENADA de pasos (por la API de Proxmox, por
#              el camino, por el interior de un invitado o por la sonda de un escalón)
#              que llevan el mundo desde su estado actual hasta la declaración. Es el
#              único sitio donde se decide "qué hay que hacer": `plan` lo imprime y
#              `apply` lo ejecuta. No hay una segunda lógica de decisión.
# INVARIANTES: es una FUNCIÓN PURA: recibe la declaración, el estado del mundo y
#              la identidad ya asignada, y devuelve la lista. No habla con la API,
#              no escribe ficheros y no conoce ningún lab concreto.
#              El plan es IDEMPOTENTE por construcción: lo que ya coincide no
#              genera llamada, así que el segundo plan de lo mismo es vacío.
# LÍMITES:     el plan no prueba que una llamada vaya a funcionar; ordena lo que
#              hay que pedir. Y no inventa recursos que la API no da (una
#              plantilla de disco, por ejemplo): los deja declarados como límite.
# VER:         README.md §Cómo se usa; AGENTS.md §Qué correr y cuándo

# ---------------------------------------------------------------------------
# El plan es una lista de pasos. Cada paso dice qué llamar y POR QUÉ, para que la
# salida de `plan` se pueda revisar sin abrir el código.
# ---------------------------------------------------------------------------

# El interior (áreas, camino, reservas derivadas) lo decide `interior.py`, que es
# puro como este fichero: importarlo no lo ensucia (no habla con nadie, no escribe
# nada). Se importa por RUTA y no por PYTHONPATH porque el motor no depende de
# variables de entorno (regla 3): la ruta se calcula desde este mismo fichero.
import os as _os
import sys as _sys

_AQUI = _os.path.dirname(_os.path.abspath(__file__))
_FILTROS = _os.path.join(_os.path.dirname(_AQUI), "filter_plugins")
if _FILTROS not in _sys.path:
    _sys.path.insert(0, _FILTROS)

import interior as modulo_interior  # noqa: E402  (la ruta se ajusta justo arriba)
import identidad as modulo_identidad  # noqa: E402  (la MAC de cada pata, derivada)

ACCION_POOL = "crear_pool"
ACCION_BRIDGE = "crear_bridge"
ACCION_RECARGAR_RED = "recargar_red"
ACCION_CREAR = "crear_invitado"
ACCION_ACTUALIZAR = "actualizar_invitado"
ACCION_ARRANCAR = "arrancar_invitado"

# Cada paso dice POR DÓNDE va, porque el plan ya no es sólo llamadas REST:
#   * `api`      -- una llamada a la API del hipervisor (la puerta de siempre);
#   * `interior` -- leer/escribir DENTRO de un invitado (REST de RouterOS o SSH);
#   * `camino`   -- el camino del lab (§5): la consola y la comprobación del túnel;
#   * `sonda`    -- comprobar que un escalón sirve, sin cambiar nada.
VIA_API = "api"


def _orden_de_arranque(invitado):
    """Dentro de un escalón: primero quien DA la primera dirección, después los demás.

      * **0** -- el puesto de control: sin él no hay camino, y es quien da la PRIMERA
        dirección (a los CHR del bridge de gestión). Va el primero de todos.
      * **1** -- un router: reparte direcciones en sus LANs, así que se converge antes
        que quien va a pedírselas.
      * **2** -- el resto: quien pide dirección a alguien que ya está sirviendo.

    Es la regla 18 un nivel más abajo: un invitado que pide dirección a quien todavía
    no la reparte se queda esperando -- y un LXC deja de pedirla al rato y se queda
    inalcanzable (medido en v3). `sorted` es estable: dentro de cada clase se conserva
    el orden de la declaración.
    """
    if modulo_interior.tiene_camino(invitado):
        return 0
    if "dhcp" in modulo_interior.areas_de(invitado):
        return 1
    return 2


def _paso(accion, metodo, ruta, parametros, porque, escalon=None, rol=None, via=VIA_API, detalle=None):
    """Un paso del plan. `porque` es obligatorio: un paso sin razón es un bug.

    `detalle` son las sub-líneas de un paso que se hace en varias piezas (el camino).
    Se imprime debajo y no cambia el `parametros`: lo que hay que hacer sigue estando
    en un solo sitio.
    """
    paso = {
        "accion": accion,
        "via": via,
        "metodo": metodo,
        "ruta": ruta,
        "parametros": parametros,
        "porque": porque,
        "escalon": escalon,
        "rol": rol,
    }
    if detalle:
        paso["detalle"] = list(detalle)
    return paso


def _esperado_del_invitado(invitado):
    """Lo declarado, más lo que decide el MOTOR y también se comprueba.

    `cmode` no lo declara ningún lab: lo pone el motor para que la consola del puesto
    de control dé una SHELL y no un `login` (§5). Se compara como cualquier otro campo
    porque lo que el motor decide, el motor lo converge: un invitado que nació con el
    `tty` de fábrica se corrige con un `PUT .../config`, sin recrearlo.
    """
    esperado = dict(invitado)
    if modulo_interior.tiene_camino(invitado):
        esperado["cmode"] = "shell"
    return esperado


def campos_que_difieren(esperado, actual):
    """Qué campos declarados no coinciden con lo que hay en Proxmox.

    Se compara sólo lo que la API de Proxmox guarda de verdad en la config: el
    nombre, el número de cores, la memoria, el bridge de la red y la descripción.
    La DIRECCIÓN IP declarada no está aquí porque vive DENTRO del invitado y la
    API no la ve: eso es un límite, y `verify` lo dice en voz alta.
    """
    diferencias = {}
    # `cmode` entra en la comparación porque lo DECIDE EL MOTOR (no el lab): la consola
    # del puesto de control tiene que dar una shell, y si un invitado nació con el
    # `tty` de fábrica eso se corrige con un `PUT .../config`, sin recrearlo.
    for campo in ("nombre", "cores", "memoria", "bridge", "descripcion", "mac", "cmode"):
        if campo not in actual:
            continue
        if actual[campo] is None:
            continue
        # Un campo que el motor NO decide para este invitado no se compara: `cmode` sólo
        # lo fija el motor en el puesto de control (para que su consola dé una shell);
        # el resto de contenedores se quedan con el `tty` de fábrica.
        if campo not in esperado:
            continue
        if str(actual[campo]) != str(esperado[campo]):
            diferencias[campo] = {"esperado": esperado[campo], "encontrado": actual[campo]}
    return diferencias


def comentario_bridge(lab, parametros):
    """El `comments` que el motor escribe en un bridge que CREA él.

    Es la prueba de propiedad del bridge, y se rellena con la plantilla del motor
    (`engine_plantilla_comentario_bridge`) para que crear y reconocer digan lo
    mismo: `destroy` busca aquí el `lab=<lab>` antes de borrar nada. Si la plantilla
    no llega (un llamante antiguo), devuelve cadena vacía y el bridge se crea sin
    marca: se conservará al destruir, que es el lado seguro del error.
    """
    return str(parametros.get("comentario_bridge") or "").replace("{lab}", str(lab))


def construir_plan(declaracion, estado, identidad, parametros):
    """(declaración, estado del mundo, identidad) -> plan ordenado.

    `parametros` es lo que el motor sabe del entorno: el nodo, la plantilla de
    sistema para los contenedores y el comentario del pool. Nada de esto es de un
    lab: son defaults del motor (vars/engine.yml).
    """
    nodo = parametros["nodo"]
    lab = declaracion["lab"]
    pasos = []

    # Fase 0 — el pool: la frontera de propiedad. Se llama como la carpeta del lab.
    # Sin pool no hay forma de saber qué invitado es de este lab sin un fichero de
    # estado, así que va lo primero.
    if lab not in (estado.get("pools") or {}):
        pasos.append(
            _paso(
                ACCION_POOL,
                "POST",
                "/pools",
                {"poolid": lab, "comment": parametros.get("comentario_pool", "")},
                f"no existe el pool '{lab}': es la frontera de propiedad del lab",
            )
        )

    # Fase 0 bis — los bridges del lab. Un bridge es del NODO, no del lab, así que
    # puede existir ya (lo comparte el nodo con otros usos): sólo se crea si falta.
    # Al crearlo se le escribe el `comments` del motor (`lab=<lab> ...`), que es la
    # ÚNICA prueba de propiedad que tendrá `destroy`: Proxmox no mete interfaces en
    # pools, así que sin esa marca un bridge declarado por el lab no se puede
    # distinguir de uno que ya estaba en el nodo. A un bridge que YA existe no se le
    # toca el comentario: no consta que lo creara este lab, y adoptarlo sería
    # atribuirse infraestructura ajena.
    faltan_bridges = []
    for bridge in declaracion["bridges"]:
        if bridge["nombre"] not in (estado.get("bridges_nodo") or []):
            faltan_bridges.append(bridge)
            parametros_bridge = {"iface": bridge["nombre"], "type": "bridge", "autostart": 1}
            comentario = comentario_bridge(lab, parametros)
            if comentario:
                parametros_bridge["comments"] = comentario
            pasos.append(
                _paso(
                    ACCION_BRIDGE,
                    "POST",
                    f"/nodes/{nodo}/network",
                    parametros_bridge,
                    f"el bridge '{bridge['nombre']}' no existe en el nodo {nodo}: se crea y se "
                    f"marca como de este lab, para que `destroy` pueda borrarlo después",
                )
            )
    if faltan_bridges:
        pasos.append(
            _paso(
                ACCION_RECARGAR_RED,
                "PUT",
                f"/nodes/{nodo}/network",
                {},
                "un bridge nuevo no entra en vigor hasta recargar la red del nodo",
            )
        )

    # Fase 1 — crear o actualizar cada invitado, en orden de arranque. El orden lo
    # pone la declaración (escalón, rol); el plan no lo reinventa.
    for invitado in identidad["invitados"]:
        actual = (estado.get("invitados") or {}).get(str(invitado["vmid"]))
        ruta_crear = f"/nodes/{nodo}/{invitado['tipo']}"
        ruta_config = f"/nodes/{nodo}/{invitado['tipo']}/{invitado['vmid']}/config"

        if actual is None:
            pasos.append(
                _paso(
                    ACCION_CREAR,
                    "POST",
                    ruta_crear,
                    _parametros_creacion(invitado, lab, declaracion, estado, parametros),
                    f"el rol '{invitado['rol']}' no está desplegado: se crea con el vmid "
                    f"{invitado['vmid']} (el menor libre del clúster)",
                    escalon=invitado["escalon"],
                    rol=invitado["rol"],
                )
            )
            continue

        diferencias = campos_que_difieren(_esperado_del_invitado(invitado), actual)
        if diferencias:
            pasos.append(
                _paso(
                    ACCION_ACTUALIZAR,
                    "PUT",
                    ruta_config,
                    _parametros_actualizacion(invitado, diferencias),
                    f"el rol '{invitado['rol']}' existe pero difiere en "
                    + ", ".join(sorted(diferencias)),
                    escalon=invitado["escalon"],
                    rol=invitado["rol"],
                )
            )

    # Fase 2 — arrancar, escalón a escalón, y CONVERGER SU INTERIOR antes de tocar el
    # escalón siguiente. El orden dentro de un escalón es el que mata la carrera del
    # DHCP por construcción (regla 18), no por suerte:
    #
    #   arrancar los invitados del escalón  ->  construir el camino (si el escalón
    #   trae el puesto de control)  ->  converger el interior de cada invitado  ->
    #   comprobar que el escalón SIRVE (contesta en el puerto por el que se deja ver).
    #
    # Por qué este orden y no otro (§10): el puesto de control da la primera
    # dirección a los CHR, y un puesto `direccion: dhcp` no arranca hasta que su
    # router está convergido y sirviendo. Un lab SIN interior no genera ni un paso de
    # más: los invitados se arrancan igual que siempre, en el mismo orden.
    for escalon in declaracion["escalones"]:
        del_escalon = [i for i in identidad["invitados"] if i["escalon"] == escalon]

        for invitado in del_escalon:
            actual = (estado.get("invitados") or {}).get(str(invitado["vmid"]))
            if actual is not None and actual.get("arrancado"):
                continue
            pasos.append(
                _paso(
                    ACCION_ARRANCAR,
                    "POST",
                    f"/nodes/{nodo}/{invitado['tipo']}/{invitado['vmid']}/status/start",
                    {},
                    f"el rol '{invitado['rol']}' pertenece al escalón {escalon} y no está arrancado",
                    escalon=escalon,
                    rol=invitado["rol"],
                )
            )

        # (a) El camino, PRIMERO y para todos los invitados del escalón que lo traen:
        #     sin camino no se entra en el puesto de control, y sin el puesto de control
        #     no se entra en ningún otro invitado. Va antes de tocar el interior de
        #     nadie, incluido el suyo.
        for invitado in del_escalon:
            pasos.extend(modulo_interior.pasos_del_camino(invitado, declaracion, estado, parametros, identidad))

        # (b) El interior del escalón, con su BARRERA delante. Sin `config:` no se
        #     entra: el motor lo despliega y se calla, exactamente como en la fase 1.
        #
        #     Dentro del escalón, primero quien DA dirección (el puesto de control con
        #     su servidor DHCP, y los routers) y después quien la PIDE: es la misma
        #     razón que ordena los escalones, un nivel más abajo. Un invitado que pide
        #     dirección a quien todavía no la reparte se queda esperando -- y un LXC
        #     deja de pedirla al rato y se queda inalcanzable (medido en v3).
        #
        #     Y la sonda (esperar_servicio) va ANTES del interior de cada invitado, no
        #     al final del escalón: un invitado recién arrancado NO contesta en el
        #     instante. Un CHR tarda en bootear y en pedir su dirección por DHCP, así
        #     que convergerlo nada más arrancarlo entra en un invitado mudo y aborta la
        #     pasada (medido: el segundo CHR de un lab de aceptación, arranque en frío,
        #     `No route to host`). La barrera pregunta por el puerto por el que el
        #     invitado se deja ver (el REST de RouterOS, el sshd de un Linux); sólo se
        #     converge lo que ya contesta, y eso deja el escalón listo --convergido y
        #     sirviendo-- antes de tocar el siguiente.
        conviene = [
            i for i in del_escalon
            if modulo_interior.declara_interior(i) or modulo_interior.tiene_camino(i)
        ]
        for invitado in sorted(conviene, key=_orden_de_arranque):
            sonda = modulo_interior.espera_de_servicio(invitado)
            if sonda is not None:
                pasos.append(sonda)
            if not modulo_interior.declara_interior(invitado):
                continue
            leido = (estado.get("interior") or {}).get(str(invitado["vmid"])) or {}
            pasos.extend(
                modulo_interior.pasos_de_convergencia(invitado, identidad, declaracion, leido, parametros)
            )

    for indice, paso in enumerate(pasos, start=1):
        paso["orden"] = indice
    return pasos


def _prefijo_mac(parametros):
    """El OUI de las MAC del motor, que viene de `vars/engine.yml` (no se incrusta).

    Está en un solo sitio porque las MAC se derivan en dos: la de un invitado de una pata
    (`identidad_mac`, al asignar la identidad) y la de cada pata de un invitado del
    interior (`identidad_mac_de_pata`). Si falta, se dice: con un prefijo inventado las
    MAC cambiarían sin que nadie lo haya pedido.
    """
    prefijo = str(parametros.get("mac_prefijo") or "").strip()
    if not prefijo:
        raise modulo_interior.ErrorMotor(
            "falta el prefijo de las MAC del motor (`engine_prefijo_mac`): sin él no se "
            "puede derivar la identidad de las patas de un invitado del interior"
        )
    return prefijo


def _red_del_invitado(invitado, declaracion, estado, parametros):
    """TODAS las patas de un invitado que declara camino, como claves `net<índice>`.

    Un invitado del interior NACE COMPLETO: una pata por cada bridge del lab y una en el
    bridge de gestión del nodo, la última (por ahí sale hacia casa). Cambiarle las patas
    a un invitado en marcha obliga a reiniciarlo, y aquí no se reinicia la máquina que
    está trabajando (§5): por eso todas se declaran al crear.

    **Cada pata lleva su MAC derivada** (`mac_de_la_pata`): la 0 es la de siempre y las
    demás salen del mismo sitio. Dejárselas a Proxmox sería estado que el motor no
    controla, y el plan las vería distintas en cada pasada.

    Las claves `netN` NO son un campo suelto (se reescriben enteras), así que esta misma
    función vale para crear y para actualizar. `_net0` sigue siendo la red de un invitado
    de una sola pata: los de la fase 1, que no declaran camino.
    """
    if not modulo_interior.tiene_camino(invitado):
        return {}
    red = {}
    for indice, pata in enumerate(
        modulo_interior.patas_del_puesto_control(invitado, declaracion, estado, parametros)
    ):
        mac = modulo_identidad.identidad_mac_de_pata(
            invitado["vmid"], indice, _prefijo_mac(parametros)
        )
        if invitado["tipo"] == "lxc":
            # En un contenedor la dirección se declara en la propia interfaz. La pata
            # del bridge de gestión del NODO lleva PUERTA (es por donde sale hacia
            # casa); las del lab no, porque la gestión no puede depender de los routers
            # que el motor está desplegando.
            red[f"net{indice}"] = (
                f"name=eth{indice},bridge={pata['bridge']},hwaddr={mac}"
                + (f",ip={pata['direccion']}" if pata.get("direccion") else "")
                + (f",gw={pata['puerta']}" if pata.get("puerta") else "")
            )
        else:
            red[f"net{indice}"] = f"virtio={mac},bridge={pata['bridge']}"
    return red


def _redes_del_invitado(invitado, declaracion, estado, parametros):
    """El bloque de red del invitado: `net0`, `net1`... una por PATA DECLARADA.

    Tres casos, y ninguno se adivina:
      * el invitado del CAMINO (el puesto de control) nace con una pata por cada bridge del
        lab y una en el bridge de gestión del NODO, la última: eso lo decide
        `_red_del_invitado` y va aparte;
      * un invitado que declara VARIAS patas (`bridges:`) nace con una por bridge, en el
        orden declarado y con la MAC de cada pata derivada (`identidad_mac_de_pata`). Es el
        caso de un CHR que sirve una LAN: sus interfaces son `ether1`, `ether2`... en ese
        orden, y por eso el orden de la declaración ES la numeración;
      * el resto (una sola pata) es `_net0`, exactamente como en la fase 1.
    """
    if modulo_interior.tiene_camino(invitado):
        return _red_del_invitado(invitado, declaracion, estado, parametros)
    patas = invitado.get("bridges") or []
    if len(patas) <= 1:
        red = {"net0": _net0(invitado)}
        red.update(_pata_de_fuera(invitado, parametros))
        return red
    red = {}
    for indice, bridge in enumerate(patas):
        mac = modulo_identidad.identidad_mac_de_pata(
            invitado["vmid"], indice, _prefijo_mac(parametros)
        )
        if invitado["tipo"] == "lxc":
            red[f"net{indice}"] = f"name=eth{indice},bridge={bridge},hwaddr={mac}"
        else:
            red[f"net{indice}"] = f"virtio={mac},bridge={bridge}"
    red.update(_pata_de_fuera(invitado, parametros))
    return red


def _pata_de_fuera(invitado, parametros):
    """La pata del EXTERIOR (área `interior.exterior`), como `{clave: valor}`, o {}.

    Es la ÚLTIMA pata y va sin dirección: se tiende al bridge del nodo que tiene salida
    (valor de ENTORNO, `pve_bridge_gestion` en secrets.yml, nunca un valor de lab) y la
    dirección se la pide el propio router por DHCP desde dentro. Se añade al nacer por la
    misma razón que las del puesto de control: cambiarle las patas a un invitado en marcha
    obliga a reiniciarlo, y aquí no se reinicia lo que está trabajando (§5).
    """
    if not modulo_interior.interfaz_exterior(invitado):
        return {}
    puente = str(parametros.get("bridge_gestion") or "")
    if not puente:
        raise modulo_interior.ErrorMotor(
            f"el invitado {invitado.get('rol')} declara exterior (salida del lab) y el "
            "motor no sabe por dónde sale este nodo: falta `pve_bridge_gestion` en "
            "secrets.yml (el bridge del nodo con dirección y salida)"
        )
    indice = len(modulo_interior.patas_de_un_invitado(invitado))
    mac = modulo_identidad.identidad_mac_de_pata(
        invitado["vmid"], indice, _prefijo_mac(parametros)
    )
    return {f"net{indice}": f"virtio={mac},bridge={puente}"}


def _net0(invitado):
    """La cadena de red de la config de Proxmox para este invitado.

    Un contenedor la declara con `name/bridge/hwaddr`; una VM con `<modelo>=<mac>`.
    Está en un solo sitio porque crear y actualizar tienen que decir lo mismo.

    **Y la dirección va aquí, como en una máquina de verdad**: una ESTACIÓN no lleva
    ninguna puesta -- al enchufarle el cable la PIDE (`dhcp`), y el router de su red le da
    dirección, puerta y DNS. Un SERVIDOR la lleva FIJA, con su puerta puesta a mano
    (`direccion` + `puerta`), y por eso no pregunta nada: sigue saliendo porque sabe por
    dónde. Lo que el lab no declara, no se inventa: sin `direccion` el invitado nace sin
    ella, que es lo que hacía siempre.
    """
    if invitado["tipo"] == "lxc":
        # La dirección va en la cadena de red SÓLO si el lab la declara: `direccion: dhcp`
        # para una estación (que al conectar la pide, y el router de su red le da dirección,
        # puerta y DNS), o una dirección con su `puerta` para una máquina fija (que no
        # pregunta nada y sale igual, porque sabe por dónde). Lo que no se declara, no se
        # inventa: un invitado sin `direccion` nace sin ella, como hasta ahora -- y eso
        # incluye a los de la fase 1, cuyo plan no cambia.
        direccion = str(invitado.get("direccion") or "")
        puerta = str(invitado.get("puerta") or "")
        red = f"name=eth0,bridge={invitado['bridge']},hwaddr={invitado['mac']}"
        if not direccion:
            return red
        if direccion.lower() == "dhcp":
            return red + ",ip=dhcp"
        red += f",ip={direccion}"
        if puerta:
            red += f",gw={puerta}"
        return red
    return f"virtio={invitado['mac']},bridge={invitado['bridge']}"


# Traducción de los campos INTERNOS (vocabulario del dominio, en castellano) a las
# claves LITERALES de la API de Proxmox. No son lo mismo: `descripcion` es
# `description` y `memoria` es `memory`. El nombre cambia según el tipo (`hostname`
# en un contenedor, `name` en una VM) y la red no es un campo suelto (se reescribe
# `net0` entero): por eso no están todos en esta tabla.
PARAMETRO_API = {
    "descripcion": "description",
    "cores": "cores",
    "memoria": "memory",
}


def _parametros_creacion(invitado, lab, declaracion, estado, parametros):
    """Los parámetros de la API para crear un invitado de este tipo.

    Se separa para que la diferencia entre una VM y un contenedor esté en un solo
    sitio y se lea de un vistazo.
    """
    comunes = {
        "vmid": invitado["vmid"],
        "description": invitado["descripcion"],
        "pool": lab,
        "cores": invitado["cores"],
        "memory": invitado["memoria"],
    }

    # Las patas: `net0` para un invitado de siempre, una por bridge declarado (`net0`,
    # `net1`...) para uno que sirve varias redes, y las del camino para el puesto de
    # control. Todas se deciden al crear: cambiarle las patas a un invitado en marcha
    # obliga a reiniciarlo y aquí no se reinicia la máquina que está trabajando (§5).
    comunes.update(_redes_del_invitado(invitado, declaracion, estado, parametros))

    if invitado["tipo"] == "lxc":
        # En un contenedor el nombre va en `hostname` y hace falta la plantilla.
        creado = {
            **comunes,
            "hostname": invitado["nombre"],
            "ostemplate": parametros["ostemplate_lxc"],
        }
        # La clave pública del motor se deja DENTRO del invitado al crearlo
        # (`ssh-public-keys`): Proxmox la escribe en el rootfs, sin `snippets` ni
        # cloud-init. Es la otra mitad del camino: sin clave no hay por dónde entrar
        # aunque el túnel esté en pie.
        if modulo_interior.tiene_camino(invitado) and parametros.get("camino_clave_publica"):
            creado["ssh-public-keys"] = parametros["camino_clave_publica"]
        # Y su consola tiene que dar una SHELL, no un `login`. Es por donde el motor le
        # pone el arranque del camino, UNA vez (§5): con el `cmode` de fábrica (`tty`)
        # la consola pide usuario y contraseña, y la línea se quedaría escrita en un
        # prompt de login sin que nadie la leyera. Medido en el código de PVE:
        # `cmode: shell` entrega la shell de root directamente en la consola.
        if modulo_interior.tiene_camino(invitado):
            creado["cmode"] = "shell"
        return creado

    # En una VM el nombre va en `name` y no hay plantilla que valga.
    creado = {**comunes, "name": invitado["nombre"]}

    # Y el AGENTE DE INVITADO, que es un canal de LECTURA del invitado hacia el
    # hipervisor: la única forma de que el motor sepa las INTERFACES de una VM, porque
    # la config de una VM QEMU no lleva `ip=` --lo pone el invitado por dentro-- y no
    # hay endpoint de interfaces más que para contenedores. Sin esto, el motor elige la
    # dirección de la pata de gestión del puesto contando por arriba A CIEGAS, con la
    # esperanza de no pisar una VM que no puede ver.
    #
    # Va aquí, con el bus del disco y la consola serie, porque se decide al NACER: el
    # canal aparece al ARRANCAR, así que añadirlo a una VM viva obliga a reiniciarla.
    # No es un valor de ningún lab (regla 7): es lo que el motor hace con toda VM que
    # crea. Y lo que se le concede al token para leerlo es `VM.GuestAgent.Audit`, que
    # en el código de PVE cubre LECTURAS y `ping`: ni `exec` (pide Unrestricted) ni los
    # ficheros (piden FileRead/FileWrite), que siguen vedados. Ver ADR 0011.
    creado["agent"] = 1

    # Y un CHR no tiene consola gráfica útil: la suya es la SERIE. Se le da un puerto serie
    # como socket y se manda ahí la pantalla (`vga: serial0`), que es lo que hace que la
    # consola de RouterOS se pueda leer POR LA API -- el protocolo de consola del navegador
    # del nodo, que habla `tools/consola.py` y sólo él -- sin abrir la consola gráfica y sin
    # pedirle una pantalla al hipervisor. Va aquí, con el bus del disco, porque se decide al
    # NACER: un invitado que nació sin consola serie se rehace (`destroy` + `apply`), que es
    # como lo crea el motor -- entero. No es un valor de ningún lab: es lo que un RouterOS
    # necesita para que se le pueda leer la consola.
    if modulo_interior.tipo_de(invitado) == "routeros":
        creado["serial0"] = "socket"
        creado["vga"] = "serial0"

    # La imagen de fábrica se adjunta SÓLO al crear: `import-from` no se acepta
    # después (medido). De ahí que la declaración de `imagen` sea una promesa que se
    # cumple al nacer el invitado, o no se cumple nunca.
    #
    # El BUS del disco no es cosmético, y esto está MEDIDO: un CHR (RouterOS) NO arranca
    # con el disco en virtio-scsi --SeaBIOS se queda en «Load system / ERROR: could not
    # find disk!» y entra en bucle de iPXE-- y sí arranca en SATA. Se vio con el dedo:
    # el CHR creado en `scsi0` no llegó ni a pedir concesión DHCP, y por eso el motor no
    # encontraba su REST («no route to host»). Así que el bus lo decide lo que el
    # invitado DECLARA SER por dentro (`config: {routeros: ...}`, vía `tipo_de`), nunca
    # el nombre del fichero de la imagen: eso sería un valor de lab.
    if invitado.get("imagen"):
        almacen = parametros["almacenamiento_imagen"]
        bus = "sata0" if modulo_interior.tipo_de(invitado) == "routeros" else "scsi0"
        creado[bus] = f"{almacen}:0,import-from={almacen}:import/{invitado['imagen']}"
        creado["bootdisk"] = bus
    return creado


def _parametros_actualizacion(invitado, diferencias):
    """Los parámetros de la API para ACTUALIZAR un invitado que ya existe.

    `diferencias` trae campos internos; aquí se traducen a las claves LITERALES de la
    API. Sin esto, un `PUT .../config` saldría con `descripcion` o `memoria` y la API
    lo rechazaría con un 400 ("property is not defined in schema").
    """
    valor = {
        "descripcion": invitado["descripcion"],
        "cores": invitado["cores"],
        "memoria": invitado["memoria"],
        "cmode": "shell",
    }
    parametros = {}
    for campo in diferencias:
        if campo in PARAMETRO_API:
            parametros[PARAMETRO_API[campo]] = valor[campo]
        elif campo == "nombre":
            parametros["hostname" if invitado["tipo"] == "lxc" else "name"] = invitado["nombre"]
        elif campo == "cmode":
            # La consola, en la clave literal de la API.
            parametros["cmode"] = valor["cmode"]
        elif campo in ("bridge", "mac"):
            if modulo_interior.tiene_camino(invitado):
                # Las patas se decidieron al nacer y una pata nueva sólo existe tras
                # arrancar el invitado: aquí no se finge una convergencia que no se
                # puede hacer. Se dice el remedio y se para.
                raise modulo_interior.ErrorMotor(
                    f"las patas del invitado {invitado['rol']} cambiaron y eso no se "
                    "cambia en caliente: hay que rehacerlo (`destroy` de ese invitado "
                    "y `apply`), que es como lo crea el motor: entero"
                )
            # La red no es un campo suelto: se reescriben las patas ENTERAS (`net0`, `net1`...).
            # Sin declaración ni estado: por aquí NO puede pasar un invitado del camino (el
            # guardián de arriba lo impide), y es el único que necesitaría leer el mundo.
            parametros.update(_redes_del_invitado(invitado, None, None, parametros))
    return parametros


def formatear_plan(plan, declaracion, estado, identidad):
    """El plan en texto, para leerlo antes de ejecutarlo.

    Dice primero de dónde sale el estado del mundo: un plan contra un clúster
    vacío simulado y un plan contra el clúster real no valen lo mismo, y quien lo
    lee tiene que saber cuál tiene delante.
    """
    lineas = []
    lineas.append(f"PLAN del lab '{declaracion['lab']}'")
    lineas.append("=" * 60)
    lineas.append("")
    lineas.append("Identidad asignada por el motor (no declarada, no guardada):")
    for invitado in identidad["invitados"]:
        lineas.append(
            "  escalón {e}  {tipo:4}  rol={rol:16} vmid={vmid:<6} mac={mac}  {origen}".format(
                e=invitado["escalon"],
                tipo=invitado["tipo"],
                rol=invitado["rol"],
                vmid=invitado["vmid"],
                mac=invitado["mac"],
                origen=invitado["origen"],
            )
        )
    lineas.append("")

    if not plan:
        lineas.append("No hay nada que hacer: el mundo ya coincide con la declaración.")
        lineas.append(f"({len(declaracion['invitados'])} invitados declarados, todos presentes y coincidentes)")
        return "\n".join(lineas)

    # La cabecera sólo cambia si el plan lleva algo que NO es una llamada REST. Así
    # los planes de un lab sin interior --que están congelados y se comparan línea a
    # línea contra su copia de referencia-- salen exactamente igual que ayer.
    solo_api = all(paso.get("via", VIA_API) == VIA_API for paso in plan)
    if solo_api:
        lineas.append(f"Llamadas REST que se harían, en orden ({len(plan)}):")
    else:
        lineas.append(f"Pasos del plan (API, interior y camino), en orden ({len(plan)}):")
    lineas.append("")
    for paso in plan:
        if paso["metodo"]:
            lineas.append(f"  {paso['orden']:>2}. {paso['metodo']:<4} {paso['ruta']}")
        else:
            # Un paso sin método no es una llamada REST: es una acción del motor
            # (converger un área, esperar a que un escalón sirva, construir el camino).
            lineas.append(f"  {paso['orden']:>2}. {paso['accion']}   [via {paso.get('via', VIA_API)}]")
        for linea in paso.get("detalle") or []:
            lineas.append(f"      - {linea}")
        if paso["parametros"]:
            for clave in sorted(paso["parametros"]):
                lineas.append(f"      {clave} = {paso['parametros'][clave]}")
        lineas.append(f"      porque: {paso['porque']}")
        lineas.append("")

    resumen = {}
    for paso in plan:
        resumen[paso["accion"]] = resumen.get(paso["accion"], 0) + 1
    lineas.append("Resumen: " + ", ".join(f"{k}={v}" for k, v in sorted(resumen.items())))
    return "\n".join(lineas)
