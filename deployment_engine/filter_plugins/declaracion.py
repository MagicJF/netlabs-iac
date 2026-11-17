# PROPÓSITO:   normaliza y valida la declaración de un lab. Es lo que Ansible
#              calcula en Jinja para saber si el estado deseado es coherente
#              ANTES de tocar la API.
# INVARIANTES: el lab declara roles y topología; NUNCA declara vmid ni MAC
#              (regla 11) -- si aparecen en la declaración, esto es un error.
#              Toda referencia cruzada tiene que resolver: un bridge citado tiene
#              que existir en el lab, un rol no puede estar en dos listas, dos
#              roles no pueden compartir dirección. Y el NOMBRE de cada bridge
#              tiene que ser uno que Proxmox acepte (formato `pve-iface`): si no,
#              la API lo rechaza con un 400 al aplicar y mejor saberlo antes.
#              El VOCABULARIO DEL INTERIOR es cerrado (regla 15): una clave que no
#              esté en `filter_plugins/interior.py` es un error aquí, no un
#              silencio que se descubre al aplicar. Y una MAC o una contraseña en
#              el YAML es un bug: la MAC se deriva (regla 14) y las credenciales
#              viven en `secrets.yml`.
# LÍMITES:     no habla con Proxmox y no sabe nada del mundo real; sólo mira el
#              YAML. Que un bridge exista en el NODO no se comprueba aquí: eso es
#              `preflight`, que sí lee la API. Que el interior de un invitado se
#              pueda alcanzar tampoco: eso necesita el túnel en pie, y se dice al
#              aplicar.
#              Además de validar, ACONSEJA (`declaracion_consejos`): lo que es legal
#              pero casi siempre es un olvido (la etapa antes de quien da la
#              dirección, la dirección estática dentro del rango del DHCP, la
#              pasarela que no es nadie del lab...). Los consejos NO bloquean ni
#              cambian el plan: el criterio lo sigue teniendo quien declara.
# VER:         README.md §Verificación; AGENTS.md §Reglas duras;
#              docs/decisiones/0005-el-driver-del-interior.md; ./lab check declaracion

# Se importa el error de Ansible si estamos dentro de Ansible. Si no (tests con
# `python3` a secas), vale una excepción propia: el fichero tiene que poder
# importarse sin la dependencia de Ansible para poder probarlo aislado.
import os
import re
import sys

try:
    from ansible.errors import AnsibleFilterError as ErrorMotor
except ImportError:  # pragma: no cover - sólo ocurre fuera de Ansible
    class ErrorMotor(Exception):
        """Error del motor, con el mismo nombre que el de Ansible."""


# El vocabulario del interior (áreas, tipos, servicios y reservas derivadas) vive en
# su propio módulo, y se importa por RUTA como el resto del motor: así la validación
# y el driver no pueden discrepar sobre qué se puede declarar.
_DIRECTORIO_FILTROS = os.path.dirname(os.path.abspath(__file__))
if _DIRECTORIO_FILTROS not in sys.path:
    sys.path.insert(0, _DIRECTORIO_FILTROS)

import identidad as modulo_identidad  # noqa: E402  (la ruta se ajusta justo arriba)
import interior as modulo_interior  # noqa: E402  (la ruta se ajusta justo arriba)

# Los dos tipos de invitado que el motor sabe desplegar, tal como los nombra la
# API de Proxmox en sus rutas.
TIPOS = ("qemu", "lxc")

# 6.3 · Qué se admite en el `ready:` de un invitado (ADR 0021). Es un vocabulario
# CERRADO porque el motor sólo sabe preguntar de estas tres maneras: las dos primeras
# son sondas de PUERTO (la que el tipo del equipo ya insinuaba, ahora declarada) y la
# tercera es la forma de decir que ese invitado no lleva barrera -- que no es lo mismo
# que callarse, porque callarse significa «decide el motor por el tipo que soy».
READY_TIPOS = ("ssh", "routeros_rest", "ninguno")

# Claves que el motor DERIVA y por tanto están PROHIBIDAS en la declaración. Si
# aparecen, alguien ha intentado fijar a mano lo que es del motor, y eso es el
# origen de los conflictos entre labs.
# Lo que el motor DERIVA y el lab no declara nunca. `nombre` salió de esta lista con el ADR
# 0015: el lab SÍ puede declarar un `nombre:` corto (el ALIAS del invitado: `srv-1`), porque
# ya no es el nombre entero -- ése lo sigue derivando el motor, con el `tipo:` y ese alias.
CLAVES_DERIVADAS = ("vmid", "mac", "name", "pool")

# Campos obligatorios de cada invitado declarado, y su tipo esperado. `address`
# NO está aquí a propósito: desde la fase 2 admite tres formas (estática, `dhcp` y
# AUSENTE, para un equipo sin dirección como un conmutador puro), así que se valida
# aparte y con más cuidado.
CAMPOS_GUEST = {
    "rol": str,
    "stage": int,
    "cores": int,
    "memory": int,
    "disk": int,
    "bridge": str,
}

# Una MAC tiene esta forma y NO se declara nunca: se deriva del vmid (regla 14).
MAC_PATRON = re.compile(r"^([0-9a-fA-F]{2}[:-]){5}[0-9a-fA-F]{2}$")
MAC_EN_TEXTO = re.compile(r"([0-9a-fA-F]{2}[:-]){5}[0-9a-fA-F]{2}")

# Claves que huelen a credencial dentro de una declaración. Las credenciales viven
# en `secrets.yml`: un lab no lleva contraseñas dentro.
CLAVES_CREDENCIAL = ("contrasena", "contraseña", "password", "clave_secreta", "token")

# Una clave (o un certificado) reconocible por su FORMA, no por el nombre de la clave
# del YAML: así no se cuela una clave pegada dentro de un campo llamado de otra cosa.
# Las claves del motor son suyas y viven fuera del repo; el lab no declara ninguna.
CLAVE_EN_TEXTO = re.compile(
    r"-----BEGIN |BEGIN CERTIFICATE|PRIVATE KEY|^ssh-(rsa|ed25519|dss) |^ecdsa-sha2-"
)

# Una dirección IPv4 con máscara, y un rango `a-b` de un pool DHCP.
IP_PATRON = re.compile(r"^\d{1,3}(\.\d{1,3}){3}(/\d{1,2})?$")

# El área `tunnel` no declara credenciales ni direcciones de casa: eso es entorno
# (secrets.yml). Lo único que puede traer son los dos valores que un lab de verdad
# puede necesitar distintos: qué host y qué puerto, y son OPCIONALES.
CLAVES_TUNNEL = ("salida", "host", "puerto")

# Los tipos de equipo que un lab declara (`tipo:`) y de los que sale la primera mitad del
# nombre del invitado: `rt-borde`, `srv-1`, `ws-2`. Vocabulario CERRADO (regla 15): un
# equipo que no quepa en ninguno pide su tipo al motor, con su ADR -- no se inventa aquí.
TIPOS_DE_EQUIPO = {
    "rt": "router (un CHR: la vía de acceso de una red)",
    "fw": "cortafuegos (un CHR que sólo filtra: no traduce, no reparte direcciones y no es la vía de acceso de nadie)",
    "srv": "servidor (nace con su dirección fija y su pasarela)",
    "ws": "puesto de trabajo (pide su dirección por DHCP)",
    "sw": "conmutador (un equipo que conmuta, o uno sin dirección)",
    "ctl": "bastión (el bastión por el que se entra al lab)",
}

# El tipo de equipo MANDA sobre las áreas: un equipo hace UNA cosa. Es la regla que el
# encargo pidió desde el principio («1 equipo = 1 responsabilidad») y que hasta ahora sólo
# estaba escrita en la prosa de los labs -- y por eso un `rt` pudo declarar una tabla de
# filtrado sin que nada lo parara. Aquí se vuelve mecánica.
#
# Se declara en NEGATIVO (lo que un tipo NO puede pedir) y con el motivo: la lista de lo
# permitido ya está en `AREAS`, y una regla en positivo se queda corta el día que el motor
# gane un área -- con lo que este trinquete dejaría de morder en silencio.
#
# El criterio, palabra por palabra el de `TIPOS_DE_EQUIPO`:
#   * filtrar no es enrutar  -> `firewall` es de un `fw`, y de nadie más.
#   * salir no es filtrar    -> `uplink` (cliente DHCP + NAT + resolutor) es de un `rt`.
#   * repartir no es filtrar -> `dhcp_server` no vive en un `fw`.
#   * conmutar no es enrutar -> un `sw` no enruta, no filtra, no traduce y no reparte.
#   * y quien NO es de red (`srv`, `ws`, `ctl`) no tiene NINGUNA de las cuatro: filtrar,
#     enrutar, ser la vía de acceso y repartir son de quien sirve la red.
#
# TODOS los tipos del vocabulario tienen entrada, y eso es parte de la regla: un tipo que no
# está aquí no tiene ninguna restricción, así que dejar uno fuera es dejar la grieta abierta
# por la puerta de al lado (bastaba con declarar la misma tabla en un `srv`).
#
# Lo que NO puede declarar un equipo que no es de red: las cuatro funciones que dan a un
# equipo su papel en la red -- filtrar, enrutar, ser la vía de acceso (traducir y salir) y
# repartir direcciones. Se escribe UNA vez y se reusa: `srv`, `ws` y `ctl` (con el vocabulario
# de un equipo de red) no son de red, y no hay tres listas distintas que mantener en sincronía.
_NO_ES_DE_RED = {
    "firewall": "filtrar es la responsabilidad de un equipo `fw` (ADR 0026)",
    "routes": "enrutar es la responsabilidad de un equipo `rt` (ADR 0026)",
    "uplink": "ser la vía de acceso (traducir y salir) es la de un `rt` (ADR 0012 y ADR 0026)",
    "dhcp_server": "repartir direcciones es la responsabilidad de quien sirve la red (ADR 0026)",
}

AREAS_QUE_NO_LE_TOCAN = {
    "rt": {"*": {
        "firewall": "filtrar es la responsabilidad de un equipo `fw` (ADR 0019 y ADR 0026); "
        "un router que además filtra es un router con dos trabajos",
    }},
    "fw": {"*": {
        "uplink": "traducir y repartir no es filtrar: la vía de acceso es un `rt` (ADR 0012)",
        "dhcp_server": "repartir direcciones no es filtrar: un `fw` no sirve DHCP (ADR 0026)",
    }},
    "sw": {"*": {
        "firewall": "un conmutador no filtra: eso es un `fw` (ADR 0026)",
        "routes": "un conmutador no enruta: eso es un `rt` (ADR 0026)",
        "uplink": "un conmutador no traduce ni sale: eso es un `rt` (ADR 0026)",
        "dhcp_server": "un conmutador no reparte direcciones (ADR 0026)",
    }},
    # Un SERVIDOR y un PUESTO no son equipos de red. Lo que hacen, lo hacen por dentro, como
    # software; la red la sirve quien es de red (`rt` enruta y reparte, `fw` filtra). Sin esta
    # entrada, cambiarle el `tipo` a un `srv` dejaba pasar la misma mezcla de responsabilidades
    # que el ADR 0026 prohíbe: el tipo que no está en esta tabla no tiene ninguna regla.
    "srv": {"*": _NO_ES_DE_RED},
    "ws": {"*": _NO_ES_DE_RED},
    # El bastión es la puerta del MOTOR, no un equipo del lab (ADR 0006): reparte direcciones
    # en la red de gestión, reenvía el túnel y enruta -- pero TODO eso por dentro de su Linux,
    # con el vocabulario de Linux, que es donde vive su declaración. Con el vocabulario de un
    # equipo de red no le toca ninguna de esas funciones, y por eso la entrada es por interior:
    # prohibirle `dhcp_server` en seco le prohibiría hacer su trabajo (el `ctl` del lab 08 lo
    # declara en `linux`, y tiene que seguir pasando).
    "ctl": {"routeros": _NO_ES_DE_RED},
}


