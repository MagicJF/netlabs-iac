#!/usr/bin/env python3
# PROPÓSITO:   probar el driver PURO del interior —*(declarado, leído) → pasos*—
#              sin Proxmox, sin RouterOS, sin red y sin Ansible. Es la prueba de que
#              la decisión de qué se escribe dentro de un invitado es una función.
# INVARIANTES: los casos que TIENEN que cumplirse, y que son el contrato del driver:
#              1. sin lectura, la forma GRUESA: un paso por área declarada;
#              2. con lectura y todo igual, CERO pasos (es la prueba de la
#                 idempotencia: si esto falla, la segunda ejecución escribe);
#              3. con lectura y algo distinto, SÓLO el área que cambia, con la
#                 operación concreta;
#              4. un invitado declarado que no se puede alcanzar -> error, no un paso;
#              5. lo que está dentro del área y no está declarado, se quita;
#              6. en un RouterOS, la `identity` va la ÚLTIMA en la primera
#                 convergencia (intercambio atómico: si no, un fallo a mitad deja al
#                 equipo con las credenciales viejas y sin túnel de vuelta);
#              7. el residuo del cliente DHCP de fábrica se declara como
#                 `reiniciar_invitado` con su motivo, nunca se ignora;
#              8. las reservas DHCP se DERIVAN (MAC del vmid) y del ámbito correcto;
#              9. a quién hay que MIRAR por dentro (`verify`, que no aprueba lo que no
#                 ha leído): sólo a quien declara áreas que piden visita.
# LÍMITES:     no prueba el driver de verdad (eso es el ciclo contra el VPS): aquí no
#              se toca ningún equipo. Los estados «leídos» están escritos a mano y son
#              el contrato de lo que el driver debe sacar de dentro de cada equipo.
# VER:         docs/decisiones/0005-areas-declaradas.md; docs/decisiones/0007-*.md

# Uso:  python3 test/test_interior.py     (código de salida != 0 si algo falla)

import os
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(RAIZ, "deployment_engine", "filter_plugins"))

import interior as motor  # noqa: E402

FALLOS = []


def comprobar(condicion, descripcion):
    print(("  OK   " if condicion else "  FALLA") + f" {descripcion}")
    if not condicion:
        FALLOS.append(descripcion)
    return bool(condicion)


def igual(obtenido, esperado, descripcion):
    return comprobar(
        obtenido == esperado, f"{descripcion}  (obtenido {obtenido!r}, esperado {esperado!r})"
    )


def operaciones_de(pasos, area):
    """Las operaciones del paso de ESA área (o None si no hay paso).

    Se busca por área y no por posición: un área declarada que no se ha leído genera
    su propio paso («converger_area_completa»), y una prueba que mirase el paso 0 se
    estaría creyendo otra cosa.
    """
    for paso in pasos:
        if paso["parametros"]["area"] == area:
            return paso["parametros"]["operaciones"]
    return None


# ---------------------------------------------------------------------------
# Fixtures: una declaración de laboratorio pequeña y su identidad derivada.
# Valores inventados a propósito (10.60.0.0/16): no son los de ningún lab del repo.
# ---------------------------------------------------------------------------

CONTROL = {
    "rol": "control",
    "tipo": "lxc",
    "stage": 1,
    "bridge": "vmb_gen",
    "address": "10.60.0.10/24",
    "config": {
        "linux": {
            "tunnel": {"salida": {"puerto": 443}},
            "dhcp_server": {
                "interface": "eth0",
                "rango": "10.60.0.50-10.60.0.99",
                "static_leases": "derived",
            },
            "ip_forward": True,
        }
    },
}

BORDE = {
    "rol": "borde",
    "tipo": "qemu",
    "stage": 1,
    "bridge": "vmb_gen",
    "address": "10.60.0.11/24",
    "image": "chr-7.25.1.raw",
    "config": {
        "routeros": {
            "identity": "rt-borde",
            "ip_services": {"deshabilitar": ["telnet", "ftp", "api", "api-ssl"]},
            "dhcp_client": {"deshabilitar": True},
            "addresses": [{"interface": "ether2", "address": "10.60.1.1/24"}],
            "routes": [{"dst_address": "0.0.0.0/0", "gateway": "10.60.0.1"}],
            "dhcp_server": [
                {
                    "interface": "ether2",
                    "pool": {"rango": "10.60.1.100-10.60.1.200"},
                    "network": {"address": "10.60.1.0/24", "gateway": "10.60.1.1", "dns": ["10.60.1.1"]},
                    "static_leases": "derived",
                }
            ],
        }
    },
}

# Un servidor en la LAN del router: tiene dirección estática, así que el router tiene
# que reservársela por su MAC derivada.
SERVIDOR = {
    "rol": "servidor",
    "tipo": "lxc",
    "stage": 2,
    "bridge": "vmb_lan",
    "address": "10.60.1.10/24",
    "config": {"linux": {}},
}

# Un puesto que toma su dirección del router: NO se le reserva nada (no declara una
# dirección estática, no hay nada que proteger).
PUESTO = {
    "rol": "puesto-1",
    "tipo": "lxc",
    "stage": 3,
    "bridge": "vmb_lan",
    "address": "dhcp",
    "config": {"linux": {}},
}

DECLARACION = {
    "lab": "lab-de-prueba",
    "address_space": "10.60.0.0/16",
    "bridges": [
        {"nombre": "vmb_gen", "address": "10.60.0.1/24"},
        {"nombre": "vmb_lan", "address": "10.60.1.1/24"},
    ],
    "tunnel": {"tipo": "bastion"},
    "guests": [CONTROL, BORDE, SERVIDOR, PUESTO],
}

IDENTIDAD = {
    "lab": "lab-de-prueba",
    "guests": [
        {"rol": "control", "vmid": 200, "mac": "BC:24:11:00:00:C8", "nombre": "lab-de-prueba-control"},
        {"rol": "borde", "vmid": 201, "mac": "BC:24:11:00:00:C9", "nombre": "lab-de-prueba-borde"},
        {"rol": "servidor", "vmid": 202, "mac": "BC:24:11:00:00:CA", "nombre": "lab-de-prueba-servidor"},
        {"rol": "puesto-1", "vmid": 203, "mac": "BC:24:11:00:00:CB", "nombre": "lab-de-prueba-puesto-1"},
    ],
}

PARAMETROS = {"bridge_gestion": "vmbr1", "tunnel_puerto_base": 20000, "nodo": "nodo-de-prueba"}

# El estado del bastión LEÍDO dentro del equipo, con todas sus áreas al día.
# El driver lee SIEMPRE todas las áreas declaradas: una lectura recortada no es un
# caso válido (el driver para y lo dice), así que los casos parciales se construyen
# cambiando UNA área de este mapa.
LECTURA_CONTROL_AL_DIA = {
    "address": {"address": "10.60.0.10/24"},
    "ip_forward": {"activo": True},
    "dhcp_server": {
        "interface": "eth0",
        "rango": "10.60.0.50-10.60.0.99",
        "servicio_activo": True,
        "offload_apagado": True,
        "static_leases": [{"mac": "BC:24:11:00:00:C9", "address": "10.60.0.11/24"}],
    },
    "tunnel": {"salida": "puesta"},
}


def lectura(areas_cambiadas=None):
    """La lectura del bastión, con las áreas que se quieran cambiar."""
    return {
        "alcanzable": True,
        "areas": dict(LECTURA_CONTROL_AL_DIA, **(areas_cambiadas or {})),
    }

# Un estado del nodo leído por API: en vmbr1 ya hay dos direcciones ocupadas.
ESTADO_NODO = {
    "bridges_direcciones": {"vmbr1": "10.10.10.1/24"},
    "direcciones_usadas": ["10.10.10.1/24", "10.10.10.2/24", "10.10.10.254/24"],
}


# ---------------------------------------------------------------------------
# El tipo y las áreas
# ---------------------------------------------------------------------------

print("TIPO Y ÁREAS\n")

igual(motor.tipo_de(BORDE), "routeros", "un invitado con `config.routeros` es un RouterOS")
igual(motor.tipo_de(CONTROL), "linux", "un invitado con `config.linux` es un Linux")
igual(motor.tipo_de({"rol": "switch"}), None, "un invitado sin `config` no tiene interior")
igual(motor.declara_interior({"rol": "switch"}), False, "sin `config`, el motor no entra")
igual(motor.tiene_tunnel(CONTROL), True, "el bastión declara el túnel")
igual(motor.tiene_tunnel(BORDE), False, "un router no es el bastión")

