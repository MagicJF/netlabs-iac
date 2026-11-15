# PROPÓSITO:   leer el estado del mundo (lo que Proxmox dice que hay) y compararlo
#              con lo declarado. Aquí vive `estado_desde_api` (normaliza las
#              respuestas de la API) y `estado_verificar` (la comparación por
#              conjuntos EN LOS DOS SENTIDOS: falta algo = fallo, sobra algo =
#              también fallo). Para calcular el plan delega en tools/plan.py, para
#              que no exista una segunda lógica de decisión. Aquí vive también la
#              decisión de qué BRIDGES puede borrar `destroy` (del nodo, no del lab:
#              su prueba de propiedad es el `comments` del motor).
# INVARIANTES: el conjunto ESPERADO se DERIVA de la declaración; el test nunca
#              recorre la lista que él mismo trae. El estado es lo que dice la API
#              (o un fixture), nunca una caché propia: no hay estado en disco.
#              Un invitado que existe pero está en el pool de OTRO lab se reporta
#              como "de otro lab", no como propio.
# LÍMITES:     la dirección IP declarada de cada rol NO se puede verificar por
#              API: la IP vive dentro del invitado y la config del hipervisor no
#              la guarda. `verify` lo dice explícitamente en vez de callarse.
#              Un bridge sin la marca del motor (o con la de otro lab) no se puede
#              reclamar: se conserva y se dice por qué.
# VER:         README.md §Verificación; README.md §Los bridges;
#              AGENTS.md §Identidad; ./lab check declaracion

import os
import sys

# `estado.py` es el filtro que Ansible ve; el cálculo del plan (mucho más grande)
# vive en tools/plan.py para poder probarse sin Ansible. El módulo se importa por
# ruta, no por PYTHONPATH: el motor no depende de variables de entorno (regla 3).
_DIRECTORIO_FILTROS = os.path.dirname(os.path.abspath(__file__))
_TOOLS = os.path.join(os.path.dirname(_DIRECTORIO_FILTROS), "tools")
for _ruta in (_TOOLS, _DIRECTORIO_FILTROS):
    if _ruta not in sys.path:
        sys.path.insert(0, _ruta)

import plan as modulo_plan  # noqa: E402  (la ruta se ajusta justo arriba)
import identidad as modulo_identidad  # noqa: E402

try:
    from ansible.errors import AnsibleFilterError as ErrorMotor
except ImportError:  # pragma: no cover - sólo ocurre fuera de Ansible
    class ErrorMotor(Exception):
        """Error del motor, con el mismo nombre que el de Ansible."""


def _red_de_net0(net0):
    """Saca (bridge, mac) de la cadena de red de la config de Proxmox.

    En una VM es `virtio=BC:24:11:00:00:64,bridge=vmbr0`; en un contenedor es
    `name=eth0,bridge=vmbr0,hwaddr=BC:24:11:00:00:64`. Las dos formas caen con
    este recorrido, que es por eso que está en un solo sitio.
    """
    bridge = None
    mac = None
    for trozo in str(net0 or "").split(","):
        clave, _, valor = trozo.partition("=")
        clave = clave.strip().lower()
        if clave == "bridge":
            bridge = valor.strip()
        elif clave == "hwaddr":
            mac = valor.strip().upper()
        elif ":" in valor and clave != "name":
            # En una VM la MAC va en la propia clave: `virtio=<mac>`.
            mac = valor.strip().upper()
    return bridge, mac


def _descripcion_sin_ruido(texto):
    """La descripción como la guarda Proxmox, sin el `\\n` que la API le pega al final.

    Proxmox trata `description` como campo de texto y le añade un salto de línea: si
    no se quita, la comparación de idempotencia ve "drift" donde no lo hay y dispara
    un PUT innecesario (rompiendo la regla de que dos ejecuciones seguidas no cambian
    nada). El `strip` sólo toca los extremos; el interior se respeta tal cual.
    """
    return (texto or "").strip()


def estado_vacio():
    """El mundo antes de que exista nada: un clúster sin invitados ni pools."""
    return {
        "nodo": "",
        "vmids_usados": [],
        "bridges_nodo": [],
        "bridges_comentarios": {},
        "pools": {},
        "invitados": {},
        "invitados_otros": {},
        # La red del NODO, como subredes: {bridge: "10.10.10.1/24"}. Es lo que permite
        # elegir una dirección libre en el bridge de gestión para la pata del puesto de
        # control (§5): el motor no guarda ninguna, la elige y la vuelve a elegir cada
        # vez. Sin esto, esa pata nacería sin dirección y no habría camino.
        "bridges_direcciones": {},
        # Direcciones que YA usa alguien en el nodo (direcciones sin máscara). Nace con
        # las de los propios bridges del nodo --la puerta de cada subred-- y crece con
        # lo que digan los contenedores del nodo (`GET /lxc/<vmid>/interfaces`).
        "direcciones_usadas": [],
    }


