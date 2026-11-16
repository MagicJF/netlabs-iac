# PROPÓSITO:   el asignador de identidad. Recibe (estado del mundo, declaración
#              del lab) y devuelve el mapa rol->identity: vmid, nombre canónico,
#              MAC y descripción. Es el corazón del encargo (regla §5).
# INVARIANTES: es una FUNCIÓN PURA: no lee ficheros, no habla con la API y no
#              guarda nada. Dadas las mismas dos entradas, da la misma salida.
#              Ningún valor derivado se escribe en el repo (regla 11).
#              Un vmid ya usado en CUALQUIER punto del clúster jamás se reutiliza.
#              Un rol que ya existe en el pool del lab CONSERVA su vmid (si no,
#              `apply` no sería idempotente).
# LÍMITES:     no puede saber si un vmid está "de verdad" libre: se lo dice el
#              estado del mundo, que viene de la API (o de un fixture, en tests).
#              Si el clúster está lleno, FALLA con un mensaje claro; nunca reasigna
#              en silencio.
# VER:         README.md §Identidad; AGENTS.md §Identidad; test/test_identidad.py

import copy
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


# Cuánto se separa una interfaz de la siguiente en el espacio de vmids: 2**20. Un vmid de
# Proxmox no pasa de 999.999 (menos de 2**20), así que la interfaz `n` de un invitado nunca
# puede chocar con la interfaz 0 de otro. Ver `identidad_mac_de_interface`.
ESPACIO_DE_INTERFACES = 1 << 20


def identidad_mac_de_interface(vmid, indice, prefijo_mac):
    """La MAC de la interfaz `indice` de un invitado con varias interfaces.

    La interfaz 0 es **exactamente** la de siempre (`identidad_mac`), así que los labs de la
    fase 1 y los invitados de una sola interfaz no cambian ni un bit. Las demás se
    derivan del mismo sitio: `f(vmid + índice * 2**20)`.

    Por qué se derivan en vez de dejárselas a Proxmox: una MAC que inventa otro es estado
    que el motor no controla, y el plan la vería distinta en cada pasada (la segunda
    ejecución escribiría y la idempotencia se caería). Aquí no se guarda nada: se vuelve
    a derivar, igual que la de la interfaz 0.
    """
    if int(indice) < 0:
        raise ErrorMotor(f"no hay interfaz negativa: {indice!r}")
    return identidad_mac(int(vmid) + int(indice) * ESPACIO_DE_INTERFACES, prefijo_mac)


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


# ---------------------------------------------------------------------------
# El nombre del POOL de un lab. El prefijo no es decorativo: Proxmox exige que un
# poolid EMPIECE POR LETRA, y la carpeta de un lab empieza por su número de antigüedad
# (ADR 0016). Es forma, no identity: el pool sigue siendo del lab y de nadie más. Vive
# aquí, que es el módulo de la identidad, y `plan`/`estado`/`destroy` la usan desde ahí
# -- una sola regla, no tres copias del prefijo.
# ---------------------------------------------------------------------------
PREFIJO_POOL = "lab_"


def identidad_pool(lab, prefijo=None):
    """El nombre del pool de un lab: el prefijo del motor + el nombre de su carpeta."""
    return f"{PREFIJO_POOL if prefijo is None else prefijo}{lab}"