# Dos tipos a la vez: no se adivina, se dice.
try:
    motor.tipo_de({"config": {"linux": {}, "routeros": {}}})
    comprobar(False, "un `config` con dos tipos da error")
except motor.ErrorMotor:
    comprobar(True, "un `config` con dos tipos da error")

areas_borde = motor.areas_de(BORDE)
igual(
    sorted(areas_borde),
    sorted(["identity", "ip_services", "dhcp_client", "addresses", "routes", "dhcp_server"]),
    "las áreas de un RouterOS son las que declara",
)
areas_control = motor.areas_de(CONTROL)
igual(
    sorted(areas_control),
    sorted(["tunnel", "dhcp_server", "ip_forward", "address"]),
    "las áreas de un Linux son las que declara (más la dirección de su interfaz)",
)
igual(
    motor.areas_a_leer(CONTROL), list(areas_control.keys()), "se leen exactamente las áreas declaradas"
)

# ---------------------------------------------------------------------------
# La dirección libre de la interfaz de gestión (derivada: nada se guarda)
# ---------------------------------------------------------------------------

print("\nDIRECCIÓN LIBRE DE LA PATA DE GESTIÓN\n")

igual(
    motor.direccion_libre("10.10.10.1/24", ["10.10.10.1/24"]),
    "10.10.10.254",
    "se cuenta por arriba (los pools DHCP reparten desde abajo)",
)
igual(
    motor.direccion_libre("10.10.10.1/24", ["10.10.10.254/24", "10.10.10.253/24"]),
    "10.10.10.252",
    "se esquivan las direcciones en uso",
)
try:
    motor.direccion_libre("10.10.10.1/25", [])
    comprobar(False, "un prefijo que no sabe manejar da error en vez de adivinar")
except motor.ErrorMotor:
    comprobar(True, "un prefijo que no sabe manejar da error en vez de adivinar")

interfaces = motor.interfaces_del_bastion(CONTROL, DECLARACION, ESTADO_NODO, PARAMETROS)
igual(len(interfaces), 3, "el bastión tiene una interfaz por bridge, más la de gestión del nodo")
# El ORDEN es el orden de `eth0, eth1, ...` dentro del invitado: primero las del LAB (la
# declarada la primera, porque es el `eth0` que citan las áreas del lab) y la de gestión
# del nodo la ÚLTIMA, que es la única con vía de acceso.
igual(
    interfaces[0]["bridge"], "vmb_gen",
    "la primera interfaz es la declarada: es el `eth0` que el lab cita en sus áreas",
)
igual(
    interfaces[0]["address"], "10.60.0.10/24", "la interfaz declarada del lab lleva su dirección declarada"
)
igual(interfaces[0]["gateway"], "", "una interfaz de un bridge del lab no lleva vía de acceso")
igual(
    interfaces[1]["address"], "10.60.1.254/24",
    "la interfaz no declarada la deriva el motor por arriba, esquivando lo declarado",
)
igual(interfaces[2]["bridge"], "vmbr1", "la ÚLTIMA interfaz es la del bridge de gestión del nodo: la salida")
igual(interfaces[2]["address"], "10.10.10.253/24", "su dirección en el nodo la DERIVA el motor")
igual(interfaces[2]["gateway"], "10.10.10.1", "y es la única con gateway: la dirección del nodo")
# Y sin bridge de gestión no se inventa nada: un puesto sin salida no se puede converger,
# así que se dice y se para (en vez de crear el invitado y descubrirlo tres pasos después).
try:
    motor.interfaces_del_bastion(
        CONTROL, DECLARACION, ESTADO_NODO, {"tunnel_puerto_base": 20000}
    )
    comprobar(False, "sin bridge de gestión el motor falla en vez de crear un puesto sin salida")
except motor.ErrorMotor as error:
    comprobar(
        "pve_bridge_gestion" in str(error),
        "sin bridge de gestión el motor falla diciendo la clave que falta",
    )
# Y si ese bridge existe en el nodo pero NO tiene dirección, tampoco hay vía de acceso por la que
# salir: se dice, no se crea una interfaz muda.
try:
    motor.interfaces_del_bastion(
        CONTROL, DECLARACION, {"bridges_direcciones": {}, "direcciones_usadas": []}, PARAMETROS
    )
    comprobar(False, "un bridge de gestión sin dirección da error, no una interfaz sin vía de acceso")
except motor.ErrorMotor as error:
    comprobar(
        "vmbr1" in str(error), "el error dice QUÉ bridge de gestión no tiene dirección"
    )

# ---------------------------------------------------------------------------
# El puerto del túnel y la línea que se manda por consola
# ---------------------------------------------------------------------------

print("\nEL TÚNEL: PUERTO DERIVADO Y LÍNEA DE CONSOLA\n")

igual(motor.puerto_tunnel(200, PARAMETROS), 20200, "el puerto del túnel se deriva del vmid")
igual(motor.puerto_tunnel(201, PARAMETROS), 20201, "y dos invitados no comparten puerto")

guion = motor.guion_tunnel("CLAVE-PRIVADA-DE-PRUEBA", "casa.example", 443, "tunnel", 20200)
comprobar(
    "-R 20200:localhost:22" in guion,
    "el guion deja reenviado el puerto del lab hacia el sshd del invitado",
)
comprobar(
    "-p 443 tunnel@casa.example" in guion,
    "y sale hacia casa por el host y el puerto que declara el lab",
)
comprobar("/etc/systemd/system/" in guion, "el guion se deja como unidad de systemd")
comprobar("Restart=always" in guion, "y con reinicio automático: el invitado que reinicia, vuelve")
comprobar("CLAVE-PRIVADA-DE-PRUEBA" in guion, "la clave del túnel viaja dentro del guion")
comprobar(
    motor.marca_tunnel() in guion,
    "el guion imprime su marca al final: la consola no devuelve código de salida, se lee el eco",
)

linea = motor.linea_consola(guion)
comprobar("\n" not in linea.strip(), "la línea de consola es UNA línea (la consola no es un canal fiable)")
comprobar(
    not any(c in linea for c in "{}'\"\\$"),
    "y va envuelta de forma que no haya comillas ni llaves que el eco pueda romper",
)
comprobar(
    __import__("base64").b64decode(linea.split()[1]).decode() == guion,
    "lo que el invitado va a ejecutar es exactamente el guion, sin reinterpretarlo",
)

# ---------------------------------------------------------------------------
# Las reservas DHCP derivadas (la MAC no se declara nunca)
# ---------------------------------------------------------------------------

print("\nRESERVAS DERIVADAS\n")

reservas_borde = motor.reservas_derivadas(DECLARACION, IDENTIDAD, BORDE, en_red="10.60.1.0/24")
igual(
    [(r["rol"], r["address"], r["mac"]) for r in reservas_borde],
    [("servidor", "10.60.1.10/24", "BC:24:11:00:00:CA")],
    "el router reserva la dirección estática del servidor de SU red, con su MAC derivada",
)
comprobar(
    all(r["rol"] != "borde" for r in reservas_borde),
    "el servidor no se reserva a sí mismo",
)
comprobar(
    all(r["rol"] != "puesto-1" for r in reservas_borde),
    "un cliente dinámico no se static_lease: no declara dirección que proteger",
)
reservas_control = motor.reservas_derivadas(DECLARACION, IDENTIDAD, CONTROL)
igual(
    [r["rol"] for r in reservas_control],
    ["borde"],
    "el bastión reserva, en su bridge, la dirección del router (ámbito por bridge)",
)

# ---------------------------------------------------------------------------
# La forma GRUESA: sin lectura dentro del equipo
# ---------------------------------------------------------------------------

print("\nFORMA GRUESA (plan sin credenciales: no se ha leído dentro)\n")