def estado_normalizar(datos):
    """Completa un estado con las claves que el resto del motor espera.

    Sirve para que un fixture escrito a mano no tenga que declarar los campos
    vacíos: se rellenan aquí de forma explícita (nunca de forma implícita y
    sorprendente).
    """
    base = estado_vacio()
    if not isinstance(datos, dict):
        raise ErrorMotor("el estado del mundo no es un mapa")
    for clave, valor in datos.items():
        base[clave] = valor
    base["vmids_usados"] = sorted(int(v) for v in (base.get("vmids_usados") or []))
    base["pools"] = base.get("pools") or {}
    base["invitados"] = base.get("invitados") or {}
    base["invitados_otros"] = base.get("invitados_otros") or {}
    base["bridges_nodo"] = base.get("bridges_nodo") or []
    base["bridges_comentarios"] = base.get("bridges_comentarios") or {}
    base["bridges_direcciones"] = base.get("bridges_direcciones") or {}
    base["direcciones_usadas"] = sorted(str(d) for d in (base.get("direcciones_usadas") or []))
    return base


def estado_desde_api(datos):
    """Normaliza las respuestas CRUDAS de la API en el estado que usa el motor.

    Entradas (todas tal cual las devuelve Proxmox):
      - `cluster_recursos`: GET /cluster/resources -- todos los invitados, con su
        `pool` y si están `running`. Es la fuente de "qué vmids están ocupados en
        TODO el clúster", que es lo que impide reutilizar un vmid de otro lab.
      - `pools_lista`: GET /pools -- los pools que existen (las fronteras de
        propiedad). Sin esto, un pool vacío parecería no existir y `apply` lo
        volvería a crear en cada ejecución: dejaría de ser idempotente.
      - `red_nodo`: GET /nodes/<nodo>/network -- los bridges que ya existen.
      - `configs`: {vmid: {config}} -- GET /nodes/<nodo>/<tipo>/<vmid>/config, para
        la descripción, los recursos y la red de los invitados DEL lab.
      - `lab`: el nombre del pool de este lab (su carpeta).
    """
    lab = datos["lab"]
    estado = estado_vacio()
    estado["nodo"] = datos.get("nodo") or ""

    configs = {str(k): v for k, v in (datos.get("configs") or {}).items()}
    recursos = datos.get("cluster_recursos") or []

    for pool in datos.get("pools_lista") or []:
        estado["pools"][pool.get("poolid")] = {"comment": pool.get("comment") or ""}

    for recurso in recursos:
        vmid = recurso.get("vmid")
        if vmid is None:
            continue
        estado["vmids_usados"].append(int(vmid))

    for interfaz in datos.get("red_nodo") or []:
        # El nodo devuelve interfaces de varios tipos; sólo interesan los bridges,
        # que son los que un lab puede necesitar crear. Del `comments` sale la marca
        # del motor (`lab=<lab>`), que es lo único que prueba que el bridge lo creó
        # este lab: Proxmox no mete interfaces en pools.
        if interfaz.get("iface") and (
            interfaz.get("type") == "bridge" or str(interfaz["iface"]).startswith("vmbr")
        ):
            estado["bridges_nodo"].append(interfaz["iface"])
            estado["bridges_comentarios"][interfaz["iface"]] = _descripcion_sin_ruido(
                interfaz.get("comments")
            )
            # La subred del bridge, tal como la declara la API: `cidr` en PVE 8/9
            # (medido en este nodo: {"iface": "vmbr1", "cidr": "10.10.10.1/24"}), y
            # `address`+`netmask` en versiones anteriores. La dirección del bridge es
            # la PUERTA de esa subred, y por eso cuenta como ocupada.
            subred = interfaz.get("cidr") or ""
            if not subred and interfaz.get("address") and interfaz.get("netmask"):
                subred = f"{interfaz['address']}/{interfaz['netmask']}"
            if subred:
                estado["bridges_direcciones"][interfaz["iface"]] = subred
                estado["direcciones_usadas"].append(subred)

    for recurso in recursos:
        vmid = recurso.get("vmid")
        if vmid is None:
            continue
        vmid = int(vmid)
        tipo = recurso.get("type")
        pool = recurso.get("pool")
        nombre = recurso.get("name") or recurso.get("id") or str(vmid)
        if pool == lab:
            config = configs.get(str(vmid), {})
            bridge, mac = _red_de_net0(config.get("net0"))
            tipo = "lxc" if tipo == "lxc" else "qemu"
            estado["invitados"][str(vmid)] = {
                "vmid": vmid,
                "nombre": config.get("name") or config.get("hostname") or nombre,
                "tipo": tipo,
                "descripcion": _descripcion_sin_ruido(config.get("description")),
                "cores": config.get("cores"),
                "memoria": config.get("memory"),
                "bridge": bridge,
                "mac": mac,
                "arrancado": recurso.get("status") == "running",
                "pool": pool,
                "nodo": recurso.get("node"),
                # Privilegiado o no: SÓLO se lee, y sólo para contenedores. En la
                # config de un contenedor, Proxmox OMITE `unprivileged` cuando el
                # contenedor es privilegiado, así que la AUSENCIA es la señal de
                # alarma, no la presencia. El motor no necesita `VM.Console` para
                # nada más, pero con él la consola de un invitado es root DENTRO de
                # ese invitado: con el contenedor sin privilegios, root dentro no es
                # root fuera (ver docs/decisiones/0004). Por eso esto se verifica.
                "privilegiado": tipo == "lxc" and not bool(config.get("unprivileged")),
                # El modo de la CONSOLA. Es lo que decide si la consola de un
                # contenedor da una shell o un `login`, y el motor necesita la shell
                # para poner el arranque del camino UNA vez (§5). Medido: Proxmox
                # OMITE `cmode` cuando vale lo de fábrica (`tty`), así que la ausencia
                # significa `tty`, no «desconocido».
                "cmode": (config.get("cmode") or "tty") if tipo == "lxc" else None,
            }
            estado["pools"].setdefault(lab, {})
        else:
            # Está en el clúster pero NO es de este lab: puede ser de otro lab, o
            # de nadie. Se guarda aparte para poder decirlo en el informe.
            estado["invitados_otros"][nombre] = {
                "vmid": vmid,
                "pool": pool,
                "descripcion": _descripcion_sin_ruido((configs.get(str(vmid)) or {}).get("description")),
            }

    estado["vmids_usados"] = sorted(set(estado["vmids_usados"]))
    estado["bridges_nodo"] = sorted(set(estado["bridges_nodo"]))
    return estado