def interfaces_declaradas(guest):
    """Los bridges del invitado, EN ORDEN: `bridges:` (varias) o `bridge:` (una).

    El orden es el de las interfaces: la primera interfaz es `eth0` (en RouterOS, `ether1`),
    la segunda `eth1`/`ether2`, y así. Un invitado de una sola interfaz puede seguir
    declarando `bridge:` (todo lo de la fase 1 sigue igual); uno que sirve varias redes
    declara `bridges: [...]` porque sus interfaces se nombran en la declaración.
    """
    if isinstance(guest.get("bridges"), list) and guest["bridges"]:
        return [str(nombre) for nombre in guest["bridges"]]
    if guest.get("bridge"):
        return [str(guest["bridge"])]
    return []


def _direccion_valida(direccion):
    """¿Es una de las formas que admite `address:`?

    `derived` es una de ellas (ADR 0020): no es una dirección, es la MARCA de que
    la ponga el IPAM. Aquí se acepta para que un `derived` sin `address_space` del
    que derivar salga con SU error («no hay de dónde»), y no con uno genérico que
    mandaría a buscar el problema en el sitio equivocado.
    """
    texto = str(direccion)
    if texto == "dhcp" or texto == modulo_identidad.DERIVADO:
        return True
    if not IP_PATRON.match(texto):
        return False
    if "/" not in texto:
        return False
    octetos = [int(o) for o in texto.split("/")[0].split(".")]
    prefijo = int(texto.split("/")[1])
    return all(0 <= o <= 255 for o in octetos) and 0 <= prefijo <= 32


def _plano(valor):
    """Lo que Ansible da, convertido en Python de verdad (dict/list/str).

    Ansible no pasa el YAML: pasa un `_AnsibleLazyTemplateDict`, un mapa PEREZOSO que
    vuelve a plantillar desde el original cada vez que se lee. Copiarlo y escribir en la
    copia no sirve de nada -- la lectura sigue devolviendo el original --, así que el IPAM
    resolvía sobre un objeto y el validador leía otro. Medido con P0_DEBUG dentro de un
    `verify` real: llegaba `_AnsibleLazyTemplateDict` y los `derived` seguían ahí.

    De ahí que TODO lo que se derive o se valide pase antes por aquí: el motor no
    razona sobre prótesis de Ansible, razona sobre datos.
    """
    if hasattr(valor, "items") and hasattr(valor, "keys"):
        return {str(clave): _plano(sub) for clave, sub in valor.items()}
    if isinstance(valor, (list, tuple)):
        return [_plano(sub) for sub in valor]
    if isinstance(valor, str):
        return str(valor)
    return valor


def declaracion_direcciones(declaracion):
    """La declaración con los `derived` ya resueltos por el IPAM (ADR 0020).

    Es lo PRIMERO que se hace al validar, normalizar o aconsejar: a partir de ahí,
    nadie más tiene que saber que `derived` existe. Es idempotente -- sobre una
    declaración sin marcas no cambia nada -- y puro, así que dos pasadas derivan
    exactamente las mismas direcciones.
    """
    if not hasattr(declaracion, "items"):
        return declaracion
    return modulo_identidad.direcciones_resolver(_plano(declaracion))


def _es_marca_derivado(valor):
    """¿El lab dejó esta dirección a que la derive el motor?"""
    return isinstance(valor, str) and valor.strip() == modulo_identidad.DERIVADO


def _derivados_sin_resolver(declaracion):
    """Las direcciones que siguen en `derived` después de pasar por el IPAM.

    Sólo puede quedar alguna por una razón: no hay `address_space` del que
    derivar. Se devuelven con su RUTA para que el error diga dónde mirar.
    """
    salida = []
    for indice, puente in enumerate((declaracion.get("lab") or {}).get("bridges") or []):
        if _es_marca_derivado(puente.get("address")):
            salida.append(f"lab.bridges[{indice}].address")
    for seccion in ("vms", "containers"):
        for indice, guest in enumerate(declaracion.get(seccion) or []):
            etiqueta = f"{seccion}[{indice}]"
            if _es_marca_derivado(guest.get("address")):
                salida.append(f"{etiqueta}.address")
            interior = ((guest.get("config") or {}).get("routeros") or {})
            for posicion, entrada in enumerate(interior.get("addresses") or []):
                if _es_marca_derivado(entrada.get("address")):
                    salida.append(f"{etiqueta}.config.routeros.addresses[{posicion}].address")
            for posicion, servidor in enumerate(interior.get("dhcp_server") or []):
                if _es_marca_derivado((servidor.get("pool") or {}).get("rango")):
                    salida.append(f"{etiqueta}.config.routeros.dhcp_server[{posicion}].pool.rango")
                red = servidor.get("network") or {}
                for campo in ("address", "gateway", "dns"):
                    if _es_marca_derivado(red.get(campo)):
                        salida.append(
                            f"{etiqueta}.config.routeros.dhcp_server[{posicion}].network.{campo}"
                        )
    return salida


def _ip_en_address_space(ip, address_space):
    """¿Cae `ip` (con o sin máscara) dentro de la espacio de direcciones declarada?

    Se comparan los PREFIJOS enteros, octeto a octeto: 10.40.1.5/24 está en
    10.40.0.0/16 porque los 16 primeros bits coinciden. No se hace aritmética de red
    más fina que esa: con IPv4 y prefijos de laboratorio sobra, y un cálculo
    complicado aquí sería otra cosa que puede estar mal sin que nadie lo note.
    """
    base, _, prefijo = str(address_space).partition("/")
    if not prefijo:
        return True
    try:
        bits = int(prefijo)
    except ValueError:
        return False
    if bits % 8 != 0:
        return True  # no se opina: prefijos que no caen en un octeto no se vigilan
    octetos = bits // 8
    if octetos < 1 or octetos > 4:
        return True  # /0 no acota nada; un prefijo imposible no se vigila aquí
    # Se conservan los `octetos` primeros de cada dirección y se comparan: es la
    # comparación de prefijo que se lee de un vistazo, sin aritmética de bits.
    return ".".join(str(ip).split("/")[0].split(".")[:octetos]) == ".".join(
        base.split(".")[:octetos]
    )


def _validar_ready(guest, etiqueta, rol, errores):
    """El bloque `ready:` de un invitado, si lo declara (ADR 0021)."""
    ready = guest.get("ready")
    if ready is None:
        return
    if not isinstance(ready, dict):
        errores.append(
            f"`{etiqueta}` ({rol}): `ready` es un mapa con `tipo` (y `espera`), y esto es "
            f"un {type(ready).__name__}: p. ej. `ready: {{tipo: ssh}}`"
        )
        return
    tipo_ready = ready.get("tipo")
    if tipo_ready not in READY_TIPOS:
        errores.append(
            f"`{etiqueta}` ({rol}): `ready.tipo` es {tipo_ready!r} y admite "
            f"{', '.join(READY_TIPOS)}. `ninguno` es la forma de decir «este invitado no "
            "lleva barrera», que NO es lo mismo que callarse (callarse es «decide el motor»)"
        )
    espera = ready.get("espera")
    if espera is not None and (
        not isinstance(espera, int) or isinstance(espera, bool) or espera <= 0
    ):
        errores.append(
            f"`{etiqueta}` ({rol}): `ready.espera` son SEGUNDOS y tiene que ser un entero "
            f"positivo, y esto es {espera!r}"
        )
    desconocidas = sorted(set(ready) - {"tipo", "espera"})
    if desconocidas:
        errores.append(
            f"`{etiqueta}` ({rol}): `ready` no admite "
            f"{', '.join('`' + c + '`' for c in desconocidas)}: admite `tipo` y `espera`"
        )
    # Un invitado que toma su dirección por DHCP no tiene dirección que preguntar hasta
    # que su router se la dé: una barrera sobre él no se puede cumplir. Decirlo aquí es
    # mejor que descubrirlo con el lab a medio desplegar y media etapa ya convergida.
    #
    # Salvo `ninguno`, que es justo lo que el lab quiere decir: «a este no le esperes».
    # Prohibir eso obligaría a callarse, y callarse significa otra cosa (que decida el
    # motor) -- y en un invitado con DHCP el motor ya no sondea, así que el lab no tenía
    # forma de DECIRLO. Medido en el lab 06: es el único sitio donde `ready` no tenía
    # nada que aportar.
    if str(guest.get("address")) == "dhcp" and tipo_ready != "ninguno":
        errores.append(
            f"`{etiqueta}` ({rol}) declara `ready` y toma su dirección por DHCP: no hay "
            "dirección que preguntar. Hoy el motor no sondea a un equipo con `address: dhcp`"
        )


def _validar_pruebas(declaracion, errores):
    """Las PRUEBAS FUNCIONALES que declara el lab (6.2, ADR 0022).

    Se valida con el mismo rigor que una regla de cortafuegos: una prueba que el motor
    no sabe lanzar es un fallo de la declaración, no una prueba que se salta en
    silencio -- porque entonces el veredicto diría «todo bien» sin haber mirado.
    """
    pruebas = declaracion.get("tests")
    if pruebas is None:
        return
    if not isinstance(pruebas, list):
        errores.append(
            f"`tests` es una LISTA de pruebas, y esto es un {type(pruebas).__name__}"
        )
        return
    # El rol de cada invitado y si es un Linux (por él se entra por SSH; un RouterOS se
    # gobierna por su REST, que es otro camino y hoy no lanza pruebas).
    linux = {}
    for seccion in ("vms", "containers"):
        for guest in declaracion.get(seccion) or []:
            if isinstance(guest, dict) and guest.get("rol"):
                interior = ((guest.get("config") or {}).get("routeros") or {})
                linux[guest["rol"]] = (not interior) and seccion == "containers"
    for indice, prueba in enumerate(pruebas):
        etiqueta = f"tests[{indice}]"
        if not isinstance(prueba, dict):
            errores.append(f"`{etiqueta}` no es un mapa con `nombre`, `desde`, `tipo` y `hacia`")
            continue
        desconocidas = sorted(set(prueba) - {"nombre", "desde", "tipo", "hacia", "puerto", "espera"})
        if desconocidas:
            errores.append(
                f"`{etiqueta}`: `tests` no admite "
                f"{', '.join('`' + c + '`' for c in desconocidas)} -- admite `nombre`, "
                "`desde`, `tipo`, `hacia`, `puerto` (sólo `servicio`) y `espera` (segundos)"
            )
        if not str(prueba.get("nombre") or "").strip():
            errores.append(f"`{etiqueta}`: sin `nombre`, una prueba no se puede citar en el veredicto")
        tipo = str(prueba.get("tipo") or "").strip()
        if tipo not in modulo_interior.PRUEBA_TIPOS:
            errores.append(
                f"`{etiqueta}` ({prueba.get('nombre')!r}): `tipo` es {prueba.get('tipo')!r} y "
                f"admite {', '.join(modulo_interior.PRUEBA_TIPOS)}"
            )
        if not str(prueba.get("hacia") or "").strip():
            errores.append(f"`{etiqueta}` ({prueba.get('nombre')!r}): `hacia` es obligatorio")
        desde = str(prueba.get("desde") or "").strip()
        if not desde:
            errores.append(
                f"`{etiqueta}` ({prueba.get('nombre')!r}): `desde` es obligatorio -- una prueba "
                "se lanza DESDE un invitado, no desde donde corre el motor"
            )
        elif desde not in linux:
            errores.append(
                f"`{etiqueta}` ({prueba.get('nombre')!r}): `desde: {desde}` no es el rol de "
                "ningún invitado del lab"
            )
        elif not linux[desde]:
            errores.append(
                f"`{etiqueta}` ({prueba.get('nombre')!r}): `desde: {desde}` no es un invitado "
                "Linux. Hoy una prueba se lanza por SSH, que es la vía de acceso del interior "
                "de un Linux; un RouterOS se gobierna por su REST y ahí no hay pruebas todavía"
            )
        if tipo == "servicio":
            puerto = prueba.get("puerto")
            if not isinstance(puerto, int) or isinstance(puerto, bool) or not 1 <= puerto <= 65535:
                errores.append(
                    f"`{etiqueta}` ({prueba.get('nombre')!r}): una prueba de `servicio` necesita "
                    f"`puerto` (1-65535), y esto es {puerto!r}"
                )
        elif prueba.get("puerto") is not None:
            errores.append(
                f"`{etiqueta}` ({prueba.get('nombre')!r}): `puerto` sólo tiene sentido en una "
                f"prueba de `servicio`, y ésta es de `{tipo}`"
            )
        espera = prueba.get("espera")
        if espera is not None and (
            not isinstance(espera, int) or isinstance(espera, bool) or espera <= 0
        ):
            errores.append(
                f"`{etiqueta}` ({prueba.get('nombre')!r}): `espera` son SEGUNDOS y tiene que ser "
                f"un entero positivo, y esto es {espera!r}"
            )


