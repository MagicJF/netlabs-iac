# PROPÓSITO:   el asignador de identidad. Recibe (estado del mundo, declaración
#              del lab) y devuelve el mapa rol->identidad: vmid, nombre canónico,
#              MAC y descripción. Es el corazón del encargo (regla §5).
# INVARIANTES: es una FUNCIÓN PURA: no lee ficheros, no habla con la API y no
#              guarda nada. Dadas las mismas dos entradas, da la misma salida.
#              Ningún valor derivado se escribe en el repo (regla 4.8).
#              Un vmid ya usado en CUALQUIER punto del clúster jamás se reutiliza.
#              Un rol que ya existe en el pool del lab CONSERVA su vmid (si no,
#              `apply` no sería idempotente).
# LÍMITES:     no puede saber si un vmid está "de verdad" libre: se lo dice el
#              estado del mundo, que viene de la API (o de un fixture, en tests).
#              Si el clúster está lleno, FALLA con un mensaje claro; nunca reasigna
#              en silencio.
# VER:         README.md §Identidad; AGENTS.md §Identidad; test/test_identidad.py

import re

try:
    from ansible.errors import AnsibleFilterError as ErrorMotor
except ImportError:  # pragma: no cover - sólo ocurre fuera de Ansible
    class ErrorMotor(Exception):
        """Error del motor, con el mismo nombre que el de Ansible."""


# La descripción que escribe el motor lleva el rol; es la mitad de la frontera de
# propiedad que permite reconstruir rol->vmid sin fichero de estado.
EXPRESION_ROL = re.compile(r"(?:^|\s)rol=([A-Za-z0-9][A-Za-z0-9_.-]*)")

# La MISMA marca, pero en el `comments` de un bridge (`lab=<lab> gestionado por
# netlabs_v4_b`). Un bridge no está en ningún pool: esta marca es la única prueba
# de que lo creó este lab, y por eso se lee con la misma expresión, no con una
# parecida que se desvíe con el tiempo.
EXPRESION_LAB = re.compile(r"(?:^|\s)lab=([A-Za-z0-9][A-Za-z0-9_.-]*)")


def identidad_mac(vmid, prefijo_mac):
    """La MAC es función pura del vmid: `BC:24:11:` + los 3 bytes bajos del vmid.

    Se escribe en orden alto->bajo (para el vmid 100: `BC:24:11:00:00:64`) y sin
    ceros a la izquierda recortados, para que el resultado sea estable y legible.
    """
    if not isinstance(vmid, int) or vmid < 0:
        raise ErrorMotor(f"no se puede derivar una MAC de un vmid inválido: {vmid!r}")
    return "{p}:{a:02X}:{b:02X}:{c:02X}".format(
        p=prefijo_mac,
        a=(vmid >> 16) & 0xFF,
        b=(vmid >> 8) & 0xFF,
        c=vmid & 0xFF,
    )


def rol_de_descripcion(descripcion):
    """Extrae `rol=<x>` de la descripción de un invitado. None si no está.

    Un invitado sin descripción del motor es un invitado que el motor no puso
    ahí: no se adopta, se reporta.
    """
    if not descripcion:
        return None
    coincidencia = EXPRESION_ROL.search(str(descripcion))
    return coincidencia.group(1) if coincidencia else None


def lab_de_comentario(comentario):
    """Extrae `lab=<x>` del comentario de una interfaz. None si no está.

    Es la prueba de propiedad de un BRIDGE, y la usa `destroy`: Proxmox no mete
    interfaces de red en pools, así que lo único que distingue "este bridge lo creó
    este lab" de "ya estaba ahí" es esta marca. Un comentario sin `lab=` (o escrito
    a mano) no la lleva: no se adopta, se conserva.
    """
    if not comentario:
        return None
    coincidencia = EXPRESION_LAB.search(str(comentario))
    return coincidencia.group(1) if coincidencia else None


def identidad_plantilla(plantilla, lab, rol, vmid=None):
    """Rellena una plantilla del motor (`{lab}`, `{rol}`, `{vmid}`)."""
    return (
        str(plantilla)
        .replace("{lab}", str(lab))
        .replace("{rol}", str(rol))
        .replace("{vmid}", "" if vmid is None else str(vmid))
    )


