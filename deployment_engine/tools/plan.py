# PROPÓSITO:   calcula el PLAN: la lista ORDENADA de pasos (por la API de Proxmox, por
#              el túnel, por el interior de un invitado o por la sonda de una etapa)
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

# El interior (áreas, túnel, reservas derivadas) lo decide `interior.py`, que es
# puro como este fichero: importarlo no lo ensucia (no habla con nadie, no escribe
# nada). Se importa por RUTA y no por PYTHONPATH porque el motor no depende de
# variables de entorno (regla 3): la ruta se calcula desde este mismo fichero.
import os as _os
import re
import sys as _sys

_AQUI = _os.path.dirname(_os.path.abspath(__file__))
_FILTROS = _os.path.join(_os.path.dirname(_AQUI), "filter_plugins")
if _FILTROS not in _sys.path:
    _sys.path.insert(0, _FILTROS)

import interior as modulo_interior  # noqa: E402  (la ruta se ajusta justo arriba)
import identidad as modulo_identidad  # noqa: E402  (la MAC de cada interfaz, derivada)

ACCION_POOL = "crear_pool"
ACCION_BRIDGE = "crear_bridge"
ACCION_RECARGAR_RED = "recargar_red"
ACCION_CREAR = "crear_guest"
ACCION_ACTUALIZAR = "actualizar_guest"
ACCION_ARRANCAR = "arrancar_guest"

# Cada paso dice POR DÓNDE va, porque el plan ya no es sólo llamadas REST:
#   * `api`      -- una llamada a la API del hipervisor (la vía de acceso de siempre);
#   * `interior` -- leer/escribir DENTRO de un invitado (REST de RouterOS o SSH);
#   * `tunnel`   -- el túnel del lab (§5): la consola y la comprobación del túnel;
#   * `sonda`    -- comprobar que una etapa sirve, sin cambiar nada.
VIA_API = "api"


def _orden_de_arranque(guest):
    """Dentro de una etapa: primero quien DA la primera dirección, después los demás.

      * **0** -- el bastión: sin él no hay túnel, y es quien da la PRIMERA
        dirección (a los CHR del bridge de gestión). Va el primero de todos.
      * **1** -- un router: reparte direcciones en sus LANs, así que se converge antes
        que quien va a pedírselas.
      * **2** -- el resto: quien pide dirección a alguien que ya está sirviendo.

    Es la regla 18 un nivel más abajo: un invitado que pide dirección a quien todavía
    no la reparte se queda esperando -- y un LXC deja de pedirla al rato y se queda
    inalcanzable (medido en v3). `sorted` es estable: dentro de cada clase se conserva
    el orden de la declaración.
    """
    if modulo_interior.tiene_tunnel(guest):
        return 0
    if "dhcp" in modulo_interior.areas_de(guest):
        return 1
    return 2