def identidad_plantilla(plantilla, lab, rol, vmid=None, equipo=None, alias=None):
    """Rellena una plantilla del motor (`{equipo}`, `{alias}`, `{lab}`, `{rol}`, `{vmid}`).

    `{equipo}` y `{alias}` son del NOMBRE (qué es el invitado); `{lab}` y `{rol}` son de la
    PROPIEDAD (de quién es), y `{rol}` sale también en el nombre cuando el lab no declara un
    `nombre:` corto.
    """
    return (
        str(plantilla)
        .replace("{equipo}", "" if equipo is None else str(equipo))
        .replace("{alias}", "" if alias is None else str(alias))
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
    poolid = identidad_pool(lab)
    for guest in (estado.get("guests") or {}).values():
        # El pool se compara con su nombre DE VERDAD (`lab_<lab>`, `identidad_pool`), no
        # con el de la carpeta: compararlo con la carpeta hacía que ningún invitado propio
        # se reconociera -- se creaba la topología entera otra vez en cada pasada, con
        # vmids nuevos, y la idempotencia se caía.
        if guest.get("pool") != poolid:
            continue
        rol = rol_de_descripcion(guest.get("descripcion"))
        if rol:
            existentes_por_rol.setdefault(rol, guest)

    asignados = set()
    salida = []

    for guest in declaracion["guests"]:
        rol = guest["rol"]

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
                **guest,
                "vmid": vmid,
                # El nombre dice QUÉ ES (`rt-borde`, `srv-1`), no de qué lab es (ADR 0015):
                # el equipo lo declara el lab con `tipo:` y el alias es su `nombre:` corto,
                # o su rol si no lo declara. Repetir nombre entre labs es legítimo: la
                # propiedad va en el pool y en la descripción, que sí llevan el lab.
                "nombre": identidad_plantilla(
                    plantilla_nombre,
                    lab,
                    rol,
                    vmid,
                    equipo=guest.get("equipo"),
                    alias=guest.get("alias") or rol,
                ),
                "mac": identidad_mac(vmid, prefijo_mac),
                "descripcion": identidad_plantilla(plantilla_descripcion, lab, rol, vmid),
                "origen": origen,
            }
        )

    return {
        "guests": salida,
        "mapa_rol_vmid": {i["rol"]: i["vmid"] for i in salida},
        "errores": errores,
    }


def identidad_guest_por_rol(identidad, rol):
    """El invitado asignado a un rol, o None. Para no repetir búsquedas en Jinja."""
    for guest in identidad.get("guests", []) or []:
        if guest["rol"] == rol:
            return guest
    return None


def identidad_por_stage(identidad):
    """Agrupa los invitados ya asignados por etapa de arranque.

    Devuelve `{stage: [invitado, ...]}` con las claves ordenadas. Arrancar por
    etapas es parte de la topología: el plan y `apply` leen esto, no una lista
    propia.
    """
    agrupado = {}
    for guest in identidad.get("guests", []) or []:
        agrupado.setdefault(guest["stage"], []).append(guest)
    return {stage: agrupado[stage] for stage in sorted(agrupado)}


# ---------------------------------------------------------------------------
# 6.1 · El asignador de DIRECCIONES (IPAM). Ver docs/decisiones/0020.
#
# La misma idea que `static_leases: derived`, extendida a todo lo que el lab
# puede dejar en `derived`: la dirección de un bridge, la de un invitado, las
# LANs que un RouterOS sirve y los rangos y redes de sus servidores DHCP.
#
# Lo que NO hace, y es la mitad del diseño: un valor EXPLÍCITO siempre GANA. El
# IPAM sólo rellena lo que el lab dejó sin escribir, así que un lab puede derivar
# todo (y no repetir números) o escribir cada dirección a mano (y no depender de
# ninguna convención), y las dos formas conviven en el mismo fichero.
# ---------------------------------------------------------------------------

DERIVADO = "derived"

# La máscara de una subred derivada. El espacio de direcciones de un lab es un
# /16 y sus bridges son /24: el IPAM trabaja en bloques de /24, que es lo que el
# repo usa hoy. Con un espacio más estrecho que /24 se dice y no se deriva (ver
# `direcciones_resolver`): un cálculo fino aquí sería otra cosa que puede estar
# mal sin que nadie lo note.
PREFIJO_DERIVADO = 24
# El primer y el último huésped que se reparten en una subred derivada. El 1 es
# la propia subred (la puerta del bridge), y el 100..200 está reservado para el
# DHCP: por eso los huéspedes fijos se reparten desde el 10 hacia arriba.
PRIMER_HUESPED = 10
PRIMER_DHCP = 100
ULTIMO_DHCP = 200


def _es_derivado(valor):
    """¿El lab pidió que esto lo derive el motor?"""
    return isinstance(valor, str) and valor.strip() == DERIVADO


