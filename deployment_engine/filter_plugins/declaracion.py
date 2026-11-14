# PROPÓSITO:   normaliza y valida la declaración de un lab. Es lo que Ansible
#              calcula en Jinja para saber si el estado deseado es coherente
#              ANTES de tocar la API.
# INVARIANTES: el lab declara roles y topología; NUNCA declara vmid ni MAC
#              (regla 4.8) -- si aparecen en la declaración, esto es un error.
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
#              pueda alcanzar tampoco: eso necesita el camino en pie, y se dice al
#              aplicar.
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

import interior as modulo_interior  # noqa: E402  (la ruta se ajusta justo arriba)

# Los dos tipos de invitado que el motor sabe desplegar, tal como los nombra la
# API de Proxmox en sus rutas.
TIPOS = ("qemu", "lxc")

# Claves que el motor DERIVA y por tanto están PROHIBIDAS en la declaración. Si
# aparecen, alguien ha intentado fijar a mano lo que es del motor, y eso es el
# origen de los conflictos entre labs.
CLAVES_DERIVADAS = ("vmid", "mac", "nombre", "name", "pool")

# Campos obligatorios de cada invitado declarado, y su tipo esperado. `direccion`
# NO está aquí a propósito: desde la fase 2 admite tres formas (estática, `dhcp` y
# AUSENTE, para un equipo sin dirección como un conmutador puro), así que se valida
# aparte y con más cuidado.
CAMPOS_INVITADO = {
    "rol": str,
    "escalon": int,
    "cores": int,
    "memoria": int,
    "disco": int,
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

# El área `camino` no declara credenciales ni direcciones de casa: eso es entorno
# (secrets.yml). Lo único que puede traer son los dos valores que un lab de verdad
# puede necesitar distintos: qué host y qué puerto, y son OPCIONALES.
CLAVES_CAMINO = ("salida", "host", "puerto")


def patas_declaradas(invitado):
    """Los bridges del invitado, EN ORDEN: `bridges:` (varias) o `bridge:` (una).

    El orden es el de las interfaces: la primera pata es `eth0` (en RouterOS, `ether1`),
    la segunda `eth1`/`ether2`, y así. Un invitado de una sola pata puede seguir
    declarando `bridge:` (todo lo de la fase 1 sigue igual); uno que sirve varias redes
    declara `bridges: [...]` porque sus interfaces se nombran en la declaración.
    """
    if isinstance(invitado.get("bridges"), list) and invitado["bridges"]:
        return [str(nombre) for nombre in invitado["bridges"]]
    if invitado.get("bridge"):
        return [str(invitado["bridge"])]
    return []


def _direccion_valida(direccion):
    """¿Es una de las tres formas que admite `direccion:`?"""
    texto = str(direccion)
    if texto == "dhcp":
        return True
    if not IP_PATRON.match(texto):
        return False
    if "/" not in texto:
        return False
    octetos = [int(o) for o in texto.split("/")[0].split(".")]
    prefijo = int(texto.split("/")[1])
    return all(0 <= o <= 255 for o in octetos) and 0 <= prefijo <= 32


def _ip_en_supernet(ip, supernet):
    """¿Cae `ip` (con o sin máscara) dentro de la supernet declarada?

    Se comparan los PREFIJOS enteros, octeto a octeto: 10.40.1.5/24 está en
    10.40.0.0/16 porque los 16 primeros bits coinciden. No se hace aritmética de red
    más fina que esa: con IPv4 y prefijos de laboratorio sobra, y un cálculo
    complicado aquí sería otra cosa que puede estar mal sin que nadie lo note.
    """
    base, _, prefijo = str(supernet).partition("/")
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


def _validar_interior(invitado, etiqueta, rol, errores):
    """Valida el vocabulario de `config:` con las reglas del §6 del encargo."""
    config = invitado.get("config")
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

    # Las interfaces que el interior nombra TIENEN que existir en el invitado. Un CHR que
    # declara configurar `ether2` necesita dos patas, y sin la segunda RouterOS contesta
    # `400 input does not match any value of interface` A MITAD de la convergencia (medido:
    # con el intercambio de la dirección de gestión ya mandado y el equipo a medias).
    # Aquí se ve antes de tocar nada.
    patas = patas_declaradas(invitado)
    for area, datos in declarado.items():
        entradas = datos if isinstance(datos, list) else ([datos] if isinstance(datos, dict) else [])
        for entrada in entradas:
            if not isinstance(entrada, dict):
                continue
            numero = re.match(r"^eth(?:er)?(\d+)$", str(entrada.get("interfaz") or ""))
            if numero and int(numero.group(1)) > len(patas):
                errores.append(
                    f"`{etiqueta}` ({rol}) declara configurar `{entrada['interfaz']}` en "
                    f"'{area}', pero el invitado sólo tiene {len(patas)} pata(s) "
                    f"({', '.join(patas) or 'ninguna'}): añade a `bridges` los bridges que "
                    "falten, en orden (las patas se deciden al crear y no se cambian en "
                    "caliente)"
                )

    # Y la dirección: un invitado con config tiene que ser alcanzable.
    direccion = invitado.get("direccion")
    if direccion in (None, ""):
        errores.append(
            f"`{etiqueta}` ({rol}) declara `config.` pero no declara `direccion`: un "
            "equipo que no se puede alcanzar no se puede converger (un conmutador "
            "puro no lleva `config`)"
        )

    if tipo == "routeros":
        _validar_routeros(declarado, etiqueta, rol, errores)
    else:
        _validar_linux(declarado, etiqueta, rol, errores)


def _validar_routeros(declarado, etiqueta, rol, errores):
    """Las formas del vocabulario de RouterOS, una a una."""
    identidad = declarado.get("identidad")
    if identidad is not None and (not isinstance(identidad, str) or not identidad.strip()):
        errores.append(f"`{etiqueta}` ({rol}): `identidad` tiene que ser texto no vacío")

    servicios = declarado.get("servicios")
    if servicios is not None:
        if not isinstance(servicios, dict) or set(servicios) - {"deshabilitar", "habilitar"}:
            errores.append(
                f"`{etiqueta}` ({rol}): `servicios` sólo admite `deshabilitar` (una lista)"
            )
        else:
            for servicio in servicios.get("deshabilitar") or []:
                if str(servicio) in modulo_interior.SERVICIOS_NUNCA_DESHABILITADOS:
                    errores.append(
                        f"`{etiqueta}` ({rol}): `servicios.deshabilitar` incluye "
                        f"'{servicio}', que es donde vive REST: es el camino de vuelta "
                        "y deshabilitarlo deja el equipo sin forma de ser configurado"
                    )
                elif str(servicio) not in modulo_interior.SERVICIOS_GESTIONADOS:
                    errores.append(
                        f"`{etiqueta}` ({rol}): el servicio '{servicio}' no está en el "
                        "alcance del área `servicios` "
                        f"({', '.join(modulo_interior.SERVICIOS_GESTIONADOS)})"
                    )

    cliente = declarado.get("cliente_dhcp")
    if cliente is not None and (
        not isinstance(cliente, dict) or not isinstance(cliente.get("deshabilitar"), bool)
    ):
        errores.append(f"`{etiqueta}` ({rol}): `cliente_dhcp` se declara `{{deshabilitar: true|false}}`")

    for indice, direccion in enumerate(declarado.get("direcciones") or []):
        if not isinstance(direccion, dict) or not direccion.get("interfaz"):
            errores.append(f"`{etiqueta}` ({rol}): `direcciones[{indice}]` necesita `interfaz` y `direccion`")
            continue
        if not _direccion_valida(direccion.get("direccion")):
            errores.append(
                f"`{etiqueta}` ({rol}): `direcciones[{indice}]` tiene una dirección que no "
                f"es IPv4 con máscara: {direccion.get('direccion')!r}"
            )

    for indice, ruta in enumerate(declarado.get("rutas") or []):
        if not isinstance(ruta, dict) or not ruta.get("destino") or not ruta.get("pasarela"):
            errores.append(f"`{etiqueta}` ({rol}): `rutas[{indice}]` necesita `destino` y `pasarela`")

    for indice, servidor in enumerate(declarado.get("dhcp") or []):
        if not isinstance(servidor, dict) or not servidor.get("interfaz"):
            errores.append(f"`{etiqueta}` ({rol}): `dhcp[{indice}]` necesita `interfaz`")
            continue
        reservas = servidor.get("reservas")
        if isinstance(reservas, str) and reservas != "derivadas":
            errores.append(
                f"`{etiqueta}` ({rol}): `dhcp[{indice}].reservas` sólo admite "
                "`derivadas` o una lista de `{rol, direccion}` (nunca con MAC)"
            )
        elif isinstance(reservas, list):
            for reserva in reservas:
                if not isinstance(reserva, dict) or set(reserva) - {"rol", "direccion"}:
                    errores.append(
                        f"`{etiqueta}` ({rol}): una reserva es `{{rol, direccion}}` y "
                        "nunca lleva MAC: la MAC se deriva del vmid (regla 14)"
                    )


def _validar_linux(declarado, etiqueta, rol, errores):
    """Las formas del vocabulario de Linux, una a una."""
    camino = declarado.get(modulo_interior.CLAVE_CAMINO)
    if camino is not None:
        if not isinstance(camino, dict):
            errores.append(f"`{etiqueta}` ({rol}): `camino` tiene que ser un mapa")
        else:
            for clave in camino:
                if clave not in CLAVES_CAMINO:
                    errores.append(
                        f"`{etiqueta}` ({rol}): `camino.{clave}` no existe: un puesto de "
                        "control declara sólo por dónde sale "
                        f"({', '.join(CLAVES_CAMINO)}), y el resto es "
                        "entorno (secrets.yml), no lab"
                    )
    if "reenvio" in declarado and not isinstance(declarado["reenvio"], bool):
        errores.append(f"`{etiqueta}` ({rol}): `reenvio` tiene que ser true o false")
    # `direcciones` (Linux): las patas EXTRA del invitado, una por bridge del lab. Se
    # declaran una a una porque el motor no adivina direcciones (regla 11) y porque un
    # puesto de control sin dirección en un bridge no puede llegar a lo que cuelga de él.
    if "direcciones" in declarado:
        patas = declarado["direcciones"]
        if not isinstance(patas, list) or not patas:
            errores.append(
                f"`{etiqueta}` ({rol}): `direcciones` tiene que ser una lista de "
                "`{interfaz, direccion}`"
            )
        else:
            for pata in patas:
                if not isinstance(pata, dict) or not pata.get("interfaz") or not pata.get("direccion"):
                    errores.append(
                        f"`{etiqueta}` ({rol}): cada entrada de `direcciones` necesita "
                        "`interfaz` y `direccion`"
                    )
    servidor = declarado.get("dhcp_servidor")
    if servidor is not None:
        if not isinstance(servidor, dict) or not servidor.get("interfaz"):
            errores.append(f"`{etiqueta}` ({rol}): `dhcp_servidor` necesita `interfaz` y `rango`")
        else:
            if not servidor.get("rango") or "-" not in str(servidor.get("rango")):
                errores.append(
                    f"`{etiqueta}` ({rol}): `dhcp_servidor.rango` tiene que ser un rango "
                    "`inicio-fin` (p. ej. 10.40.0.50-10.40.0.99)"
                )
            reservas = servidor.get("reservas")
            if reservas is not None and reservas != "derivadas" and not isinstance(reservas, list):
                errores.append(
                    f"`{etiqueta}` ({rol}): `dhcp_servidor.reservas` sólo admite "
                    "`derivadas` o una lista de `{rol, direccion}`"
                )


def _supernet_de(declaracion):
    """La supernet declarada por el lab, o None. Es opcional: un lab de la fase 1 no
    la declara y no se le exige."""
    valor = (declaracion.get("lab") or {}).get("supernet")
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
                "declara `reservas: derivadas` o `{rol, direccion}`, nunca la MAC."
            )
        elif CLAVE_EN_TEXTO.search(valor):
            errores.append(
                f"`{ruta}` parece una CLAVE (o un certificado): las claves del motor son "
                "suyas y viven fuera del repo (regla 3); el lab no declara ninguna. "
                "La clave del camino la genera el motor y la deja él mismo dentro del "
                "puesto de control."
            )