def _validar_intromision(declaracion, errores):
    """Los bloques `capture:` e `impairment:` del lab (6.4, ADR 0023).

    Se validan aquí y no al ejecutar el verbo: un experimento que no se puede montar
    (un bridge que el bastión no pisa, unos segundos que faltan) tiene que salir al
    leer la declaración, no con el lab medio desplegado y el `netem` a medias.
    """
    puentes = [
        p.get("nombre") for p in ((declaracion.get("lab") or {}).get("bridges") or [])
        if isinstance(p, dict)
    ]
    for clave, admite in (
        ("capture", {"bridge", "filtro", "segundos"}),
        ("impairment", {"bridge", "segundos", "retardo", "jitter", "perdida"}),
    ):
        decl = declaracion.get(clave)
        if decl is None:
            continue
        if not isinstance(decl, dict):
            errores.append(f"`{clave}` es un mapa (no {type(decl).__name__})")
            continue
        desconocidas = sorted(set(decl) - admite)
        if desconocidas:
            errores.append(
                f"`{clave}` no admite "
                f"{', '.join('`' + c + '`' for c in desconocidas)}: admite "
                f"{', '.join(sorted(admite))}"
            )
        puente = str(decl.get("bridge") or "").strip()
        if not puente:
            errores.append(f"`{clave}.bridge` es obligatorio: hay que decir POR DÓNDE mirar")
        elif puente not in puentes:
            errores.append(f"`{clave}.bridge` es '{puente}', que no es un bridge de este lab")
        elif modulo_interior.interfaz_del_bastion(declaracion, puente) is None:
            # Y no basta con que sea un bridge del lab: el bastión tiene que PISARLO. No
            # los pisa todos por decreto -- su dotación es el bridge de gestión más los que
            # declara en `bridges:` --, y decirlo aquí evita descubrirlo al ejecutar el
            # verbo con el lab ya desplegado (que es como se descubrió: ver informe §6.4).
            errores.append(
                f"`{clave}.bridge` es '{puente}', pero el bastión de este lab no tiene una "
                "interfaz ahí: no habría desde dónde mirar. El bastión pisa su bridge de "
                "gestión y los que declara en `bridges:`; si quieres medir en otro, "
                "añádeselo primero al bastión"
            )
        segundos = decl.get("segundos")
        if not isinstance(segundos, int) or isinstance(segundos, bool) or segundos <= 0:
            errores.append(
                f"`{clave}.segundos` es obligatorio y son SEGUNDOS (un entero positivo): un "
                "experimento sin final es una mina en el lab"
            )
        if clave == "impairment" and not (
            decl.get("retardo") or decl.get("jitter") or decl.get("perdida")
        ):
            errores.append(
                "`impairment` no dice qué estropear: hace falta al menos uno de "
                "`retardo`, `jitter` o `perdida`"
            )
    # La captura y el impairment se montan EN EL BASTIÓN, y el bastión es quien tiene
    # una pata en el bridge. Sin bastión no hay dónde montarlas.
    if isinstance(declaracion.get("capture"), dict) or isinstance(declaracion.get("impairment"), dict):
        # OJO: aquí la declaración es la CRUDA (el validador ve `vms`/`containers`), y
        # `bastion()` lee la NORMALIZADA (`guests`): se pregunta por la señal, que es lo
        # que hace a un invitado ser el bastión -- que declare su túnel.
        hay_bastion = any(
            modulo_interior.tiene_tunnel(g)
            for g in (
                list(declaracion.get("vms") or []) + list(declaracion.get("containers") or [])
            )
            if isinstance(g, dict)
        )
        if not hay_bastion:
            errores.append(
                "`capture`/`impairment` necesitan un bastión (un invitado con su túnel): es "
                "quien tiene una interfaz en el bridge por el que se mira"
            )


def _validar_interior(guest, etiqueta, rol, errores):
    """Valida el vocabulario de `config:` con las reglas del §6 del encargo."""
    config = guest.get("config")
    if config is None:
        return
    if not isinstance(config, dict) or not config:
        errores.append(f"`{etiqueta}` ({rol}): `config` está vacío o no es un mapa")
        return
    tipos = [t for t in modulo_interior.TIPOS if t in config]
    if len(tipos) != 1:
        errores.append(
            f"`{etiqueta}` ({rol}): `config` tiene que traer EXACTAMENTE una clave de "
            f"tipo ({', '.join(modulo_interior.TIPOS)}) y trae {sorted(config.keys())}"
        )
        return
    tipo = tipos[0]
    declarado = config[tipo] or {}
    if not isinstance(declarado, dict):
        errores.append(f"`{etiqueta}` ({rol}): `config.{tipo}` no es un mapa")
        return

    conocidas = set(modulo_interior.AREAS[tipo]) | set(modulo_interior.AREAS_PENDIENTES[tipo])
    for area in declarado:
        if area in modulo_interior.AREAS[tipo]:
            continue
        if area in modulo_interior.AREAS_PENDIENTES[tipo]:
            errores.append(
                f"`{etiqueta}` ({rol}): el área '{area}' está en el vocabulario del "
                "encargo pero el motor todavía NO la converge. Se rechaza aquí en vez "
                "de aceptarla y no hacer nada con ella. Añadirla es un driver, su "
                "verificación y su ADR."
            )
            continue
        errores.append(
            f"`{etiqueta}` ({rol}): el área '{area}' no existe en el vocabulario del "
            f"interior `{tipo}` (las que hay: {', '.join(sorted(conocidas))}). El "
            "vocabulario es cerrado: una primitiva nueva se añade al motor, con ADR."
        )

    # Y el TIPO manda sobre las áreas (ADR 0026): un equipo hace UNA cosa. Va DESPUÉS del
    # vocabulario a propósito -- primero se dice si el área existe, y sólo si existe se
    # discute si le toca a este equipo. Un motivo por área, no un «no puedes».
    tipo_de_equipo = guest.get("tipo")
    # La tabla es por tipo y, dentro, por INTERIOR (`*` = cualquiera de ellos y el nombre de
    # un interior = sólo ahí). Hace falta la segunda dimensión porque hay NOMBRES DE ÁREA
    # COMPARTIDOS entre vocabularios: `dhcp_server` existe en RouterOS y en Linux, y el
    # bastión tiene que poder repartir direcciones con su Linux sin que la regla del equipo
    # de red se lo impida.
    por_interior = AREAS_QUE_NO_LE_TOCAN.get(tipo_de_equipo, {})
    prohibidas = {
        area: motivo
        for clave in ("*", tipo)
        for area, motivo in (por_interior.get(clave) or {}).items()
    }
    for area in declarado:
        if area in prohibidas:
            errores.append(
                f"`{etiqueta}` ({rol}) es un `{tipo_de_equipo}` y declara el área "
                f"'{area}': {prohibidas[area]}. Un equipo, una responsabilidad: lo que "
                "haga falta de más se declara en OTRO equipo."
            )

    # Las interfaces que el interior nombra TIENEN que existir en el invitado. Un CHR que
    # declara configurar `ether2` necesita dos interfaces, y sin la segunda RouterOS contesta
    # `400 input does not match any value of interface` A MITAD de la convergencia (medido:
    # con el intercambio de la dirección de gestión ya mandado y el equipo a medias).
    # Aquí se ve antes de tocar nada.
    interfaces = interfaces_declaradas(guest)
    for area, datos in declarado.items():
        entradas = datos if isinstance(datos, list) else ([datos] if isinstance(datos, dict) else [])
        for entrada in entradas:
            if not isinstance(entrada, dict):
                continue
            numero = re.match(r"^eth(?:er)?(\d+)$", str(entrada.get("interface") or ""))
            if numero and int(numero.group(1)) > len(interfaces):
                errores.append(
                    f"`{etiqueta}` ({rol}) declara configurar `{entrada['interface']}` en "
                    f"'{area}', pero el invitado sólo tiene {len(interfaces)} interface(s) "
                    f"({', '.join(interfaces) or 'ninguna'}): añade a `bridges` los bridges que "
                    "falten, en orden (las interfaces se deciden al crear y no se cambian en "
                    "caliente)"
                )

    # El área `uplink` no admite opciones: es una MARCA. La interfaz de fuera, su interfaz y su
    # dirección las deriva el motor (el plan tiende la interfaz, y el router pide dirección por
    # DHCP desde dentro), así que una opción aquí sería una invención del lab -- y este
    # vocabulario es cerrado (regla 15): se rechaza antes de tocar nada.
    exterior = declarado.get("uplink")
    if exterior not in (None, {}, [], ""):
        errores.append(
            f"`{etiqueta}` ({rol}): el área 'uplink' no lleva opciones y se declaró "
            f"{exterior!r}. Es una marca (`uplink: {{}}`): que este router ES la salida "
                        "del lab. La interfaz de fuera, su dirección y su salida las pone el motor."
        )

    # Y la dirección: un invitado con config tiene que ser alcanzable.
    direccion = guest.get("address")
    if direccion in (None, ""):
        errores.append(
            f"`{etiqueta}` ({rol}) declara `config.` pero no declara `address`: un "
            "equipo que no se puede alcanzar no se puede converger (un conmutador "
            "puro no lleva `config`)"
        )
    elif (modulo_interior.es_direccion_dinamica(direccion)
          and modulo_interior.areas_que_piden_visita(guest)):
        # Los puestos dinámicos declaran SÓLO el tipo (`linux: {}`) con `address: dhcp`:
        # su dirección se lee del HOST y no se configura dentro, así que no piden visita.
        # Pero un `dhcp` CON áreas que exijan entrar no se puede converger: no se sabe a
        # qué dirección conectar, y el motor no entra a ciegas (regla 16). Se dice aquí,
        # no se intenta.
        piden = ", ".join(sorted(modulo_interior.areas_que_piden_visita(guest)))
        errores.append(
            f"`{etiqueta}` ({rol}) declara `address: dhcp` y áreas que piden ENTRAR "
            f"({piden}): sin una dirección estática el motor no sabe a dónde conectar. "
            "Deja sólo el tipo (`linux: {}`) o declara una dirección."
        )

    if tipo == "routeros":
        _validar_routeros(declarado, etiqueta, rol, errores)
    else:
        _validar_linux(declarado, etiqueta, rol, errores)


