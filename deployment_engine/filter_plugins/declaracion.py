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
#              pueda alcanzar tampoco: eso necesita el camino en pie, y se dice al
#              aplicar.
#              Además de validar, ACONSEJA (`declaracion_consejos`): lo que es legal
#              pero casi siempre es un olvido (el escalón antes de quien da la
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

    # El área `exterior` no admite opciones: es una MARCA. La pata de fuera, su interfaz y su
    # dirección las deriva el motor (el plan tiende la pata, y el router pide dirección por
    # DHCP desde dentro), así que una opción aquí sería una invención del lab -- y este
    # vocabulario es cerrado (regla 15): se rechaza antes de tocar nada.
    exterior = declarado.get("exterior")
    if exterior not in (None, {}, [], ""):
        errores.append(
            f"`{etiqueta}` ({rol}): el área 'exterior' no lleva opciones y se declaró "
            f"{exterior!r}. Es una marca (`exterior: {{}}`): que este router ES la salida "
            "del lab. La pata de fuera, la interfaz y la dirección las pone el motor."
        )

    # Y la dirección: un invitado con config tiene que ser alcanzable.
    direccion = invitado.get("direccion")
    if direccion in (None, ""):
        errores.append(
            f"`{etiqueta}` ({rol}) declara `config.` pero no declara `direccion`: un "
            "equipo que no se puede alcanzar no se puede converger (un conmutador "
            "puro no lleva `config`)"
        )
    elif (modulo_interior.es_direccion_dinamica(direccion)
          and modulo_interior.areas_que_piden_visita(invitado)):
        # Los puestos dinámicos declaran SÓLO el tipo (`linux: {}`) con `direccion: dhcp`:
        # su dirección se lee del HOST y no se configura dentro, así que no piden visita.
        # Pero un `dhcp` CON áreas que exijan entrar no se puede converger: no se sabe a
        # qué dirección conectar, y el motor no entra a ciegas (regla 16). Se dice aquí,
        # no se intenta.
        piden = ", ".join(sorted(modulo_interior.areas_que_piden_visita(invitado)))
        errores.append(
            f"`{etiqueta}` ({rol}) declara `direccion: dhcp` y áreas que piden ENTRAR "
            f"({piden}): sin una dirección estática el motor no sabe a dónde conectar. "
            "Deja sólo el tipo (`linux: {}`) o declara una dirección."
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
                    "de la identidad (regla 11). Quítalo de la declaración."
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


# ---------------------------------------------------------------------------
# Consejos -- lo que es LEGAL pero casi siempre es un olvido
# ---------------------------------------------------------------------------
# Un validador que sólo dice "no" obliga a aprender a golpes, y la mitad de los
# tropiezos de un lab nuevo son legales y silenciosos: un invitado que arranca en
# el mismo escalón que quien le da la dirección, una dirección estática dentro del
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
    "escalones",
    "dhcp",
    "pasarela",
    "imagen",
    "bridge-vacio",
    "dos-dhcp",
    "sin-quien-la-dirija",
    "exterior-sin-dns",
    "exterior-con-ruta",
)


def _indice_de_interfaz(interfaz):
    """`eth0`/`ether1` -> 0; la PRIMERA pata, en los dos vocabularios.

    Linux cuenta desde cero (`eth0`) y RouterOS desde uno (`ether1`), y las dos
    formas nombran la misma posición: la primera pata declarada.
    """
    texto = str(interfaz or "")
    numero = re.match(r"^ether(\d+)$", texto) or re.match(r"^eth(\d+)$", texto)
    if not numero:
        return None
    return int(numero.group(1)) - 1 if texto.startswith("ether") else int(numero.group(1))