def _direcciones_v4(lectura):
    """Las direcciones IPv4 de una lectura de interfaces, sea de un contenedor o de una VM.

    Dos formas y un solo significado (medido):
      - CONTENEDOR (`GET /nodes/<nodo>/lxc/<vmid>/interfaces`): una LISTA de entradas con
        `name`, `inet` e `inet6`; la IPv4 viene en `inet`, con la máscara.
      - VM, por el AGENTE (`GET /nodes/<nodo>/qemu/<vmid>/agent/network-get-interfaces`):
        un OBJETO con `result` y, dentro, entradas con `name` e `ip-addresses` (una lista
        de `{ip-address, prefix, ip-address-type}`). Se cogen las de tipo `ipv4`.

    Una lectura VACÍA (`{}`) es una lectura que se TOLERÓ porque falló --al token le falta
    `VM.GuestAgent.Audit` en la ACL del nodo, o la VM no nació con agente--: no aporta nada
    y NO se confunde con «no tiene direcciones». El motor no inventa lo que no puede leer.
    """
    if isinstance(lectura, dict):
        lectura = lectura.get("result") or []
    if not isinstance(lectura, list):
        return
    for entrada in lectura:
        if not isinstance(entrada, dict):
            continue
        if entrada.get("inet"):
            yield str(entrada["inet"])
        for direccion in (entrada.get("ip-addresses") or []):
            if not isinstance(direccion, dict):
                continue
            if direccion.get("ip-address-type") not in (None, "ipv4"):
                continue
            if not direccion.get("ip-address"):
                continue
            # Con la máscara, como la da un contenedor: así «una dirección en uso» es
            # la misma cadena venga de donde venga, y el consumidor (`direccion_libre`)
            # no tiene que saber de dónde salió. Si el agente no dice el prefijo, se
            # conserva la dirección sola: se dice lo que se sabe, no se rellena.
            prefijo = direccion.get("prefix")
            yield (f"{direccion['ip-address']}/{prefijo}" if prefijo is not None
                   else str(direccion["ip-address"]))


def estado_con_direcciones(estado, interfaces):
    """Mete en el estado las direcciones que usan los invitados del nodo.

    `interfaces` es {vmid: lectura} y la lectura viene de una de las dos puertas de
    lectura que hay (ver `_direcciones_v4`): la de un CONTENEDOR
    (`GET /nodes/<nodo>/lxc/<vmid>/interfaces`) o la de una VM por su AGENTE
    (`.../qemu/<vmid>/agent/network-get-interfaces`, ADR 0011). Las dos acaban en la
    misma lista de direcciones usadas, que es lo único que importa aquí. Sólo se miran
    las IPv4: el motor no gestiona IPv6 dentro de los labs.

    Por qué esto es una función pura y no un bucle de plantilla: es la MISMA pregunta
    que hace `direccion_libre` («¿está libre esta dirección?»), y tenerla en dos
    sitios sería tener dos verdades. Se prueba con fixtures, sin Proxmox.

    Lo que sigue sin poder saberse, y se dice en vez de fingirlo: la lectura de una VM
    depende de que naciera con el agente Y de que el token tenga el privilegio. Cuando
    falla, la puerta lo TOLERA (su error queda en el diario) y esa VM sigue siendo
    invisible -- el motor se queda como estaba, contando por ARRIBA (`.254`, `.253`…)
    para no pisar lo que no ve. Lo que no se puede saber, se dice.
    """
    usadas = set(str(d) for d in (estado.get("direcciones_usadas") or []))
    for vmid in sorted((interfaces or {}), key=lambda v: str(v)):
        for direccion in _direcciones_v4(interfaces.get(vmid)):
            usadas.add(direccion)
    estado = dict(estado)
    estado["direcciones_usadas"] = sorted(usadas)
    return estado


def estado_resumen(estado):
    """Una línea con lo esencial del estado del mundo, para el informe humano."""
    return (
        f"nodo={estado.get('nodo') or '?'} "
        f"vmids_usados={len(estado.get('vmids_usados') or [])} "
        f"pools={sorted((estado.get('pools') or {}).keys())} "
        f"invitados_del_pool={len(estado.get('invitados') or {})} "
        f"bridges={len(estado.get('bridges_nodo') or [])}"
    )


# --- Bridges: del nodo, no del lab -------------------------------------------
# Un invitado se puede probar con el pool; un BRIDGE no, porque Proxmox no mete
# interfaces de red en ningún pool. La única prueba de que un bridge lo creó este
# lab es el `comments` que le escribió `plan` al crearlo (`lab=<lab> ...`), y la
# segunda guarda es que ningún invitado de FUERA del lab lo esté usando. En la duda
# se conserva: un bridge huérfano es inerte, uno borrado por error es una caída.