def _validar_routeros(declarado, etiqueta, rol, errores):
    """Las formas del vocabulario de RouterOS, una a una."""
    identidad = declarado.get("identity")
    if identidad is not None and (not isinstance(identidad, str) or not identidad.strip()):
        errores.append(f"`{etiqueta}` ({rol}): `identity` tiene que ser texto no vacío")

    servicios = declarado.get("ip_services")
    if servicios is not None:
        if not isinstance(servicios, dict) or set(servicios) - {"deshabilitar", "habilitar"}:
            errores.append(
                f"`{etiqueta}` ({rol}): `ip_services` sólo admite `deshabilitar` (una lista)"
            )
        else:
            for servicio in servicios.get("deshabilitar") or []:
                if str(servicio) in modulo_interior.SERVICIOS_NUNCA_DESHABILITADOS:
                    errores.append(
                        f"`{etiqueta}` ({rol}): `servicios.deshabilitar` incluye "
                        f"'{servicio}', que es donde vive REST: es el túnel de vuelta "
                        "y deshabilitarlo deja el equipo sin forma de ser configurado"
                    )
                elif str(servicio) not in modulo_interior.SERVICIOS_GESTIONADOS:
                    errores.append(
                        f"`{etiqueta}` ({rol}): el servicio '{servicio}' no está en el "
                        "alcance del área `ip_services` "
                        f"({', '.join(modulo_interior.SERVICIOS_GESTIONADOS)})"
                    )

    cliente = declarado.get("dhcp_client")
    if cliente is not None and (
        not isinstance(cliente, dict) or not isinstance(cliente.get("deshabilitar"), bool)
    ):
        errores.append(f"`{etiqueta}` ({rol}): `dhcp_client` se declara `{{deshabilitar: true|false}}`")

    for indice, direccion in enumerate(declarado.get("addresses") or []):
        if not isinstance(direccion, dict) or not direccion.get("interface"):
            errores.append(f"`{etiqueta}` ({rol}): `addresses[{indice}]` necesita `interface` y `address`")
            continue
        if not _direccion_valida(direccion.get("address")):
            errores.append(
                f"`{etiqueta}` ({rol}): `addresses[{indice}]` tiene una dirección que no "
                f"es IPv4 con máscara: {direccion.get('address')!r}"
            )

    for indice, ruta in enumerate(declarado.get("routes") or []):
        if not isinstance(ruta, dict) or not ruta.get("dst_address") or not ruta.get("gateway"):
            errores.append(f"`{etiqueta}` ({rol}): `routes[{indice}]` necesita `dst_address` y `gateway`")

    # El CORTAFUEGOS: una LISTA de reglas en orden (el orden es la semántica), con el
    # vocabulario cerrado de `CAMPOS_FILTRO` y dos campos obligatorios (`chain` y `action`).
    # Y una guarda que no es de forma sino de SUPERVIVENCIA: un `drop` de entrada sin un
    # `accept` de entrada ANTES deja al motor fuera del equipo (su túnel es una conexión de
    # ENTRADA), y recuperarlo pide consola. Se caza aquí, antes de tocar nada.
    cortafuegos = declarado.get("firewall")
    if cortafuegos is not None:
        if not isinstance(cortafuegos, list):
            errores.append(
                f"`{etiqueta}` ({rol}): `firewall` es una LISTA de reglas, en orden "
                "(el orden es la semántica: RouterOS para en la primera que casa)"
            )
        else:
            conocidos = {declarado_key for declarado_key, _ in modulo_interior.CAMPOS_FILTRO}
            acciones = {"accept", "drop", "reject"}
            hay_accept_entrada = False
            for indice, regla in enumerate(cortafuegos):
                if not isinstance(regla, dict):
                    errores.append(f"`{etiqueta}` ({rol}): `firewall[{indice}]` no es un mapa")
                    continue
                inventados = sorted(set(regla) - conocidos)
                if inventados:
                    errores.append(
                        f"`{etiqueta}` ({rol}): `firewall[{indice}]` usa campos que no están "
                        f"en el vocabulario ({', '.join(inventados)}); los que hay: "
                        f"{', '.join(sorted(conocidos))}"
                    )
                cadena = str(regla.get("chain") or "")
                accion = str(regla.get("action") or "")
                if cadena not in ("input", "forward", "output"):
                    errores.append(
                        f"`{etiqueta}` ({rol}): `firewall[{indice}].chain` tiene que ser "
                        f"input, forward u output (y es {cadena or 'nada'!r})"
                    )
                if accion not in acciones:
                    errores.append(
                        f"`{etiqueta}` ({rol}): `firewall[{indice}].action` tiene que ser "
                        f"{', '.join(sorted(acciones))} (y es {accion or 'nada'!r})"
                    )
                if cadena == "input" and accion == "accept":
                    hay_accept_entrada = True
                if cadena == "input" and accion in ("drop", "reject") and not hay_accept_entrada:
                    errores.append(
                        f"`{etiqueta}` ({rol}): `firewall[{indice}]` cierra la entrada "
                        f"(`{accion}` en `input`) sin haber dejado pasar nada antes. El motor "
                        "entra por ahí (el túnel del bastión es una conexión de ENTRADA): sin "
                        "un `accept` de `input` ANTES, el equipo deja de obedecer y hay que "
                        "recuperarlo por consola"
                    )

    for indice, servidor in enumerate(declarado.get("dhcp_server") or []):
        if not isinstance(servidor, dict) or not servidor.get("interface"):
            errores.append(f"`{etiqueta}` ({rol}): `dhcp_server[{indice}]` necesita `interface`")
            continue
        reservas = servidor.get("static_leases")
        if isinstance(reservas, str) and reservas != "derived":
            errores.append(
                f"`{etiqueta}` ({rol}): `dhcp_server[{indice}].static_leases` sólo admite "
                "`derived` o una lista de `{role, address}` (nunca con MAC)"
            )
        elif isinstance(reservas, list):
            for reserva in reservas:
                if not isinstance(reserva, dict) or set(reserva) - {"rol", "address"}:
                    errores.append(
                        f"`{etiqueta}` ({rol}): una reserva es `{{role, address}}` y "
                        "nunca lleva MAC: la MAC se deriva del vmid (regla 14)"
                    )


def _validar_linux(declarado, etiqueta, rol, errores):
    """Las formas del vocabulario de Linux, una a una."""
    tunnel = declarado.get(modulo_interior.CLAVE_TUNNEL)
    if tunnel is not None:
        if not isinstance(tunnel, dict):
            errores.append(f"`{etiqueta}` ({rol}): `tunnel` tiene que ser un mapa")
        else:
            for clave in tunnel:
                if clave not in CLAVES_TUNNEL:
                    errores.append(
                        f"`{etiqueta}` ({rol}): `tunnel.{clave}` no existe: un puesto de "
                        "control declara sólo por dónde sale "
                        f"({', '.join(CLAVES_TUNNEL)}), y el resto es "
                        "entorno (secrets.yml), no lab"
                    )
    if "ip_forward" in declarado and not isinstance(declarado["ip_forward"], bool):
        errores.append(f"`{etiqueta}` ({rol}): `ip_forward` tiene que ser true o false")
    # `addresses` (Linux): las interfaces EXTRA del invitado, una por bridge del lab. Se
    # declaran una a una porque el motor no adivina direcciones (regla 11) y porque un
    # bastión sin dirección en un bridge no puede llegar a lo que cuelga de él.
    if "addresses" in declarado:
        interfaces = declarado["addresses"]
        if not isinstance(interfaces, list) or not interfaces:
            errores.append(
                f"`{etiqueta}` ({rol}): `addresses` tiene que ser una lista de "
                "`{interface, address}`"
            )
        else:
            for interface in interfaces:
                if not isinstance(interface, dict) or not interface.get("interface") or not interface.get("address"):
                    errores.append(
                        f"`{etiqueta}` ({rol}): cada entrada de `addresses` necesita "
                        "`interface` y `address`"
                    )
    servidor = declarado.get("dhcp_server")
    if servidor is not None:
        if not isinstance(servidor, dict) or not servidor.get("interface"):
            errores.append(f"`{etiqueta}` ({rol}): `dhcp_server` necesita `interface` y `rango`")
        else:
            if not servidor.get("rango") or "-" not in str(servidor.get("rango")):
                errores.append(
                    f"`{etiqueta}` ({rol}): `dhcp_server.rango` tiene que ser un rango "
                    "`inicio-fin` (p. ej. 10.40.0.50-10.40.0.99)"
                )
            reservas = servidor.get("static_leases")
            if reservas is not None and reservas != "derived" and not isinstance(reservas, list):
                errores.append(
                    f"`{etiqueta}` ({rol}): `dhcp_server.static_leases` sólo admite "
                    "`derived` o una lista de `{role, address}`"
                )
    # `servicio`: el NOMBRE de un servicio del vocabulario CERRADO (hoy sólo `caddy`). El
    # motor lo instala, escribe su configuración y lo deja sirviendo. Un nombre que no esté
    # se RECHAZA aquí con el motivo -- en vez de aceptarlo y no hacer nada con él -- porque el
    # vocabulario es cerrado (regla 15): una primitiva nueva se añade al motor, con su ADR.
    servicio = declarado.get("servicio")
    if servicio is not None and (
        not isinstance(servicio, str) or servicio not in modulo_interior.SERVICIOS_LINUX
    ):
        errores.append(
            f"`{etiqueta}` ({rol}): el servicio {servicio!r} no está en el vocabulario "
            f"cerrado de `servicio` (los que hay: {', '.join(modulo_interior.SERVICIOS_LINUX)}). "
            "Un servicio que el motor no sabe instalar y servir se rechaza aquí, no se acepta "
            "y se ignora. Añadirlo es una primitiva nueva, con su ADR."
        )


def _address_space_de(declaracion):
    """La espacio de direcciones declarada por el lab, o None. Es opcional: un lab de la fase 1 no
    la declara y no se le exige."""
    valor = (declaracion.get("lab") or {}).get("address_space")
    if valor is None:
        return None
    texto = str(valor)
    if "/" not in texto or not IP_PATRON.match(texto):
        return ""
    return texto

# Formato de nombre de interfaz de red que Proxmox acepta (formato `pve-iface` de
# `PVE::JSONSchema`): empieza por letra y sigue con letras/dígitos/guion_bajo (NO
# admite guiones). El sufijo opcional `[:.]<n>` es para VLANs.
#
# OJO con la LONGITUD: la API acepta hasta 20 caracteres, pero el NÚCLEO sólo
# admite 15 (`IFNAMSIZ`). Un bridge de 16 a 20 caracteres pasa la validación de la
# API y luego revienta al recargar la red ("interface name too long"), dejando el
# bridge sin activar. Por eso aquí se exige el límite ESTRICTO del núcleo: 15.
IFACE_PATRON = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]{1,20}([:.]\d+)?$")
IFACE_MIN = 2
IFACE_MAX = 15