def identidad_asignar(
    declaracion,
    estado,
    plantilla_descripcion,
    plantilla_nombre,
    prefijo_mac,
    vmid_minimo,
    vmid_maximo,
):
    """(declaración normalizada, estado del mundo) -> mapa rol->identidad.

    Devuelve `{"invitados": [...], "mapa_rol_vmid": {...}, "errores": [...]}`.
    Si `errores` no está vacío, el llamante NO debe seguir: aplicar con una
    identidad a medias es peor que no aplicar.
    """
    errores = []
    lab = declaracion["lab"]

    usados = {int(v) for v in estado.get("vmids_usados", []) or []}

    # Invitados que YA son de este lab: los que el pool tiene y cuya descripción
    # lleva un rol. De ahí sale la identidad que se conserva.
    #
    # Se exige que el invitado esté en el pool DEL LAB, de forma ESTRICTA: sin
    # `pool` no se adopta. Es la última defensa contra adoptar el invitado de un
    # vecino, y el lado seguro del error: si un invitado propio llegara sin `pool`
    # en su estado (no ocurre: /cluster/resources lo da siempre), se crearía de
    # nuevo en vez de reutilizarlo -- y eso se ve en `verify` como "sobra", no se
    # queda callado.
    existentes_por_rol = {}
    for invitado in (estado.get("invitados") or {}).values():
        if invitado.get("pool") != lab:
            continue
        rol = rol_de_descripcion(invitado.get("descripcion"))
        if rol:
            existentes_por_rol.setdefault(rol, invitado)

    asignados = set()
    salida = []

    for invitado in declaracion["invitados"]:
        rol = invitado["rol"]

        if rol in existentes_por_rol:
            vmid = int(existentes_por_rol[rol]["vmid"])
            origen = "existente"
            if vmid in asignados:
                errores.append(
                    f"el vmid {vmid} aparece asignado a dos roles distintos: el pool del lab "
                    f"tiene dos invitados con `rol={rol}` en su descripción"
                )
                continue
        else:
            vmid = None
            for candidato in range(int(vmid_minimo), int(vmid_maximo) + 1):
                if candidato not in usados:
                    vmid = candidato
                    break
            if vmid is None:
                errores.append(
                    f"clúster lleno: no queda ningún vmid libre entre {vmid_minimo} y "
                    f"{vmid_maximo} para el rol '{rol}'. No se reasigna nada en silencio."
                )
                continue
            origen = "nuevo"

        asignados.add(vmid)
        usados.add(vmid)

        salida.append(
            {
                **invitado,
                "vmid": vmid,
                "nombre": identidad_plantilla(plantilla_nombre, lab, rol, vmid),
                "mac": identidad_mac(vmid, prefijo_mac),
                "descripcion": identidad_plantilla(plantilla_descripcion, lab, rol, vmid),
                "origen": origen,
            }
        )

    return {
        "invitados": salida,
        "mapa_rol_vmid": {i["rol"]: i["vmid"] for i in salida},
        "errores": errores,
    }


def identidad_invitado_por_rol(identidad, rol):
    """El invitado asignado a un rol, o None. Para no repetir búsquedas en Jinja."""
    for invitado in identidad.get("invitados", []) or []:
        if invitado["rol"] == rol:
            return invitado
    return None


def identidad_por_escalon(identidad):
    """Agrupa los invitados ya asignados por escalón de arranque.

    Devuelve `{escalon: [invitado, ...]}` con las claves ordenadas. Arrancar por
    escalones es parte de la topología: el plan y `apply` leen esto, no una lista
    propia.
    """
    agrupado = {}
    for invitado in identidad.get("invitados", []) or []:
        agrupado.setdefault(invitado["escalon"], []).append(invitado)
    return {escalon: agrupado[escalon] for escalon in sorted(agrupado)}


class FilterModule:
    """Filtros que Ansible ve como `| identidad_asignar`."""

    def filters(self):
        return {
            "identidad_mac": identidad_mac,
            "identidad_rol_de_descripcion": rol_de_descripcion,
            "identidad_lab_de_comentario": lab_de_comentario,
            "identidad_asignar": identidad_asignar,
            "identidad_invitado_por_rol": identidad_invitado_por_rol,
            "identidad_por_escalon": identidad_por_escalon,
        }