def _usos_de_bridges(configs):
    """(usos, sin_leer) leyendo TODAS las interfaces (net0, net1, …) de unas configs.

    `usos` es {bridge: [(vmid, nombre)]}. Se miran todas las interfaces y no sólo
    `net0`: un invitado con dos patas puede tener la segunda en un bridge del lab, y
    borrarlo lo dejaría sin esa red.

    `sin_leer` son los vmids cuya config NO se pudo leer. Se distinguen de un
    invitado sin interfaces porque una lectura con éxito SIEMPRE trae contenido (al
    menos `digest`); un mapa vacío sólo sale de un error de la API. La diferencia
    importa: con una config sin leer no se puede descartar que ese invitado use el
    bridge, y ahí no se borra.
    """
    usos = {}
    sin_leer = []
    for vmid, config in (configs or {}).items():
        if not isinstance(config, dict) or not config:
            sin_leer.append(str(vmid))
            continue
        nombre = config.get("name") or config.get("hostname") or str(vmid)
        for clave, valor in config.items():
            if not str(clave).startswith("net"):
                continue
            bridge, _ = _red_de_net0(valor)
            if bridge:
                usos.setdefault(bridge, []).append((str(vmid), str(nombre)))
    return usos, sorted(sin_leer)


def estado_bridges_candidatos(declaracion, estado):
    """Los bridges que este lab declara, existen en el nodo y llevan SU marca.

    Son los únicos que `destroy` puede plantearse borrar. Se separa del borrado
    final para no gastar ni una llamada leyendo la red de los invitados ajenos
    cuando no hay nada marcado que borrar.
    """
    lab = declaracion["lab"]
    en_nodo = set(estado.get("bridges_nodo") or [])
    comentarios = estado.get("bridges_comentarios") or {}
    return sorted(
        bridge["nombre"]
        for bridge in declaracion["bridges"]
        if bridge["nombre"] in en_nodo
        and modulo_identidad.lab_de_comentario(comentarios.get(bridge["nombre"])) == lab
    )


def estado_bridges_a_borrar(declaracion, estado, configs_fuera):
    """Qué bridges borra `destroy` y por qué conserva los demás.

    `configs_fuera` son las configs de los invitados que NO son de este lab (las de
    los propios se van con el lab, así que no cuentan como uso). Devuelve
    `{"borrar": [...], "conservar": [{"nombre", "motivo"}, ...]}`.
    """
    lab = declaracion["lab"]
    comentarios = estado.get("bridges_comentarios") or {}
    candidatos = estado_bridges_candidatos(declaracion, estado)
    usos, sin_leer = _usos_de_bridges(configs_fuera)

    conservar = []
    borrar = []
    # La duda va siempre al lado de conservar: si no se pudo leer la red de algún
    # invitado ajeno, no se puede descartar que use el bridge.
    if candidatos and sin_leer:
        for nombre in candidatos:
            conservar.append(
                {
                    "nombre": nombre,
                    "motivo": f"no se pudo leer la red de {len(sin_leer)} invitado(s) ajenos "
                    f"({', '.join(sin_leer)}): no se borra sin poder descartar que lo usen",
                }
            )
    else:
        for nombre in candidatos:
            if usos.get(nombre):
                quien = ", ".join(f"vmid={v} ({n})" for v, n in sorted(usos[nombre]))
                conservar.append(
                    {"nombre": nombre, "motivo": f"lo usa un invitado que no es de este lab: {quien}"}
                )
                continue
            borrar.append(nombre)

    # Y lo que este lab declara pero NO se puede borrar, con el motivo dicho.
    en_nodo = set(estado.get("bridges_nodo") or [])
    for bridge in declaracion["bridges"]:
        nombre = bridge["nombre"]
        if nombre not in en_nodo or nombre in borrar or any(c["nombre"] == nombre for c in conservar):
            continue
        dueno = modulo_identidad.lab_de_comentario(comentarios.get(nombre))
        if dueno:
            motivo = f"su comentario dice que es del lab '{dueno}', no de '{lab}': no se toca"
        else:
            motivo = (
                "no lleva la marca del motor en su comentario: no consta que lo creara este lab "
                "(pudo estar en el nodo antes de que el lab llegara)"
            )
        conservar.append({"nombre": nombre, "motivo": motivo})

    return {"borrar": sorted(borrar), "conservar": conservar}


def estado_bridges_texto(decision):
    """El informe de bridges de un `destroy`, en texto: primero lo que se borra."""
    lineas = []
    borrar = decision.get("borrar") or []
    conservar = decision.get("conservar") or []
    if borrar:
        lineas.append(f"bridges que se borran ({len(borrar)}): lo creó este lab y no los usa nadie")
        for nombre in borrar:
            lineas.append(f"  - {nombre}")
    if conservar:
        lineas.append(f"bridges que se conservan ({len(conservar)}): son del nodo, no del lab")
        for item in conservar:
            lineas.append(f"  - {item['nombre']}: {item['motivo']}")
    if not borrar and not conservar:
        lineas.append("bridges: este lab no declara ninguno que exista en el nodo")
    return "\n".join(lineas)