pasos_gruesos = motor.pasos_de_convergencia(BORDE, IDENTIDAD, DECLARACION, {}, PARAMETROS)
# UN paso por invitado, no uno por área: el plan es una explicación del trabajo, y cuatro
# frases idénticas sobre el mismo equipo cuentan como cuatro lo que es una sola
# conversación con él. Las áreas declaradas se dicen dentro del `porque`, que es donde
# informan sin prometer nada.
igual(
    [(p["accion"], p["parametros"]["area"]) for p in pasos_gruesos],
    [("converger_interior", None)],
    "sin lectura, UN paso por invitado (no uno por área)",
)
comprobar(
    all(p["via"] == "interior" and p["porque"] for p in pasos_gruesos),
    "cada paso dice por dónde va y por qué (un paso sin razón es un bug)",
)
comprobar(
    all(area in pasos_gruesos[0]["porque"] for area in motor.areas_de(BORDE)),
    "y el paso nombra las áreas que va a recorrer, que es lo que se puede decir sin leer",
)
igual(
    motor.pasos_de_convergencia(PUESTO, IDENTIDAD, DECLARACION, {}, PARAMETROS),
    [],
    "un puesto con sólo `address: dhcp` no pide visita: su dirección se lee del HOST "
    "(§6.3) y no se sabe a dónde conectar para entrar, así que el motor no entra a ciegas",
)
igual(
    sorted(motor.areas_que_piden_visita(PUESTO)),
    [],
    "y por eso no le queda NINGUNA área que exija entrar (sólo la dinámica)",
)
comprobar(
    bool(motor.areas_que_piden_visita(BORDE)),
    "en cambio un router con áreas declara visita: su interior sí se converge",
)

# Sin `config` no hay pasos: el motor despliega y se calla.
igual(
    motor.pasos_de_convergencia({"rol": "switch", "stage": 1}, IDENTIDAD, DECLARACION, {}, PARAMETROS),
    [],
    "un invitado sin interior no genera ningún paso",
)

# ---------------------------------------------------------------------------
# La forma EXACTA: con lectura. Aquí vive la idempotencia.
# ---------------------------------------------------------------------------

print("\nFORMA EXACTA (con lectura dentro del equipo)\n")

# 1) Todo ya como está declarado: CERO pasos. Si esto falla, la segunda ejecución escribe.
LEIDO_AL_DIA = {
    "alcanzable": True,
    "areas": {
        "identity": {"nombre": "rt-borde", "usuario_motor": True, "clave_motor": True, "credencial_motor": True},
        "ip_services": {"deshabilitados": ["api", "api-ssl", "ftp", "telnet"]},
        "dhcp_client": {"habilitado": False},
        "addresses": {"estaticas": [{"interface": "ether1", "address": "10.60.0.11/24"}, {"interface": "ether2", "address": "10.60.1.1/24"}], "dinamicas": []},
        "routes": {
            "estaticas": [{"dst_address": "0.0.0.0/0", "gateway": "10.60.0.1"}],
            "dinamicas": [],
        },
        "dhcp_server": {
            "servidores": [
                {
                    "interface": "ether2",
                    "rango": "10.60.1.100-10.60.1.200",
                    "network": {"address": "10.60.1.0/24", "gateway": "10.60.1.1", "dns": ["10.60.1.1"]},
                }
            ],
            "static_leases": [{"mac": "BC:24:11:00:00:CA", "address": "10.60.1.10"}],
        },
    },
}
igual(
    motor.pasos_de_convergencia(BORDE, IDENTIDAD, DECLARACION, LEIDO_AL_DIA, PARAMETROS),
    [],
    "un equipo ya convergido NO genera ni un paso (idempotencia por construcción)",
)

# 2) Una sola cosa distinta: un área, con su operación concreta.
LEIDO_FALTA_UNA_RUTA = {
    "alcanzable": True,
    "areas": dict(LEIDO_AL_DIA["areas"], routes={"estaticas": [], "dinamicas": []}),
}
pasos = motor.pasos_de_convergencia(BORDE, IDENTIDAD, DECLARACION, LEIDO_FALTA_UNA_RUTA, PARAMETROS)
igual(len(pasos), 1, "lo que cambia es UNA cosa: un solo paso")
igual(pasos[0]["parametros"]["area"], "routes", "y es el área de rutas")
igual(
    pasos[0]["parametros"]["operaciones"],
    [{"op": "add_route", "dst_address": "0.0.0.0/0", "gateway": "10.60.0.1"}],
    "con la operación concreta que falta",
)

# 3) Lo que está dentro del área y no está declarado, se quita.
LEIDO_CON_SOBRA = {
    "alcanzable": True,
    "areas": dict(
        LEIDO_AL_DIA["areas"],
        ip_services={"deshabilitados": ["api", "api-ssl", "ftp", "telnet", "ssh"]},
        addresses={
            "estaticas": [
                {"interface": "ether1", "address": "10.60.0.11/24"},
                {"interface": "ether2", "address": "10.60.1.1/24"},
                {"interface": "ether3", "address": "10.60.2.1/24"},
            ],
            "dinamicas": [],
        },
    ),
}
pasos_sobra = motor.pasos_de_convergencia(BORDE, IDENTIDAD, DECLARACION, LEIDO_CON_SOBRA, PARAMETROS)
areas_con_paso = {p["parametros"]["area"]: p["parametros"]["operaciones"] for p in pasos_sobra}
igual(
    areas_con_paso.get("ip_services"),
    [{"op": "enable_service", "servicio": "ssh"}],
    "un servicio apagado que el motor gestiona y no está declarado, se vuelve a habilitar",
)
igual(
    areas_con_paso.get("addresses"),
    [{"op": "remove_address", "interface": "ether3", "address": "10.60.2.1/24"}],
    "una dirección de más dentro del área, se quita",
)

# 4) El intercambio atómico: en la PRIMERA convergencia la identidad va la última.
LEIDO_SIN_IDENTIDAD = {
    "alcanzable": True,
    "areas": {
        "identity": {"nombre": "", "usuario_motor": False, "clave_motor": False, "credencial_motor": False},
        "ip_services": {"deshabilitados": []},
        "dhcp_client": {"habilitado": True},
        "addresses": {"estaticas": [], "dinamicas": []},
        "routes": {"estaticas": [], "dinamicas": []},
        "dhcp_server": {"servidores": [], "static_leases": []},
    },
}
pasos_primera = motor.pasos_de_convergencia(
    BORDE, IDENTIDAD, DECLARACION, LEIDO_SIN_IDENTIDAD, PARAMETROS
)
igual(
    pasos_primera[-1]["parametros"]["area"],
    "identity",
    "la identidad del router va la ÚLTIMA (intercambio atómico)",
)
comprobar(
    {"op": "disable_dhcp_client"}
    in next(
        p for p in pasos_primera if p["parametros"]["area"] == "dhcp_client"
    )["parametros"]["operaciones"],
    "y el cliente DHCP de fábrica se deshabilita antes que la identidad",
)

# 5) El residuo del cliente de fábrica: se declara, con su motivo, y no se ignora.
igual(
    motor.residuo_dinamico({"residuo": {}}),
    (False, ""),
    "un RouterOS sin residuo no necesita reinicio",
)
hay_residuo, motivo = motor.residuo_dinamico(
    {"residuo": {"direccion_dinamica": "10.60.0.11/24", "ruta_dinamica": True}}
)
comprobar(hay_residuo, "una dirección o una ruta dinámica del cliente de fábrica es residuo")
comprobar("dinámica" in motivo, "y el motivo se dice en castellano, para el informe")
pasos_residuo = motor.pasos_de_convergencia(
    BORDE,
    IDENTIDAD,
    DECLARACION,
    dict(LEIDO_AL_DIA, residuo={"direccion_dinamica": "10.60.0.11/24", "ruta_dinamica": True}),
    PARAMETROS,
)
igual(
    [(p["accion"], p["via"]) for p in pasos_residuo],
    [("reiniciar_guest", "api")],
    "el residuo se arregla con un reinicio DECLARADO en el plan (por la API), no escondido",
)
comprobar(
    "reinicia UNA vez" in pasos_residuo[0]["porque"],
    "y el paso explica que es una vez por vida del invitado, no en cada ejecución",
)

# 6) Un invitado con interior que no se puede alcanzar: el verbo PARA, no sigue a ciegas.
try:
    motor.pasos_de_convergencia(
        BORDE,
        IDENTIDAD,
        DECLARACION,
        {"alcanzable": False, "motivo": "el túnel está caído"},
        PARAMETROS,
    )
    comprobar(False, "sin túnel, converger un interior da error")
except motor.ErrorMotor as error:
    comprobar(
        "el túnel está caído" in str(error),
        "sin túnel, converger un interior da error diciendo QUÉ falta",
    )