def _direcciones_declaradas(declaracion):
    """Todas las direcciones y rangos que un lab declara, para vigilar la supernet.

    Devuelve (ruta, texto). Se incluyen los bridges del lab (su dirección es la
    puerta de los invitados de ese bridge), las direcciones de los invitados y las
    que el interior declara por dentro (direcciones de un RouterOS, pools, redes y
    rangos del DHCP).
    """
    salida = []
    for indice, bridge in enumerate((declaracion.get("lab") or {}).get("bridges") or []):
        if bridge.get("direccion"):
            salida.append((f"lab.bridges[{indice}].direccion", bridge["direccion"]))
    for seccion in ("vms", "containers"):
        for indice, invitado in enumerate(declaracion.get(seccion) or []):
            etiqueta = f"{seccion}[{indice}]"
            direccion = invitado.get("direccion")
            if direccion and str(direccion) != "dhcp":
                salida.append((f"{etiqueta}.direccion", direccion))
            config = (invitado.get("config") or {}).get("routeros") or {}
            for i, item in enumerate(config.get("direcciones") or []):
                if item.get("direccion"):
                    salida.append((f"{etiqueta}.config.routeros.direcciones[{i}]", item["direccion"]))
            for i, servidor in enumerate(config.get("dhcp") or []):
                if (servidor.get("pool") or {}).get("rango"):
                    rango = str(servidor["pool"]["rango"])
                    for trozo in rango.split("-"):
                        salida.append((f"{etiqueta}.config.routeros.dhcp[{i}].pool", trozo))
                if (servidor.get("red") or {}).get("prefijo"):
                    salida.append(
                        (f"{etiqueta}.config.routeros.dhcp[{i}].red", servidor["red"]["prefijo"])
                    )
                for i_r, reserva in enumerate(servidor.get("reservas") or []):
                    if isinstance(reserva, dict) and reserva.get("direccion"):
                        salida.append(
                            (f"{etiqueta}.config.routeros.dhcp[{i}].reservas[{i_r}]", reserva["direccion"])
                        )
                if servidor.get("red", {}).get("pasarela"):
                    salida.append(
                        (f"{etiqueta}.config.routeros.dhcp[{i}].red.pasarela", servidor["red"]["pasarela"])
                    )
            for ruta, item in enumerate(config.get("rutas") or []):
                if item.get("pasarela"):
                    salida.append((f"{etiqueta}.config.routeros.rutas[{ruta}].pasarela", item["pasarela"]))
            linux = (invitado.get("config") or {}).get("linux") or {}
            servidor_dhcp = linux.get("dhcp_servidor") or {}
            if servidor_dhcp.get("rango"):
                for trozo in str(servidor_dhcp["rango"]).split("-"):
                    salida.append((f"{etiqueta}.config.linux.dhcp_servidor.rango", trozo))
    return salida