def _invitado_normalizado(recurso):
    """Un invitado del clúster, con los nombres que usa el motor.

    La API habla en inglés (`node`, `type`, `name`) y el dominio del motor en
    castellano (`nodo`, `tipo`, `rol_o_nombre`). Esta es la única traducción, y por
    eso la usan los tres filtros que recorren `GET /cluster/resources`.
    """
    return {
        "vmid": int(recurso["vmid"]),
        "tipo": "lxc" if recurso.get("type") == "lxc" else "qemu",
        "nodo": recurso.get("node"),
        "rol_o_nombre": recurso.get("name") or str(recurso.get("vmid")),
    }


def pve_contenedores_cluster(cluster_recursos):
    """TODOS los contenedores del clúster, de este lab o de cualquier otro.

    Hace falta para una sola pregunta, y es la del camino (§5): ¿qué direcciones está
    usando ya alguien en la red del nodo, para poder elegir una LIBRE para la pata de
    gestión del puesto de control? No se filtra por pool a propósito: un contenedor
    ajeno con dirección en el mismo bridge ocupa igual. Un contenedor declara sus
    interfaces a la API, así que se leen sin más. Las VMs QEMU NO salen de aquí: van por
    `pve_vms_cluster`, y sus direcciones se leen por el agente de invitado (ADR 0011),
    que es una lectura más pobre --depende de que la VM naciera con él y de que el token
    tenga `VM.GuestAgent.Audit`-- y por eso se pide aparte, tolerando el fallo.
    """
    return sorted(
        (_invitado_normalizado(r) for r in (cluster_recursos or [])
         if r.get("type") == "lxc" and r.get("vmid") is not None),
        key=lambda i: i["vmid"],
    )


def pve_vms_cluster(cluster_recursos):
    """TODAS las VMs QEMU del clúster, de este lab o de cualquier otro.

    La misma pregunta que `pve_contenedores_cluster`, para las máquinas virtuales: su
    config NO lleva `ip=` --la dirección la configura el invitado por dentro-- y no hay
    endpoint de interfaces para VMs, así que la única forma de saber qué dirección usa
    una VM es preguntársela a ella por el AGENTE DE INVITADO (ADR 0011). Una VM nacida
    antes de que el motor encendiera el agente no contesta y no se ve: se tolera y se
    dice, nunca se finge.
    """
    return sorted(
        (_invitado_normalizado(r) for r in (cluster_recursos or [])
         if r.get("type") == "qemu" and r.get("vmid") is not None),
        key=lambda i: i["vmid"],
    )


def pve_invitados_del_pool(cluster_recursos, lab):
    """Los invitados que la API dice que están en el pool del lab.

    Es lo que se usa para pedir la configuración de cada uno (descripción, recursos,
    red). Sólo mira el pool: la frontera de propiedad, no un rango de vmids.
    """
    salida = []
    for recurso in cluster_recursos or []:
        if recurso.get("pool") != lab:
            continue
        if recurso.get("vmid") is None:
            continue
        salida.append(_invitado_normalizado(recurso))
    return sorted(salida, key=lambda i: i["vmid"])


def pve_invitados_fuera_del_pool(cluster_recursos, lab):
    """Los invitados que NO son de este lab: de otro pool, o de nadie.

    `destroy` los necesita para una sola cosa: saber si alguno usa un bridge del lab
    antes de borrarlo. Los invitados sin pool cuentan igual que los de otro lab: si
    uno está colgado de un bridge del lab, ese bridge NO se borra.
    """
    salida = []
    for recurso in cluster_recursos or []:
        if recurso.get("pool") == lab or recurso.get("vmid") is None:
            continue
        salida.append(_invitado_normalizado(recurso))
    return sorted(salida, key=lambda i: i["vmid"])


def estado_plan(declaracion, estado, identidad, parametros):
    """El plan ordenado. Delegado al módulo puro para que no haya dos decisiones."""
    return modulo_plan.construir_plan(declaracion, estado, identidad, parametros)


def estado_plan_texto(plan, declaracion, estado, identidad):
    """El plan, en texto, listo para imprimir."""
    return modulo_plan.formatear_plan(plan, declaracion, estado, identidad)