def _es_direccion(valor):
    """¿Esto es una dirección con máscara, y no una marca ni un `dhcp`?

    El IPAM no puede dar por hecho que lo que hay en un `address:` sea una dirección:
    puede ser `derived` (que él mismo acaba de dejar sin resolver, si no cabía en el
    espacio) o `dhcp`. Parsear eso como si fuera una IP revienta con un `ValueError`
    que no dice nada -- y pasó.
    """
    if not isinstance(valor, str) or "/" not in valor:
        return False
    try:
        return all(0 <= int(o) <= 255 for o in valor.split("/")[0].split(".")) and len(
            valor.split("/")[0].split(".")
        ) == 4
    except ValueError:
        return False


def _a_entero(direccion):
    """`192.0.2.11/24` o `192.0.2.11` -> un entero de 32 bits."""
    octetos = [int(o) for o in str(direccion).split("/")[0].split(".")]
    return (octetos[0] << 24) | (octetos[1] << 16) | (octetos[2] << 8) | octetos[3]


def _a_texto(entero):
    """Un entero de 32 bits -> `192.0.2.11`."""
    return ".".join(str((entero >> bits) & 0xFF) for bits in (24, 16, 8, 0))


def _subred(direccion):
    """La subred /24 que contiene a esa dirección, como entero."""
    return (_a_entero(direccion) >> (32 - PREFIJO_DERIVADO)) << (32 - PREFIJO_DERIVADO)


def _huesped(subred_entero, numero):
    """La dirección `numero` de esa subred /24, con su máscara: `10.42.1.11/24`."""
    return f"{_a_texto(subred_entero + numero)}/{PREFIJO_DERIVADO}"


def _patas_de(guest):
    """Las interfaces declaradas de un invitado, EN ORDEN. Las dos formas."""
    if guest.get("bridges"):
        return list(guest["bridges"])
    if guest.get("bridge"):
        return [guest["bridge"]]
    return []


def _numero_de_interfaz(interfaz):
    """`ether2` -> 2, `eth0` -> 0. Es el índice que da el ORDEN de `bridges:`."""
    digitos = re.sub(r"[^0-9]", "", str(interfaz))
    return int(digitos) if digitos else 0


def _primera_libre(subred_entero, ocupadas, desde=PRIMER_HUESPED):
    """El primer huésped de esa subred que no esté ocupado."""
    for numero in range(desde, PRIMER_DHCP):
        if subred_entero + numero not in ocupadas:
            return numero
    return None