# 7) Linux: la dirección dinámica no se escribe, se comprueba (§6.3).
igual(
    motor.pasos_de_convergencia(
        PUESTO,
        IDENTIDAD,
        DECLARACION,
        {"alcanzable": True, "areas": {"address": {"address": "10.60.1.77/24"}}},
        PARAMETROS,
    ),
    [],
    "un `address: dhcp` no genera escritura: se comprueba, no se escribe",
)
igual(
    operaciones_de(
        motor.pasos_de_convergencia(
            CONTROL,
            IDENTIDAD,
            DECLARACION,
            lectura({"address": {"address": ""}}),
            PARAMETROS,
        ),
        "address",
    ),
    [{"op": "add_address", "interface": "eth0", "address": "10.60.0.10/24"}],
    "una dirección estática que falta, se escribe (y en eth0: la interfaz del contenedor)",
)

# El servidor DHCP de un Linux: dnsmasq, offload y reservas derivadas.
# Dos estados distintos, y la diferencia importa:
#   * el área NO está en la lectura -> el driver no la leyó: el verbo PARA y lo dice
#     (sin leer no se puede afirmar que coincide, y escribir «por si acaso» rompería
#     la idempotencia);
#   * el área está y sale vacía     -> la leyó y no hay nada: el diff exacto escribe
#     todo lo declarado, que es más preciso y no es a ciegas.
try:
    motor.pasos_de_convergencia(
        CONTROL,
        IDENTIDAD,
        DECLARACION,
        {"alcanzable": True, "areas": {"tunnel": {"salida": "puesta"}}},
        PARAMETROS,
    )
    comprobar(False, "un área declarada que el driver NO leyó da error en vez de escribir a ciegas")
except motor.ErrorMotor as error:
    comprobar(
        "no leyó el área" in str(error)
        and any(area in str(error) for area in ("address", "ip_forward", "dhcp_server")),
        "un área declarada que el driver NO leyó da error diciendo CUÁL falta",
    )
igual(
    operaciones_de(
        motor.pasos_de_convergencia(
            CONTROL,
            IDENTIDAD,
            DECLARACION,
            lectura({"dhcp_server": {}}),
            PARAMETROS,
        ),
        "dhcp_server",
    ),
    [
        {"op": "write_dnsmasq", "interface": "eth0", "rango": "10.60.0.50-10.60.0.99"},
        {"op": "disable_offload", "interface": "eth0"},
        {"op": "add_static_lease", "mac": "BC:24:11:00:00:C9", "address": "10.60.0.11/24"},
        {"op": "reload_dnsmasq"},
    ],
    "y si se leyó y estaba vacío, el diff exacto escribe lo declarado (con sus reservas derivadas)",
)

# Con lectura: sin offload apagado no hay DHCP que funcione (medido en v3).
igual(
    operaciones_de(
        motor.pasos_de_convergencia(
            CONTROL,
            IDENTIDAD,
            DECLARACION,
            lectura(
                {
                    "dhcp_server": {
                        "interface": "eth0",
                        "rango": "10.60.0.50-10.60.0.99",
                        "servicio_activo": True,
                        "offload_apagado": False,
                        "static_leases": [{"mac": "BC:24:11:00:00:C9", "address": "10.60.0.11/24"}],
                    }
                }
            ),
            PARAMETROS,
        ),
        "dhcp_server",
    ),
    [
        {"op": "disable_offload", "interface": "eth0"},
        {"op": "reload_dnsmasq"},
    ],
    "el offload se apaga y dnsmasq recarga: sin eso las ofertas llegan rotas y el CHR las tira",
)

# Y si solo cambia una reserva, dnsmasq se recarga igual (no basta con que esté vivo).
igual(
    operaciones_de(
        motor.pasos_de_convergencia(
            CONTROL,
            IDENTIDAD,
            DECLARACION,
            lectura(
                {
                    "dhcp_server": {
                        "interface": "eth0",
                        "rango": "10.60.0.50-10.60.0.99",
                        "servicio_activo": True,
                        "offload_apagado": True,
                        "static_leases": [],
                    }
                }
            ),
            PARAMETROS,
        ),
        "dhcp_server",
    ),
    [
        {"op": "add_static_lease", "mac": "BC:24:11:00:00:C9", "address": "10.60.0.11/24"},
        {"op": "reload_dnsmasq"},
    ],
    "una reserva nueva se pone y dnsmasq recarga, aunque el servicio ya esté vivo",
)

# El reenvío del kernel: lo necesita el servidor DHCP.
igual(
    operaciones_de(
        motor.pasos_de_convergencia(
            CONTROL,
            IDENTIDAD,
            DECLARACION,
            lectura({"ip_forward": {"activo": False}}),
            PARAMETROS,
        ),
        "ip_forward",
    ),
    [{"op": "enable_ip_forward"}],
    "sin reenvío no hay servidor DHCP: se activa",
)

# El tunnel: lo pone la consola UNA vez; después sólo se comprueba.
igual(
    motor.pasos_de_convergencia(CONTROL, IDENTIDAD, DECLARACION, lectura(), PARAMETROS),
    [],
    "con la salida ya puesta, el túnel no se vuelve a mandar por consola (ni nada más)",
)
igual(
    operaciones_de(
        motor.pasos_de_convergencia(
            CONTROL,
            IDENTIDAD,
            DECLARACION,
            lectura({"tunnel": {"salida": ""}}),
            PARAMETROS,
        ),
        "tunnel",
    ),
    [{"op": "send_console_line"}],
    "sin salida, hay que volver a mandar la línea por consola",
)

# ---------------------------------------------------------------------------
# La sonda de etapa (regla 18)
# ---------------------------------------------------------------------------

print("\nLA SONDA DE LA ETAPA\n")

sonda_borde = motor.espera_de_servicio(BORDE)
igual(sonda_borde["via"], "sonda", "la sonda no es un `wait_for`: es una petición a lo prometido")
igual(sonda_borde["parametros"]["puerto"], 80, "a un RouterOS se le pregunta por su REST")
igual(
    sonda_borde["parametros"]["address"], "10.60.0.11",
    "en la dirección que la declaración promete, sin máscara",
)
igual(motor.espera_de_servicio(CONTROL)["parametros"]["puerto"], 22, "a un Linux, por su sshd")
igual(motor.espera_de_servicio({"rol": "switch"}), None, "un invitado sin interior no se sondea")
comprobar(
    "etapa" in sonda_borde["porque"] and "puerto 80" in sonda_borde["porque"],
    "y el paso explica que la etapa siguiente no se toca hasta que este conteste",
)

# ---------------------------------------------------------------------------
# Los pasos del túnel (§5): el plan los emite, el ejecutor los hace
# ---------------------------------------------------------------------------

print("\nLOS PASOS DEL TÚNEL\n")

CONTROL_CON_VMID = dict(CONTROL, vmid=200, stage=1)
pasos_tunnel = motor.pasos_del_tunnel(CONTROL_CON_VMID, DECLARACION, ESTADO_NODO, PARAMETROS)
igual(
    [paso["accion"] for paso in pasos_tunnel],
    ["construir_tunnel", "comprobar_tunnel"],
    "sin túnel en pie, se construye y se comprueba (en este orden)",
)
igual(pasos_tunnel[0]["via"], "tunnel", "los dos pasos del túnel van por el túnel, no por la API")
igual(
    pasos_tunnel[0]["parametros"]["puerto"], 20200,
    "el puerto del túnel se DERIVA del vmid del puesto: nada que guardar",
)
comprobar(
    len(pasos_tunnel[0].get("detalle") or []) >= 4,
    "el paso del túnel se explica por piezas (clave, authorized_keys, consola, marca)",
)
igual(
    len(pasos_tunnel[0]["parametros"]["interfaces"]), 3,
    "y lleva sus interfaces: el puesto nace completo, con todas",
)
comprobar(
    "CLAVE-PRIVADA" not in __import__("json").dumps(pasos_tunnel).upper(),
    "el plan NO lleva secretos: la clave del túnel se lee al ejecutar, no viaja en el paso",
)
igual(
    [
        paso["accion"]
        for paso in motor.pasos_del_tunnel(
            CONTROL_CON_VMID, DECLARACION,
            dict(ESTADO_NODO, tunnel={"responde": True}), PARAMETROS
        )
    ],
    ["comprobar_tunnel"],
    "si el túnel YA responde no se reconstruye: sólo se comprueba (que es una lectura)",
)