def _nombre_bridge_valido(nombre):
    """¿Aceptaría Proxmox este nombre de interfaz? (formato `pve-iface`)."""
    texto = str(nombre)
    if not (IFACE_MIN <= len(texto) <= IFACE_MAX):
        return False
    return bool(IFACE_PATRON.match(texto))


def _direccion_sin_mascara(direccion):
    """`192.0.2.11/24` -> `192.0.2.11`. La máscara no distingue a nadie."""
    return str(direccion).split("/", 1)[0].strip()


def _buscar_prohibidos(valor, ruta, errores):
    """MACs y credenciales, en cualquier rincón de la declaración.

    Se recorre el valor entero en vez de mirar sólo las claves de arriba: una MAC
    escondida tres niveles dentro sigue siendo una MAC declarada, y este es el
    único sitio donde se puede ver antes de que la API la acepte.
    """
    if isinstance(valor, dict):
        for clave, hijo in valor.items():
            nombre = str(clave).lower()
            if any(credencial in nombre for credencial in CLAVES_CREDENCIAL):
                errores.append(
                    f"`{ruta}.{clave}`: una credencial NO se declara en el lab, vive en "
                    "`deployment_engine/secrets.yml`"
                )
            _buscar_prohibidos(hijo, f"{ruta}.{clave}", errores)
        return
    if isinstance(valor, list):
        for indice, hijo in enumerate(valor):
            _buscar_prohibidos(hijo, f"{ruta}[{indice}]", errores)
        return
    if isinstance(valor, str):
        if MAC_PATRON.match(valor.strip()) or MAC_EN_TEXTO.search(valor):
            errores.append(
                f"`{ruta}` declara una MAC ({valor}): la MAC se DERIVA del vmid "
                "(regla 14) y no se declara nunca. Si hace falta una reserva DHCP, se "
                "declara `static_leases: derived` o `{role, address}`, nunca la MAC."
            )
        elif CLAVE_EN_TEXTO.search(valor):
            errores.append(
                f"`{ruta}` parece una CLAVE (o un certificado): las claves del motor son "
                "suyas y viven fuera del repo (regla 3); el lab no declara ninguna. "
                "La clave del túnel la genera el motor y la deja él mismo dentro del "
                "bastión."
            )


def _direcciones_declaradas(declaracion):
    """Todas las direcciones y rangos que un lab declara, para vigilar la espacio de direcciones.

    Devuelve (ruta, texto). Se incluyen los bridges del lab (su dirección es la
    pasarela de los invitados de ese bridge), las direcciones de los invitados y las
    que el interior declara por dentro (direcciones de un RouterOS, pools, redes y
    rangos del DHCP).
    """
    salida = []
    for indice, bridge in enumerate((declaracion.get("lab") or {}).get("bridges") or []):
        if bridge.get("address"):
            salida.append((f"lab.bridges[{indice}].address", bridge["address"]))
    for seccion in ("vms", "containers"):
        for indice, guest in enumerate(declaracion.get(seccion) or []):
            etiqueta = f"{seccion}[{indice}]"
            direccion = guest.get("address")
            if direccion and str(direccion) != "dhcp":
                salida.append((f"{etiqueta}.address", direccion))
            config = (guest.get("config") or {}).get("routeros") or {}
            for i, item in enumerate(config.get("addresses") or []):
                if item.get("address"):
                    salida.append((f"{etiqueta}.config.routeros.addresses[{i}]", item["address"]))
            for i, servidor in enumerate(config.get("dhcp_server") or []):
                if (servidor.get("pool") or {}).get("rango"):
                    rango = str(servidor["pool"]["rango"])
                    for trozo in rango.split("-"):
                        salida.append((f"{etiqueta}.config.routeros.dhcp[{i}].pool", trozo))
                if (servidor.get("network") or {}).get("address"):
                    salida.append(
                        (f"{etiqueta}.config.routeros.dhcp[{i}].network", servidor["network"]["address"])
                    )
                for i_r, reserva in enumerate(servidor.get("static_leases") or []):
                    if isinstance(reserva, dict) and reserva.get("address"):
                        salida.append(
                            (f"{etiqueta}.config.routeros.dhcp[{i}].static_leases[{i_r}]", reserva["address"])
                        )
                if servidor.get("network", {}).get("gateway"):
                    salida.append(
                        (f"{etiqueta}.config.routeros.dhcp[{i}].network.gateway", servidor["network"]["gateway"])
                    )
            for ruta, item in enumerate(config.get("routes") or []):
                if item.get("gateway"):
                    salida.append((f"{etiqueta}.config.routeros.routes[{ruta}].gateway", item["gateway"]))
            linux = (guest.get("config") or {}).get("linux") or {}
            servidor_dhcp = linux.get("dhcp_server") or {}
            if servidor_dhcp.get("rango"):
                for trozo in str(servidor_dhcp["rango"]).split("-"):
                    salida.append((f"{etiqueta}.config.linux.dhcp_server.rango", trozo))
    return salida


def declaracion_address_space(declaracion):
    """La espacio de direcciones declarada, o None. Lo usa `./lab check address-space`.

    Resuelve el IPAM primero (ADR 0020): lo que se vigila es que las direcciones de
    verdad caigan dentro del espacio, no que la marca `derived` lo haga.
    """
    if isinstance(declaracion, dict):
        declaracion = declaracion_direcciones(declaracion)
    return _address_space_de(declaracion)