def estado_verificar(declaracion, estado, identidad):
    """Compara lo declarado con lo que hay, EN LOS DOS SENTIDOS.

    Devuelve un informe estructurado. `ok` es False si falta algo, sobra algo, un
    invitado está parado o un campo declarado no coincide.
    """
    lab = declaracion["lab"]
    invitados_pool = estado.get("invitados") or {}
    otros = estado.get("invitados_otros") or {}

    faltan = []
    sobran = []
    drift = []
    parados = []
    otros_lab = []
    conformes = []
    no_verificable = [
        "la dirección IP declarada de cada rol no es verificable por API: vive dentro "
        "del invitado y la config del hipervisor no la guarda",
    ]

    roles_declarados = set()

    # --- Lado esperado: lo DERIVA la declaración (entrada), no el resultado -----
    for esperado in identidad["invitados"]:
        rol = esperado["rol"]
        roles_declarados.add(rol)
        actual = invitados_pool.get(str(esperado["vmid"]))

        if actual is None:
            # ¿Existe un invitado con el mismo nombre canónico pero en otro pool?
            # Entonces no falta: está, pero no es nuestro. Decirlo así es lo honesto.
            gemelo = otros.get(esperado["nombre"])
            if gemelo is not None:
                otros_lab.append(
                    {
                        "rol": rol,
                        "nombre": esperado["nombre"],
                        "vmid": gemelo["vmid"],
                        "pool": gemelo["pool"],
                        "nota": f"existe con el nombre canónico del rol, pero su pool es "
                        f"'{gemelo['pool']}', no '{lab}'",
                    }
                )
            else:
                faltan.append({"rol": rol, "vmid": esperado["vmid"], "nombre": esperado["nombre"]})
            continue

        diferencias = modulo_plan.campos_que_difieren(esperado, actual)
        if diferencias:
            for campo, valores in sorted(diferencias.items()):
                drift.append(
                    {"rol": rol, "vmid": esperado["vmid"], "campo": campo,
                     "esperado": valores["esperado"], "encontrado": valores["encontrado"]}
                )
        if not actual.get("arrancado"):
            parados.append({"rol": rol, "vmid": esperado["vmid"]})
        if not diferencias and actual.get("arrancado"):
            conformes.append({"rol": rol, "vmid": esperado["vmid"]})

    # --- Lado real: lo que SOBRA en el pool del lab ----------------------------
    # Un invitado en el pool que ya no está declarado delata una copia a mano o un
    # borrado en la declaración que se quedó atrás. Es un fallo, no un aviso.
    for vmid, actual in sorted(invitados_pool.items(), key=lambda par: int(par[0])):
        rol = modulo_identidad.rol_de_descripcion(actual.get("descripcion"))
        if rol not in roles_declarados:
            sobran.append(
                {
                    "vmid": actual.get("vmid", vmid),
                    "nombre": actual.get("nombre"),
                    "rol": rol or "(sin descripción del motor)",
                    "nota": "está en el pool del lab pero no lo declara ningún rol"
                    if rol
                    else "está en el pool del lab sin descripción del motor: no lo puso este motor",
                }
            )

    # El límite que el motor se impone por tener `VM.Console`: ningún invitado del
    # lab puede estar privilegiado, porque root dentro de un contenedor privilegiado
    # es root fuera. Se comprueba LEYENDO la config, no prometiéndolo.
    privilegiados = estado_invitados_privilegiados(estado)

    ok = not (faltan or sobran or drift or parados or otros_lab or privilegiados)

    return {
        "lab": lab,
        "nodo": estado.get("nodo") or "",
        "ok": ok,
        "esperados": len(identidad["invitados"]),
        "encontrados_en_pool": len(invitados_pool),
        "conformes": conformes,
        "faltan": faltan,
        "sobran": sobran,
        "drift": drift,
        "parados": parados,
        "otros_lab": otros_lab,
        "privilegiados": privilegiados,
        "no_verificable": no_verificable,
    }


def _texto_operacion(operacion):
    """Una operación del interior, en texto. Las operaciones son dicts `{area, op}`
    (`interior_operaciones`) que Ansible entrega como dicts perezosos: se materializan
    aquí para poder unirlos en una línea, sin depender de su tipo exacto."""
    try:
        operacion = dict(operacion)
    except (TypeError, ValueError):
        return str(operacion)
    return f"[{operacion.get('area')}] {operacion.get('op')}"


def estado_informe_texto(informe):
    """El informe de verificación en texto, con la conclusión la primera."""
    lineas = []
    estado_txt = "CORRECTO" if informe["ok"] else "CON DRIFT"
    lineas.append("=" * 60)
    lineas.append(f"VERIFICACIÓN del lab '{informe['lab']}' — {estado_txt}")
    lineas.append("=" * 60)
    lineas.append(
        f"esperados={informe['esperados']}  encontrados_en_el_pool={informe['encontrados_en_pool']}"
    )
    lineas.append("")

    if informe["faltan"]:
        lineas.append(f"FALTAN ({len(informe['faltan'])}): lo declarado y no desplegado")
        for item in informe["faltan"]:
            lineas.append(f"  - rol={item['rol']} (le correspondería el vmid {item['vmid']}, {item['nombre']})")
        lineas.append("")

    if informe["sobran"]:
        lineas.append(f"SOBRAN ({len(informe['sobran'])}): en el pool del lab y no declarados")
        for item in informe["sobran"]:
            lineas.append(f"  - vmid={item['vmid']} nombre={item['nombre']} rol={item['rol']}: {item['nota']}")
        lineas.append("")

    if informe["drift"]:
        lineas.append(f"DRIFT ({len(informe['drift'])}): existe pero no coincide")
        for item in informe["drift"]:
            lineas.append(
                f"  - rol={item['rol']} vmid={item['vmid']} campo={item['campo']}: "
                f"declarado={item['esperado']} encontrado={item['encontrado']}"
            )
        lineas.append("")

    if informe["parados"]:
        lineas.append(f"PARADOS ({len(informe['parados'])}): existen pero no están arrancados")
        for item in informe["parados"]:
            lineas.append(f"  - rol={item['rol']} vmid={item['vmid']}")
        lineas.append("")

    if informe["otros_lab"]:
        lineas.append(f"DE OTRO LAB ({len(informe['otros_lab'])}): existen, pero no son de este lab")
        for item in informe["otros_lab"]:
            lineas.append(f"  - rol={item['rol']}: {item['nota']}")
        lineas.append("")

    if informe.get("privilegiados"):
        lineas.append(
            f"PRIVILEGIADOS ({len(informe['privilegiados'])}): contenedores del lab SIN "
            "`unprivileged`, y el motor entra por consola en los invitados"
        )
        for item in informe["privilegiados"]:
            lineas.append(
                f"  - vmid={item['vmid']} nombre={item['nombre']}: root dentro de un "
                "contenedor privilegiado es root fuera del contenedor"
            )
        lineas.append("")

    if informe.get("interior"):
        # El INTERIOR: `verify` también ha mirado DENTRO de los invitados (y sin tocar
        # nada). Se cuenta aparte del mundo de la API porque son dos cosas distintas:
        # un invitado puede existir y coincidir por fuera y estar mal por dentro.
        interior = informe["interior"]
        malos = {rol: e for rol, e in interior.items()
                 if not e.get("alcanzable") or e.get("pendiente")}
        lineas.append(
            f"EL INTERIOR ({len(interior) - len(malos)}/{len(interior)} invitado(s) "
            "leído(s) por dentro y coincidente(s) con lo declarado)"
        )
        for rol, entrada in sorted(malos.items()):
            if not entrada.get("alcanzable"):
                lineas.append(f"  - rol={rol}: NO se pudo leer ({entrada.get('motivo')})")
            else:
                lineas.append(
                    f"  - rol={rol}: le quedan {len(entrada['pendiente'])} operación(es): "
                    f"{', '.join(_texto_operacion(o) for o in entrada['pendiente'])}"
                )
        lineas.append("")

    if informe["conformes"]:
        lineas.append(f"CONFORMES ({len(informe['conformes'])}): existen, coinciden y están arrancados")
        for item in informe["conformes"]:
            lineas.append(f"  - rol={item['rol']} vmid={item['vmid']}")
        lineas.append("")

    if informe["no_verificable"]:
        lineas.append("LÍMITES de esta verificación (dicho, no maquillado):")
        for linea in informe["no_verificable"]:
            lineas.append(f"  - {linea}")
        lineas.append("")

    return "\n".join(lineas)