def direcciones_resolver(declaracion):
    """Resuelve los `derived` de una declaración. PURA: (declaración) -> declaración.

    Devuelve una COPIA con cada `derived` convertido en una dirección de verdad.
    El reparto es estable (no depende de nada que no esté en la declaración), que
    es lo que exige la idempotencia: la segunda pasada deriva exactamente lo mismo.

    Lo que se deriva, y en este orden (el orden ES el reparto):
      1. `lab.bridges[].address` -> la subred /24 siguiente del `address_space`, y
         la dirección `.1` de esa subred (la puerta del bridge).
      2. `guest.address` -> el primer huésped libre de la subred de SU PRIMER bridge.
      3. `config.routeros.addresses[].address` -> el `.1` de la subred del bridge
         que le toca por el ORDEN de las interfaces (`etherN` -> la pata N-1).
      4. `config.routeros.dhcp_server[].pool.rango` -> `.100-.200` de su subred;
         y `network.address` / `network.gateway` / `network.dns` -> la subred, la
         puerta de esa subred y esa misma puerta como resolutor.
    """
    salida = copy.deepcopy(declaracion)
    lab = salida.get("lab") or {}
    # Una declaración NORMALIZADA no se toca: su `lab` es un NOMBRE, no un mapa, y no hay
    # nada que derivar en ella (lo derivado ya es dirección de verdad). Sin esto, pasarle
    # una normalizada revienta con un `AttributeError` en vez de no hacer nada.
    if not isinstance(lab, dict):
        return salida
    espacio = lab.get("address_space")
    puentes = lab.get("bridges") or []
    if puentes and not isinstance(puentes[0], dict):
        return salida
    invitados = (salida.get("vms") or []) + (salida.get("containers") or [])

    # 1. Los bridges, y con ellos las subredes del lab.
    subred_de_puente = {}
    puerta_de_subred = {}
    ocupadas = set()
    siguiente_subred = 0
    for puente in puentes:
        if _es_derivado(puente.get("address")):
            if espacio and int(str(espacio).split("/")[1]) <= PREFIJO_DERIVADO:
                base = _subred(espacio) + siguiente_subred * (1 << (32 - PREFIJO_DERIVADO))
                # El bloque tiene que CABER en el espacio: un /24 no da para dos /24, y
                # derivar una dirección fuera del espacio sería peor que no derivarla
                # -- el check lo cazaría, pero con un error que manda a mirar el sitio
                # equivocado. Si no cabe, se queda en `derived` y lo dice el validador.
                limite = _a_entero(espacio) + (1 << (32 - int(str(espacio).split("/")[1])))
                if base + (1 << (32 - PREFIJO_DERIVADO)) <= limite:
                    siguiente_subred += 1
                    puente["address"] = _huesped(base, 1)
        if _es_direccion(puente.get("address")):
            subred = _subred(puente["address"])
            subred_de_puente[puente["nombre"]] = subred
            puerta_de_subred[subred] = _a_entero(str(puente["address"]).split("/")[0])
            ocupadas.add(_a_entero(puente["address"]))

    for guest in invitados:
        patas = _patas_de(guest)

        # 2. La dirección del invitado, en su PRIMER bridge.
        if _es_derivado(guest.get("address")):
            subred = subred_de_puente.get(patas[0]) if patas else None
            if subred is not None:
                numero = _primera_libre(subred, ocupadas)
                if numero is not None:
                    guest["address"] = _huesped(subred, numero)
                    ocupadas.add(subred + numero)

        interior = ((guest.get("config") or {}).get("routeros") or {})

        # 3. Las LANs que el RouterOS sirve: la interfaz `etherN` es la pata N-1.
        for entrada in interior.get("addresses") or []:
            if not _es_derivado(entrada.get("address")):
                continue
            indice = _numero_de_interfaz(entrada.get("interface"))
            subred = subred_de_puente.get(patas[indice - 1]) if 0 < indice <= len(patas) else None
            if subred is None:
                continue
            entrada["address"] = _huesped(subred, 1)
            puerta_de_subred.setdefault(subred, _a_entero(entrada["address"]))
            ocupadas.add(_a_entero(entrada["address"]))

        # 4. El DHCP que sirve: su rango, su red y su puerta salen de la subred.
        for servidor in interior.get("dhcp_server") or []:
            indice = _numero_de_interfaz(servidor.get("interface"))
            subred = subred_de_puente.get(patas[indice - 1]) if 0 < indice <= len(patas) else None
            if subred is None:
                continue
            if _es_derivado((servidor.get("pool") or {}).get("rango")):
                servidor["pool"]["rango"] = (
                    f"{_a_texto(subred + PRIMER_DHCP)}-{_a_texto(subred + ULTIMO_DHCP)}"
                )
            red = servidor.get("network") or {}
            if _es_derivado(red.get("address")):
                red["address"] = f"{_a_texto(subred)}/{PREFIJO_DERIVADO}"
            puerta = puerta_de_subred.get(subred)
            if _es_derivado(red.get("gateway")) and puerta is not None:
                red["gateway"] = _a_texto(puerta)
            if _es_derivado(red.get("dns")) and puerta is not None:
                red["dns"] = [_a_texto(puerta)]

    return salida


class FilterModule:
    """Filtros que Ansible ve como `| identidad_asignar`."""

    def filters(self):
        return {
            "identidad_mac": identidad_mac,
            "identidad_pool": identidad_pool,
            "identidad_asignar": identidad_asignar,
            "identidad_guest_por_rol": identidad_guest_por_rol,
            "identidad_por_stage": identidad_por_stage,
        }