def _paso(accion, metodo, ruta, parametros, porque, stage=None, rol=None, via=VIA_API, detalle=None):
    """Un paso del plan. `porque` es obligatorio: un paso sin razón es un bug.

    `detalle` son las sub-líneas de un paso que se hace en varias piezas (el túnel).
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
        "stage": stage,
        "rol": rol,
    }
    if detalle:
        paso["detalle"] = list(detalle)
    return paso


def _esperado_del_guest(guest):
    """Lo declarado, más lo que decide el MOTOR y también se comprueba.

    `cmode` no lo declara ningún lab: lo pone el motor para que la consola del puesto
    de control dé una SHELL y no un `login` (§5). Se compara como cualquier otro campo
    porque lo que el motor decide, el motor lo converge: un invitado que nació con el
    `tty` de fábrica se corrige con un `PUT .../config`, sin recrearlo.
    """
    esperado = dict(guest)
    if modulo_interior.tiene_tunnel(guest):
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
    # del bastión tiene que dar una shell, y si un invitado nació con el
    # `tty` de fábrica eso se corrige con un `PUT .../config`, sin recrearlo.
    for campo in ("nombre", "cores", "memory", "bridge", "descripcion", "mac", "cmode"):
        if campo not in actual:
            continue
        if actual[campo] is None:
            continue
        # Un campo que el motor NO decide para este invitado no se compara: `cmode` sólo
        # lo fija el motor en el bastión (para que su consola dé una shell);
        # el resto de contenedores se quedan con el `tty` de fábrica.
        if campo not in esperado:
            continue
        if str(actual[campo]) != str(esperado[campo]):
            diferencias[campo] = {"esperado": esperado[campo], "encontrado": actual[campo]}
    return diferencias


def _puentes_de(bloque):
    """El bridge de CADA interfaz de un bloque `netN`, por número de interfaz.

    Se saca del TEXTO que el motor escribe (`net0=...,bridge=X,...`), con la misma forma en
    que lo lee de la API: así crear y comparar dicen lo mismo, que es la razón por la que la
    cadena se construye en un solo sitio (`_redes_del_guest`).
    """
    puentes = {}
    for clave, valor in (bloque or {}).items():
        numero = re.match(r"^net(\d+)$", str(clave))
        if not numero:
            continue
        encontrado = re.search(r"(?:^|,)bridge=([^,]+)", str(valor))
        if encontrado:
            puentes[int(numero.group(1))] = encontrado.group(1)
    return puentes


def _puentes_de_estado(actual):
    """Los bridges que el ESTADO guarda de cada interfaz del invitado, por número.

    El estado los lleva en `interfaces` (los arma `estado_desde_api` para TODAS las `netN`),
    con las claves en texto porque viajan por variables de Ansible: aquí se convierten a
    número, que es como los cuenta `_puentes_de`.

    Se lee del estado y no de la config cruda a propósito: `construir_plan` recibe el estado,
    y una comprobación que pidiera campos que el estado no guarda daría por roto un invitado
    perfecto (los vería todos «en ningún bridge»). Le pasó a este mismo cambio.
    """
    puentes = {}
    for indice, bridge in ((actual or {}).get("interfaces") or {}).items():
        try:
            puentes[int(indice)] = bridge
        except (TypeError, ValueError):
            continue
    return puentes


def interfaces_que_difieren(guest, actual, declaracion, estado, parametros):
    """Qué interfaces del invitado NO están en el bridge que la declaración pide.

    `campos_que_difieren` mira `bridge` -- la PRIMERA. Un invitado con varias patas puede
    tener la segunda en otro bridge sin que nadie se entere: la declaración pide
    `[gestion, borde]`, el nodo tiene `[gestion, troncal]`, y como la primera coincide el
    plan dice que no hay nada que hacer. El interior configura entonces una interfaz que ya
    no está donde la declaración dice, y el invitado se queda sin camino.

    Se compara contra lo que escribiría CREAR (`_redes_del_guest`), no contra una copia: si
    cada uno lo calculara por su cuenta, el plan vería diferencias que no son.

    Y no se arregla: cambiarle las interfaces a un invitado EN MARCHA lo obliga a reiniciar, y
    aquí no se reinicia lo que está trabajando (§5). Lo dice quien llama, con el remedio.
    """
    esperados = _puentes_de(_redes_del_guest(guest, declaracion, estado, parametros))
    actuales = _puentes_de_estado(actual)
    return {
        numero: {"esperado": esperados[numero], "encontrado": actuales.get(numero)}
        for numero in sorted(esperados)
        if actuales.get(numero) != esperados[numero]
    }


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

    # Fase 0 — el pool: la frontera de propiedad. Su nombre lleva el prefijo del motor
    # porque Proxmox exige que un poolid EMPIECE POR LETRA y la carpeta de un lab empieza
    # por su número de antigüedad (ADR 0016). Sin pool no hay forma de saber qué invitado
    # es de este lab sin un fichero de estado, así que va lo primero.
    pool = modulo_identidad.identidad_pool(lab)
    if pool not in (estado.get("pools") or {}):
        pasos.append(
            _paso(
                ACCION_POOL,
                "POST",
                "/pools",
                {"poolid": pool, "comment": parametros.get("comentario_pool", "")},
                f"no existe el pool '{pool}': es la frontera de propiedad del lab",
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
    # pone la declaración (etapa, rol); el plan no lo reinventa.
    for guest in identidad["guests"]:
        actual = (estado.get("guests") or {}).get(str(guest["vmid"]))
        ruta_crear = f"/nodes/{nodo}/{guest['tipo']}"
        ruta_config = f"/nodes/{nodo}/{guest['tipo']}/{guest['vmid']}/config"

        if actual is None:
            pasos.append(
                _paso(
                    ACCION_CREAR,
                    "POST",
                    ruta_crear,
                    _parametros_creacion(guest, lab, declaracion, estado, parametros),
                    f"el rol '{guest['rol']}' no está desplegado: se crea con el vmid "
                    f"{guest['vmid']} (el menor libre del clúster)",
                    stage=guest["stage"],
                    rol=guest["rol"],
                )
            )
            continue

        diferencias = campos_que_difieren(_esperado_del_guest(guest), actual)
        if diferencias:
            pasos.append(
                _paso(
                    ACCION_ACTUALIZAR,
                    "PUT",
                    ruta_config,
                    _parametros_actualizacion(guest, diferencias),
                    f"el rol '{guest['rol']}' existe pero difiere en "
                    + ", ".join(sorted(diferencias)),
                    stage=guest["stage"],
                    rol=guest["rol"],
                )
            )

        # Y las INTERFACES, que `campos_que_difieren` no mira más allá de la primera: un
        # invitado con varias patas puede tener la segunda en OTRO bridge sin que nadie se
        # entere. No se puede arreglar en marcha (§5: aquí no se reinicia lo que está
        # trabajando), así que no se rodea -- se para y se dice el remedio.
        de_interfaces = interfaces_que_difieren(guest, actual, declaracion, estado, parametros)
        if de_interfaces:
            donde = "; ".join(
                f"net{numero} está en {dato['encontrado'] or 'NINGÚN bridge'} y la "
                f"declaración pide {dato['esperado']}"
                for numero, dato in de_interfaces.items()
            )
            raise modulo_interior.ErrorMotor(
                f"el rol '{guest['rol']}' (vmid {guest['vmid']}) tiene las interfaces donde "
                f"no las pide la declaración: {donde}. Cambiarle las interfaces a un invitado "
                "EN MARCHA lo obliga a reiniciar, y este motor no reinicia lo que está "
                "trabajando: se rehace el invitado, con "
                f"`./lab --lab {lab} destroy --yes` y luego `apply`."
            )

    # Fase 2 — arrancar, etapa a etapa, y CONVERGER SU INTERIOR antes de tocar el
    # etapa siguiente. El orden dentro de una etapa es el que mata la carrera del
    # DHCP por construcción (regla 18), no por suerte:
    #
    #   arrancar los invitados de la etapa  ->  construir el túnel (si la etapa
    #   trae el bastión)  ->  converger el interior de cada invitado  ->
    #   comprobar que la etapa SIRVE (contesta en el puerto por el que se deja ver).
    #
    # Por qué este orden y no otro (§10): el bastión da la primera
    # dirección a los CHR, y un puesto `address: dhcp` no arranca hasta que su
    # router está convergido y sirviendo. Un lab SIN interior no genera ni un paso de
    # más: los invitados se arrancan igual que siempre, en el mismo orden.
    for stage in declaracion["stages"]:
        del_stage = [i for i in identidad["guests"] if i["stage"] == stage]

        for guest in del_stage:
            actual = (estado.get("guests") or {}).get(str(guest["vmid"]))
            if actual is not None and actual.get("arrancado"):
                continue
            pasos.append(
                _paso(
                    ACCION_ARRANCAR,
                    "POST",
                    f"/nodes/{nodo}/{guest['tipo']}/{guest['vmid']}/status/start",
                    {},
                    f"el rol '{guest['rol']}' pertenece a la etapa {stage} y no está arrancado",
                    stage=stage,
                    rol=guest["rol"],
                )
            )

        # (a) El túnel, PRIMERO y para todos los invitados de la etapa que lo traen:
        #     sin túnel no se entra en el bastión, y sin el bastión
        #     no se entra en ningún otro invitado. Va antes de tocar el interior de
        #     nadie, incluido el suyo.
        for guest in del_stage:
            pasos.extend(modulo_interior.pasos_del_tunnel(guest, declaracion, estado, parametros, identidad))

        # (b) El interior de la etapa, con su BARRERA delante. Sin `config:` no se
        #     entra: el motor lo despliega y se calla, exactamente como en la fase 1.
        #
        #     Dentro de la etapa, primero quien DA dirección (el bastión con
        #     su servidor DHCP, y los routers) y después quien la PIDE: es la misma
        #     razón que ordena los etapas, un nivel más abajo. Un invitado que pide
        #     dirección a quien todavía no la reparte se queda esperando -- y un LXC
        #     deja de pedirla al rato y se queda inalcanzable (medido en v3).
        #
        #     Y la sonda (esperar_servicio) va ANTES del interior de cada invitado, no
        #     al final de la etapa: un invitado recién arrancado NO contesta en el
        #     instante. Un CHR tarda en bootear y en pedir su dirección por DHCP, así
        #     que convergerlo nada más arrancarlo entra en un invitado mudo y aborta la
        #     pasada (medido: el segundo CHR de un lab de aceptación, arranque en frío,
        #     `No route to host`). La barrera pregunta por el puerto por el que el
        #     invitado se deja ver (el REST de RouterOS, el sshd de un Linux); sólo se
        #     converge lo que ya contesta, y eso deja la etapa listo --convergido y
        #     sirviendo-- antes de tocar el siguiente.
        conviene = [
            i for i in del_stage
            if modulo_interior.declara_interior(i) or modulo_interior.tiene_tunnel(i)
        ]
        for guest in sorted(conviene, key=_orden_de_arranque):
            sonda = modulo_interior.espera_de_servicio(guest)
            if sonda is not None:
                pasos.append(sonda)
            if not modulo_interior.declara_interior(guest):
                continue
            leido = (estado.get("interior") or {}).get(str(guest["vmid"])) or {}
            pasos.extend(
                modulo_interior.pasos_de_convergencia(guest, identidad, declaracion, leido, parametros)
            )

    for indice, paso in enumerate(pasos, start=1):
        paso["orden"] = indice
    return pasos


def _prefijo_mac(parametros):
    """El OUI de las MAC del motor, que viene de `vars/engine.yml` (no se incrusta).

    Está en un solo sitio porque las MAC se derivan en dos: la de un invitado de una interfaz
    (`identidad_mac`, al asignar la identidad) y la de cada interfaz de un invitado del
    interior (`identidad_mac_de_interface`). Si falta, se dice: con un prefijo inventado las
    MAC cambiarían sin que nadie lo haya pedido.
    """
    prefijo = str(parametros.get("mac_prefijo") or "").strip()
    if not prefijo:
        raise modulo_interior.ErrorMotor(
            "falta el prefijo de las MAC del motor (`engine_prefijo_mac`): sin él no se "
            "puede derivar la identidad de las interfaces de un invitado del interior"
        )
    return prefijo


def _red_del_guest(guest, declaracion, estado, parametros):
    """TODAS las interfaces de un invitado que declara túnel, como claves `net<índice>`.

    Un invitado del interior NACE COMPLETO: una interfaz por cada bridge del lab y una en el
    bridge de gestión del nodo, la última (por ahí sale hacia casa). Cambiarle las interfaces
    a un invitado en marcha obliga a reiniciarlo, y aquí no se reinicia la máquina que
    está trabajando (§5): por eso todas se declaran al crear.

    **Cada interfaz lleva su MAC derivada** (`mac_de_la_interfaz`): la 0 es la de siempre y las
    demás salen del mismo sitio. Dejárselas a Proxmox sería estado que el motor no
    controla, y el plan las vería distintas en cada pasada.

    Las claves `netN` NO son un campo suelto (se reescriben enteras), así que esta misma
    función vale para crear y para actualizar. `_net0` sigue siendo la red de un invitado
    de una sola interface: los de la fase 1, que no declaran túnel.
    """
    if not modulo_interior.tiene_tunnel(guest):
        return {}
    red = {}
    for indice, interface in enumerate(
        modulo_interior.interfaces_del_bastion(guest, declaracion, estado, parametros)
    ):
        mac = modulo_identidad.identidad_mac_de_interface(
            guest["vmid"], indice, _prefijo_mac(parametros)
        )
        if guest["tipo"] == "lxc":
            # En un contenedor la dirección se declara en la propia interfaz. La interfaz
            # del bridge de gestión del NODO lleva PASARELA (es por donde sale hacia
            # casa); las del lab no, porque la gestión no puede depender de los routers
            # que el motor está desplegando.
            red[f"net{indice}"] = (
                f"name=eth{indice},bridge={interface['bridge']},hwaddr={mac}"
                + (f",ip={interface['address']}" if interface.get("address") else "")
                + (f",gw={interface['gateway']}" if interface.get("gateway") else "")
            )
        else:
            red[f"net{indice}"] = f"virtio={mac},bridge={interface['bridge']}"
    return red


def _redes_del_guest(guest, declaracion, estado, parametros):
    """El bloque de red del invitado: `net0`, `net1`... una por PATA DECLARADA.

    Tres casos, y ninguno se adivina:
      * el invitado del TÚNEL (el bastión) nace con una interfaz por cada bridge del
        lab y una en el bridge de gestión del NODO, la última: eso lo decide
        `_red_del_invitado` y va aparte;
      * un invitado que declara VARIAS interfaces (`bridges:`) nace con una por bridge, en el
        orden declarado y con la MAC de cada interfaz derivada (`identidad_mac_de_interface`). Es el
        caso de un CHR que sirve una LAN: sus interfaces son `ether1`, `ether2`... en ese
        orden, y por eso el orden de la declaración ES la numeración;
      * el resto (una sola interfaz) es `_net0`, exactamente como en la fase 1.
    """
    if modulo_interior.tiene_tunnel(guest):
        return _red_del_guest(guest, declaracion, estado, parametros)
    interfaces = guest.get("bridges") or []
    if len(interfaces) <= 1:
        red = {"net0": _net0(guest)}
        red.update(_interface_de_fuera(guest, parametros))
        return red
    red = {}
    for indice, bridge in enumerate(interfaces):
        mac = modulo_identidad.identidad_mac_de_interface(
            guest["vmid"], indice, _prefijo_mac(parametros)
        )
        if guest["tipo"] == "lxc":
            red[f"net{indice}"] = f"name=eth{indice},bridge={bridge},hwaddr={mac}"
        else:
            red[f"net{indice}"] = f"virtio={mac},bridge={bridge}"
    red.update(_interface_de_fuera(guest, parametros))
    return red


def _interface_de_fuera(guest, parametros):
    """La interfaz del EXTERIOR (área `interior.uplink`), como `{clave: valor}`, o {}.

    Es la ÚLTIMA interfaz y va sin dirección: se tiende al bridge del nodo que tiene salida
    (valor de ENTORNO, `pve_bridge_gestion` en secrets.yml, nunca un valor de lab) y la
    dirección se la pide el propio router por DHCP desde dentro. Se añade al nacer por la
    misma razón que las del bastión: cambiarle las interfaces a un invitado en marcha
    obliga a reiniciarlo, y aquí no se reinicia lo que está trabajando (§5).
    """
    if not modulo_interior.interfaz_exterior(guest):
        return {}
    puente = str(parametros.get("bridge_gestion") or "")
    if not puente:
        raise modulo_interior.ErrorMotor(
            f"el invitado {guest.get('rol')} declara exterior (salida del lab) y el "
            "motor no sabe por dónde sale este nodo: falta `pve_bridge_gestion` en "
            "secrets.yml (el bridge del nodo con dirección y salida)"
        )
    indice = len(modulo_interior.interfaces_de_un_guest(guest))
    mac = modulo_identidad.identidad_mac_de_interface(
        guest["vmid"], indice, _prefijo_mac(parametros)
    )
    return {f"net{indice}": f"virtio={mac},bridge={puente}"}


def _net0(guest):
    """La cadena de red de la config de Proxmox para este invitado.

    Un contenedor la declara con `name/bridge/hwaddr`; una VM con `<modelo>=<mac>`.
    Está en un solo sitio porque crear y actualizar tienen que decir lo mismo.

    **Y la dirección va aquí, como en una máquina de verdad**: una ESTACIÓN no lleva
    ninguna puesta -- al enchufarle el cable la PIDE (`dhcp`), y el router de su red le da
    dirección, vía de acceso y DNS. Un SERVIDOR la lleva FIJA, con su pasarela puesta a mano
    (`address` + `gateway`), y por eso no pregunta nada: sigue saliendo porque sabe por
    dónde. Lo que el lab no declara, no se inventa: sin `address` el invitado nace sin
    ella, que es lo que hacía siempre.
    """
    if guest["tipo"] == "lxc":
        # La dirección va en la cadena de red SÓLO si el lab la declara: `address: dhcp`
        # para una estación (que al conectar la pide, y el router de su red le da dirección,
        # vía de acceso y DNS), o una dirección con su `gateway` para una máquina fija (que no
        # pregunta nada y sale igual, porque sabe por dónde). Lo que no se declara, no se
        # inventa: un invitado sin `address` nace sin ella, como hasta ahora -- y eso
        # incluye a los de la fase 1, cuyo plan no cambia.
        direccion = str(guest.get("address") or "")
        gateway = str(guest.get("gateway") or "")
        red = f"name=eth0,bridge={guest['bridge']},hwaddr={guest['mac']}"
        if not direccion:
            return red
        if direccion.lower() == "dhcp":
            return red + ",ip=dhcp"
        red += f",ip={direccion}"
        if gateway:
            red += f",gw={gateway}"
        return red
    return f"virtio={guest['mac']},bridge={guest['bridge']}"


# Traducción de los campos INTERNOS (vocabulario del dominio, en castellano) a las
# claves LITERALES de la API de Proxmox. No son lo mismo: `descripcion` es
# `description` y `memory` es `memory`. El nombre cambia según el tipo (`hostname`
# en un contenedor, `name` en una VM) y la red no es un campo suelto (se reescribe
# `net0` entero): por eso no están todos en esta tabla.
PARAMETRO_API = {
    "descripcion": "description",
    "cores": "cores",
    "memory": "memory",
}


def _parametros_creacion(guest, lab, declaracion, estado, parametros):
    """Los parámetros de la API para crear un invitado de este tipo.

    Se separa para que la diferencia entre una VM y un contenedor esté en un solo
    sitio y se lea de un vistazo.
    """
    comunes = {
        "vmid": guest["vmid"],
        "description": guest["descripcion"],
        "pool": modulo_identidad.identidad_pool(lab),
        "cores": guest["cores"],
        "memory": guest["memory"],
    }

    # Las interfaces: `net0` para un invitado de siempre, una por bridge declarado (`net0`,
    # `net1`...) para uno que sirve varias redes, y las del túnel para el puesto de
    # control. Todas se deciden al crear: cambiarle las interfaces a un invitado en marcha
    # obliga a reiniciarlo y aquí no se reinicia la máquina que está trabajando (§5).
    comunes.update(_redes_del_guest(guest, declaracion, estado, parametros))

    if guest["tipo"] == "lxc":
        # En un contenedor el nombre va en `hostname` y hace falta la plantilla.
        creado = {
            **comunes,
            "hostname": guest["nombre"],
            "ostemplate": parametros["ostemplate_lxc"],
        }
        # La clave pública del motor se deja DENTRO del invitado al crearlo
        # (`ssh-public-keys`): Proxmox la escribe en el rootfs, sin `snippets` ni
        # cloud-init. Es la otra mitad del tunnel: sin clave no hay por dónde entrar
        # aunque el túnel esté en pie.
        if modulo_interior.tiene_tunnel(guest) and parametros.get("tunnel_clave_publica"):
            creado["ssh-public-keys"] = parametros["tunnel_clave_publica"]
        # Y su consola tiene que dar una SHELL, no un `login`. Es por donde el motor le
        # pone el arranque del túnel, UNA vez (§5): con el `cmode` de fábrica (`tty`)
        # la consola pide usuario y contraseña, y la línea se quedaría escrita en un
        # prompt de login sin que nadie la leyera. Medido en el código de PVE:
        # `cmode: shell` entrega la shell de root directamente en la consola.
        if modulo_interior.tiene_tunnel(guest):
            creado["cmode"] = "shell"
        return creado

    # En una VM el nombre va en `name` y no hay plantilla que valga.
    creado = {**comunes, "name": guest["nombre"]}

    # Y el AGENTE DE INVITADO, que es un canal de LECTURA del invitado hacia el
    # hipervisor: la única forma de que el motor sepa las INTERFACES de una VM, porque
    # la config de una VM QEMU no lleva `ip=` --lo pone el invitado por dentro-- y no
    # hay endpoint de interfaces más que para contenedores. Sin esto, el motor elige la
    # dirección de la interfaz de gestión del puesto contando por arriba A CIEGAS, con la
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
    # del nodo, que habla `tools/console.py` y sólo él -- sin abrir la consola gráfica y sin
    # pedirle una pantalla al hipervisor. Va aquí, con el bus del disco, porque se decide al
    # NACER: un invitado que nació sin consola serie se rehace (`destroy` + `apply`), que es
    # como lo crea el motor -- entero. No es un valor de ningún lab: es lo que un RouterOS
    # necesita para que se le pueda leer la consola.
    if modulo_interior.tipo_de(guest) == "routeros":
        creado["serial0"] = "socket"
        creado["vga"] = "serial0"

    # La imagen de fábrica se adjunta SÓLO al crear: `import-from` no se acepta
    # después (medido). De ahí que la declaración de `image` sea una promesa que se
    # cumple al nacer el invitado, o no se cumple nunca.
    #
    # El BUS del disco no es cosmético, y esto está MEDIDO: un CHR (RouterOS) NO arranca
    # con el disco en virtio-scsi --SeaBIOS se queda en «Load system / ERROR: could not
    # find disk!» y entra en bucle de iPXE-- y sí arranca en SATA. Se vio con el dedo:
    # el CHR creado en `scsi0` no llegó ni a pedir concesión DHCP, y por eso el motor no
    # encontraba su REST («no route to host»). Así que el bus lo decide lo que el
    # invitado DECLARA SER por dentro (`config: {routeros: ...}`, vía `tipo_de`), nunca
    # el nombre del fichero de la image: eso sería un valor de lab.
    if guest.get("image"):
        almacen = parametros["almacenamiento_imagen"]
        bus = "sata0" if modulo_interior.tipo_de(guest) == "routeros" else "scsi0"
        creado[bus] = f"{almacen}:0,import-from={almacen}:import/{guest['image']}"
        creado["bootdisk"] = bus
    return creado


def _parametros_actualizacion(guest, diferencias):
    """Los parámetros de la API para ACTUALIZAR un invitado que ya existe.

    `diferencias` trae campos internos; aquí se traducen a las claves LITERALES de la
    API. Sin esto, un `PUT .../config` saldría con `descripcion` o `memory` y la API
    lo rechazaría con un 400 ("property is not defined in schema").
    """
    valor = {
        "descripcion": guest["descripcion"],
        "cores": guest["cores"],
        "memory": guest["memory"],
        "cmode": "shell",
    }
    parametros = {}
    for campo in diferencias:
        if campo in PARAMETRO_API:
            parametros[PARAMETRO_API[campo]] = valor[campo]
        elif campo == "nombre":
            parametros["hostname" if guest["tipo"] == "lxc" else "name"] = guest["nombre"]
        elif campo == "cmode":
            # La consola, en la clave literal de la API.
            parametros["cmode"] = valor["cmode"]
        elif campo in ("bridge", "mac"):
            if modulo_interior.tiene_tunnel(guest):
                # Las interfaces se decidieron al nacer y una interfaz nueva sólo existe tras
                # arrancar el invitado: aquí no se finge una convergencia que no se
                # puede hacer. Se dice el remedio y se para.
                raise modulo_interior.ErrorMotor(
                    f"las interfaces del invitado {guest['rol']} cambiaron y eso no se "
                    "cambia en caliente: hay que rehacerlo (`destroy` de ese invitado "
                    "y `apply`), que es como lo crea el motor: entero"
                )
            # La red no es un campo suelto: se reescriben las interfaces ENTERAS (`net0`, `net1`...).
            # Sin declaración ni estado: por aquí NO puede pasar un invitado del túnel (el
            # guardián de arriba lo impide), y es el único que necesitaría leer el mundo.
            parametros.update(_redes_del_guest(guest, None, None, parametros))
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
    for guest in identidad["guests"]:
        lineas.append(
            "  etapa {e}  {tipo:4}  rol={rol:16} vmid={vmid:<6} mac={mac}  {origen}".format(
                e=guest["stage"],
                tipo=guest["tipo"],
                rol=guest["rol"],
                vmid=guest["vmid"],
                mac=guest["mac"],
                origen=guest["origen"],
            )
        )
    lineas.append("")

    if not plan:
        lineas.append("No hay nada que hacer: el mundo ya coincide con la declaración.")
        lineas.append(f"({len(declaracion['guests'])} invitados declarados, todos presentes y coincidentes)")
        return "\n".join(lineas)

    # La cabecera sólo cambia si el plan lleva algo que NO es una llamada REST. Así
    # los planes de un lab sin interior --que están congelados y se comparan línea a
    # línea contra su copia de referencia-- salen exactamente igual que ayer.
    solo_api = all(paso.get("via", VIA_API) == VIA_API for paso in plan)
    if solo_api:
        lineas.append(f"Llamadas REST que se harían, en orden ({len(plan)}):")
    else:
        lineas.append(f"Pasos del plan (API, interior y túnel), en orden ({len(plan)}):")
    lineas.append("")
    for paso in plan:
        if paso["metodo"]:
            lineas.append(f"  {paso['orden']:>2}. {paso['metodo']:<4} {paso['ruta']}")
        else:
            # Un paso sin método no es una llamada REST: es una acción del motor
            # (converger un área, esperar a que una etapa sirva, construir el túnel).
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