def declaracion_validar(declaracion, carpeta=None):
    """Devuelve la lista de incoherencias del estado deseado. Vacía = coherente.

    `carpeta` es el nombre del directorio del lab (`labs/<carpeta>/`). Si se pasa,
    se exige que coincida con el nombre declarado: el pool se llama como la
    carpeta, y si los dos nombres divergen, la frontera de propiedad miente.
    """
    errores = []

    if not isinstance(declaracion, dict):
        return ["la declaración no es un mapa YAML (se esperaba una clave `lab`)"]

    lab = declaracion.get("lab")
    if not isinstance(lab, dict):
        return ["falta la sección `lab` (nombre, bridges, stages)"]

    # 6.1 · El IPAM lo PRIMERO (ADR 0020): lo que el lab dejó en `derived` se resuelve
    # antes de validar nada, para que todo lo de abajo vea direcciones de verdad y
    # ninguna regla tenga que saber que la marca existe.
    declaracion = declaracion_direcciones(declaracion)

    nombre = lab.get("nombre")
    if not isinstance(nombre, str) or not nombre.strip():
        errores.append("`lab.nombre` falta o está vacío")
    elif carpeta is not None and nombre != carpeta:
        errores.append(
            f"`lab.nombre` es '{nombre}' pero la carpeta es '{carpeta}': "
            "el pool se llama como la carpeta y los dos nombres tienen que coincidir"
        )

    # --- bridges del lab ---------------------------------------------------
    bridges = lab.get("bridges")
    if not isinstance(bridges, list) or not bridges:
        errores.append("`lab.bridges` falta o está vacío (el lab tiene que declarar sus bridges)")
        bridges = []
    nombres_bridge = []
    for indice, bridge in enumerate(bridges):
        if not isinstance(bridge, dict) or not bridge.get("nombre"):
            errores.append(f"`lab.bridges[{indice}]` no tiene `nombre`")
            continue
        nombre_bridge = bridge["nombre"]
        if not _nombre_bridge_valido(nombre_bridge):
            errores.append(
                f"`lab.bridges[{indice}]` ('{nombre_bridge}'): Proxmox no acepta ese "
                "nombre de interfaz (empezar por letra, sólo letras/dígitos/guion_bajo, "
                "2 a 15 caracteres, sin guiones). La API lo rechazaría al aplicar."
            )
        nombres_bridge.append(nombre_bridge)
    duplicados = {n for n in nombres_bridge if nombres_bridge.count(n) > 1}
    if duplicados:
        errores.append(f"hay bridges repetidos en el lab: {sorted(duplicados)}")

    # --- etapas de arranque --------------------------------------------
    stages = lab.get("stages")
    if not isinstance(stages, list) or not stages:
        errores.append("`lab.stages` falta o está vacío (el orden de arranque es parte de la topología)")
        stages = []
    for stage in stages:
        if not isinstance(stage, int) or stage < 1:
            errores.append(f"etapa inválido {stage!r}: tienen que ser enteros >= 1")

    # --- lo que no se declara nunca, también fuera de los invitados ---------
    # La sección `lab` no es un rincón libre: una MAC o una clave escondida ahí sigue
    # siendo algo que una declaración no lleva (las claves del motor son suyas y viven
    # fuera del repo). Se busca en TODA la sección, no sólo en las claves conocidas.
    _buscar_prohibidos(lab, "lab", errores)

    # --- invitados ---------------------------------------------------------
    guests = []
    for seccion, tipo in (("vms", "qemu"), ("containers", "lxc")):
        lista = declaracion.get(seccion, [])
        if lista is None:
            lista = []
        if not isinstance(lista, list):
            errores.append(f"`{seccion}` no es una lista")
            continue
        for indice, guest in enumerate(lista):
            if not isinstance(guest, dict):
                errores.append(f"`{seccion}[{indice}]` no es un mapa")
                continue
            guests.append((f"{seccion}[{indice}]", tipo, guest))

    roles = []
    direcciones = []
    stages_usados = []
    puestos_control = []
    # Los nombres derivados que ya han salido, para vigilar que dos invitados del MISMO lab
    # no se llamen igual (`srv-1` dos veces). Entre labs distintos SÍ puede repetirse: el pool
    # y la descripción (`lab=… rol=…`) son los que dicen de quién es cada uno.
    nombres_derivados = {}
    for etiqueta, tipo, guest in guests:
        rol = guest.get("rol")
        if not isinstance(rol, str) or not rol.strip():
            errores.append(f"`{etiqueta}` no tiene `rol`")
            continue
        roles.append(rol)

        # --- el nombre: qué EQUIPO es, y cómo se le llama (ADR 0015) -----------
        # El nombre dice qué es el invitado, no de qué lab es: `rt-borde`, `srv-1`. Se deriva
        # de dos mitades declaradas -- el `tipo:` (obligatorio, vocabulario cerrado) y el
        # alias, que es su `nombre:` corto, o su rol si no lo declara.
        equipo = guest.get("tipo")
        if equipo is None:
            errores.append(
                f"`{etiqueta}` ({rol}): falta `tipo:`. El nombre de un invitado dice qué "
                "EQUIPO es (no de qué lab es), y el tipo lo declara el lab. Admitidos: "
                f"{', '.join(sorted(TIPOS_DE_EQUIPO))}."
            )
        elif str(equipo) not in TIPOS_DE_EQUIPO:
            errores.append(
                f"`{etiqueta}` ({rol}): `tipo: '{equipo}'` no está en el vocabulario "
                f"({', '.join(sorted(TIPOS_DE_EQUIPO))}). Un equipo nuevo se pide al motor "
                "con su ADR: no se inventa un tipo aquí."
            )
        alias = guest.get("nombre")
        if alias is not None:
            # Un alias puede llegar como NÚMERO (`nombre: 1`), que es lo natural para
            # numerar puestos, servidores y controles: se lee como texto.
            if isinstance(alias, int) and not isinstance(alias, bool):
                alias = str(alias)
            if not isinstance(alias, str) or not re.match(r"^[A-Za-z0-9][A-Za-z0-9._-]*$", alias):
                errores.append(
                    f"`{etiqueta}` ({rol}): `nombre: '{alias}'` no vale como alias: letras, "
                    "números, punto, guion y guion bajo, empezando por letra o número (es la "
                    "mitad del nombre del invitado, el que se lee en Proxmox)"
                )
                alias = None
        # Y el nombre entero, para vigilar repeticiones DENTRO del lab (si las dos mitades
        # están bien; si no, ya hay un error arriba y no se añade ruido).
        if str(equipo) in TIPOS_DE_EQUIPO:
            nombre_derivado = f"{equipo}-{alias if isinstance(alias, str) and alias else rol}"
            if nombre_derivado in nombres_derivados:
                errores.append(
                    f"`{etiqueta}` ({rol}): el nombre '{nombre_derivado}' ya lo lleva el rol "
                    f"'{nombres_derivados[nombre_derivado]}' de este mismo lab -- dos invitados "
                    "de un lab no pueden llamarse igual (entre labs distintos sí)"
                )
            nombres_derivados[nombre_derivado] = rol

        # Lo que el motor deriva, prohibido en la declaración.
        for clave in CLAVES_DERIVADAS:
            if clave in guest:
                errores.append(
                    f"`{etiqueta}` ({rol}) declara `{clave}`: eso lo deriva el motor "
                    "de la identidad (regla 11). Quítalo de la declaración."
                )

        # Un invitado de VARIAS interfaces declara `bridges:` (la lista) en vez de `bridge:`.
        # Las dos formas dicen lo mismo; la lista es la que deja nombrar `ether2`, etc.
        tiene_interfaces = isinstance(guest.get("bridges"), list) and bool(guest["bridges"])
        for campo, esperado in CAMPOS_GUEST.items():
            if campo not in guest:
                if campo == "bridge" and tiene_interfaces:
                    continue
                errores.append(f"`{etiqueta}` ({rol}) no declara `{campo}`")
                continue
            valor = guest[campo]
            if esperado is int:
                if not isinstance(valor, int) or isinstance(valor, bool) or valor <= 0:
                    errores.append(f"`{etiqueta}` ({rol}): `{campo}` tiene que ser un entero > 0 (es {valor!r})")
            elif not isinstance(valor, str) or not valor.strip():
                errores.append(f"`{etiqueta}` ({rol}): `{campo}` tiene que ser texto no vacío")

        if tiene_interfaces:
            if len(set(guest["bridges"])) != len(guest["bridges"]):
                errores.append(f"`{etiqueta}` ({rol}): `bridges` repite un bridge")
            for nombre in guest["bridges"]:
                if not isinstance(nombre, str) or nombre not in nombres_bridge:
                    errores.append(
                        f"`{etiqueta}` ({rol}) usa el bridge '{nombre}', "
                        "que el lab no declara en `lab.bridges`"
                    )
        elif guest.get("bridge") and guest["bridge"] not in nombres_bridge:
            errores.append(
                f"`{etiqueta}` ({rol}) usa el bridge '{guest['bridge']}', "
                "que el lab no declara en `lab.bridges`"
            )
        if guest.get("stage") is not None and guest["stage"] not in stages:
            errores.append(
                f"`{etiqueta}` ({rol}) está en la etapa {guest['stage']}, "
                "que no aparece en `lab.stages`"
            )
        if isinstance(guest.get("stage"), int):
            stages_usados.append(guest["stage"])

        # --- la dirección: tres formas, y la de en medio es `dhcp` -------------
        direccion = guest.get("address")
        if direccion not in (None, ""):
            if not _direccion_valida(direccion):
                errores.append(
                    f"`{etiqueta}` ({rol}): `address` admite tres formas -- `<ip>/<prefijo>` "
                    f"(estática), `dhcp` (dinámica) y ausente (equipo sin dirección) -- y "
                    f"esto no es ninguna: {direccion!r}"
                )
            elif str(direccion) != "dhcp":
                direcciones.append((rol, _direccion_sin_mascara(direccion)))

        # --- la image: sólo para una VM, y es lo que la hace arrancar ---------
        imagen = guest.get("image")
        if imagen is not None:
            if tipo != "qemu":
                errores.append(
                    f"`{etiqueta}` ({rol}) declara `image` y es un contenedor: una imagen "
                    "de fábrica es el disco de una VM (se importa AL CREAR, §9.3)"
                )
            elif not isinstance(imagen, str) or not imagen.strip():
                errores.append(f"`{etiqueta}` ({rol}): `image` tiene que ser texto no vacío")

        # --- lo que no se declara nunca: MACs y credenciales -------------------
        _buscar_prohibidos(guest, f"{etiqueta}", errores)
        # --- la barrera que el lab declara (6.3, ADR 0021) ---------------------
        _validar_ready(guest, etiqueta, rol, errores)
        # --- el vocabulario del interior (cerrado) ----------------------------
        _validar_interior(guest, etiqueta, rol, errores)
        if modulo_interior.tiene_tunnel(guest):
            puestos_control.append(rol)

    repetidos = {r for r in roles if roles.count(r) > 1}
    if repetidos:
        errores.append(
            f"roles repetidos: {sorted(repetidos)}. Un rol identifica a un invitado "
            "y sólo a uno: el nombre canónico y la descripción se derivan de él."
        )

    # Un etapa declarado y vacío es una promesa que la declaración no cumple.
    for stage in stages:
        if isinstance(stage, int) and stage not in stages_usados:
            errores.append(f"la etapa {stage} está declarado pero ningún invitado lo usa")

    # Dos roles con la misma dirección chocan en la red del lab.
    vistas = {}
    for rol, direccion in direcciones:
        if direccion in vistas:
            errores.append(f"los roles '{vistas[direccion]}' y '{rol}' comparten la dirección {direccion}")
        else:
            vistas[direccion] = rol

    # --- el tunnel: uno, y sólo uno, y tiene que coincidir con `lab.tunnel` ----
    tunnel = (lab.get("tunnel") or {}).get("tipo")
    if tunnel is not None and tunnel != "bastion":
        errores.append(
            f"`lab.tunnel.tipo` es {tunnel!r}: el único túnel que el motor sabe "
            "construir es `puesto_control` (§5). Otra cosa es otra fase, con su ADR."
        )
    if tunnel is not None and not puestos_control:
        errores.append(
            "`lab.tunnel` está declarado y ningún invitado declara "
            "`config.linux.tunnel`: el túnel lo levanta un bastión, y sin "
            "él no hay por dónde entrar en el lab"
        )
    if tunnel is None and puestos_control:
        errores.append(
            f"el rol '{puestos_control[0]}' se declara bastión "
            "(`config.linux.tunnel`) pero el lab no declara `lab.tunnel`: decláralo, o "
            "quita el `tunnel` del invitado"
        )
    if len(puestos_control) > 1:
        errores.append(
            f"hay más de un bastión declarado ({sorted(puestos_control)}): "
            "el puerto del túnel se deriva del vmid y dos puestos en el mismo lab se "
            "pisarían"
        )

    # --- la address_space: todo lo del lab vive dentro, y se puede comprobar --------
    address_space = _address_space_de(declaracion)
    if address_space == "":
        errores.append(
            f"`lab.espacio de direcciones` ({lab.get('address_space')!r}) no es una red con máscara "
            "(p. ej. 10.40.0.0/16)"
        )
    elif address_space is not None:
        for ruta_declarada, valor in _direcciones_declaradas(declaracion):
            if not _ip_en_address_space(valor, address_space):
                errores.append(
                    f"`{ruta_declarada}` ({valor}) se sale de la espacio de direcciones del lab "
                    f"({address_space}): todo lo del lab vive dentro, y hay un check que lo "
                    "vigila porque es lo que hace imposible que dos labs se pisen"
                )

    # --- 6.2 · Las pruebas funcionales que declara el lab (ADR 0022) ----------------
    _validar_pruebas(declaracion, errores)

    # --- 6.4 · La captura y el impairment que declara el lab (ADR 0023) --------------
    _validar_intromision(declaracion, errores)

    # --- 6.1 · Un `derived` que no se pudo derivar ---------------------------------
    # El IPAM (al principio) ya lo intentó. Si algo sigue en `derived` es que no hay
    # `address_space` del que derivar: se DICE, no se resuelve a medias en silencio.
    for ruta_derivada in _derivados_sin_resolver(declaracion):
        errores.append(
            f"`{ruta_derivada}` pide `derived` y el lab no declara `address_space`: no "
            "hay espacio de direcciones del que derivar (ADR 0020). O se declara el "
            "espacio, o esa dirección se escribe entera."
        )

    return errores


# ---------------------------------------------------------------------------
# Consejos -- lo que es LEGAL pero casi siempre es un olvido
# ---------------------------------------------------------------------------
# Un validador que sólo dice "no" obliga a aprender a golpes, y la mitad de los
# tropiezos de un lab nuevo son legales y silenciosos: un invitado que arranca en
# el mismo etapa que quien le da la dirección, una dirección estática dentro del
# rango del DHCP (que un cliente dinámico le puede robar), una pasarela que no es
# nadie del lab, una VM sin imagen, un bridge declarado por el que no pasa nadie,
# dos servidores DHCP en el mismo bridge, o una dirección dinámica en un bridge del
# lab donde no hay quien la dé, o un router que es la salida del lab mientras ningún
# servidor DHCP del lab anuncia DNS (sale a internet y no resuelve un solo nombre).
#
# NO son errores: no bloquean, no cambian el plan y no tocan los diarios. Son eso,
# consejos, y el criterio lo sigue teniendo quien declara. Cada uno es
# `{codigo, donde, mensaje, remedio}`: el código agrupa (y es lo que se prueba en
# `test/test_declaracion.py`), `donde` localiza, y `remedio` dice qué escribir.
CONSEJOS_CONOCIDOS = (
    "stages",
    "dhcp",
    "gateway",
    "image",
    "bridge-vacio",
    "dos-dhcp",
    "sin-quien-la-dirija",
    "uplink-sin-dns",
    "uplink-con-ruta",
)


def _indice_de_interfaz(interfaz):
    """`eth0`/`ether1` -> 0; la PRIMERA interfaz, en los dos vocabularios.

    Linux cuenta desde cero (`eth0`) y RouterOS desde uno (`ether1`), y las dos
    formas nombran la misma posición: la primera interfaz declarada.
    """
    texto = str(interfaz or "")
    numero = re.match(r"^ether(\d+)$", texto) or re.match(r"^eth(\d+)$", texto)
    if not numero:
        return None
    return int(numero.group(1)) - 1 if texto.startswith("ether") else int(numero.group(1))


def _bridge_de_interfaz(guest, interfaz):
    """Sobre qué bridge del lab está esa interfaz, o None si esa interfaz no existe.

    Sirve para un invitado que declara TODAS sus interfaces (`bridges:`), que es un
    RouterOS o una VM. NO sirve para el bastión: sus interfaces extra
    (`addresses`) no están en `bridges:` porque una por cada bridge del lab se las
    pone el motor. Para ésas está `_bridge_de`, que va por la RED de la dirección.
    """
    indice = _indice_de_interfaz(interfaz)
    interfaces = interfaces_declaradas(guest)
    if indice is None or not (0 <= indice < len(interfaces)):
        return None
    return interfaces[indice]


