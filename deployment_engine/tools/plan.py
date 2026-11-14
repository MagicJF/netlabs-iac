# PROPÓSITO:   calcula el PLAN: la lista ORDENADA de llamadas REST que llevan el
#              mundo desde su estado actual hasta la declaración. Es el único
#              sitio donde se decide "qué hay que hacer": `plan` lo imprime y
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


def campos_que_difieren(esperado, actual):
    """Qué campos declarados no coinciden con lo que hay en Proxmox.

    Se compara sólo lo que la API de Proxmox guarda de verdad en la config: el
    nombre, el número de cores, la memoria, el bridge de la red y la descripción.
    La DIRECCIÓN IP declarada no está aquí porque vive DENTRO del invitado y la
    API no la ve: eso es un límite, y `verify` lo dice en voz alta.
    """
    diferencias = {}
    for campo in ("nombre", "cores", "memoria", "bridge", "descripcion", "mac"):
        if campo not in actual:
            continue
        if actual[campo] is None:
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
                    _parametros_creacion(invitado, lab, parametros),
                    f"el rol '{invitado['rol']}' no está desplegado: se crea con el vmid "
                    f"{invitado['vmid']} (el menor libre del clúster)",
                    escalon=invitado["escalon"],
                    rol=invitado["rol"],
                )
            )
            continue

        diferencias = campos_que_difieren(invitado, actual)
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
            pasos.extend(modulo_interior.pasos_del_camino(invitado, declaracion, estado, parametros))

        # (b) El interior del escalón. Sin `config:` no se entra: el motor lo despliega
        #     y se calla, exactamente como en la fase 1.
        #
        #     Dentro del escalón, primero quien DA dirección (el puesto de control con
        #     su servidor DHCP, y los routers) y después quien la PIDE: es la misma
        #     razón que ordena los escalones, un nivel más abajo. Un invitado que pide
        #     dirección a quien todavía no la reparte se queda esperando -- y un LXC
        #     deja de pedirla al rato y se queda inalcanzable (medido en v3).
        interiores = [i for i in del_escalon if modulo_interior.declara_interior(i)]
        for invitado in sorted(interiores, key=_orden_de_arranque):
            leido = (estado.get("interior") or {}).get(str(invitado["vmid"])) or {}
            pasos.extend(
                modulo_interior.pasos_de_convergencia(invitado, identidad, declaracion, leido, parametros)
            )

        # (c) La sonda del escalón: sólo se pasa al siguiente si este SIRVE. Se sondea
        #     lo que declara interior (lo que no se configura no se promete).
        for invitado in del_escalon:
            if not (modulo_interior.declara_interior(invitado) or modulo_interior.tiene_camino(invitado)):
                continue
            sonda = modulo_interior.espera_de_servicio(invitado)
            if sonda is not None:
                pasos.append(sonda)

    for indice, paso in enumerate(pasos, start=1):
        paso["orden"] = indice
    return pasos


def _net0(invitado):
    """La cadena de red de la config de Proxmox para este invitado.

    Un contenedor la declara con `name/bridge/hwaddr`; una VM con `<modelo>=<mac>`.
    Está en un solo sitio porque crear y actualizar tienen que decir lo mismo.
    """
    if invitado["tipo"] == "lxc":
        return f"name=eth0,bridge={invitado['bridge']},hwaddr={invitado['mac']}"
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


def _parametros_creacion(invitado, lab, parametros):
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
        "net0": _net0(invitado),
    }
    if invitado["tipo"] == "lxc":
        # En un contenedor el nombre va en `hostname` y hace falta la plantilla.
        return {
            **comunes,
            "hostname": invitado["nombre"],
            "ostemplate": parametros["ostemplate_lxc"],
        }
    # En una VM el nombre va en `name` y no hay plantilla que valga.
    return {**comunes, "name": invitado["nombre"]}


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
    }
    parametros = {}
    for campo in diferencias:
        if campo in PARAMETRO_API:
            parametros[PARAMETRO_API[campo]] = valor[campo]
        elif campo == "nombre":
            parametros["hostname" if invitado["tipo"] == "lxc" else "name"] = invitado["nombre"]
        elif campo in ("bridge", "mac"):
            # La red no es un campo suelto: se reescribe `net0` entero.
            parametros["net0"] = _net0(invitado)
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