# Y los DOS pasos llevan la MISMA lista de reenvíos REST. No es cosmético: `tunnel.yml`
# calcula lo que autoriza en `authorized_keys` desde `parametros.rest`, así que un paso del
# túnel sin la lista la reescribe VACÍA, deja el túnel sin los reenvíos REST y el bastión se
# queda mudo en cuanto reconecta (la sesión abierta antes de la reescritura sigue viva, así
# que nada avisa). Pasó de verdad: 230 «request was denied» de sshd y 0 invitados leídos.
_rest_de = lambda paso: [i["puerto"] for i in paso["parametros"].get("rest") or []]

# Con el mapa de identidad delante (`borde` = vmid 201), la lista no es vacía: es el puerto
# que sale del vmid. En el plan de verdad la identidad viaja siempre; aquí se pasa a mano.
pasos_con_identidad = motor.pasos_del_tunnel(
    CONTROL_CON_VMID, DECLARACION, ESTADO_NODO, PARAMETROS, IDENTIDAD
)
igual(
    _rest_de(pasos_con_identidad[0]), [21201],
    "el reenvío REST sale del vmid del equipo que tiene interior de RouterOS (21000 + 201)",
)
comprobar(
    _rest_de(pasos_con_identidad[0]) == _rest_de(pasos_con_identidad[1]),
    "y los DOS pasos del túnel llevan la misma lista: el que se emite siempre es el que "
    "converge la línea de authorized_keys",
)
igual(
    _rest_de(
        motor.pasos_del_tunnel(
            CONTROL_CON_VMID, DECLARACION,
            dict(ESTADO_NODO, tunnel={"responde": True}), PARAMETROS, IDENTIDAD
        )[0]
    ),
    [21201],
    "aunque el túnel ya responda y sólo se compruebe, el paso sigue llevando la lista: "
    "es la que deja authorized_keys como estaba",
)
igual(
    motor.pasos_del_tunnel(BORDE, DECLARACION, {}, PARAMETROS), [],
    "un invitado que no es el bastión no genera pasos de túnel",
)


# ---------------------------------------------------------------------------
# El driver de LINUX: el inventario, la vía de acceso y lo que se midió al conectarlo
# (14-nov-2026). Todo lo de aquí salió de un fallo DE VERDAD al encenderlo.
# ---------------------------------------------------------------------------

print("\nEL DRIVER DE LINUX\n")

import base64 as _base64  # noqa: E402
import yaml as _yaml  # noqa: E402
import declaracion as _validador  # noqa: E402

# La declaración que CIRCULA por el motor está normalizada: sus invitados son una lista
# plana (`guests`), no `containers`/`vms`. Si el motor la lee como el fichero del lab,
# no encuentra el bastión, el inventario se queda sin puerto y el paso muere
# con «No first item, sequence was empty». Pasó: por eso se prueba con esta forma.
_CRUDA = _yaml.safe_load(open(os.path.join(RAIZ, "labs", "04_lab-red-routeros", "04_lab-red-routeros.yml")))
_NORMALIZADA = _validador.declaracion_normalizar(_CRUDA)
igual(
    motor.bastion(_NORMALIZADA), "control",
    "el bastión se saca de la declaración NORMALIZADA (la que circula de verdad)",
)
igual(
    motor.bastion({"guests": [{"rol": "puesto-1", "config": {"linux": {"address": "dhcp"}}}]}),
    "",
    "un lab que no declara túnel no tiene bastión: '' y no un nombre inventado",
)

# Los drivers que el motor DICE que tiene y los ficheros que tiene que haber. Si alguien
# añade un driver sin declararlo, `apply` para en un paso que sí sabe hacer; si lo declara
# sin escribir el fichero, promete lo que no puede.
_CARPETA_TAREAS = os.path.join(RAIZ, "deployment_engine", "tasks")
_FICHEROS = {
    f[len("configurar_"):-len(".yml")]
    for f in os.listdir(_CARPETA_TAREAS)
    if f.startswith("configurar_") and f.endswith(".yml")
}
igual(
    set(motor.DRIVERS["interior"]), _FICHEROS,
    "los drivers declarados y los ficheros `configurar_<tipo>.yml` cuadran (ni uno de más ni uno de menos)",
)

# `rc` 255 lo pone ssh cuando NO consigue entrar: eso es «no llegué», no «está mal». Cualquier
# otro código distinto de cero es el invitado CONTESTANDO que eso no está, y es un estado
# legítimo del que sí se puede decidir.
_leido_255 = motor.leido_de_lecturas(
    [{"ansible_loop_var": "interior_comando", "interior_comando": {"area": "tunnel"},
      "stdout": "", "rc": 255, "stderr": "root@127.0.0.1: Permission denied (publickey,password)."}],
    {"rol": "control"},
)
igual(_leido_255["alcanzable"], False, "rc 255 = no se pudo entrar: el motor para en vez de seguir a ciegas")
comprobar(
    "Permission denied" in _leido_255["motivo"],
    "y lo que se enseña es el motivo que dijo ssh, no uno inventado",
)
igual(
    motor.leido_de_lecturas([{"ansible_loop_var": "interior_comando", "interior_comando": {"area": "tunnel"}, "stdout": "", "rc": 1}], {"rol": "control"})["alcanzable"],
    True,
    "rc 1 = el invitado contestó que eso no está: se llegó, y eso se puede decidir",
)

# --- El servidor DHCP: el sitio donde la idempotencia se pierde sin querer -----------
CONTROL_CON_DHCP = {
    "rol": "control", "stage": 1, "tipo": "lxc", "bridge": "vmb_gestion",
    "address": "10.40.0.10/24",
    "config": {"linux": {
        "tunnel": {},
        "ip_forward": True,
        "dhcp_server": {"interface": "eth0", "rango": "10.40.0.50-10.40.0.99", "static_leases": "derived"},
    }},
}
PUESTO_CON_DHCP = {
    "rol": "puesto-1", "stage": 1, "tipo": "lxc", "bridge": "vmb_gestion",
    "address": "10.40.0.20/24", "config": {"linux": {"tunnel": {}}},
}
DECLARACION_DHCP = {
    "lab": "prueba", "stages": [1],
    "bridges": [{"nombre": "vmb_gestion", "address_space": "10.40.0.0/24"}],
    "guests": [CONTROL_CON_DHCP, PUESTO_CON_DHCP],
    "address_space": "10.40.0.0/24",
    "tunnel": {"tipo": "bastion"},
}
IDENTIDAD_DHCP = {"guests": [
    # La identidad lleva la MAC de cada interfaz (la deriva el motor del vmid): es de donde
    # sale la de la reserva. 109 = 0x6D y 110 = 0x6E.
    {"rol": "control", "vmid": 109, "tipo": "lxc", "nombre": "prueba-control",
     "mac": "BC:24:11:00:00:6D"},
    {"rol": "puesto-1", "vmid": 110, "tipo": "lxc", "nombre": "prueba-puesto-1",
     "mac": "BC:24:11:00:00:6E"},
]}

# El texto que de verdad devuelve el invitado: la configuración tal y como la escribe
# dnsmasq (`inicio,fin,mascara,tiempo`) y los offloads como los imprime `ethtool -k`.
LECTURA_DHCP_AL_DIA = {
    "alcanzable": True,
    "areas": {
        "tunnel": {"salida": True},
        "address": {"address": "10.40.0.10/24"},
        "ip_forward": {"activo": True},
        "dhcp_server": {
            "interface": "eth0",
            "rango": "10.40.0.50-10.40.0.99",
            "static_leases": [{"mac": "BC:24:11:00:00:6E", "address": "10.40.0.20"}],
            "configurado": True,
            "servicio_activo": True,
            "offload_apagado": True,
            "herramientas": {"dnsmasq": True, "ethtool": True},
        },
    },
}
igual(
    motor.operaciones_de_pasos(motor.pasos_de_convergencia(
        CONTROL_CON_DHCP, IDENTIDAD_DHCP, DECLARACION_DHCP, LECTURA_DHCP_AL_DIA, PARAMETROS)),
    [],
    "un invitado al día -> CERO operaciones: es la prueba de que la segunda pasada no escribe",
)