def _misma_red(una, otra, prefijo):
    """¿Están las dos direcciones en la misma red de `prefijo` bits?

    Se comparan los octetos que cubre el prefijo, como texto: se lee de un vistazo y
    no hace falta aritmética de bits. Con un prefijo que no cae en un octeto no se
    opina (devolver un "no" falso sería peor que no decir nada).
    """
    octetos = prefijo // 8
    if prefijo % 8 or not 1 <= octetos <= 4:
        return False
    return ".".join(_direccion_sin_mascara(una).split(".")[:octetos]) == ".".join(
        _direccion_sin_mascara(otra).split(".")[:octetos]
    )


def _redes_de_los_bridges(declaracion):
    """[(nombre, direccion-con-mascara)]: la RED de cada bridge es su identidad.

    Un bridge del lab se declara con su dirección (`192.0.2.1/24`) y esa dirección es
    la vía de acceso de su red; por eso es también lo que dice sobre qué bridge cae una
    dirección cualquiera del lab.
    """
    return [
        (bridge["nombre"], str(bridge["address"]))
        for bridge in (declaracion.get("lab") or {}).get("bridges") or []
        if isinstance(bridge, dict) and bridge.get("nombre") and bridge.get("address")
    ]


def _bridge_de(valor, redes):
    """El bridge del lab cuya red contiene esa dirección, o None.

    `redes` sale de `_redes_de_los_bridges`. Es la forma de saber el bridge de una
    dirección declarada SIN depender de qué interfaz la lleva: el bastión
    declara `eth1` pero no declara sobre qué bridge está (una por cada bridge del lab
    se la pone el motor),
    y su dirección sí lo dice.
    """
    for nombre, direccion_bridge in redes:
        base, _, prefijo = direccion_bridge.partition("/")
        if prefijo.isdigit() and _misma_red(valor, base, int(prefijo)):
            return nombre
    return None


def _guests(declaracion):
    """(seccion, indice, rol, tipo, invitado), en orden de declaración."""
    salida = []
    for seccion, tipo in (("vms", "qemu"), ("containers", "lxc")):
        for indice, guest in enumerate(declaracion.get(seccion) or []):
            if isinstance(guest, dict):
                salida.append((seccion, indice, guest.get("rol"), tipo, guest))
    return salida


def _servidores_dhcp(declaracion):
    """Quién da direcciones, en qué bridge y desde qué etapa.

    Los dos vocabularios: un bastión Linux (`dhcp_server`) y un
    RouterOS (`dhcp`). Sin esto no se puede saber si un invitado con `address:
    dhcp` tiene quien le conteste, ni si arranca antes de que le contesten.

    El bridge se saca de la RED que el servidor reparte (el rango, o la red que
    anuncia), que es lo que de verdad dice sobre qué red está sirviendo; la interfaz
    queda como segunda vía, porque un RouterOS sí declara todas sus interfaces.
    """
    redes = _redes_de_los_bridges(declaracion)
    servidores = []
    for seccion, indice, rol, _tipo, guest in _guests(declaracion):
        config = guest.get("config") or {}
        linux = (config.get("linux") or {}).get("dhcp_server")
        if isinstance(linux, dict) and linux.get("interface"):
            rango = str(linux.get("rango") or "")
            principio = rango.partition("-")[0] if rango else ""
            servidores.append({
                "rol": rol,
                "stage": guest.get("stage"),
                "bridge": (
                    _bridge_de(principio, redes)
                    or _bridge_de_interfaz(guest, linux["interface"])
                ),
                "rango": rango,
                "donde": f"`{seccion}[{indice}]` ({rol})",
            })
        for i, servidor in enumerate((config.get("routeros") or {}).get("dhcp_server") or []):
            if not isinstance(servidor, dict) or not servidor.get("interface"):
                continue
            rango = str((servidor.get("pool") or {}).get("rango") or "")
            principio = rango.partition("-")[0] if rango else ""
            servidores.append({
                "rol": rol,
                "stage": guest.get("stage"),
                "bridge": (
                    _bridge_de((servidor.get("network") or {}).get("address") or principio, redes)
                    or _bridge_de_interfaz(guest, servidor["interface"])
                ),
                "rango": rango,
                "donde": f"`{seccion}[{indice}]`.config.routeros.dhcp[{i}] ({rol})",
            })
    return servidores


def _direcciones_estaticas(declaracion):
    """Las direcciones que el lab FIJA, con el bridge sobre el que las fija.

    Incluye las de los bridges: la dirección de un bridge es la vía de acceso de los
    invitados que cuelgan de él, y por eso cuenta como "alguien del lab" cuando se
    mira si una pasarela existe. El bridge de cada dirección se deduce de su RED
    (una dirección dice a qué red pertenece), no de la interfaz que la lleva.
    """
    redes = _redes_de_los_bridges(declaracion)
    estaticas = []
    for indice, bridge in enumerate((declaracion.get("lab") or {}).get("bridges") or []):
        if isinstance(bridge, dict) and bridge.get("address"):
            estaticas.append({
                "rol": None,
                "bridge": bridge.get("nombre"),
                "address": str(bridge["address"]),
                "donde": f"`lab.bridges[{indice}]`",
            })
    for seccion, indice, rol, _tipo, guest in _guests(declaracion):
        direccion = guest.get("address")
        if direccion not in (None, "") and str(direccion) != "dhcp":
            estaticas.append({
                "rol": rol,
                "bridge": (
                    _bridge_de(direccion, redes)
                    or _bridge_de_interfaz(
                        guest, "eth0" if guest.get("bridge") else "ether1"
                    )
                ),
                "address": str(direccion),
                "donde": f"`{seccion}[{indice}]` ({rol})",
            })
        config = guest.get("config") or {}
        for vocabulario, clave in (("routeros", "addresses"), ("linux", "addresses")):
            for i, interface in enumerate((config.get(vocabulario) or {}).get(clave) or []):
                if isinstance(interface, dict) and interface.get("address"):
                    estaticas.append({
                        "rol": rol,
                        "bridge": (
                            _bridge_de(interface["address"], redes)
                            or _bridge_de_interfaz(guest, interface.get("interface"))
                        ),
                        "address": str(interface["address"]),
                        "donde": f"`{seccion}[{indice}]`.config.{vocabulario}.{clave}[{i}] ({rol})",
                    })
    return estaticas


def _pasarelas(declaracion):
    """Las pasarelas que el lab nombra: rutas y la que anuncia su DHCP."""
    salida = []
    for seccion, indice, rol, _tipo, guest in _guests(declaracion):
        routeros = (guest.get("config") or {}).get("routeros") or {}
        for i, ruta in enumerate(routeros.get("routes") or []):
            if isinstance(ruta, dict) and ruta.get("gateway"):
                salida.append({
                    "rol": rol,
                    "valor": str(ruta["gateway"]),
                    "donde": f"`{seccion}[{indice}]`.config.routeros.routes[{i}] ({rol})",
                })
        for i, servidor in enumerate(routeros.get("dhcp_server") or []):
            if not isinstance(servidor, dict):
                continue
            pasarela = (servidor.get("network") or {}).get("gateway")
            if pasarela:
                salida.append({
                    "rol": rol,
                    "valor": str(pasarela),
                    "donde": f"`{seccion}[{indice}]`.config.routeros.dhcp[{i}].network ({rol})",
                })
    return salida


def _ip_en_rango(direccion, rango):
    """¿Cae la dirección dentro del rango `inicio-fin`? Se comparan enteros.

    Comparar texto daría `192.0.2.9 > 192.0.2.50`, que es falso por la razón
    equivocada: aquí se comparan los octetos como números.
    """
    if "-" not in str(rango):
        return False
    inicio, _, fin = str(rango).partition("-")

    def entero(valor):
        trozos = _direccion_sin_mascara(valor).split(".")
        if len(trozos) != 4:
            return None
        try:
            return sum(int(t) << (8 * (3 - i)) for i, t in enumerate(trozos))
        except ValueError:
            return None

    extremo = entero(direccion)
    minimo, maximo = entero(inicio), entero(fin)
    if None in (extremo, minimo, maximo):
        return False
    return minimo <= extremo <= maximo