def declaracion_supernet(declaracion):
    """La supernet declarada, o None. Lo usa `./lab check supernet`."""
    return _supernet_de(declaracion)


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
        return ["falta la sección `lab` (nombre, bridges, escalones)"]

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

    # --- escalones de arranque --------------------------------------------
    escalones = lab.get("escalones")
    if not isinstance(escalones, list) or not escalones:
        errores.append("`lab.escalones` falta o está vacío (el orden de arranque es parte de la topología)")
        escalones = []
    for escalon in escalones:
        if not isinstance(escalon, int) or escalon < 1:
            errores.append(f"escalón inválido {escalon!r}: tienen que ser enteros >= 1")

    # --- lo que no se declara nunca, también fuera de los invitados ---------
    # La sección `lab` no es un rincón libre: una MAC o una clave escondida ahí sigue
    # siendo algo que una declaración no lleva (las claves del motor son suyas y viven
    # fuera del repo). Se busca en TODA la sección, no sólo en las claves conocidas.
    _buscar_prohibidos(lab, "lab", errores)

    # --- invitados ---------------------------------------------------------
    invitados = []
    for seccion, tipo in (("vms", "qemu"), ("containers", "lxc")):
        lista = declaracion.get(seccion, [])
        if lista is None:
            lista = []
        if not isinstance(lista, list):
            errores.append(f"`{seccion}` no es una lista")
            continue
        for indice, invitado in enumerate(lista):
            if not isinstance(invitado, dict):
                errores.append(f"`{seccion}[{indice}]` no es un mapa")
                continue
            invitados.append((f"{seccion}[{indice}]", tipo, invitado))

    roles = []
    direcciones = []
    escalones_usados = []
    puestos_control = []
    for etiqueta, tipo, invitado in invitados:
        rol = invitado.get("rol")
        if not isinstance(rol, str) or not rol.strip():
            errores.append(f"`{etiqueta}` no tiene `rol`")
            continue
        roles.append(rol)

        # Lo que el motor deriva, prohibido en la declaración.
        for clave in CLAVES_DERIVADAS:
            if clave in invitado:
                errores.append(
                    f"`{etiqueta}` ({rol}) declara `{clave}`: eso lo deriva el motor "
                    "de la identidad (regla 4.8). Quítalo de la declaración."
                )

        # Un invitado de VARIAS patas declara `bridges:` (la lista) en vez de `bridge:`.
        # Las dos formas dicen lo mismo; la lista es la que deja nombrar `ether2`, etc.
        tiene_patas = isinstance(invitado.get("bridges"), list) and bool(invitado["bridges"])
        for campo, esperado in CAMPOS_INVITADO.items():
            if campo not in invitado:
                if campo == "bridge" and tiene_patas:
                    continue
                errores.append(f"`{etiqueta}` ({rol}) no declara `{campo}`")
                continue
            valor = invitado[campo]
            if esperado is int:
                if not isinstance(valor, int) or isinstance(valor, bool) or valor <= 0:
                    errores.append(f"`{etiqueta}` ({rol}): `{campo}` tiene que ser un entero > 0 (es {valor!r})")
            elif not isinstance(valor, str) or not valor.strip():
                errores.append(f"`{etiqueta}` ({rol}): `{campo}` tiene que ser texto no vacío")

        if tiene_patas:
            if len(set(invitado["bridges"])) != len(invitado["bridges"]):
                errores.append(f"`{etiqueta}` ({rol}): `bridges` repite un bridge")
            for nombre in invitado["bridges"]:
                if not isinstance(nombre, str) or nombre not in nombres_bridge:
                    errores.append(
                        f"`{etiqueta}` ({rol}) usa el bridge '{nombre}', "
                        "que el lab no declara en `lab.bridges`"
                    )
        elif invitado.get("bridge") and invitado["bridge"] not in nombres_bridge:
            errores.append(
                f"`{etiqueta}` ({rol}) usa el bridge '{invitado['bridge']}', "
                "que el lab no declara en `lab.bridges`"
            )
        if invitado.get("escalon") is not None and invitado["escalon"] not in escalones:
            errores.append(
                f"`{etiqueta}` ({rol}) está en el escalón {invitado['escalon']}, "
                "que no aparece en `lab.escalones`"
            )
        if isinstance(invitado.get("escalon"), int):
            escalones_usados.append(invitado["escalon"])

        # --- la dirección: tres formas, y la de en medio es `dhcp` -------------
        direccion = invitado.get("direccion")
        if direccion not in (None, ""):
            if not _direccion_valida(direccion):
                errores.append(
                    f"`{etiqueta}` ({rol}): `direccion` admite tres formas -- `<ip>/<prefijo>` "
                    f"(estática), `dhcp` (dinámica) y ausente (equipo sin dirección) -- y "
                    f"esto no es ninguna: {direccion!r}"
                )
            elif str(direccion) != "dhcp":
                direcciones.append((rol, _direccion_sin_mascara(direccion)))

        # --- la imagen: sólo para una VM, y es lo que la hace arrancar ---------
        imagen = invitado.get("imagen")
        if imagen is not None:
            if tipo != "qemu":
                errores.append(
                    f"`{etiqueta}` ({rol}) declara `imagen` y es un contenedor: una imagen "
                    "de fábrica es el disco de una VM (se importa AL CREAR, §9.3)"
                )
            elif not isinstance(imagen, str) or not imagen.strip():
                errores.append(f"`{etiqueta}` ({rol}): `imagen` tiene que ser texto no vacío")

        # --- lo que no se declara nunca: MACs y credenciales -------------------
        _buscar_prohibidos(invitado, f"{etiqueta}", errores)
        # --- el vocabulario del interior (cerrado) ----------------------------
        _validar_interior(invitado, etiqueta, rol, errores)
        if modulo_interior.tiene_camino(invitado):
            puestos_control.append(rol)

    repetidos = {r for r in roles if roles.count(r) > 1}
    if repetidos:
        errores.append(
            f"roles repetidos: {sorted(repetidos)}. Un rol identifica a un invitado "
            "y sólo a uno: el nombre canónico y la descripción se derivan de él."
        )

    # Un escalón declarado y vacío es una promesa que la declaración no cumple.
    for escalon in escalones:
        if isinstance(escalon, int) and escalon not in escalones_usados:
            errores.append(f"el escalón {escalon} está declarado pero ningún invitado lo usa")

    # Dos roles con la misma dirección chocan en la red del lab.
    vistas = {}
    for rol, direccion in direcciones:
        if direccion in vistas:
            errores.append(f"los roles '{vistas[direccion]}' y '{rol}' comparten la dirección {direccion}")
        else:
            vistas[direccion] = rol

    # --- el camino: uno, y sólo uno, y tiene que coincidir con `lab.camino` ----
    camino = (lab.get("camino") or {}).get("tipo")
    if camino is not None and camino != "puesto_control":
        errores.append(
            f"`lab.camino.tipo` es {camino!r}: el único camino que el motor sabe "
            "construir es `puesto_control` (§5). Otra cosa es otra fase, con su ADR."
        )
    if camino is not None and not puestos_control:
        errores.append(
            "`lab.camino` está declarado y ningún invitado declara "
            "`config.linux.camino`: el camino lo levanta un puesto de control, y sin "
            "él no hay por dónde entrar en el lab"
        )
    if camino is None and puestos_control:
        errores.append(
            f"el rol '{puestos_control[0]}' se declara puesto de control "
            "(`config.linux.camino`) pero el lab no declara `lab.camino`: decláralo, o "
            "quita el `camino` del invitado"
        )
    if len(puestos_control) > 1:
        errores.append(
            f"hay más de un puesto de control declarado ({sorted(puestos_control)}): "
            "el puerto del camino se deriva del vmid y dos puestos en el mismo lab se "
            "pisarían"
        )

    # --- la supernet: todo lo del lab vive dentro, y se puede comprobar --------
    supernet = _supernet_de(declaracion)
    if supernet == "":
        errores.append(
            f"`lab.supernet` ({lab.get('supernet')!r}) no es una red con máscara "
            "(p. ej. 10.40.0.0/16)"
        )
    elif supernet is not None:
        for ruta_declarada, valor in _direcciones_declaradas(declaracion):
            if not _ip_en_supernet(valor, supernet):
                errores.append(
                    f"`{ruta_declarada}` ({valor}) se sale de la supernet del lab "
                    f"({supernet}): todo lo del lab vive dentro, y hay un check que lo "
                    "vigila porque es lo que hace imposible que dos labs se pisen"
                )

    return errores


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

    lab = declaracion["lab"]
    invitados = []
    for seccion, tipo in (("vms", "qemu"), ("containers", "lxc")):
        for invitado in declaracion.get(seccion, []) or []:
            invitados.append(
                {
                    "rol": invitado["rol"],
                    "tipo": tipo,
                    "escalon": invitado["escalon"],
                    "cores": invitado["cores"],
                    "memoria": invitado["memoria"],
                    "disco": invitado["disco"],
                    # Las patas declaradas, EN ORDEN: `bridges:` (varias) o `bridge:`
                    # (una). `bridge` se mantiene (la primera) porque el resto del motor
                    # lee ese campo desde la fase 1.
                    "bridges": patas_declaradas(invitado),
                    "bridge": (invitado.get("bridge") or patas_declaradas(invitado)[0]),
                    # `direccion` puede NO estar declarada (equipo sin dirección: un
                    # conmutador puro). Se normaliza a None para que nadie tenga que
                    # distinguir "no está la clave" de "está vacía".
                    "direccion": invitado.get("direccion") or None,
                    # El interior se copia TAL CUAL: el vocabulario ya está validado, y
                    # normalizarlo aquí sería una segunda traducción que podría
                    # discrepar de la del driver.
                    "config": invitado.get("config") or None,
                    "imagen": invitado.get("imagen") or None,
                }
            )

    # Orden de arranque: por escalón, y dentro del escalón, estable por rol.
    # Es el orden que seguirá el plan; tenerlo aquí evita que cada verbo lo
    # invente por su cuenta.
    invitados.sort(key=lambda i: (i["escalon"], i["rol"]))

    return {
        "lab": lab["nombre"],
        "escalones": sorted(set(lab["escalones"])),
        "bridges": [
            {"nombre": b["nombre"], "direccion": b.get("direccion")} for b in lab["bridges"]
        ],
        "invitados": invitados,
        # La supernet es opcional (un lab de la fase 1 no la declara) y el camino
        # también: sin ellos, el plan sale exactamente como salía antes de la fase 2.
        "supernet": lab.get("supernet") or None,
        "camino": lab.get("camino") or None,
    }


class FilterModule:
    """Registro de filtros que Ansible ve como `| declaracion_normalizar`."""

    def filters(self):
        return {
            "declaracion_validar": declaracion_validar,
            "declaracion_normalizar": declaracion_normalizar,
            "declaracion_supernet": declaracion_supernet,
        }
