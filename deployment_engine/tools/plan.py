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

ACCION_POOL = "crear_pool"
ACCION_BRIDGE = "crear_bridge"
ACCION_RECARGAR_RED = "recargar_red"
ACCION_CREAR = "crear_invitado"
ACCION_ACTUALIZAR = "actualizar_invitado"
ACCION_ARRANCAR = "arrancar_invitado"


def _paso(accion, metodo, ruta, parametros, porque, escalon=None, rol=None):
    """Un paso del plan. `porque` es obligatorio: un paso sin razón es un bug."""
    return {
        "accion": accion,
        "metodo": metodo,
        "ruta": ruta,
        "parametros": parametros,
        "porque": porque,
        "escalon": escalon,
        "rol": rol,
    }


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

    # Fase 2 — arrancar, escalón a escalón. Los invitados de un escalón superior no
    # arrancan hasta que el inferior está en marcha.
    for escalon in declaracion["escalones"]:
        for invitado in identidad["invitados"]:
            if invitado["escalon"] != escalon:
                continue
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

    lineas.append(f"Llamadas REST que se harían, en orden ({len(plan)}):")
    lineas.append("")
    for paso in plan:
        lineas.append(f"  {paso['orden']:>2}. {paso['metodo']:<4} {paso['ruta']}")
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