def declaracion_consejos(declaracion, carpeta=None):
    """Los consejos del estado deseado: legal, pero casi siempre un olvido.

    La declaración tiene que ser COHERENTE antes de pedir consejo (los consejos no
    sustituyen a los errores): si hay errores, esto devuelve lo que se pueda leer
    sin tropezar, y quien llama enseña primero los errores.
    """
    consejos = []
    if not isinstance(declaracion, dict) or not isinstance(declaracion.get("lab"), dict):
        return consejos
    # 6.1 · El IPAM primero, como en la validación: los consejos hablan de las
    # direcciones de verdad, no de la marca que las pide (ADR 0020).
    declaracion = declaracion_direcciones(declaracion)

    def aconsejar(codigo, donde, mensaje, remedio):
        consejos.append(
            {"codigo": codigo, "donde": donde, "mensaje": mensaje, "remedio": remedio}
        )

    guests = _guests(declaracion)
    servidores = _servidores_dhcp(declaracion)
    estaticas = _direcciones_estaticas(declaracion)
    address_space = _address_space_de(declaracion)
    bridges = [
        b["nombre"]
        for b in (declaracion["lab"].get("bridges") or [])
        if isinstance(b, dict) and b.get("nombre")
    ]
    # Quién cuelga de cada bridge: sirve para el bridge vacío y para saber sobre qué
    # red cae una dirección estática.
    por_bridge = {nombre: [] for nombre in bridges}
    for seccion, indice, rol, _tipo, guest in guests:
        for nombre in interfaces_declaradas(guest):
            por_bridge.setdefault(nombre, []).append(f"`{seccion}[{indice}]` ({rol})")

    # --- 1. la etapa: nadie arranca antes que quien le da la dirección -------
    for servidor in servidores:
        for seccion, indice, rol, tipo, guest in guests:
            if str(guest.get("address")) != "dhcp":
                continue
            if servidor["bridge"] not in interfaces_declaradas(guest):
                continue
            if tipo == "lxc" and modulo_interior.tiene_tunnel(guest):
                continue  # el bastión no se pide la dirección a sí mismo
            stage, del_servidor = guest.get("stage"), servidor["stage"]
            if not isinstance(stage, int) or not isinstance(del_servidor, int):
                continue
            if stage <= del_servidor:
                aconsejar(
                    "stages",
                    f"`{seccion}[{indice}]` ({rol})",
                    f"pide su dirección por DHCP en `{servidor['bridge']}`, donde se la da "
                    f"{servidor['donde']} (etapa {del_servidor}), y está en la etapa "
                    f"{stage}: arrancarían a la vez, y quién contesta primero es una "
                    "carrera, no un diseño",
                    f"pon a '{rol}' en una etapa POSTERIOR al {del_servidor} (regla 18: "
                    "nunca se arranca una etapa antes de que el anterior sirva)",
                )

    # --- 2. una dirección estática dentro del rango del DHCP ------------------
    for servidor in servidores:
        if not servidor["rango"]:
            continue
        for estatica in estaticas:
            if estatica["bridge"] != servidor["bridge"]:
                continue
            if _ip_en_rango(estatica["address"], servidor["rango"]):
                aconsejar(
                    "dhcp",
                    estatica["donde"],
                    f"fija {_direccion_sin_mascara(estatica['address'])} y esa dirección "
                    f"cae DENTRO del rango que reparte {servidor['donde']} "
                    f"({servidor['rango']}) en el mismo bridge: un cliente dinámico puede "
                    "pedirla antes y dejarla ocupada",
                    "saca la dirección del rango del pool (los estáticos van fuera), o "
                    "declara `static_leases: derived` para que el DHCP la respete",
                )

    # --- 3. una pasarela que no es nadie del lab ------------------------------
    if address_space:
        conocidas = {_direccion_sin_mascara(e["address"]) for e in estaticas}
        for pasarela in _pasarelas(declaracion):
            valor = pasarela["valor"]
            if valor in conocidas or not _ip_en_address_space(valor, address_space):
                continue
            aconsejar(
                "gateway",
                pasarela["donde"],
                f"usa {valor} como pasarela y esa dirección no es de nadie del lab, "
                f"aunque cae dentro de su espacio de direcciones ({address_space}): o es un número mal "
                "escrito, o falta el equipo que la tiene",
                "revisa el número, o declara el invitado (o el bridge) que tiene esa "
                "dirección",
            )

    # --- 4. una VM con configuración y sin imagen ------------------------------
    for seccion, indice, rol, tipo, guest in guests:
        if tipo == "qemu" and guest.get("config") and not guest.get("image"):
            aconsejar(
                "image",
                f"`{seccion}[{indice}]` ({rol})",
                "es una VM que declara `config` y no declara `image`: nacerá sin disco, "
                "así que no arrancará nada que configurar (y la imagen sólo se puede "
                "adjuntar AL CREAR: después habría que recrear la máquina)",
                "declara `image:` con la imagen de fábrica de ese invitado",
            )

    # --- 5. un bridge por el que no pasa nadie --------------------------------
    for nombre in bridges:
        if not por_bridge.get(nombre):
            aconsejar(
                "bridge-vacio",
                f"`lab.bridges` ('{nombre}')",
                "el lab declara ese bridge y no cuelga nadie de él: se creará en el "
                "nodo sin que nadie lo use",
                f"quítalo de `lab.bridges`, o cuelga de '{nombre}' el invitado que "
                "faltaba",
            )

    # --- 6. dos servidores DHCP en el mismo bridge ----------------------------
    por_bridge_servidores = {}
    for servidor in servidores:
        if servidor["bridge"]:
            por_bridge_servidores.setdefault(servidor["bridge"], []).append(servidor)
    for bridge, suyos in por_bridge_servidores.items():
        if len(suyos) > 1:
            quienes = ", ".join(s["donde"] for s in suyos)
            aconsejar(
                "dos-dhcp",
                f"`lab.bridges` ('{bridge}')",
                f"hay más de un servidor DHCP en el mismo bridge ({quienes}): los dos "
                "reparten en la misma red y quién contesta primero es una carrera",
                "deja un solo servidor DHCP por bridge (o separa las redes)",
            )

    # --- 7. una dirección dinámica donde no hay quien la dé --------------------
    servidos = {s["bridge"] for s in servidores if s["bridge"]}
    for seccion, indice, rol, tipo, guest in guests:
        if str(guest.get("address")) != "dhcp":
            continue
        if tipo == "lxc" and modulo_interior.tiene_tunnel(guest):
            continue
        for nombre in interfaces_declaradas(guest):
            if nombre in bridges and nombre not in servidos:
                aconsejar(
                    "sin-quien-la-dirija",
                    f"`{seccion}[{indice}]` ({rol})",
                    f"pide su dirección por DHCP en `{nombre}`, que es un bridge DEL LAB, "
                    "y no hay ningún servidor DHCP declarado que sirva en él: nadie le "
                    "va a contestar",
                    f"declara un servidor DHCP en '{nombre}' (el router de esa red o el "
                    "bastión), o dale una dirección estática",
                )

    # --- 8. la salida del lab, pero sin quién resuelva nombres ----------------
    # Un router con `uplink` da SALIDA a internet. Pero un invitado que lo tiene de
    # pasarela pregunta por NOMBRES a quien le dio la dirección -- el servidor DHCP de su
    # red --, y si ese servidor no anuncia DNS el lab sale a internet y no resuelve nada.
    # Es el fallo que más veces se lee como "no tiene salida", y no lo es.
    salidas = []
    anuncian_dns = []
    for seccion, indice, rol, _tipo, guest in guests:
        config = guest.get("config") or {}
        routeros = config.get("routeros") or {}
        if "uplink" in routeros:
            salidas.append(f"`{seccion}[{indice}]` ({rol})")
            # Y una ruta por defecto declarada en el que es la salida es una de dos: su
            # cliente de fuera ya le enseña una (la aprende por DHCP), así que las dos
            # compiten por el mismo destino -- y la declarada obliga al lab a saber la
            # pasarela de FUERA, que es justo lo que `uplink` evita tener que saber.
            por_defecto = [
                ruta
                for ruta in routeros.get("routes") or []
                if isinstance(ruta, dict) and str(ruta.get("dst_address")) in ("0.0.0.0/0", "::/0")
            ]
            if por_defecto:
                aconsejar(
                    "uplink-con-ruta",
                    f"`{seccion}[{indice}]`.config.routeros.routes ({rol})",
                    "este router es la salida del lab y además le declaras una ruta por "
                    "defecto: la que pone el motor por la pasarela de fuera y la tuya compiten "
                    "por el mismo destino",
                    "quita la ruta por defecto declarada: la salida la pone el motor por la "
                    "vía de acceso de fuera, y así el lab no necesita saber la pasarela de la red de "
                    "casa",
                )
        for servidor in (config.get("routeros") or {}).get("dhcp_server") or []:
            if isinstance(servidor, dict) and (servidor.get("network") or {}).get("dns"):
                anuncian_dns.append(f"`{seccion}[{indice}]`.config.routeros.dhcp ({rol})")
        servidor_linux = (config.get("linux") or {}).get("dhcp_server")
        if isinstance(servidor_linux, dict) and (servidor_linux.get("network") or {}).get("dns"):
            anuncian_dns.append(
                f"`{seccion}[{indice}]`.config.linux.dhcp_server ({rol})"
            )
    if salidas and not anuncian_dns:
        aconsejar(
            "uplink-sin-dns",
            ", ".join(salidas),
            "este router es la salida del lab, y ningún servidor DHCP del lab anuncia DNS: "
            "los invitados que salgan por él tendrán salida y no resolverán ningún nombre "
            "(ni `apt`, ni `ping`, ni nada que se llame en vez de numerarse)",
            "añade `red: {…, dns: [<la dirección del router de esa red>]}` al servidor DHCP "
            "de la red por la que salen",
        )

    return consejos


def declaracion_normalizar(declaracion, carpeta=None):
    """Devuelve la declaración normalizada, o falla con TODAS las incoherencias.

    Normalizar = una sola forma de leerla, para que nadie tenga que repetir el
    render en cada sitio: una lista de invitados en orden de arranque, con su tipo
    resuelto (`qemu`/`lxc`) y sus campos obligatorios.
    """
    errores = declaracion_validar(declaracion, carpeta=carpeta)
    if errores:
        raise ErrorMotor(
            "la declaración del lab es incoherente:\n  - " + "\n  - ".join(errores)
        )

    # 6.1 · El IPAM, igual que en la validación (ADR 0020): lo que se normaliza son
    # direcciones de verdad, y todo lo que venga detrás -- el plan, los drivers, los
    # checks -- no tiene por qué saber que la marca `derived` existe.
    declaracion = declaracion_direcciones(declaracion)

    lab = declaracion["lab"]
    guests = []
    for seccion, tipo in (("vms", "qemu"), ("containers", "lxc")):
        for guest in declaracion.get(seccion, []) or []:
            guests.append(
                {
                    "rol": guest["rol"],
                    "tipo": tipo,
                    # El nombre se deriva de estas dos (ADR 0015): `equipo` es el `tipo:` que
                    # declara el lab (rt/srv/ws/sw/ctl) y `alias`, su `nombre:` corto. Aquí se
                    # llaman así para no confundirlos con `tipo` -- que en esta normalización
                    # es la VIRTUALIZACIÓN (`qemu`/`lxc`) -- ni con `nombre`, que es el nombre
                    # ya derivado que cuelga de la identidad.
                    "equipo": guest.get("tipo"),
                    # El alias llega como texto (`nombre: srv`) o como número (`nombre: 1`):
                    # la declaración admite las dos formas, y aquí se unifican.
                    "alias": (
                        None if guest.get("nombre") is None else str(guest["nombre"])
                    ),
                    "stage": guest["stage"],
                    "cores": guest["cores"],
                    "memory": guest["memory"],
                    "disk": guest["disk"],
                    # Las interfaces declaradas, EN ORDEN: `bridges:` (varias) o `bridge:`
                    # (una). `bridge` se mantiene (la primera) porque el resto del motor
                    # lee ese campo desde la fase 1.
                    "bridges": interfaces_declaradas(guest),
                    "bridge": (guest.get("bridge") or interfaces_declaradas(guest)[0]),
                    # `address` puede NO estar declarada (equipo sin dirección: un
                    # conmutador puro). Se normaliza a None para que nadie tenga que
                    # distinguir "no está la clave" de "está vacía". Y puede ser `dhcp`:
                    # una ESTACIÓN, que al conectar pide dirección -- como una máquina
                    # de verdad. `gateway` es SU vía de acceso, y sólo se declara cuando la
                    # dirección es fija (un SERVIDOR real la lleva puesta a mano): el
                    # motor no la adivina ni la reparte.
                    "address": guest.get("address") or None,
                    "gateway": guest.get("gateway") or None,
                    # El interior se copia TAL CUAL: el vocabulario ya está validado, y
                    # normalizarlo aquí sería una segunda traducción que podría
                    # discrepar de la del driver.
                    "config": guest.get("config") or None,
                    "image": guest.get("image") or None,
                }
            )

    # Orden de arranque: por etapa, y dentro de la etapa, estable por rol.
    # Es el orden que seguirá el plan; tenerlo aquí evita que cada verbo lo
    # invente por su cuenta.
    guests.sort(key=lambda i: (i["stage"], i["rol"]))

    return {
        "lab": lab["nombre"],
        "stages": sorted(set(lab["stages"])),
        "bridges": [
            {"nombre": b["nombre"], "address": b.get("address")} for b in lab["bridges"]
        ],
        "guests": guests,
        # La espacio de direcciones es opcional (un lab de la fase 1 no la declara) y el túnel
        # también: sin ellos, el plan sale exactamente como salía antes de la fase 2.
        "address_space": lab.get("address_space") or None,
        "tunnel": lab.get("tunnel") or None,
        # 6.2 / 6.4 · Las PRUEBAS y los EXPERIMENTOS del lab (ADR 0022 y 0023). No son
        # estado del mundo, pero el verbo que los ejecuta recibe la declaración
        # NORMALIZADA: si no viajan hasta aquí, el verbo no encuentra nada que lanzar.
        "tests": declaracion.get("tests") or [],
        "capture": declaracion.get("capture") or None,
        "impairment": declaracion.get("impairment") or None,
    }


class FilterModule:
    """Registro de filtros que Ansible ve como `| declaracion_normalizar`."""

    def filters(self):
        return {
            "declaracion_validar": declaracion_validar,
            "declaracion_normalizar": declaracion_normalizar,
            "declaracion_address_space": declaracion_address_space,
            "declaracion_consejos": declaracion_consejos,
            "declaracion_direcciones": declaracion_direcciones,
        }