def estado_privilegios(concedidos, exigidos, vedados):
    """Compara los privilegios CONCEDIDOS al token con los que el motor EXIGE y los
    que VEDA.

    `concedidos` sale de la API (GET /access/roles/<rol> devuelve `privs` como una
    cadena separada por comas); las otras dos listas son del motor (vars/engine.yml)
    y son una afirmación sobre lo que el motor necesita y lo que no debe poder
    hacer jamás. Este filtro sólo compara: no decide qué privilegios hacen falta.

    Es la mitad LÓGICA de la guarda de mínimos privilegios; la otra mitad es la
    operación nula que `preflight` hace contra la API y que debe responder 403
    (ver tasks/guardia_privilegios): sin ella, esto sería una intención.

    Devuelve {ok, faltan, sobran, concedidos, texto}.
    """
    def _lista(valor):
        if valor is None:
            return []
        if isinstance(valor, str):
            return [p.strip() for p in valor.split(",") if p.strip()]
        # `GET /access/roles/<rol>` devuelve un MAPA privilegio -> 1, no una lista:
        # las claves SON los privilegios concedidos. `GET /access/roles` (la lista)
        # los da como cadena en `privs`. Se aceptan las dos formas.
        if isinstance(valor, dict):
            return sorted(str(p).strip() for p in valor if str(p).strip())
        return [str(p).strip() for p in valor if str(p).strip()]

    concedidos = _lista(concedidos)
    exigidos = _lista(exigidos)
    vedados = _lista(vedados)

    conjunto = set(concedidos)
    faltan = sorted(set(exigidos) - conjunto)
    sobran = sorted(set(vedados) & conjunto)

    lineas = [
        f"El rol del token tiene {len(concedidos)} privilegio(s) concedido(s).",
        f"  Exigidos por el motor: {len(exigidos)}",
        f"  Vedados  por el motor: {len(vedados)}",
    ]
    if faltan:
        lineas.append("  FALTAN (el motor los necesita y no los tiene):")
        lineas += [f"    - {p}" for p in faltan]
    if sobran:
        lineas.append("  SOBRAN (el motor los veda y los tiene):")
        lineas += [f"    - {p}" for p in sobran]
    if not faltan and not sobran:
        lineas.append("  Ni falta ninguno de los exigidos ni está ninguno de los vedados.")

    return {
        "ok": not faltan and not sobran,
        "faltan": faltan,
        "sobran": sobran,
        "concedidos": sorted(conjunto),
        "texto": "\n".join(lineas),
    }


def estado_invitados_privilegiados(estado):
    """Los invitados del lab que NO nacieron sin privilegios, según lo que dice la API.

    Es la comprobación del límite que el motor se impone a sí mismo al aceptar
    `VM.Console` (docs/decisiones/0004): la consola de un invitado es root DENTRO de
    ese invitado, y con el contenedor sin privilegios root dentro no es root fuera.

    Se LEE, no se promete: en la config de un contenedor Proxmox omite
    `unprivileged` cuando el contenedor es privilegiado, así que la ausencia es el
    aviso. Una VM no entra aquí: la distinción privilegiado/no privilegiado es de
    los contenedores.

    Devuelve una lista de {vmid, nombre} (vacía si todo está bien).
    """
    privilegiados = []
    for vmid, invitado in sorted((estado.get("invitados") or {}).items(),
                                 key=lambda par: int(par[0])):
        if invitado.get("privilegiado"):
            privilegiados.append({
                "vmid": invitado.get("vmid", vmid),
                "nombre": invitado.get("nombre"),
            })
    return privilegiados


