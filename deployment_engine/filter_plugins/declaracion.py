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
# LÍMITES:     no habla con Proxmox y no sabe nada del mundo real; sólo mira el
#              YAML. Que un bridge exista en el NODO no se comprueba aquí: eso es
#              `preflight`, que sí lee la API.
# VER:         README.md §Verificación; AGENTS.md §Reglas duras; ./lab check declaracion

# Se importa el error de Ansible si estamos dentro de Ansible. Si no (tests con
# `python3` a secas), vale una excepción propia: el fichero tiene que poder
# importarse sin la dependencia de Ansible para poder probarlo aislado.
import re

try:
    from ansible.errors import AnsibleFilterError as ErrorMotor
except ImportError:  # pragma: no cover - sólo ocurre fuera de Ansible
    class ErrorMotor(Exception):
        """Error del motor, con el mismo nombre que el de Ansible."""

# Los dos tipos de invitado que el motor sabe desplegar, tal como los nombra la
# API de Proxmox en sus rutas.
TIPOS = ("qemu", "lxc")

# Claves que el motor DERIVA y por tanto están PROHIBIDAS en la declaración. Si
# aparecen, alguien ha intentado fijar a mano lo que es del motor, y eso es el
# origen de los conflictos entre labs.
CLAVES_DERIVADAS = ("vmid", "mac", "nombre", "name", "pool")

# Campos obligatorios de cada invitado declarado, y su tipo esperado.
CAMPOS_INVITADO = {
    "rol": str,
    "escalon": int,
    "cores": int,
    "memoria": int,
    "disco": int,
    "bridge": str,
    "direccion": str,
}

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

        for campo, esperado in CAMPOS_INVITADO.items():
            if campo not in invitado:
                errores.append(f"`{etiqueta}` ({rol}) no declara `{campo}`")
                continue
            valor = invitado[campo]
            if esperado is int:
                if not isinstance(valor, int) or isinstance(valor, bool) or valor <= 0:
                    errores.append(f"`{etiqueta}` ({rol}): `{campo}` tiene que ser un entero > 0 (es {valor!r})")
            elif not isinstance(valor, str) or not valor.strip():
                errores.append(f"`{etiqueta}` ({rol}): `{campo}` tiene que ser texto no vacío")

        if invitado.get("bridge") and invitado["bridge"] not in nombres_bridge:
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
        if invitado.get("direccion"):
            direcciones.append((rol, _direccion_sin_mascara(invitado["direccion"])))

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
                    "bridge": invitado["bridge"],
                    "direccion": invitado["direccion"],
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
    }


class FilterModule:
    """Registro de filtros que Ansible ve como `| declaracion_normalizar`."""

    def filters(self):
        return {
            "declaracion_validar": declaracion_validar,
            "declaracion_normalizar": declaracion_normalizar,
        }