_AREAS = motor.leido_de_lecturas(
    [{"ansible_loop_var": "interior_comando", "interior_comando": {"area": "dhcp_server"}, "rc": 0, "stdout": (
        "port=0\ninterface=eth0\ndhcp-range=10.40.0.50,10.40.0.99,255.255.255.0,12h\n"
        "---NETLABS---\ntx-checksumming: on\ngeneric-segmentation-offload: off\n"
        "tcp-segmentation-offload: off\n---NETLABS---\ndnsmasq=/usr/sbin/dnsmasq\nethtool=NO\n"
    )}],
    CONTROL_CON_DHCP,
)["areas"]["dhcp_server"]
igual(
    _AREAS["rango"], "10.40.0.50-10.40.0.99",
    "el rango leído se normaliza a la forma declarada (sin esto, el fichero se reescribe en cada pasada)",
)
igual(_AREAS["offload_apagado"], False, "un offload encendido se ve tal cual (`tx-checksumming: on`)")
igual(
    _AREAS["herramientas"], {"dnsmasq": True, "ethtool": False},
    "y se sabe qué herramientas hay dentro, para no instalar por si acaso",
)

# Un puesto recién creado: sin herramientas, sin configuración y con los offloads puestos.
# El ORDEN importa: primero lo que hace falta para que exista el servidor (dnsmasq,
# ethtool), después su configuración, después los offloads -- porque sin ethtool no se
# pueden apagar -- y sólo entonces arrancarlo.
_OPERACIONES_NUEVO = motor.operaciones_de_pasos(motor.pasos_de_convergencia(
    CONTROL_CON_DHCP, IDENTIDAD_DHCP, DECLARACION_DHCP,
    motor.leido_de_lecturas(
        [{"ansible_loop_var": "interior_comando", "interior_comando": {"area": "tunnel"}, "rc": 0, "stdout": "active"},
         {"ansible_loop_var": "interior_comando", "interior_comando": {"area": "address"}, "rc": 0, "stdout":
          "2: eth0    inet 10.40.0.10/24 brd 10.40.0.255 scope global eth0"},
         {"ansible_loop_var": "interior_comando", "interior_comando": {"area": "ip_forward"}, "rc": 0, "stdout": "0"},
         {"ansible_loop_var": "interior_comando", "interior_comando": {"area": "dhcp_server"}, "rc": 0, "stdout": '---NETLABS---\ntx-checksumming: on\ngeneric-segmentation-offload: on\ntcp-segmentation-offload: on\n---NETLABS---\ndnsmasq=NO\nethtool=NO\n---NETLABS---\ninactive'}],
        CONTROL_CON_DHCP),
    PARAMETROS,
))
_ESCRITURAS = motor.escrituras_linux(
    _OPERACIONES_NUEVO, CONTROL_CON_DHCP, DECLARACION_DHCP, IDENTIDAD_DHCP, PARAMETROS)
comprobar(
    {e["area"] for e in _ESCRITURAS} <= {"dhcp_server", "ip_forward", "address", "tunnel"},
    "el motor sólo escribe en áreas DECLARADAS: no se inventa ninguna",
)
_ORDEN = [e["comando"] for e in _ESCRITURAS]
_INSTALAR = next(i for i, c in enumerate(_ORDEN) if c.startswith("DEBIAN_FRONTEND=noninteractive apt-get install"))
comprobar(
    all(_INSTALAR < i for i, c in enumerate(_ORDEN)
        if "ethtool -K" in c or "dnsmasq.conf" in c),
    "las herramientas del aparato se ponen ANTES de usarlas: sin dnsmasq no hay servidor y sin ethtool no se apagan los offloads",
)
comprobar(
    any("ethtool -K eth0 tx off gso off tso off" in e["comando"] for e in _ESCRITURAS),
    "y los offloads se apagan con `ethtool -K` (medido: `ip link` NO sabe hacerlo)",
)
_CONFIG = [e for e in _ESCRITURAS if "base64 -d > /etc/dnsmasq.d/netlabs.conf" in e["comando"]]
comprobar(len(_CONFIG) == 1, "la configuración se escribe en un solo paso, codificada (nada de comillas rotas)")
if _CONFIG:
    _TEXTO = _base64.b64decode(_CONFIG[0]["comando"].split()[1]).decode()
    comprobar("port=0" in _TEXTO, "el servidor DHCP no monta un DNS que nadie ha declarado (`port=0`)")
    comprobar(
        "dhcp-host=BC:24:11:00:00:6E,10.40.0.20" in _TEXTO,
        "y lleva la reserva del equipo con dirección fija, con la MAC DERIVADA de su vmid (110 = 0x6E)",
    )
    import identidad as _identidad
    comprobar(
        _identidad.identidad_mac(110, "BC:24:11") == "BC:24:11:00:00:6E",
        "la MAC de la reserva es la que el motor DERIVA del vmid: nadie la escribe a mano (regla 14)",
    )

# ---------------------------------------------------------------------------
print("\n== un bastión declara una dirección por cada bridge del lab ==")
# Medido: sin dirección en la LAN, el CHR que cuelga de ella no contesta al REST y su
# convergencia no se puede ni empezar (10.40.1.11 en 'nucleo'). La forma es `addresses`
# (lista), y se funde en el área `address` para que la convergencia tenga un solo túnel.
_PUESTO = {
    "rol": "control",
    "tipo": "lxc",
    "address": "10.40.0.10/24",
    "config": {"linux": {"addresses": [{"interface": "eth1", "address": "10.40.1.2/24"}]}},
}
comprobar(
    motor.areas_de(_PUESTO)["address"]
    == [
        {"interface": "eth0", "address": "10.40.0.10/24"},
        {"interface": "eth1", "address": "10.40.1.2/24"},
    ],
    "la de gestión sale del campo `address` y va PRIMERO; las otras interfaces, declaradas una a una",
)
comprobar(
    motor.areas_de(_PUESTO).get("addresses") is None,
    "`addresses` no es un área aparte: se funde en `address` (una sola forma de converger)",
)
_LEIDO_PUESTO = motor.leido_linux(
    [
        {
            "area": "address",
            "rc": 0,
            "encontrado": "2: eth0    inet 10.40.0.10/24 brd 10.40.0.255 scope global eth0\n"
            "3: eth1    inet 10.40.1.2/24 brd 10.40.1.255 scope global eth1\n",
        }
    ]
)
comprobar(
    _LEIDO_PUESTO["address"]["addresses"]
    == [
        {"interface": "eth0", "address": "10.40.0.10/24"},
        {"interface": "eth1", "address": "10.40.1.2/24"},
    ],
    "y la lectura saca TODAS las interfaces con dirección, no sólo eth0",
)
comprobar(
    _LEIDO_PUESTO["address"]["address"] == "10.40.0.10/24",
    "la de gestión sigue siendo la de eth0: es la que el plan usa para levantar el túnel",
)
comprobar(
    motor._address_linux_canonica(
        motor.areas_de(_PUESTO)["address"], _LEIDO_PUESTO["address"]
    )
    == [],
    "con las dos interfaces puestas, la segunda pasada no escribe nada (idempotencia)",
)
comprobar(
    motor._address_linux_canonica(
        motor.areas_de(_PUESTO)["address"],
        {
            "address": "10.40.0.10/24",
            "addresses": [{"interface": "eth0", "address": "10.40.0.10/24"}],
        },
    )
    == [{"op": "add_address", "interface": "eth1", "address": "10.40.1.2/24"}],
    "si falta la interfaz de la LAN, se pone SÓLO esa: lo que ya está no se toca",
)

# ---------------------------------------------------------------------------
# `verify` MIRA DENTRO: a quién se le pregunta, y qué cuenta como aprobado
# ---------------------------------------------------------------------------

comprobar(
    motor.guests_a_verificar(
        {
            "vms": [
                {"rol": "borde", "config": {"routeros": {"identity": {"nombre": "b"}}}},
                {"rol": "sin-interior", "recursos": {}},
            ],
            "containers": [
                {"rol": "control", "config": {"linux": {"tunnel": {"salida": "x"}}}},
                # Sólo `address: dhcp`: no hay nada que preguntarle dentro.
                {"rol": "puesto", "address": "dhcp", "config": {"linux": {}}},
            ],
        }
    )
    == [
        {"rol": "borde", "tipo": "routeros"},
        {"rol": "control", "tipo": "linux"},
    ],
    "verify sólo abre conexión a quien declara áreas que piden visita (sin `config`, no se entra)",
)