def estado_privilegios_roles(roles_leidos, por_rol, vedados):
    """Compara los roles del nodo con lo que el motor exige, **rol a rol**.

    `roles_leidos` es lo que devuelve `GET /access/roles`: una lista de
    `{roleid, privs}` (la `privs` viene como cadena separada por comas). `por_rol`
    es el mapa del motor (vars/engine.yml: un rol por RUTA, con los privilegios de
    esa ruta) y `vedados` es lo que el motor no puede tener en ninguna.

    Se compara por rol y no contra la unión de todo: un solo rol concedido en cinco
    rutas da la UNIÓN en todas partes, y eso es lo que hay que cazar -- «lo tiene,
    pero donde no debe» es tan grave como «no lo tiene».

    Devuelve `{ok, faltan, sobran, ausentes, texto}`. `ausentes` son los roles que el
    motor espera y el nodo no tiene: eso también es un fallo, y con nombre.
    """
    def _lista(valor):
        if valor is None:
            return []
        if isinstance(valor, str):
            return sorted(p.strip() for p in valor.split(",") if p.strip())
        if isinstance(valor, dict):
            return sorted(str(p).strip() for p in valor if str(p).strip())
        return sorted(str(p).strip() for p in valor if str(p).strip())

    esperados = {str(rol): _lista(privs) for rol, privs in (por_rol or {}).items()}
    no_permitidos = set(_lista(vedados))

    en_el_nodo = {}
    for rol in roles_leidos or []:
        if isinstance(rol, dict):
            en_el_nodo[str(rol.get("roleid"))] = _lista(rol.get("privs"))

    faltan, sobran, ausentes = {}, {}, []
    for rol, exigidos in esperados.items():
        if rol not in en_el_nodo:
            ausentes.append(rol)
            continue
        concedidos = set(en_el_nodo[rol])
        if set(exigidos) - concedidos:
            faltan[rol] = sorted(set(exigidos) - concedidos)
        # Sobran DOS cosas: lo vedado y lo que es de otra ruta. Lo segundo se ve
        # porque el rol de una ruta no debe tener privilegios que sólo otra ruta
        # declara (p. ej. `Sys.Modify` en el rol de `/vms`).
        de_otras_rutas = set().union(*[set(v) for k, v in esperados.items() if k != rol]) \
            if len(esperados) > 1 else set()
        de_mas = (concedidos & no_permitidos) | (concedidos - set(exigidos) - de_otras_rutas)
        if de_mas:
            sobran[rol] = sorted(de_mas)
        # Y `de_otras_rutas` en el rol equivocado también sobra: en su ruta propia
        # falta y aquí está de más.
        mal_colocados = sorted((concedidos & de_otras_rutas) - set(exigidos))
        if mal_colocados:
            sobran[rol] = sorted(set(sobran.get(rol, [])) | set(mal_colocados))

    lineas = [
        f"El motor exige {len(esperados)} rol(es), uno por ruta: {', '.join(sorted(esperados))}.",
    ]
    for rol in sorted(ausentes):
        lineas.append(f"  FALTA EL ROL «{rol}»: el nodo no lo tiene (esperado: {len(esperados[rol])} privilegio(s)).")
    for rol in sorted(faltan):
        lineas.append(f"  A «{rol}» le FALTAN: {', '.join(faltan[rol])}")
    for rol in sorted(sobran):
        lineas.append(f"  A «{rol}» le SOBRAN: {', '.join(sobran[rol])}")

    ok = not ausentes and not faltan and not sobran
    if ok:
        lineas.append("  Cada rol tiene lo suyo y nada de lo vedado, ni lo de otra ruta.")

    return {
        "ok": ok,
        "faltan": faltan,
        "sobran": sobran,
        "ausentes": ausentes,
        "texto": "\n".join(lineas),
    }


class FilterModule:
    """Filtros que Ansible ve como `| estado_desde_api`, `| estado_verificar`…"""
    def filters(self):
        return {
            "estado_vacio": estado_vacio,
            "estado_normalizar": estado_normalizar,
            "estado_desde_api": estado_desde_api,
            "estado_privilegios_roles": estado_privilegios_roles,
            "estado_con_direcciones": estado_con_direcciones,
            "pve_contenedores_cluster": pve_contenedores_cluster,
            "pve_vms_cluster": pve_vms_cluster,
            "estado_resumen": estado_resumen,
            "estado_bridges_candidatos": estado_bridges_candidatos,
            "estado_bridges_a_borrar": estado_bridges_a_borrar,
            "estado_bridges_texto": estado_bridges_texto,
            "pve_invitados_del_pool": pve_invitados_del_pool,
            "pve_invitados_fuera_del_pool": pve_invitados_fuera_del_pool,
            "estado_plan": estado_plan,
            "estado_plan_texto": estado_plan_texto,
            "estado_verificar": estado_verificar,
            "estado_informe_texto": estado_informe_texto,
            "estado_privilegios": estado_privilegios,
            "estado_invitados_privilegiados": estado_invitados_privilegiados,
        }