def _bridge_de_interfaz(invitado, interfaz):
    """Sobre qué bridge del lab está esa pata, o None si esa pata no existe.

    Sirve para un invitado que declara TODAS sus patas (`bridges:`), que es un
    RouterOS o una VM. NO sirve para el puesto de control: sus patas extra
    (`direcciones`) no están en `bridges:` porque una por cada bridge del lab se las
    pone el motor. Para ésas está `_bridge_de`, que va por la RED de la dirección.
    """
    indice = _indice_de_interfaz(interfaz)
    patas = patas_declaradas(invitado)
    if indice is None or not (0 <= indice < len(patas)):
        return None
    return patas[indice]


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
    la puerta de su red; por eso es también lo que dice sobre qué bridge cae una
    dirección cualquiera del lab.
    """
    return [
        (bridge["nombre"], str(bridge["direccion"]))
        for bridge in (declaracion.get("lab") or {}).get("bridges") or []
        if isinstance(bridge, dict) and bridge.get("nombre") and bridge.get("direccion")
    ]


def _bridge_de(valor, redes):
    """El bridge del lab cuya red contiene esa dirección, o None.

    `redes` sale de `_redes_de_los_bridges`. Es la forma de saber el bridge de una
    dirección declarada SIN depender de qué interfaz la lleva: el puesto de control
    declara `eth1` pero no declara sobre qué bridge está (una por cada bridge del lab
    se la pone el motor),
    y su dirección sí lo dice.
    """
    for nombre, direccion_bridge in redes:
        base, _, prefijo = direccion_bridge.partition("/")
        if prefijo.isdigit() and _misma_red(valor, base, int(prefijo)):
            return nombre
    return None


def _invitados(declaracion):
    """(seccion, indice, rol, tipo, invitado), en orden de declaración."""
    salida = []
    for seccion, tipo in (("vms", "qemu"), ("containers", "lxc")):
        for indice, invitado in enumerate(declaracion.get(seccion) or []):
            if isinstance(invitado, dict):
                salida.append((seccion, indice, invitado.get("rol"), tipo, invitado))
    return salida


def _servidores_dhcp(declaracion):
    """Quién da direcciones, en qué bridge y desde qué escalón.

    Los dos vocabularios: un puesto de control Linux (`dhcp_servidor`) y un
    RouterOS (`dhcp`). Sin esto no se puede saber si un invitado con `direccion:
    dhcp` tiene quien le conteste, ni si arranca antes de que le contesten.

    El bridge se saca de la RED que el servidor reparte (el rango, o la red que
    anuncia), que es lo que de verdad dice sobre qué red está sirviendo; la interfaz
    queda como segunda vía, porque un RouterOS sí declara todas sus patas.
    """
    redes = _redes_de_los_bridges(declaracion)
    servidores = []
    for seccion, indice, rol, _tipo, invitado in _invitados(declaracion):
        config = invitado.get("config") or {}
        linux = (config.get("linux") or {}).get("dhcp_servidor")
        if isinstance(linux, dict) and linux.get("interfaz"):
            rango = str(linux.get("rango") or "")
            principio = rango.partition("-")[0] if rango else ""
            servidores.append({
                "rol": rol,
                "escalon": invitado.get("escalon"),
                "bridge": (
                    _bridge_de(principio, redes)
                    or _bridge_de_interfaz(invitado, linux["interfaz"])
                ),
                "rango": rango,
                "donde": f"`{seccion}[{indice}]` ({rol})",
            })
        for i, servidor in enumerate((config.get("routeros") or {}).get("dhcp") or []):
            if not isinstance(servidor, dict) or not servidor.get("interfaz"):
                continue
            rango = str((servidor.get("pool") or {}).get("rango") or "")
            principio = rango.partition("-")[0] if rango else ""
            servidores.append({
                "rol": rol,
                "escalon": invitado.get("escalon"),
                "bridge": (
                    _bridge_de((servidor.get("red") or {}).get("prefijo") or principio, redes)
                    or _bridge_de_interfaz(invitado, servidor["interfaz"])
                ),
                "rango": rango,
                "donde": f"`{seccion}[{indice}]`.config.routeros.dhcp[{i}] ({rol})",
            })
    return servidores


def _direcciones_estaticas(declaracion):
    """Las direcciones que el lab FIJA, con el bridge sobre el que las fija.

    Incluye las de los bridges: la dirección de un bridge es la puerta de los
    invitados que cuelgan de él, y por eso cuenta como "alguien del lab" cuando se
    mira si una pasarela existe. El bridge de cada dirección se deduce de su RED
    (una dirección dice a qué red pertenece), no de la interfaz que la lleva.
    """
    redes = _redes_de_los_bridges(declaracion)
    estaticas = []
    for indice, bridge in enumerate((declaracion.get("lab") or {}).get("bridges") or []):
        if isinstance(bridge, dict) and bridge.get("direccion"):
            estaticas.append({
                "rol": None,
                "bridge": bridge.get("nombre"),
                "direccion": str(bridge["direccion"]),
                "donde": f"`lab.bridges[{indice}]`",
            })
    for seccion, indice, rol, _tipo, invitado in _invitados(declaracion):
        direccion = invitado.get("direccion")
        if direccion not in (None, "") and str(direccion) != "dhcp":
            estaticas.append({
                "rol": rol,
                "bridge": (
                    _bridge_de(direccion, redes)
                    or _bridge_de_interfaz(
                        invitado, "eth0" if invitado.get("bridge") else "ether1"
                    )
                ),
                "direccion": str(direccion),
                "donde": f"`{seccion}[{indice}]` ({rol})",
            })
        config = invitado.get("config") or {}
        for vocabulario, clave in (("routeros", "direcciones"), ("linux", "direcciones")):
            for i, pata in enumerate((config.get(vocabulario) or {}).get(clave) or []):
                if isinstance(pata, dict) and pata.get("direccion"):
                    estaticas.append({
                        "rol": rol,
                        "bridge": (
                            _bridge_de(pata["direccion"], redes)
                            or _bridge_de_interfaz(invitado, pata.get("interfaz"))
                        ),
                        "direccion": str(pata["direccion"]),
                        "donde": f"`{seccion}[{indice}]`.config.{vocabulario}.{clave}[{i}] ({rol})",
                    })
    return estaticas


def _pasarelas(declaracion):
    """Las pasarelas que el lab nombra: rutas y la que anuncia su DHCP."""
    salida = []
    for seccion, indice, rol, _tipo, invitado in _invitados(declaracion):
        routeros = (invitado.get("config") or {}).get("routeros") or {}
        for i, ruta in enumerate(routeros.get("rutas") or []):
            if isinstance(ruta, dict) and ruta.get("pasarela"):
                salida.append({
                    "rol": rol,
                    "valor": str(ruta["pasarela"]),
                    "donde": f"`{seccion}[{indice}]`.config.routeros.rutas[{i}] ({rol})",
                })
        for i, servidor in enumerate(routeros.get("dhcp") or []):
            if not isinstance(servidor, dict):
                continue
            pasarela = (servidor.get("red") or {}).get("pasarela")
            if pasarela:
                salida.append({
                    "rol": rol,
                    "valor": str(pasarela),
                    "donde": f"`{seccion}[{indice}]`.config.routeros.dhcp[{i}].red ({rol})",
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

    def aconsejar(codigo, donde, mensaje, remedio):
        consejos.append(
            {"codigo": codigo, "donde": donde, "mensaje": mensaje, "remedio": remedio}
        )

    invitados = _invitados(declaracion)
    servidores = _servidores_dhcp(declaracion)
    estaticas = _direcciones_estaticas(declaracion)
    supernet = _supernet_de(declaracion)
    bridges = [
        b["nombre"]
        for b in (declaracion["lab"].get("bridges") or [])
        if isinstance(b, dict) and b.get("nombre")
    ]
    # Quién cuelga de cada bridge: sirve para el bridge vacío y para saber sobre qué
    # red cae una dirección estática.
    por_bridge = {nombre: [] for nombre in bridges}
    for seccion, indice, rol, _tipo, invitado in invitados:
        for nombre in patas_declaradas(invitado):
            por_bridge.setdefault(nombre, []).append(f"`{seccion}[{indice}]` ({rol})")

    # --- 1. el escalón: nadie arranca antes que quien le da la dirección -------
    for servidor in servidores:
        for seccion, indice, rol, tipo, invitado in invitados:
            if str(invitado.get("direccion")) != "dhcp":
                continue
            if servidor["bridge"] not in patas_declaradas(invitado):
                continue
            if tipo == "lxc" and modulo_interior.tiene_camino(invitado):
                continue  # el puesto de control no se pide la dirección a sí mismo
            escalon, del_servidor = invitado.get("escalon"), servidor["escalon"]
            if not isinstance(escalon, int) or not isinstance(del_servidor, int):
                continue
            if escalon <= del_servidor:
                aconsejar(
                    "escalones",
                    f"`{seccion}[{indice}]` ({rol})",
                    f"pide su dirección por DHCP en `{servidor['bridge']}`, donde se la da "
                    f"{servidor['donde']} (escalón {del_servidor}), y está en el escalón "
                    f"{escalon}: arrancarían a la vez, y quién contesta primero es una "
                    "carrera, no un diseño",
                    f"pon a '{rol}' en un escalón POSTERIOR al {del_servidor} (regla 18: "
                    "nunca se arranca un escalón antes de que el anterior sirva)",
                )

    # --- 2. una dirección estática dentro del rango del DHCP ------------------
    for servidor in servidores:
        if not servidor["rango"]:
            continue
        for estatica in estaticas:
            if estatica["bridge"] != servidor["bridge"]:
                continue
            if _ip_en_rango(estatica["direccion"], servidor["rango"]):
                aconsejar(
                    "dhcp",
                    estatica["donde"],
                    f"fija {_direccion_sin_mascara(estatica['direccion'])} y esa dirección "
                    f"cae DENTRO del rango que reparte {servidor['donde']} "
                    f"({servidor['rango']}) en el mismo bridge: un cliente dinámico puede "
                    "pedirla antes y dejarla ocupada",
                    "saca la dirección del rango del pool (los estáticos van fuera), o "
                    "declara `reservas: derivadas` para que el DHCP la respete",
                )

    # --- 3. una pasarela que no es nadie del lab ------------------------------
    if supernet:
        conocidas = {_direccion_sin_mascara(e["direccion"]) for e in estaticas}
        for pasarela in _pasarelas(declaracion):
            valor = pasarela["valor"]
            if valor in conocidas or not _ip_en_supernet(valor, supernet):
                continue
            aconsejar(
                "pasarela",
                pasarela["donde"],
                f"usa {valor} como pasarela y esa dirección no es de nadie del lab, "
                f"aunque cae dentro de su supernet ({supernet}): o es un número mal "
                "escrito, o falta el equipo que la tiene",
                "revisa el número, o declara el invitado (o el bridge) que tiene esa "
                "dirección",
            )

    # --- 4. una VM con configuración y sin imagen ------------------------------
    for seccion, indice, rol, tipo, invitado in invitados:
        if tipo == "qemu" and invitado.get("config") and not invitado.get("imagen"):
            aconsejar(
                "imagen",
                f"`{seccion}[{indice}]` ({rol})",
                "es una VM que declara `config` y no declara `imagen`: nacerá sin disco, "
                "así que no arrancará nada que configurar (y la imagen sólo se puede "
                "adjuntar AL CREAR: después habría que recrear la máquina)",
                "declara `imagen:` con la imagen de fábrica de ese invitado",
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
    for seccion, indice, rol, tipo, invitado in invitados:
        if str(invitado.get("direccion")) != "dhcp":
            continue
        if tipo == "lxc" and modulo_interior.tiene_camino(invitado):
            continue
        for nombre in patas_declaradas(invitado):
            if nombre in bridges and nombre not in servidos:
                aconsejar(
                    "sin-quien-la-dirija",
                    f"`{seccion}[{indice}]` ({rol})",
                    f"pide su dirección por DHCP en `{nombre}`, que es un bridge DEL LAB, "
                    "y no hay ningún servidor DHCP declarado que sirva en él: nadie le "
                    "va a contestar",
                    f"declara un servidor DHCP en '{nombre}' (el router de esa red o el "
                    "puesto de control), o dale una dirección estática",
                )

    # --- 8. la salida del lab, pero sin quién resuelva nombres ----------------
    # Un router con `exterior` da SALIDA a internet. Pero un invitado que lo tiene de
    # pasarela pregunta por NOMBRES a quien le dio la dirección -- el servidor DHCP de su
    # red --, y si ese servidor no anuncia DNS el lab sale a internet y no resuelve nada.
    # Es el fallo que más veces se lee como "no tiene salida", y no lo es.
    salidas = []
    anuncian_dns = []
    for seccion, indice, rol, _tipo, invitado in invitados:
        config = invitado.get("config") or {}
        routeros = config.get("routeros") or {}
        if "exterior" in routeros:
            salidas.append(f"`{seccion}[{indice}]` ({rol})")
            # Y una ruta por defecto declarada en el que es la salida es una de dos: su
            # cliente de fuera ya le enseña una (la aprende por DHCP), así que las dos
            # compiten por el mismo destino -- y la declarada obliga al lab a saber la
            # pasarela de FUERA, que es justo lo que `exterior` evita tener que saber.
            por_defecto = [
                ruta
                for ruta in routeros.get("rutas") or []
                if isinstance(ruta, dict) and str(ruta.get("destino")) in ("0.0.0.0/0", "::/0")
            ]
            if por_defecto:
                aconsejar(
                    "exterior-con-ruta",
                    f"`{seccion}[{indice}]`.config.routeros.rutas ({rol})",
                    "este router es la salida del lab y además le declaras una ruta por "
                    "defecto: la que pone el motor por la puerta de fuera y la tuya compiten "
                    "por el mismo destino",
                    "quita la ruta por defecto declarada: la salida la pone el motor por la "
                    "puerta de fuera, y así el lab no necesita saber la pasarela de la red de "
                    "casa",
                )
        for servidor in (config.get("routeros") or {}).get("dhcp") or []:
            if isinstance(servidor, dict) and (servidor.get("red") or {}).get("dns"):
                anuncian_dns.append(f"`{seccion}[{indice}]`.config.routeros.dhcp ({rol})")
        servidor_linux = (config.get("linux") or {}).get("dhcp_servidor")
        if isinstance(servidor_linux, dict) and (servidor_linux.get("red") or {}).get("dns"):
            anuncian_dns.append(
                f"`{seccion}[{indice}]`.config.linux.dhcp_servidor ({rol})"
            )
    if salidas and not anuncian_dns:
        aconsejar(
            "exterior-sin-dns",
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
                    # distinguir "no está la clave" de "está vacía". Y puede ser `dhcp`:
                    # una ESTACIÓN, que al conectar pide dirección -- como una máquina
                    # de verdad. `puerta` es SU puerta, y sólo se declara cuando la
                    # dirección es fija (un SERVIDOR real la lleva puesta a mano): el
                    # motor no la adivina ni la reparte.
                    "direccion": invitado.get("direccion") or None,
                    "puerta": invitado.get("puerta") or None,
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
            "declaracion_consejos": declaracion_consejos,
        }