# La MISMA pregunta sobre la declaración NORMALIZADA (la que `verify` tiene en la mano):
# una sola lista `guests`, con el tipo ya resuelto.
comprobar(
    motor.guests_a_verificar(
        {
            "lab": "x",
            "guests": [
                {"rol": "control", "tipo": "lxc", "config": {"linux": {"tunnel": {"salida": "x"}}}},
                {"rol": "puesto", "tipo": "lxc", "address": "dhcp", "config": {"linux": {}}},
            ],
        }
    )
    == [{"rol": "control", "tipo": "linux"}],
    "la declaración normalizada (`guests`) se lee igual que la cruda",
)

comprobar(
    motor.informe_ok({}) is True
    and motor.informe_ok({"a": {"alcanzable": True, "pendiente": []}}) is True
    and motor.informe_ok({"a": {"alcanzable": True, "pendiente": ["add_address"]}}) is False
    and motor.informe_ok({"a": {"alcanzable": False, "pendiente": []}}) is False,
    "el interior no se aprueba si un invitado no se pudo leer o le queda algo pendiente",
)

# ---------------------------------------------------------------------------
# EL REST POR EL TÚNEL: el bastión abre, ADEMÁS, el puerto 80 de cada equipo
# con el que el motor habla por REST, para que la llamada la haga el motor y no el puesto
# (nada de `delegate_to`: docs/decisiones/0010-*.md).
# ---------------------------------------------------------------------------

# El puerto sale del vmid, como el del túnel, y las dos bandas no se pisan.
comprobar(
    motor.puerto_rest_tunnel(102, {}) == 21102
    and motor.puerto_rest_tunnel(102, {"tunnel_rest_puerto_base": 30000}) == 30102
    and motor.puerto_rest_tunnel(102, {}) != motor.puerto_tunnel(102, {}),
    "el puerto del REST de un invitado se deriva de su vmid, en una banda propia",
)

DECLARACION_REST = {
    "lab": "x",
    "guests": [
        {"rol": "borde", "tipo": "vm", "address": "10.40.0.11/24", "config": {"routeros": {}}},
        {"rol": "control", "tipo": "lxc", "address": "dhcp", "config": {"linux": {"tunnel": {}}}},
        {"rol": "nucleo", "tipo": "vm", "address": "10.40.1.11/24", "config": {"routeros": {}}},
        {"rol": "puesto", "tipo": "lxc", "address": "dhcp", "config": {"linux": {}}},
        {"rol": "suelto", "tipo": "vm", "address": "10.40.2.11/24"},
    ],
}
IDENTIDAD_REST = {
    "guests": [
        {"rol": "borde", "vmid": 102},
        {"rol": "control", "vmid": 103},
        {"rol": "nucleo", "vmid": 104},
        {"rol": "puesto", "vmid": 105},
        {"rol": "suelto", "vmid": 106},
    ]
}

# Sólo los que declaran `config.routeros`: el vocabulario es cerrado, y a un Linux o a un
# invitado sin interior no se le abre el REST de nadie. El orden es estable (por rol) para
# que un `apply` no reescriba el guion por nada.
comprobar(
    motor.interfaces_rest_del_bastion(DECLARACION_REST, IDENTIDAD_REST, {})
    == [
        {"rol": "borde", "address": "10.40.0.11", "puerto": 21102, "puerto_servicio": 80},
        {"rol": "nucleo", "address": "10.40.1.11", "puerto": 21104, "puerto_servicio": 80},
    ],
    "sólo los equipos con `config.routeros` reciben interfaz de REST, y salen ordenados por rol",
)

# La dirección se cita SIN el prefijo (lo que viaja en `-R` es una dirección, no una red),
# y un equipo sin dirección declarada no entra: no hay a dónde reenviar, y fingirlo sería
# mentir en el guion.
comprobar(
    motor.interfaces_rest_del_bastion(
        {
            "lab": "x",
            "guests": [
                {"rol": "sin_dir", "tipo": "vm", "config": {"routeros": {}}},
                {"rol": "en_dhcp", "tipo": "vm", "address": "dhcp", "config": {"routeros": {}}},
            ],
        },
        {"guests": [{"rol": "sin_dir", "vmid": 110}, {"rol": "en_dhcp", "vmid": 111}]},
        {},
    )
    == [],
    "un RouterOS sin dirección declarada (o en dhcp) no recibe interface: no hay a dónde reenviar",
)

comprobar(
    motor.interfaces_rest_del_bastion(DECLARACION_REST, None, {}) == []
    and motor.interfaces_rest_del_bastion(DECLARACION_REST, {"guests": []}, {}) == [],
    "sin mapa de identidad no hay interfaces de REST que abrir (no se inventa un puerto)",
)

# El guion: un `-R` por equipo, cada uno siguiendo la línea como los demás argumentos del
# `ssh`. Es lo que hace que el túnel sirva al motor en SU máquina.
GUION_CON_REST = motor.guion_tunnel(
    "CLAVE", "casa.example", 443, "hermes", 20103,
    [{"rol": "borde", "address": "10.40.0.11", "puerto": 21102, "puerto_servicio": 80}],
)
GUION_SIN_REST = motor.guion_tunnel("CLAVE", "casa.example", 443, "hermes", 20103)

comprobar(
    "-R 21102:10.40.0.11:80" in GUION_CON_REST
    and "-R 20103:localhost:22" in GUION_CON_REST
    and "\n  -p 443 hermes@casa.example\n" in GUION_CON_REST,
    "el guion del túnel reenvía también el REST de cada equipo, por el MISMO túnel",
)

comprobar(
    "-R 21102:10.40.0.11:80" not in GUION_SIN_REST
    and "-R 20103:localhost:22" in GUION_SIN_REST,
    "un lab sin RouterOS no añade reenvíos de más: el túnel sólo lleva la consola",
)

# Cada línea del `ssh` que sigue tiene que acabar en `\` + salto de verdad (una sola
# barra): con dos, la shell corta la orden y el túnel no se levanta. Se mira el byte.
LINEAS_SSH = [
    linea
    for linea in GUION_CON_REST.splitlines()
    if linea.startswith("  -") or linea.startswith("  -R") or "exec ssh" in linea
]
comprobar(
    all(linea.endswith("\\") or linea.endswith("casa.example") for linea in LINEAS_SSH)
    and all(not linea.endswith("\\\\") for linea in LINEAS_SSH),
    "cada línea del `ssh` del guion continúa con UNA barra (si no, el túnel no se levanta)",
)

# El estado viaja por texto: un «False» con letras es una CADENA, y `bool('False')` es
# True en Python. Si esto se creyera, un túnel caído pasaría por túnel en pie.
comprobar(
    motor.tunnel_responde({"tunnel": {"responde": False}}) is False
    and motor.tunnel_responde({"tunnel": {"responde": "False"}}) is False
    and motor.tunnel_responde({"tunnel": {"responde": True}}) is True
    and motor.tunnel_responde({"tunnel": {"responde": "True"}}) is True
    and motor.tunnel_responde({}) is False
    and motor.tunnel_responde({"tunnel": {}}) is False,
    "un «False» que llega como texto NO se lee como «el túnel responde»",
)

# La línea de `authorized_keys`: `permitlisten` se REPITE. Una lista dentro de una sola
# opción hace que sshd NO encuentre la clave y conteste «Permission denied (publickey)»,
# que no dice nada de lo que pasa de verdad. Es un fallo que no se ve leyendo el código.
AUTORIZADOS = motor.permitlisten_de([20103, 21102, 21104])
comprobar(
    AUTORIZADOS == 'permitlisten="20103",permitlisten="21102",permitlisten="21104"'
    and 'permitlisten="20103,21102' not in AUTORIZADOS,
    "la línea autorizada REPITE `permitlisten` en vez de meter la lista dentro de la opción",
)

# Y la OTRA mitad del mismo fallo: el filtro ya arma las opciones enteras, así que la línea
# de `tunnel.yml` NO puede volver a envolverlas (`permitlisten="{{ ... }}"` las dejaría
# como `permitlisten="permitlisten="20103"..."`, y esa sí que es mala de leer).
_TUNNEL_YML = (motor.__file__ or "").rsplit("/filter_plugins/", 1)[0] + "/tasks/tunnel.yml"
with open(_TUNNEL_YML) as _f:
    _LINEA_TUNNEL = _f.read()
comprobar(
    "permitlisten=\"{{ tunnel_puertos_autorizados }}\"" not in _LINEA_TUNNEL
    and "{{ tunnel_puertos_autorizados }}" in _LINEA_TUNNEL,
    "la línea de `authorized_keys` usa las opciones tal cual las arma el filtro (sin envolverlas dos veces)",
)

# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# 6.2 / 6.3 / 6.4 · Las pruebas, la barrera y la intromisión (ADR 0021-0023)
# ---------------------------------------------------------------------------

# 6.2 · Las PRUEBAS FUNCIONALES. Lo que se prueba aquí es la FORMA del comando que se
# lanza en el invitado: un fallo ahí no se ve hasta que hay un lab desplegado delante.
_pruebas = motor.pruebas_de(
    {
        "tests": [
            {"nombre": "ping", "desde": "ws-1", "tipo": "ping", "hacia": "10.0.0.1"},
            {"nombre": "web", "desde": "ws-1", "tipo": "servicio", "hacia": "10.0.0.9", "puerto": 80},
            {"nombre": "nombres", "desde": "ws-1", "tipo": "dns", "hacia": "ejemplo.test", "espera": 60},
        ]
    },
    intentos_por_defecto=6,
)
comprobar(
    [p["tipo"] for p in _pruebas] == ["ping", "servicio", "dns"],
    "6.2 · `pruebas_de` respeta el orden en que el lab las declara",
)
comprobar(
    _pruebas[2]["intentos"] == 10 and _pruebas[0]["intentos"] == 6,
    "6.2 · `espera` son SEGUNDOS: 60 s -> 10 intentos de 6 s; sin espera, los del motor",
)
comprobar(
    all(p["comando"].count("'") == 2 for p in _pruebas),
    "6.2 · cada comando va en UN `bash -c '...'`: ni UNA comilla simple dentro (partiría el entrecomillado)",
)
comprobar(
    "exit 3" in _pruebas[0]["comando"] and "exit 3" in _pruebas[2]["comando"],
    "6.2 · ping y dns distinguen «no se pudo comprobar» (3) de «falló» (1): sin eso, el entorno sale en rojo",
)
comprobar(
    "exit 3" not in _pruebas[1]["comando"],
    "6.2 · una prueba de `servicio` no tiene «no se pudo comprobar»: un puerto o contesta o no contesta",
)
comprobar(
    "10.0.0.9:80" in _pruebas[1]["comando"] and "ping -c 2 -W 2 10.0.0.1" in _pruebas[0]["comando"],
    "6.2 · el comando apunta al destino que declara el lab (y al puerto, en un servicio)",
)


# 6.3 · La BARRERA declarada. Sin `ready` el motor insinúa (y eso no puede cambiar);
# con `ready` el lab decide.
def _invitado(rol, address, interior="linux", **extra):
    """Un invitado de mentira, con su `config` -- que es lo que hace que el motor
    insinúe una barrera. Un invitado SIN `config` no tiene ninguna (y eso es justo lo
    que el `ready:` viene a arreglar)."""
    base = {
        "rol": rol,
        "tipo": "ws",
        "stage": 1,
        "address": address,
        "config": {interior: {}},
    }
    base.update(extra)
    return base


comprobar(
    motor.espera_de_servicio(_invitado("ws-1", "10.0.0.11/24"))["parametros"]["puerto"] == 22
    and motor.espera_de_servicio(_invitado("r1", "10.0.0.1/24", interior="routeros"))["parametros"][
        "puerto"
    ]
    == 80,
    "6.3 · sin `ready:`, la barrera sigue siendo la que el motor insinúa por el tipo (nada cambia para los labs de hoy)",
)
comprobar(
    motor.espera_de_servicio({"rol": "ws-1", "tipo": "ws", "stage": 1, "address": "10.0.0.11/24"})
    is None,
    "6.3 · y sin `config` declarado sigue sin haber barrera (que es el agujero que `ready:` cierra)",
)
comprobar(
    motor.espera_de_servicio(
        {"rol": "ws-1", "tipo": "ws", "stage": 1, "address": "10.0.0.11/24", "ready": {"tipo": "ssh"}}
    )["parametros"]["puerto"]
    == 22,
    "6.3 · `ready: {tipo: ssh}` da barrera a un invitado que no declaraba interior (antes no se podía pedir)",
)
comprobar(
    motor.espera_de_servicio(_invitado("ws-1", "10.0.0.11/24", ready={"tipo": "ninguno"})) is None,
    "6.3 · `ready: {tipo: ninguno}` QUITA la barrera: el lab dice que ese invitado no tiene que contestar",
)
comprobar(
    motor.espera_de_servicio(_invitado("ws-1", "10.0.0.11/24", ready={"tipo": "ssh", "espera": 70}))[
        "parametros"
    ]["intentos"]
    == 10,
    "6.3 · `ready.espera` son SEGUNDOS: la barrera espera lo que dice el lab (70 s -> 10 intentos de 7 s)",
)
comprobar(
    motor.espera_de_servicio(_invitado("ws-1", "10.0.0.11/24"))["parametros"]["intentos"] is None,
    "6.3 · sin `espera`, la ventana es la del motor (`None` = `engine_sonda_intentos`)",
)
comprobar(
    motor.espera_de_servicio(_invitado("ws-1", "dhcp")) is None,
    "6.3 · a un invitado con `address: dhcp` no se le sondea: no hay dirección que preguntar",
)


# 6.4 · La CAPTURA y el IMPAIRMENT desde el bastión
_INTROMISION = {
    "lab": {
        "nombre": "p0_intromision",
        "bridges": [{"nombre": "vmb_gestion"}, {"nombre": "vmb_lan"}],
    },
    "containers": [
        {
            "rol": "control",
            "tipo": "ctl",
            "nombre": 1,
            "bridges": ["vmb_gestion", "vmb_lan"],
            "config": {"linux": {"tunnel": {}}},
        },
        {"rol": "srv-1", "tipo": "srv", "nombre": 1, "bridge": "vmb_lan"},
    ],
    "capture": {"bridge": "vmb_lan", "filtro": "tcp port 80", "segundos": 20},
    "impairment": {"bridge": "vmb_lan", "retardo": "200ms", "perdida": "5%", "segundos": 15},
}
_captura = motor.captura_de(_INTROMISION)
_impairment = motor.impairment_de(_INTROMISION)
comprobar(
    _captura["interfaz"] == "eth1" and _impairment["interfaz"] == "eth1",
    "6.4 · la interfaz del bastión sale del ORDEN de sus patas (vmb_lan es la 2a -> eth1)",
)
comprobar(
    "tcpdump -i eth1 -n -l tcp port 80" in _captura["comando"] and "timeout 20" in _captura["comando"],
    "6.4 · la captura mira SU interfaz, con el filtro del lab, y se acota con sus segundos",
)
comprobar(
    "netem delay 200ms loss 5%" in _impairment["comando"],
    "6.4 · el impairment se traduce a `netem` tal cual lo declara el lab",
)
comprobar(
    _impairment["comando"].count("tc qdisc del") == 2 and "sleep 15" in _impairment["comando"],
    "6.4 · el impairment es ACOTADO: se pone, se espera y SE QUITA en el mismo comando (nunca queda puesto)",
)
comprobar(
    motor.captura_de(
        {
            "lab": {"nombre": "x", "bridges": [{"nombre": "vmb_uno"}]},
            "containers": [{"rol": "ws-1", "tipo": "ws", "nombre": 1, "bridge": "vmb_uno"}],
            "capture": {"bridge": "vmb_uno", "segundos": 5},
        }
    )["error"].startswith("el bastión"),
    "6.4 · sin bastión no hay dónde montarlo, y `captura_de` lo dice en vez de devolver un comando a medias",
)
comprobar(
    motor.captura_de({"lab": {"nombre": "x"}}) is None,
    "6.4 · sin `capture:` declarado no hay nada que capturar: el verbo lo dice, no adivina por dónde mirar",
)


if FALLOS:
    print(f"\nRESULTADO: {len(FALLOS)} fallo(s).")
    sys.exit(1)
print("\nRESULTADO: el driver puro del interior cumple su contrato.")
