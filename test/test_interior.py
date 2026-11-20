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
        "ip_services": {"deshabilitados": ["api", "api-ssl", "ftp", "telnet"],
                        "ssh_password_auth": "yes"},
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
        ip_services={"deshabilitados": ["api", "api-ssl", "ftp", "telnet", "ssh"],
                    "ssh_password_auth": "yes"},
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
        "ip_services": {"deshabilitados": [], "ssh_password_auth": "yes"},
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


# ---------------------------------------------------------------------------
# El área `servicio` (ADR 0027 y 0028): un servicio instalado, configurado y SIRVIENDO.
#
# El valor declarado es el NOMBRE del servicio, de un vocabulario CERRADO (`caddy` y
# `netxms`). El contrato es el MISMO que el del resto del interior: (declarado, leído)
# -> operaciones, y un invitado ya convergido no produce NINGUNA (regla 6).
# ---------------------------------------------------------------------------

EQUIPO_SERVICIO = {
    "rol": "caddy",
    "tipo": "ctl",
    "stage": 1,
    "bridge": "vmb_gen",
    "address": "10.60.0.20/24",
    "config": {"linux": {"tunnel": {}, "servicio": "caddy"}},
}

# El MISMO equipo, pero con el otro miembro del vocabulario: la declaración sólo cambia de
# nombre, y es el motor el que sabe que NetXMS necesita una base y una web.
EQUIPO_NETXMS = dict(EQUIPO_SERVICIO, rol="monitor",
                     config={"linux": {"tunnel": {}, "servicio": "netxms"}})

comprobar(
    "servicio" in motor.areas_de(EQUIPO_SERVICIO)
    and "servicio" in motor.areas_que_piden_visita(EQUIPO_SERVICIO),
    "un Linux que declara `servicio` lo tiene como área y pide ENTRAR (hay que leerlo para decidir)",
)
igual(
    motor.areas_de(EQUIPO_SERVICIO)["servicio"], "caddy",
    "el valor del área es el NOMBRE del servicio, tal cual (no se envuelve en un mapa)",
)
igual(
    motor.SERVICIOS_LINUX, ("caddy", "netxms"),
    "el vocabulario de servicios es CERRADO: hoy caddy y netxms (ADR 0028)",
)
igual(
    motor.areas_de(EQUIPO_NETXMS)["servicio"], "netxms",
    "y el segundo miembro se declara igual: el nombre, sin más",
)


def _encontrado_servicio(herramientas, activa, habilitada, ficheros, servido, extra="na"):
    """El `encontrado` del área, tal y como lo deja la vía de acceso (SIETE bloques).

    `herramientas` es {ejecutable: valor de `command -v`}; `ficheros` es la lista de
    contenidos EN ORDEN (uno por fichero gobernado); los dos últimos bloques van siempre.
    """
    bloques = ["\n".join(f"{h}={v}" for h, v in herramientas.items()), activa, habilitada]
    bloques += [str(f) for f in ficheros]
    bloques += [servido, extra]
    return ("\n" + motor.SEPARADOR + "\n").join(bloques)


def _leer_servicio(herramientas, activa, habilitada, ficheros, servido, extra="na"):
    return motor.leido_linux([
        {"area": "servicio", "rc": 0,
         "encontrado": _encontrado_servicio(herramientas, activa, habilitada, ficheros,
                                            servido, extra)}
    ])["servicio"]


_SIN_CADDY = {"caddy": "NO", "curl": "NO"}
_CON_CADDY = {"caddy": "/usr/bin/caddy", "curl": "/usr/bin/curl"}
_FICHEROS_CADDY = [motor.configuracion_servicio("caddy"), motor.pagina_servicio()]

# Un invitado FRESCO: sin el paquete, sin habilitar y sin servir.
_SERVICIO_FRESCO = _leer_servicio(_SIN_CADDY, "inactive", "disabled", ["", ""], "NO-SIRVE")
igual(
    _SERVICIO_FRESCO["herramientas"], {"caddy": False, "curl": False},
    "la relectura de un invitado fresco no encuentra NI el paquete NI `curl`",
)
comprobar(
    _SERVICIO_FRESCO["activo"] is False
    and _SERVICIO_FRESCO["habilitado"] is False
    and _SERVICIO_FRESCO["sirve"] is False
    # Los dos ficheros llegan EN BLANCO (con el salto de línea que deja el propio comando): se
    # comparan por su contenido sin espacios de sobra, que es lo que hace el canónico.
    and [f.strip() for f in _SERVICIO_FRESCO["ficheros_leidos"]] == ["", ""],
    "la relectura de un invitado fresco lo ve todo por poner: unidad, habilitación, los dos "
    "ficheros (en blanco) y el servicio sin servir",
)
igual(
    [o["op"] for o in motor._servicio_canonico("caddy", _SERVICIO_FRESCO)],
    ["install_service", "write_service_config", "enable_service", "reload_service"],
    "el diff de un invitado fresco pide instalarlo, configurarlo, arrancarlo y dejarlo sirviendo",
)

# Un invitado CONVERGIDO: los DOS ficheros con el contenido EXACTO del motor, la unidad viva y
# habilitada, y sirviendo.
_SERVICIO_AL_DIA = _leer_servicio(
    _CON_CADDY, "active", "enabled", _FICHEROS_CADDY, motor.pagina_servicio(),
)
igual(
    motor._servicio_canonico("caddy", _SERVICIO_AL_DIA), [],
    "un invitado ya convergido NO produce operación: es la prueba de la idempotencia (regla 6)",
)

# LA MARCA NO ES PRUEBA (hallazgo del revisor, reproducido). Una configuración EDITADA a mano
# conserva la marca del motor; darla por buena dejaba el área sin gobernar el fichero que
# escribe -- que es justo lo que promete. El contenido se compara entero.
_CONFIG_TOCADA = motor.configuracion_servicio("caddy") + "\n# tocado a mano\n"
_SERVICIO_TOCADO = _leer_servicio(
    _CON_CADDY, "active", "enabled", [_CONFIG_TOCADA, motor.pagina_servicio()],
    motor.pagina_servicio(),
)
comprobar(
    motor.MARCA_SERVICIO in _CONFIG_TOCADA
    and [o["op"] for o in motor._servicio_canonico("caddy", _SERVICIO_TOCADO)]
    == ["write_service_config", "reload_service"],
    "una configuración con la MARCA pero cambiada se reescribe: la marca no prueba que el "
    "fichero esté bien, se compara su contenido entero",
)

# Y una PÁGINA BORRADA tampoco cuela (el otro fichero que el motor gobierna): antes sólo se
# recargaba el servicio y la página no volvía nunca.
_SIN_PAGINA = _leer_servicio(
    _CON_CADDY, "active", "enabled",
    [motor.configuracion_servicio("caddy"), ""], motor.pagina_servicio(),
)
igual(
    [o["op"] for o in motor._servicio_canonico("caddy", _SIN_PAGINA)],
    ["write_service_config", "reload_service"],
    "una página borrada se vuelve a escribir: los dos ficheros gobernados se comparan, no se suponen",
)

# VIVO PERO DESHABILITADO (hallazgo del revisor, reproducido): `is-active` no es `is-enabled`.
# Un servicio vivo que no arranca al reiniciar el invitado no está gobernado.
_SERVICIO_DESHABILITADO = _leer_servicio(
    _CON_CADDY, "active", "disabled", _FICHEROS_CADDY, motor.pagina_servicio(),
)
igual(
    [o["op"] for o in motor._servicio_canonico("caddy", _SERVICIO_DESHABILITADO)],
    ["enable_service"],
    "un servicio vivo pero DESHABILITADO se habilita: si no, no arranca al reiniciar el invitado "
    "(`is-active` no es `is-enabled`)",
)

# Un nombre fuera del vocabulario no produce decisión (el validador ya lo caza antes de tocar
# nada): el driver no inventa opciones para algo que no conoce.
igual(
    motor._servicio_canonico("nginx", _SERVICIO_FRESCO), [],
    "un servicio fuera del vocabulario no se decide aquí: el validador lo rechaza antes",
)
igual(motor.configuracion_servicio("nginx"), "", "y no hay configuración de motor para él")
igual(motor.lectura_servicio("nginx"), "", "ni lectura: no sabe qué preguntar de un desconocido")

# Y el camino ENTERO por `pasos_de_convergencia`: del invitado declarado salen los pasos del
# área, y `escrituras_linux` los traduce a comandos IDEMPOTENTES que la vía de acceso ejecuta.
_LEIDO_SERVICIO = {
    "alcanzable": True,
    "areas": {
        "tunnel": {"salida": "puesta"},
        "address": {"address": "10.60.0.20/24"},
        "servicio": _SERVICIO_FRESCO,
    },
}
_PASOS_SERVICIO = motor.pasos_de_convergencia(
    EQUIPO_SERVICIO, IDENTIDAD, DECLARACION, _LEIDO_SERVICIO, PARAMETROS
)
_ESCRITURAS_SERVICIO = motor.escrituras_linux(
    motor.operaciones_de_pasos(_PASOS_SERVICIO),
    EQUIPO_SERVICIO, DECLARACION, IDENTIDAD, PARAMETROS,
)
igual(
    [o["op"] for o in motor.operaciones_de_pasos(_PASOS_SERVICIO)],
    ["install_service", "write_service_config", "enable_service", "reload_service"],
    "del invitado declarado salen, en orden, las cuatro operaciones del área `servicio`",
)
comprobar(
    all(o["area"] == "servicio" for o in _ESCRITURAS_SERVICIO),
    "las escrituras del servicio están marcadas con su área (para el diario y para el error)",
)
comprobar(
    any("DEBIAN_FRONTEND=noninteractive apt-get install -y -qq caddy curl" in c["comando"]
        for c in _ESCRITURAS_SERVICIO),
    "instalar el servicio incluye `curl`: la relectura lo necesita para comprobar que sirve",
)
comprobar(
    any("apt-get update -qq" in c["comando"] for c in _ESCRITURAS_SERVICIO),
    "instalar el servicio REFRESCA las listas de apt antes: la imagen base las trae "
    "envejecidas y apuntan a versiones que ya no están (404, medido)",
)
comprobar(
    any("/etc/caddy/Caddyfile" in c["comando"] and "/var/www/html/index.html" in c["comando"]
        and "base64 -d" in c["comando"] for c in _ESCRITURAS_SERVICIO),
    "la configuración del servicio y su página se escriben con la MISMA orden (base64 -d)",
)
comprobar(
    any("systemctl enable --now caddy" in c["comando"] for c in _ESCRITURAS_SERVICIO)
    and any("systemctl restart caddy" in c["comando"] for c in _ESCRITURAS_SERVICIO),
    "el servicio se habilita/arranca y se recarga con systemd (su unidad, no un proceso suelto)",
)
comprobar(
    all(motor.pendiente_de_driver(o) is None
        for o in motor.operaciones_de_pasos(_PASOS_SERVICIO)),
    "el driver SABE traducir las cuatro operaciones del servicio (no queda ninguna pendiente)",
)

# Y que la REELECTURA no deja nada pendiente: con el invitado ya convergido, no hay paso.
_LEIDO_SERVICIO_AL_DIA = dict(
    _LEIDO_SERVICIO, areas=dict(_LEIDO_SERVICIO["areas"], servicio=_SERVICIO_AL_DIA)
)
igual(
    motor.pasos_de_convergencia(
        EQUIPO_SERVICIO, IDENTIDAD, DECLARACION, _LEIDO_SERVICIO_AL_DIA, PARAMETROS
    ),
    [],
    "releído y al día, el invitado declarado con `servicio` no deja ningún paso (convergió)",
)


# ---------------------------------------------------------------------------
# El SEGUNDO miembro del vocabulario: NetXMS (ADR 0028). Un servicio con DEPENDENCIAS -- base
# de datos y contenedor de servlets -- no cabe en la forma de `caddy`, y el motor no finge:
# si la base no está preparada, se prepara antes de arrancar (y si no, se pediría recargar
# para siempre con un servidor que no arranca).
# ---------------------------------------------------------------------------

_NETXMS_DIA = {
    "netxmsd": "/usr/bin/netxmsd",
    "nxdbmgr": "/usr/bin/nxdbmgr",
    "psql": "/usr/bin/psql",
    "curl": "/usr/bin/curl",
    "java": "/usr/bin/java",
}
_FICHEROS_NETXMS = list(motor._ficheros_servicio("netxms").values())
igual(
    list(motor._ficheros_servicio("netxms")),
    ["/etc/netxmsd.conf", motor.RUTA_DROPIN_NETXMS, motor.RUTA_PREPARADOR_NETXMS],
    "NetXMS gobierna TRES ficheros: su configuración, el `drop-in` que se la señala a systemd "
    "y el preparador de la base (en ese orden)",
)
comprobar(
    all(clave in _FICHEROS_NETXMS[0] for clave in ("DBDriver = pgsql", "DBLogin = netxms",
                                                   "DBHost = 127.0.0.1")),
    "su configuración dice DÓNDE está su base (driver, usuario y host): sin eso no hay servidor",
)
comprobar(
    all(clave in _FICHEROS_NETXMS[0] for clave in ("Module = webapi", "[WEBAPI]",
                                                   "Address = loopback", "Port = 8000")),
    "su configuración CARGA el módulo del API REST -- sin él sólo queda el `login` y los "
    "recursos contestan 404 -- y lo deja en LOOPBACK: quien use el API entra por túnel",
)
comprobar(
    "http://127.0.0.1:8000/v1/objects" in _FICHEROS_NETXMS[2]
    and '"$(api_web)" != "si"' in _FICHEROS_NETXMS[2],
    "la LECTURA pregunta por los RECURSOS del API (401/403 en `/v1/objects`) y no se fía del "
    "fichero: el fichero dice lo que se pidió, la respuesta dice lo que el servidor CARGÓ",
)
comprobar(
    "systemctl restart netxms-server" in _FICHEROS_NETXMS[2]
    and "reponer_clave" in _FICHEROS_NETXMS[2],
    "el preparador REINICIA sólo cuando falta el API (el módulo se lee al arrancar) y detrás "
    "repone la clave buena: ese arranque deja el hash en la forma que no verifica",
)
comprobar(
    all(pieza in _FICHEROS_NETXMS[2]
        for pieza in ('nxdbmgr -c /etc/netxmsd.conf -p "$ADMIN_CLAVE" init pgsql',
                      "createdb", "nxmc.war", "pg_isready")),
    "el preparador inicializa el ESQUEMA (el paquete no lo trae, y sin `-c` no encuentra la "
    "configuración) dejando puesta la clave del administrador EN EL `init` (`-p`: sin ella la "
    "genera al azar y la web no se podría entrar), crea la base y despliega la web",
)
comprobar(
    "ExecStart=/usr/bin/netxmsd -S -c /etc/netxmsd.conf" in _FICHEROS_NETXMS[1]
    and "\nExecStart=\n" in _FICHEROS_NETXMS[1],
    "el `drop-in` le dice a systemd DÓNDE está la configuración, y vacía `ExecStart` antes de "
    "redefinirlo (systemd acumula las líneas, y sin vaciar arrancaría dos veces el servidor)",
)

_SERVICIO_NETXMS_FRESCO = _leer_servicio(
    {h: "NO" for h in _NETXMS_DIA}, "inactive", "disabled", ["", "", ""], "NO-SIRVE",
    extra="no")
igual(
    [o["op"] for o in motor._servicio_canonico("netxms", _SERVICIO_NETXMS_FRESCO)],
    ["install_service", "write_service_config", "prepare_service", "enable_service",
     "reload_service"],
    "un NetXMS fresco pide, EN ESTE ORDEN, instalar, escribir, preparar la base, arrancar y "
    "dejarlo sirviendo (preparar va antes de arrancar: `nxdbmgr init` lee la configuración)",
)

_SERVICIO_NETXMS_AL_DIA = _leer_servicio(
    _NETXMS_DIA, "active", "enabled", _FICHEROS_NETXMS, "<html>login</html>", extra="si")
igual(
    motor._servicio_canonico("netxms", _SERVICIO_NETXMS_AL_DIA), [],
    "un NetXMS ya convergido NO produce operación: base inicializada, web sirviendo (regla 6)",
)

# La base se pierde (o nunca se inicializó) con el servidor VIVO y la web sirviendo: el motor
# no puede mirar sólo `is-active`, tiene que preguntar por el esquema.
igual(
    [o["op"] for o in motor._servicio_canonico(
        "netxms", dict(_SERVICIO_NETXMS_AL_DIA, extra="no"))],
    ["prepare_service"],
    "con la base sin esquema se pide PREPARAR aunque la unidad esté viva y la web conteste",
)

# Y la web que no contesta: se recarga el servicio (es lo que la levanta), sin tocar la base.
igual(
    [o["op"] for o in motor._servicio_canonico(
        "netxms", dict(_SERVICIO_NETXMS_AL_DIA, sirve=False))],
    ["reload_service"],
    "si la web no contesta, se recarga; la base preparada no se vuelve a preparar",
)

# Los comandos del segundo miembro: repositorio APT ajeno, preparador y web en el 8080.
_LEIDO_NETXMS = dict(_LEIDO_SERVICIO, areas=dict(_LEIDO_SERVICIO["areas"],
                                                 servicio=_SERVICIO_NETXMS_FRESCO))
_PASOS_NETXMS = motor.pasos_de_convergencia(
    EQUIPO_NETXMS, IDENTIDAD, DECLARACION, _LEIDO_NETXMS, PARAMETROS
)
_ESCRITURAS_NETXMS = motor.escrituras_linux(
    motor.operaciones_de_pasos(_PASOS_NETXMS), EQUIPO_NETXMS, DECLARACION, IDENTIDAD, PARAMETROS,
)
comprobar(
    all(motor.pendiente_de_driver(o) is None
        for o in motor.operaciones_de_pasos(_PASOS_NETXMS)),
    "el driver SABE traducir también las cinco operaciones de NetXMS (preparar incluida)",
)
comprobar(
    any("netxms-release" in c["comando"] and "apt-get update -qq" in c["comando"]
        for c in _ESCRITURAS_NETXMS),
    "instalar NetXMS añade su repositorio APT (no está en Debian) y refresca las listas después",
)
comprobar(
    any("netlabs-servicio-netxms preparar" in c["comando"] for c in _ESCRITURAS_NETXMS),
    "y la operación de preparar ejecuta el preparador que el motor dejó escrito",
)
comprobar(
    "/nxmc/" in motor.SERVICIOS_LINUX_OPCIONES["netxms"]["sirve"]
    and "8080" in motor.SERVICIOS_LINUX_OPCIONES["netxms"]["sirve"]
    and "-fsSL" in motor.SERVICIOS_LINUX_OPCIONES["netxms"]["sirve"],
    "NetXMS se comprueba SIRVIENDO la web (Tomcat en el 8080), no el puerto del servidor",
)

# La lectura de NetXMS, ya construida, pide lo suyo: sus herramientas, sus dos ficheros, la
# web y el estado de la base. Y la de `caddy` sigue pidiendo lo suyo (no se generalizó de más).
_ORDEN_NETXMS = motor.lectura_servicio("netxms")
comprobar(
    _ORDEN_NETXMS.count(motor.SEPARADOR) == 7
    and "systemctl is-active netxms-server" in _ORDEN_NETXMS
    and "cat /etc/netxmsd.conf" in _ORDEN_NETXMS
    and "estado" in _ORDEN_NETXMS,
    "la lectura de NetXMS lleva OCHO bloques: herramientas, vivo, habilitado, TRES "
    "ficheros, la web y el estado de la base",
)
_ORDEN_CADDY = motor.lectura_servicio("caddy")
comprobar(
    _ORDEN_CADDY.count(motor.SEPARADOR) == 6
    and "cat /etc/caddy/Caddyfile" in _ORDEN_CADDY
    and "http://127.0.0.1/" in _ORDEN_CADDY,
    "la de caddy sigue con SUS siete bloques: su configuración y su página, sin base ni web",
)
igual(
    motor.leido_linux([{"area": "servicio", "rc": 0, "encontrado": "a=1"}]),
    {},
    "una lectura a medias (sin sus bloques) NO se convierte en un estado inventado",
)

# ---------------------------------------------------------------------------
# LA VIGILANCIA: el área `monitorizacion`, y la pata de gestión que la publica
# ---------------------------------------------------------------------------
# Un servidor de vigilancia tiene que SABER a quién mira: si no, su árbol de nodos queda
# vacío y la web no enseña nada. El área `monitorizacion` es lo que se lo dice, y es una
# MARCA (como `uplink`): el lab declara QUE ese servidor vigila, y el CÓMO -- ronda la red
# por la que ve a los equipos -- es del motor. Y un invitado que publica un servicio (que se
# ENTRA en él) necesita la misma pata de gestión que el bastión, aunque no sea el bastión.
print("\nLA VIGILANCIA: el servidor sabe a quién mira, y sale por donde sale el nodo\n")

EQUIPO_VIGILANTE = dict(
    EQUIPO_NETXMS,
    config={"linux": {"tunnel": {}, "servicio": "netxms", "monitorizacion": {}}},
)
igual(
    motor.areas_de(EQUIPO_VIGILANTE)["monitorizacion"], {},
    "el área `monitorizacion` es una MARCA (`{}`), no lleva opciones: el cómo es del motor",
)
comprobar(
    "monitorizacion" in motor.areas_a_leer(EQUIPO_VIGILANTE)
    and "monitorizacion" in motor.areas_que_piden_visita(EQUIPO_VIGILANTE),
    "y pide ENTRAR al invitado: hay que leerlo para decidir si ya está sembrado",
)
_LECTURA_VIGILANCIA = [
    l for l in motor.lecturas_linux(EQUIPO_VIGILANTE) if l["area"] == "monitorizacion"
]
igual(
    len(_LECTURA_VIGILANCIA), 1,
    "un vigilante se pregunta UNA cosa: si ya sabe a quién mirar",
)
# El vigilante de verdad (el del lab 08) declara el área `routes` para llegar a las zonas: con
# ella, la lectura se pregunta CON la lista declarada como argumento. Sin ella, el motor no
# pasa lista ninguna y el guion cae a las rutas vivas -- eso lo prueba el caso de la relectura,
# más abajo, ejecutando el guion de verdad.
_VIGILANTE_CON_RUTAS = dict(
    EQUIPO_VIGILANTE,
    config={"linux": {
        "tunnel": {}, "servicio": "netxms", "monitorizacion": {},
        "routes": [{"dst_address": "10.44.1.0/24", "gateway": "10.44.0.12"}],
    }},
)
igual(
    [l for l in motor.lecturas_linux(_VIGILANTE_CON_RUTAS) if l["area"] == "monitorizacion"][0]["comando"],
    motor.SERVICIOS_LINUX_OPCIONES["netxms"]["monitorizacion"]["comando_objetivos"].format(
        objetivos=" ".join(motor.objetivos_declarados(motor.areas_de(_VIGILANTE_CON_RUTAS)))
    ),
    "con `routes` declaradas, se pregunta por el comando del SERVICIO con la lista DECLARADA de "
    "objetivos como argumento: así la lectura decide en la MISMA pasada, aunque las rutas aún no "
    "se hayan escrito (hallazgo P1, PR #14)",
)
igual(
    motor.leido_linux([{"area": "monitorizacion", "rc": 0, "encontrado": "si"}]),
    {"monitorizacion": {"sembrado": True}},
    "`si` es que ya está sembrado; cualquier otra cosa (o nada) es que no",
)
igual(
    motor.leido_linux([{"area": "monitorizacion", "rc": 0, "encontrado": "no"}]),
    {"monitorizacion": {"sembrado": False}},
    "y `no` es que todavía no",
)
igual(
    [o["op"] for o in motor._monitorizacion_canonica({}, {"sembrado": False}, "netxms")],
    ["sembrar_monitorizacion"],
    "un vigilante sin sembrar pide sembrar",
)
igual(
    motor._monitorizacion_canonica({}, {"sembrado": True}, "netxms"), [],
    "y un vigilante ya sembrado NO produce operación: es idempotente (regla 6)",
)
igual(
    motor._monitorizacion_canonica({}, {"sembrado": False}, "caddy"), [],
    "un servicio que no sabe vigilar no dispara un sembrado que nadie traduciría",
)
_ESCRITURAS_VIGILANCIA = motor.escrituras_linux(
    [{"op": "sembrar_monitorizacion", "servicio": "netxms"}],
    EQUIPO_VIGILANTE, DECLARACION, IDENTIDAD, PARAMETROS,
)
igual(
    [c["area"] for c in _ESCRITURAS_VIGILANCIA], ["monitorizacion"],
    "el sembrado se marca con su área (para el diario y para el error)",
)
comprobar(
    any("netlabs-servicio-netxms sembrar" in c["comando"] for c in _ESCRITURAS_VIGILANCIA),
    "y ejecuta el sembrado del servicio, que es quien sabe a quién mirar",
)

# La pata de gestión: la pide el bastión Y el que publica un servicio -- pero sólo el
# bastión se lleva, además, una pata por cada bridge del lab.
EQUIPO_PUBLICA = dict(
    EQUIPO_NETXMS, rol="monitor",
    bridge="vmb_gen", address="10.60.0.20/24", tipo="lxc",
    config={"linux": {"servicio": "netxms", "monitorizacion": {}}},
)
comprobar(
    not motor.tiene_tunnel(EQUIPO_PUBLICA) and motor.publica_servicio(EQUIPO_PUBLICA)
    and motor.necesita_pata_de_gestion(EQUIPO_PUBLICA),
    "un invitado que publica un servicio NO es el bastión, pero TAMBIÉN necesita la pata de gestión",
)
_ESTADO_PATA = {
    "bridges_direcciones": {"vmbr1": "10.10.10.1/24"},
    "direcciones_usadas": ["10.10.10.1/24", "10.10.10.254/24"],
}
_INTERFACES_PUBLICA = motor.interfaces_del_publicador(
    EQUIPO_PUBLICA, DECLARACION, _ESTADO_PATA, PARAMETROS,
)
igual(
    [i["bridge"] for i in _INTERFACES_PUBLICA], ["vmb_gen", "vmbr1"],
    "sus interfaces son LAS SUYAS más la salida: no se lleva una pata por cada bridge del lab",
)
igual(
    _INTERFACES_PUBLICA[0]["address"], "10.60.0.20/24",
    "la primera lleva la dirección que el lab declara",
)
igual(
    (_INTERFACES_PUBLICA[1]["address"], _INTERFACES_PUBLICA[1]["gateway"]),
    ("10.10.10.253/24", "10.10.10.1"),
    "y la salida es la del nodo, con su vía de acceso: por ahí se ENTRA en su web y se "
    "alcanza el repositorio para instalarla (la .254 ya estaba ocupada)",
)

# El preparador de NetXMS tiene que dejar una web ENTRABLE y saber sembrar. Sin las dos
# cosas, «vigila la red» sería una promesa sin respaldo: una web sin clave no se entra, y
# un servidor sin sembrar enseña un árbol vacío.
_PREPARADOR_NETXMS = motor._preparador_netxms()
comprobar(
    f'ADMIN_CLAVE="{motor.NETXMS_ADMIN["clave"]}"' in _PREPARADOR_NETXMS
    and '-p "$ADMIN_CLAVE" init' in _PREPARADOR_NETXMS,
    "el preparador PONE la clave del administrador en el `init` (`-p`): sin ella `nxdbmgr` "
    "genera una al azar y la web no se podría entrar",
)
comprobar(
    'set-user-password "$ADMIN"' not in _PREPARADOR_NETXMS,
    "y NO usa `set-user-password` para ponerla: pide la clave por el terminal y en un guion "
    "contesta «Cannot read password» (medido); `-p` en el `init` es la única forma sin manos",
)
comprobar(
    _PREPARADOR_NETXMS.index("systemctl stop netxms-server") < _PREPARADOR_NETXMS.index("-p \"$ADMIN_CLAVE\" init"),
    "y para el servidor ANTES de tocar la base: el paquete lo arranca al instalarse, y con él "
    "en marcha `nxdbmgr` contesta «Database is locked by server» y no aplica nada",
)
comprobar(
    "v1/login" in _PREPARADOR_NETXMS
    and "http_code" in _PREPARADOR_NETXMS
    and not any(l.strip().startswith("nxadm") for l in _PREPARADOR_NETXMS.splitlines()),
    "y `estado` no da el servicio por bueno si no se puede ENTRAR: la clave se comprueba "
    "autenticando por el API WEB (la puerta de la interfaz), y la CONSOLA no aparece en el "
    "servicio -- `nxadm` autentica bien y aun así deja la clave rota para la web (medido)",
)
_desde_preparar = _PREPARADOR_NETXMS[_PREPARADOR_NETXMS.rindex("systemctl daemon-reload"):]
comprobar(
    "se_entra" in _PREPARADOR_NETXMS
    and "drop database if exists" in _PREPARADOR_NETXMS
    and 0 <= _desde_preparar.index("systemctl start netxms-server")
    < _desde_preparar.index("systemctl stop netxms-server"),
    "y para preguntarle la clave a una web ya desplegada el motor ARRANCA el servidor (en un "
    "invitado nuevo el paquete lo deja caído) y sólo después lo para si hay que tocar la base "
    "-- con él en marcha la base está bloqueada --",
)
comprobar(
    "systemctl is-active --quiet netxms-server || systemctl start netxms-server"
    in _PREPARADOR_NETXMS,
    "y el servidor se ARRANCA al final SÓLO si no está ya arrancado: un reinicio de más no es "
    "inocuo (al arrancar, el paquete reescribe el hash del administrador y ese hash ya no "
    "verifica: medido), y un `preparar` que sólo para deja el servicio caído",
)
comprobar(
    'rm -f "$MARCA"' in _PREPARADOR_NETXMS,
    "y al rehacer la base se borra la marca del sembrado: una marca que sobrevive a su base "
    "diría «ya está sembrado» sobre una base sin un solo nodo",
)
comprobar(
    f"COMUNIDAD=\"{motor.COMUNIDAD_SNMP}\"" in _PREPARADOR_NETXMS
    and "DefaultCommunityString" in _PREPARADOR_NETXMS
    and "NetworkDiscovery.ActiveDiscovery.EnableSNMPProbing" in _PREPARADOR_NETXMS,
    "y le dice al servidor que PREGUNTE (descubrimiento activo) y con qué comunidad (la del motor)",
)
comprobar(
    "reponer_clave" in _PREPARADOR_NETXMS
    and "select password from users where id=1" in _PREPARADOR_NETXMS
    and _PREPARADOR_NETXMS.index("reponer_clave")
    < _PREPARADOR_NETXMS.index("drop database if exists")
    and 'reponer_clave\n' in _PREPARADOR_NETXMS
    and 'se_entra=$(entra)' in _PREPARADOR_NETXMS,
    "y un 'rechaza' se cura PRIMERO devolviendo el hash bueno que `init` dejó -- guardado aparte, "
    "sin tocar un solo dato -- y sólo después, si eso no basta, rehaciendo la base: rehacerla de "
    "entrada se llevaba por delante todo lo descubierto (medido: de 9 equipos a 3). Y tras "
    "reponer se VUELVE A PREGUNTAR: decidir con la respuesta vieja no vale (hallazgo P1, PR #13)",
)
comprobar(
    "clave_sql=$(mktemp)" in _PREPARADOR_NETXMS
    and "-f $clave_sql" in _PREPARADOR_NETXMS
    and 'chown postgres "$clave_sql"' in _PREPARADOR_NETXMS
    and 'buena=$(cat "$CLAVE_BUENA")' not in _PREPARADOR_NETXMS
    and "password='$buena'" not in _PREPARADOR_NETXMS,
    "y el valor de la clave NO viaja DENTRO de ninguna orden: `como_postgres` mete la cadena en "
    "`su postgres -c`, que es un SEGUNDO shell, y un hash que lleva `$` ($argon2id$v=19$…) salía "
    "de ahí con sus `$` expandidos a vacío -- la clave quedaba escrita como basura, el servidor "
    "la rechazaba y todo login contestaba 403: el área `servicio` no convergía NUNCA y la única "
    "salida aparente era tirar la base (medido; el patrón viejo reproducido en shell: "
    "password='='=19=65536''). Se escribe con `printf` -- que no re-expande -- a un fichero que "
    "psql lee con `-f`, y el fichero se borra en el acto",
)
comprobar(
    'if [ "$esquema_actual" != "si" ] || [ "$se_entra" = "rechaza" ]; then' in _PREPARADOR_NETXMS
    and "no-contesta" in _PREPARADOR_NETXMS,
    "y la sonda del API distingue TRES casos -- `si` / `rechaza` / `no-contesta` -- y sólo "
    "`rechaza` rehace la base: rehacerla porque el API aún no contesta (servidor arrancando) "
    "tiraba el descubrimiento entero (medido)",
)
comprobar(
    "4*)" in _PREPARADOR_NETXMS
    and _PREPARADOR_NETXMS.index("4*)") < _PREPARADOR_NETXMS.index("echo rechaza")
    and "repuesto" not in _PREPARADOR_NETXMS,
    "y una caída de conexión (000) o un 5xx NUNCA se toman por un rechazo de credenciales: sólo "
    "un 4xx -- el servidor CONTESTA y no acepta la clave -- llega al camino de rehacer la base",
)
comprobar(
    "reponer_clave" not in _PREPARADOR_NETXMS.split("entra() {")[1].split("\n}")[0]
    and "reponer_clave" in _PREPARADOR_NETXMS.split("preparar)")[1],
    "y la cura NO vive en `entra`, que es lo que llama la LECTURA: una lectura que reinicia el "
    "servicio o reescribe la clave deja de ser una lectura, y `verify` cambiaría el mundo que dice "
    "comprobar (hallazgo P1 del revisor, PR #16). Vive en `preparar`, que es quien escribe: allí un "
    "`rechaza` prueba el camino barato y sólo si eso no basta se rehace la base",
)
comprobar(
    _PREPARADOR_NETXMS.index("clave_sql=$(mktemp)")
    < _PREPARADOR_NETXMS.index("systemctl stop netxms-server")
    and _PREPARADOR_NETXMS.count("systemctl start netxms-server") >= 1,
    "y reponer la clave tiene el ORDEN que no deja al vigilante apagado: el fichero se escribe "
    "ANTES de parar el servicio -- si falla, no se ha tocado nada -- y el `systemctl start` va "
    "después y sin condición, para que un fallo de en medio no lo deje caído (hallazgo P1, PR #16)",
)
comprobar(
    "flags = flags & 247" in _PREPARADOR_NETXMS
    and "grace_logins = 5" in _PREPARADOR_NETXMS
    and 'where name = \'$ADMIN\'' in _PREPARADOR_NETXMS
    and _PREPARADOR_NETXMS.count("limpiar_entrada") >= 2,
    "y la ENTRADA se abre con la clave BUENA: el flag de cambiar la clave y las gracias son lo "
    "que cierra la puerta cuando se agotan (medido: 403 con `errorCode 61` y el hash correcto), y "
    "se limpian al inicializar la base y otra vez cuando el servidor rechaza la clave",
)
comprobar(
    _PREPARADOR_NETXMS.index("abrir_entrada\n        se_entra=$(entra)")
    < _PREPARADOR_NETXMS.index("reponer_clave\n            se_entra=$(entra)"),
    "y en un `rechaza` se prueba PRIMERO abrir la entrada y DESPUÉS reponer el hash: reponer la "
    "clave no arregla una puerta cerrada por el flag, así que el orden barato es el que converge",
)
comprobar(
    'salida=$(curl' in _PREPARADOR_NETXMS
    and '[ -n "$salida" ] || salida=000' in _PREPARADOR_NETXMS
    and "2>/dev/null || echo 000" not in _PREPARADOR_NETXMS,
    "y `respuesta_de_la_web` devuelve UN solo valor: el `|| echo 000` de antes añadía otro `000` "
    "al que `curl -w` ya imprime en una caída, y el lector recibía `000000` y lo tomaba por un "
    "rechazo (hallazgo P1, PR #13)",
)
comprobar(
    'if [ "$esquema_actual" = "error" ]; then' in _PREPARADOR_NETXMS
    and "salida=$(tablas) || { echo error; return 0; }" in _PREPARADOR_NETXMS
    and 'case "$nodos" in' in _PREPARADOR_NETXMS
    and '[ "$nodos" -gt 0 ]' in _PREPARADOR_NETXMS,
    "y la consulta del esquema distingue `error` de «vacía» (se aborta SIN tocar la base si "
    "falla), y el sembrado exige un entero > 0 antes de escribir su marca (hallazgos P1, PR #13)",
)
comprobar(
    "sembrar)" in _PREPARADOR_NETXMS
    and "vigilados" in _PREPARADOR_NETXMS
    and f'MARCA="{motor.RUTA_MARCA_SEMBRADO}"' in _PREPARADOR_NETXMS,
    "el sembrado espera a que los hallazgos del servidor estén en la base y deja su marca -- "
    "sin consola de por medio",
)
comprobar(
    "NetworkDiscovery.ActiveDiscovery.AddressRange $" not in _PREPARADOR_NETXMS
    and "NetworkDiscovery.ActiveDiscovery.Enabled 1" not in _PREPARADOR_NETXMS,
    "y el rango NO se declara con la variable `NetworkDiscovery.ActiveDiscovery.AddressRange` "
    "(ni con `...Enabled`): medido sobre la fuente de NetXMS 7.0, esas variables NO se leen, así "
    "que escribirla era una promesa sin respaldo -- los nodos que aparecían salían del "
    "descubrimiento pasivo (ARP), no de la ronda",
)
comprobar(
    "address_lists" in _PREPARADOR_NETXMS
    and "list_type = 1" in _PREPARADOR_NETXMS
    and "delete from address_lists where list_type = 1" in _PREPARADOR_NETXMS
    and "insert into address_lists" in _PREPARADOR_NETXMS,
    "el rango se ESCRIBE en la tabla `address_lists` (list_type=1, de donde NetXMS 7.0 SÍ toma "
    "los objetivos del descubrimiento activo): se borran las que el motor no declara y se ponen "
    "las declaradas (regla 17)",
)
comprobar(
    "objetivos()" in _PREPARADOR_NETXMS
    and "grep ' via '" in _PREPARADOR_NETXMS
    and "grep -v ' proto dhcp '" in _PREPARADOR_NETXMS
    and "awk '{print $1}'" in _PREPARADOR_NETXMS,
    "y las redes a vigilar son VARIAS y DERIVADAS: la propia (de la interfaz) y las de las rutas "
    "estáticas del invitado (las que pone el área `routes`) -- ninguna es un valor de lab, y el "
    "rango cubre las zonas a las que el vigilante tiene camino",
)
comprobar(
    "NetworkDiscovery.ActiveDiscovery.Interval 3600" in _PREPARADOR_NETXMS,
    "y el intervalo va en SEGUNDOS (3600 = una hora): el motor escribía «1» creyendo que eran "
    "horas, y en NetXMS 7.0 eran 1 SEGUNDO -- una ronda por segundo sobre redes ya no vacías",
)

# --- Los objetivos del descubrimiento: se EJECUTAN, no se leen como texto ----------------
# Los dos hallazgos del PR #14 no se arreglan con un comentario: se prueban con los VALORES
# que el guion de verdad produce. El banco de aquí abajo escribe el guion que el motor deja
# en el invitado y lo ejecuta con `ip`/`psql` falsos que devuelven las salidas REALES de los
# comandos. Así se comprueba la red Y la máscara que acaban en `address_lists`.
import subprocess as _subprocess
import tempfile as _tempfile


def _banco_preparador(rutas, direccion="10.44.0.10/24", codigo_curl="201", codigo_api="401"):
    """Un banco con `ip`/`psql`/`/su`/`curl` falsos; devuelve (guion, banco, marca).

    `direccion` es la que devuelve `ip addr show` (para probar la derivación de red con
    prefijos distintos de /24), `codigo_curl` lo que contesta el API web (para probar una
    caída, `000`) y `codigo_api` lo que contestan sus RECURSOS (`/v1/objects`): 401 es
    «módulo cargado», 404 «módulo sin cargar» -- la diferencia que vigila `estado`.
    Los ficheros `nodos`/`falla_nodos`/`falla_esquema` dentro del banco permiten
    fingir que la base contesta, que falla la consulta de equipos o la del esquema.
    """
    banco = _tempfile.mkdtemp(prefix="netlabs-preparador-")
    binario = os.path.join(banco, "bin")
    os.makedirs(binario)
    webapps = os.path.join(banco, "webapps")
    os.makedirs(webapps)
    with open(os.path.join(webapps, "nxmc.war"), "w", encoding="utf-8") as f:
        f.write("war")
    with open(os.path.join(banco, "rutas"), "w", encoding="utf-8") as f:
        f.write("\n".join(rutas) + "\n")
    with open(os.path.join(banco, "guardados"), "w", encoding="utf-8") as f:
        f.write("")

    def _falso(nombre, cuerpo):
        ruta = os.path.join(binario, nombre)
        with open(ruta, "w", encoding="utf-8") as f:
            f.write("#!/bin/sh\n" + cuerpo + "\n")
        os.chmod(ruta, 0o755)

    _falso("ip", 'case "$*" in\n'
                 f'  *"addr show"*) echo "2: eth0    inet {direccion} brd 10.44.0.255 scope global eth0" ;;\n'
                 '  *"route show"*) cat "$BANCO/rutas" ;;\n'
                 'esac')
    _falso("su", 'shift 2\nexec sh -c "$*"')
    _falso("psql", r'''printf '%s\n' "$*" >> "$BANCO/psql.log"
case "$*" in
  *"count(*) from nodes"*) [ -f "$BANCO/falla_nodos" ] && exit 1; cat "$BANCO/nodos" 2>/dev/null || echo "${NODOS:-3}" ;;
  *"information_schema.tables"*) [ -f "$BANCO/falla_esquema" ] && exit 1; echo 1 ;;
  *"flags, grace_logins"*) cat "$BANCO/puerta" 2>/dev/null || echo "0|5" ;;
  *"delete from address_lists"*) : > "$BANCO/guardados" ;;
  *"insert into address_lists"*) echo "$*" | sed -n "s/.*values (1, 0, 0, 0, 0, '\([^']*\)', '\([^']*\)',.*/\1|\2/p" >> "$BANCO/guardados" ;;
  *"from address_lists"*) cat "$BANCO/guardados" ;;
  *) exit 0 ;;
esac''')
    _falso("curl", f'''case "$*" in
  */v1/objects*) echo {codigo_api} ;;
  *) echo {codigo_curl} ;;
esac''')
    _falso("systemctl", 'printf \'%s\\n\' "$*" >> "$BANCO/systemctl.log"\nexit 0')
    _falso("sleep", "exit 0")
    _falso("nxdbmgr", 'printf \'%s\\n\' "$*" >> "$BANCO/nxdbmgr.log"\nexit 0')
    marca = os.path.join(banco, "sembrado")
    guion = _PREPARADOR_NETXMS.replace(
        'MARCA="%s"' % motor.RUTA_MARCA_SEMBRADO, 'MARCA="%s"' % marca
    ).replace(
        'WEBAPPS="%s"' % motor.NETXMS_WEBAPPS, 'WEBAPPS="%s"' % webapps
    )
    ruta_guion = os.path.join(banco, "netlabs-servicio-netxms")
    with open(ruta_guion, "w", encoding="utf-8") as f:
        f.write(guion)
    return ruta_guion, banco, marca


def _corre_preparador(guion, banco, verbo, *extra):
    entorno = dict(os.environ)
    entorno["PATH"] = os.path.join(banco, "bin") + ":" + entorno.get("PATH", "")
    entorno["BANCO"] = banco
    proceso = _subprocess.run(
        ["sh", guion, verbo, *extra], capture_output=True, text=True, env=entorno, timeout=60
    )
    return proceso.stdout.strip(), proceso.returncode


# P2: una ruta a un HOST sale de `ip route show` SIN `/32`; el destino sin barra es /32 y
# `addr2` (la máscara) tiene que ser "32", nunca la dirección entera. Se miran los VALORES
# que el guion escribe, no que el texto contenga cierta cadena.
_guion_p2, _banco_p2, _ = _banco_preparador([
    "10.44.0.0/24 dev eth0 proto kernel scope link src 10.44.0.10",
    "10.44.1.0/24 via 10.44.0.12 dev eth0 proto static",
    "10.44.5.7 via 10.44.0.12 dev eth0 proto static",
])
_salida_p2, _rc_p2 = _corre_preparador(_guion_p2, _banco_p2, "objetivos")
igual(
    sorted(_salida_p2.split()),
    ["10.44.0.0/24", "10.44.1.0/24", "10.44.5.7/32"],
    "un destino SIN barra se declara /32: la red y la máscara son valores distintos y válidos",
)
igual(_rc_p2, 0, "y el verbo de lectura termina bien con una ruta a un host")
_corre_preparador(_guion_p2, _banco_p2, "sembrar")
with open(os.path.join(_banco_p2, "psql.log"), encoding="utf-8") as _f:
    _log_p2 = _f.read()
comprobar(
    "'10.44.5.7', '32'" in _log_p2 and "'10.44.0.0', '24'" in _log_p2,
    "y lo que se INSERTA en `address_lists` es addr1='10.44.5.7', addr2='32' (no la dirección "
    "entera como máscara): NetXMS espera una máscara en addr2",
)

# P1: tras un despliegue correcto, si el `apply` cambia las rutas, la LECTURA tiene que
# notarlo y el motor tiene que volver a sembrar. Se prueba el guion de verdad: marca puesta,
# objetivos guardados viejos, rutas nuevas.
_guion_p1, _banco_p1, _ = _banco_preparador([
    "10.44.1.0/24 via 10.44.0.12 dev eth0 proto static",
])
_corre_preparador(_guion_p1, _banco_p1, "sembrar")
igual(
    _corre_preparador(_guion_p1, _banco_p1, "sembrado")[0], "si",
    "tras un despliegue correcto, `sembrado` dice `si`: los objetivos guardados son los de ahora",
)
igual(
    _corre_preparador(_guion_p1, _banco_p1, "estado")[0], "si",
    "y `estado` también: base, web, acceso y objetivos coinciden",
)

# Y la PUERTA: una base heredada con el flag de cambiar la clave (`flags=8`) y las gracias
# agotadas deja entrar MIENTRAS queden gracias, así que sólo la lectura de la puerta lo ve.
# Con el fichero `puerta` del banco se finge ese estado sin rehacer el guion.
with open(os.path.join(_banco_p1, "puerta"), "w", encoding="utf-8") as _f:
    _f.write("8|0\n")
igual(
    _corre_preparador(_guion_p1, _banco_p1, "estado")[0], "no",
    "y `estado` dice `no` con la PUERTA cerrada aunque se entre: el flag de cambiar la clave o "
    "las gracias agotadas se rompen en la pasada siguiente, así que la lectura los mira",
)
os.unlink(os.path.join(_banco_p1, "puerta"))
with open(os.path.join(_banco_p1, "rutas"), "w", encoding="utf-8") as _f:
    _f.write("10.44.2.0/24 via 10.44.0.13 dev eth0 proto static\n")
igual(
    _corre_preparador(_guion_p1, _banco_p1, "sembrado")[0], "no",
    "si las rutas cambian, `sembrado` deja de valer: la marca sola mentiría",
)
igual(
    _corre_preparador(_guion_p1, _banco_p1, "estado")[0], "no",
    "y el paso de LECTURA (`estado`) lo nota: pide volver a preparar en vez de dar el área por buena",
)
igual(
    [o["op"] for o in motor._monitorizacion_canonica({}, {"sembrado": False}, "netxms")],
    ["sembrar_monitorizacion"],
    "la decisión pura: con `sembrado` en `no`, el motor pide sembrar (no hay comentario que lo tape)",
)
_corre_preparador(_guion_p1, _banco_p1, "sembrar")
igual(
    _corre_preparador(_guion_p1, _banco_p1, "sembrado")[0], "si",
    "y tras sembrar con las rutas nuevas, vuelve a converger: los objetivos guardados son los de ahora",
)
igual(
    _corre_preparador(_guion_p1, _banco_p1, "estado")[0], "si",
    "y la segunda lectura ya no pide nada: dos pasadas seguidas dejan el mismo estado (regla 6)",
)

# P1, la parte que faltaba (hallazgo del revisor): la lectura corre ANTES de que se escriban las
# rutas. Si `estado`/`sembrado` comparasen contra las rutas de VERDAD, verían las viejas, dirían
# `si`, el `apply` no pediría reescribir los objetivos y el área acabaría la pasada con un
# pendiente: haría falta OTRA pasada. El motor le pasa la lista DECLARADA como argumento y la
# lectura decide con ella, así que converge en UNA sola pasada.
igual(
    motor.objetivos_declarados({
        "address": [{"interface": "eth0", "address": "10.44.0.20/24"}],
        "routes": [{"dst_address": "10.44.1.0/24", "gateway": "10.44.0.12"},
                   {"dst_address": "10.44.5.7", "gateway": "10.44.0.12"}],
    }),
    ["10.44.0.0/24", "10.44.1.0/24", "10.44.5.7/32"],
    "la lista DECLARADA de objetivos es la red de gestión y los destinos de las rutas (un host, /32)",
)
igual(
    motor.objetivos_declarados({"address": "dhcp", "routes": [{"dst_address": "10.0.0.0/8"}]}),
    ["10.0.0.0/8"],
    "con `address: dhcp` no se puede derivar la red de gestión: se pasa sólo lo que sí se sabe",
)
igual(
    motor.objetivos_declarados({"address": [{"interface": "eth0", "address": "dhcp"}]}),
    [],
    "y si no se puede derivar NADA, la lista va vacía: el guion cae a las rutas de verdad de siempre",
)
# P1 de la RELECTURA: si el lab fija la dirección pero no declara el área `routes`, la tabla
# del equipo se deja intacta, así que `preparar` guarda la red propia MÁS las rutas que el
# equipo ya tenía. La expectativa tiene que ser esa misma --la viva--: con la red propia sola,
# la comparación no cuadraba nunca y el motor volvía a preparar y sembrar en CADA pasada
# (rompía la idempotencia y dejaba `verify` con un pendiente eterno).
_SIN_RUTAS = {"address": [{"interface": "eth0", "address": "10.44.0.20/24"}]}
igual(
    motor.objetivos_declarados(_SIN_RUTAS), [],
    "sin área `routes` la expectativa NO se inventa: la decide el guion con las rutas vivas",
)
_guion_sr, _banco_sr, _ = _banco_preparador([
    "10.44.0.0/24 dev eth0 proto kernel scope link src 10.44.0.10",
    "10.44.1.0/24 via 10.44.0.12 dev eth0 proto static",
])
# Se siembra y se lee pasándole lo MISMO que le pasa el motor (la lista declarada como
# argumentos): es la única forma de que la prueba vea lo que ve el motor.
_corre_preparador(_guion_sr, _banco_sr, "sembrar", *motor.objetivos_declarados(_SIN_RUTAS))
igual(
    _corre_preparador(_guion_sr, _banco_sr, "sembrado", *motor.objetivos_declarados(_SIN_RUTAS))[0],
    "si",
    "sin área `routes`: tras sembrar, `sembrado` dice `si` -- las rutas vivas SON la expectativa",
)
igual(
    _corre_preparador(_guion_sr, _banco_sr, "estado", *motor.objetivos_declarados(_SIN_RUTAS))[0],
    "si",
    "y `estado` también: el área queda convergida y una segunda pasada no vuelve a preparar (regla 6)",
)
# P1 de la SEGUNDA relectura: quedarse SIN rutas (`routes: []`, lista explícita vacía) no es lo
# mismo que no declarar el área. El área SÍ se gestiona y va a quitar las rutas que haya, así que
# la expectativa es la red propia -- la VIVA en ese momento todavía tiene la ruta vieja, y contra
# esa la lectura diría `si` y dejaría sus redes en la lista para siempre.
igual(
    motor.objetivos_declarados({**_SIN_RUTAS, "routes": []}), ["10.44.0.0/24"],
    "con `routes: []` (el área se gestiona y se queda sin rutas) la expectativa SÍ es la red propia",
)
_guion_vr, _banco_vr, _ = _banco_preparador([
    "10.44.0.0/24 dev eth0 proto kernel scope link src 10.44.0.10",
    "10.44.1.0/24 via 10.44.0.12 dev eth0 proto static",
])
_corre_preparador(_guion_vr, _banco_vr, "sembrar")
_RUTAS_VACIAS = {**_SIN_RUTAS, "routes": []}
igual(
    _corre_preparador(_guion_vr, _banco_vr, "sembrado", *motor.objetivos_declarados(_RUTAS_VACIAS))[0],
    "no",
    "quitada la última ruta declarada, `sembrado` dice `no` AUNQUE la ruta vieja siga en el equipo: "
    "así se reescriben los objetivos en la MISMA pasada, antes de que el área borre la ruta",
)
igual(
    _corre_preparador(_guion_vr, _banco_vr, "estado", *motor.objetivos_declarados(_RUTAS_VACIAS))[0],
    "no",
    "y `estado` también: nada de dar por buena la lista vieja",
)
_guion_una, _banco_una, _ = _banco_preparador([
    "10.44.0.0/24 dev eth0 proto kernel scope link src 10.44.0.10",
    "10.44.1.0/24 via 10.44.0.12 dev eth0 proto static",
])
_corre_preparador(_guion_una, _banco_una, "sembrar")
_DECLARADA_NUEVA = "10.44.0.0/24 10.44.1.0/24 10.44.2.0/24"
# Se pasa IGUAL que el motor: la lista como ARGUMENTOS SEPARADOS, no entrecomillada (así se
# cazó que sólo se leía el primero).
igual(
    _corre_preparador(_guion_una, _banco_una, "sembrado", *_DECLARADA_NUEVA.split())[0], "no",
    "declarada una ruta NUEVA, `sembrado` contesta `no` AUNQUE las rutas del equipo todavía sean "
    "las viejas: es lo que hace que el motor lo pida en la MISMA pasada",
)
igual(
    _corre_preparador(_guion_una, _banco_una, "estado", *_DECLARADA_NUEVA.split())[0], "no",
    "y el paso de LECTURA (`estado`) también: pide volver a preparar en vez de dar el área por buena",
)
# El `apply` de verdad: primero se escriben las rutas declaradas (área `routes`) y después se
# siembra (área `monitorizacion`, que va después). Todo en la MISMA pasada.
with open(os.path.join(_banco_una, "rutas"), "w", encoding="utf-8") as _f:
    _f.write("10.44.0.0/24 dev eth0 proto kernel scope link src 10.44.0.10\n"
             "10.44.1.0/24 via 10.44.0.12 dev eth0 proto static\n"
             "10.44.2.0/24 via 10.44.0.13 dev eth0 proto static\n")
_corre_preparador(_guion_una, _banco_una, "sembrar")
igual(
    _corre_preparador(_guion_una, _banco_una, "sembrado", *_DECLARADA_NUEVA.split())[0], "si",
    "escritas las rutas nuevas y sembrado, la lectura con la declarada ya dice `si`: el área "
    "convergió en UNA sola pasada, sin necesidad de otra",
)
igual(
    _corre_preparador(_guion_una, _banco_una, "sembrado")[0], "si",
    "y la lectura A MANO (sin argumento) coincide: la lista derivada del equipo es la declarada",
)


# --- El área `latido`: aparecer sin que nadie te pregunte ------------------------------
# Lo que promete el área es UNA cosa: que el equipo se VEA. No configura nada suyo ni abre
# nada en la red -- da un toque a su pasarela, y con eso su MAC queda en la tabla ARP de su
# router, que es lo que el sondeo de la vigilancia LEE para encolar el nodo. Por eso lo que
# se prueba aquí es: que la MARCA (`{}`) basta como declaración, que armado no se toca, que
# un cambio de cadencia se nota, que lo que se escribe es lo que luego se lee (ida y vuelta)
# y que el toque NO sale del lab.
comprobar(
    [o["op"] for o in motor._latido_canonico({}, {})] == ["write_latido", "start_latido"],
    "`latido: {}` es una MARCA y basta para declararla: con el equipo sin nada puesto, el plan "
    "escribe el latido y lo arma. La marca es el diccionario VACÍO, así que tratar el vacío "
    "como «no declarado» sería un fallo SILENCIOSO: el invitado no se vería y el motor diría "
    "que ha convergido",
)
_ficheros_latido = motor.escrituras_latido("2min")
_LATIDO_ARMADO = {
    "activo": True, "habilitado": True,
    "ficheros_leidos": list(_ficheros_latido.values()),
}
igual(
    [o["op"] for o in motor._latido_canonico({}, _LATIDO_ARMADO)],
    [],
    "y con el latido ya armado (activo, habilitado y con sus TRES ficheros ENTEROS) no hay NADA "
    "que hacer: dos pasadas seguidas dejan el mismo estado (regla 6)",
)
igual(
    [o["op"] for o in motor._latido_canonico({"cada": "5min"}, _LATIDO_ARMADO)],
    ["write_latido", "start_latido"],
    "pero si el lab cambia la cadencia, el temporizador ya no coincide y se reescribe: mirando "
    "sólo que esté `active`, el motor diría «convergido» con la cadencia VIEJA puesta",
)
# Hallazgo P1: un latido ROTO tiene que verse. Antes `_latido_canonico` sólo miraba la MARCA del
# comentario del temporizador: si borraban el guion, o alguien editaba `OnUnitActiveSec` sin
# tocar el comentario, seguía diciendo «no hay trabajo» con el latido roto.
igual(
    [o["op"] for o in motor._latido_canonico({}, {
        "activo": True, "habilitado": True,
        "ficheros_leidos": [
            _ficheros_latido[f"/etc/systemd/system/{motor.UNIDAD_LATIDO}"],
            _ficheros_latido[f"/etc/systemd/system/{motor.UNIDAD_LATIDO_SERVICIO}"],
            "",  # el guion YA NO está (lo borraron)
        ],
    })],
    ["write_latido", "start_latido"],
    "y si el guion desaparece, el motor lo vuelve a escribir: leer sólo la marca lo dejaría roto "
    "y diría «convergido» (hallazgo P1, PR #13)",
)
igual(
    [o["op"] for o in motor._latido_canonico({}, {
        "activo": True, "habilitado": True,
        "ficheros_leidos": [
            _ficheros_latido[f"/etc/systemd/system/{motor.UNIDAD_LATIDO}"]
            .replace("OnUnitActiveSec=2min", "OnUnitActiveSec=9min"),
            _ficheros_latido[f"/etc/systemd/system/{motor.UNIDAD_LATIDO_SERVICIO}"],
            _ficheros_latido[motor.RUTA_LATIDO],
        ],
    })],
    ["write_latido", "start_latido"],
    "y si alguien edita `OnUnitActiveSec` sin tocar el comentario, también: se compara el "
    "temporizador ENTERO, no la marca del comentario (hallazgo P1, PR #13)",
)
# Lectura REAL: el comando del área trae los TRES ficheros separados por `SEPARADOR`, y
# `leido_linux` los junta. El ida y vuelta -- lo que el motor escribe es lo que el lector saca --
# es lo que hace que la segunda pasada salga limpia.
_leido_latido = motor.leido_linux([{
    "area": "latido", "rc": 0,
    "encontrado": ("active\nenabled\n" + motor.SEPARADOR + "\n"
                   + _ficheros_latido[f"/etc/systemd/system/{motor.UNIDAD_LATIDO}"]
                   + motor.SEPARADOR + "\n"
                   + _ficheros_latido[f"/etc/systemd/system/{motor.UNIDAD_LATIDO_SERVICIO}"]
                   + motor.SEPARADOR + "\n"
                   + _ficheros_latido[motor.RUTA_LATIDO]),
}])
igual(
    [o["op"] for o in motor._latido_canonico({}, _leido_latido["latido"])],
    [],
    "y lo que el LECTOR saca de un latido sano coincide con lo que el motor escribe: si "
    "divergieran, reescribiría siempre y el lab nunca convergería",
)
comprobar(
    set(_ficheros_latido) == {motor.RUTA_LATIDO,
                              f"/etc/systemd/system/{motor.UNIDAD_LATIDO}",
                              f"/etc/systemd/system/{motor.UNIDAD_LATIDO_SERVICIO}"},
    "el latido son TRES ficheros y ninguno sobra: el guion que da el toque, la unidad que lo "
    "ejecuta una vez y el temporizador que lo repite",
)
_guion = _ficheros_latido[motor.RUTA_LATIDO]
comprobar(
    "ping -c 1" in _guion and "$PUERTA" in _guion and "route show default" in _guion
    and "8.8.8.8" not in _guion and "http" not in _guion,
    "el toque va a la PASARELA (sacada de la ruta por defecto) y no a internet: el trabajo lo "
    "hace la pregunta por la MAC, que ocurre igual -- y así el latido se queda dentro de la "
    "red del lab y funciona con el cortafuegos en `drop` y sin salida",
)

# --- El área `routes` de un Linux: el camino, declarado por el lab ----------------------
igual(
    [o["op"] for o in motor._routes_canonicas(
        [{"dst_address": "10.44.1.0/24", "gateway": "10.44.0.11"}], {"estaticas": []}, gobierna_por_defecto=False, persistir=False)],
    ["add_route"],
    "una ruta declarada que no está, se pone: es el camino a las zonas que el lab le da al "
    "bastión -- sin él el motor no llega a los invitados que el lab pone detrás de un fw",
)
igual(
    [o["op"] for o in motor._routes_canonicas(
        [{"dst_address": "10.44.1.0/24", "gateway": "10.44.0.11"}],
        {"estaticas": [{"dst_address": "10.44.1.0/24", "gateway": "10.44.0.11"}]}, gobierna_por_defecto=False, persistir=False)],
    [],
    "y puesta, no se toca: la lectura saca el mismo par (destino, pasarela) que se declaró, "
    "así que la segunda pasada no hace nada (regla 6)",
)
igual(
    [o["op"] for o in motor._routes_canonicas(
        [], {"estaticas": [{"dst_address": "10.44.9.0/24", "gateway": "10.44.0.11"}]}, gobierna_por_defecto=False, persistir=False)],
    ["remove_route"],
    "y dentro de un área declarada, lo que no está en el YAML se quita (regla 17): una ruta "
    "estática que sobra se va -- el área gobierna lo que declara, ni más ni menos",
)
comprobar(
    "routes" in _validador.AREAS_QUE_NO_LE_TOCAN["ctl"].get("routeros", {})
    and "routes" not in _validador.AREAS_QUE_NO_LE_TOCAN["ctl"].get("*", {}),
    "y un `ctl` SÍ puede declarar `routes` con su LINUX (el vigilante necesita el camino a las "
    "zonas detrás de los `fw`): la prohibición de enrutar está acotada a su interior RouterOS, "
    "igual que la de repartir direcciones",
)
comprobar(
    bool(_validador.CADENCIA_PATRON.match("2min")) and bool(_validador.CADENCIA_PATRON.match("30s"))
    and not _validador.CADENCIA_PATRON.match("cinco")
    and not _validador.CADENCIA_PATRON.match("2 minutos"),
    "y la cadencia del lab se valida con su patrón (número y unidad: `30s`, `2min`, `1h`): un "
    "«cada: cinco» no llega nunca a systemd, que no armaría el temporizador y dejaría al "
    "invitado fuera de la topología sin decir por qué",
)

# --- Los hallazgos P1 del PR #13, uno por uno --------------------------------------------
# Cada arreglo entra con su prueba, y la prueba tiene que CAZAR el fallo: se escribe, se revierte
# el arreglo a mano, se comprueba que FALLA, y se vuelve a poner.

# 5. Instalar el servicio (`servicio: netxms`) NO debe empezar a vigilar: los ajustes de
#    descubrimiento viven DETRÁS del área `monitorizacion`, no en `preparar`. Con el caso
#    `sembrar` seccionado, se mira que `preparar` no los encienda y que el verbo `sembrar` sí.
_caso_sembrar = _PREPARADOR_NETXMS.index("sembrar)")
comprobar(
    "NetworkDiscovery.Type 3" not in _PREPARADOR_NETXMS[:_caso_sembrar]
    and "NetworkDiscovery.Type 3" in _PREPARADOR_NETXMS[_caso_sembrar:]
    and "DefaultCommunityString" not in _PREPARADOR_NETXMS[:_caso_sembrar],
    "instalar el servicio NO enciende el descubrimiento: sus ajustes viven DETRÁS del área "
    "`monitorizacion` (`sembrar`), no en `preparar` (hallazgo P1, PR #13) -- el lab 10, que "
    "sólo declara `servicio: netxms`, no debe empezar a peinar su red cada hora",
)
_guion_solo, _banco_solo, _ = _banco_preparador(["10.44.0.0/24 dev eth0 proto kernel scope link src 10.44.0.10"])
_, _rc_solo = _corre_preparador(_guion_solo, _banco_solo, "preparar")
_log_nx_solo = ""
if os.path.exists(os.path.join(_banco_solo, "nxdbmgr.log")):
    with open(os.path.join(_banco_solo, "nxdbmgr.log"), encoding="utf-8") as _f:
        _log_nx_solo = _f.read()
igual(
    _corre_preparador(_guion_solo, _banco_solo, "estado")[0], "si",
    "y un invitado con el servicio puesto y la base sana ya está CONVERGIDO sin descubrimiento: "
    "`estado` no compara objetivos si el motor nunca sembró (nada que mirar, servicio servido)",
)
comprobar(
    "NetworkDiscovery" not in _log_nx_solo and _rc_solo == 0,
    "y `preparar` no deja ni un ajuste de descubrimiento en el servidor: lo enciende `sembrar`",
)

# 6. La red del descubrimiento se deriva de la dirección COMPLETA y su prefijo, no de un /24 fijo.
igual(motor.red_de_direccion("10.44.1.20/16"), "10.44.0.0/16",
      "la red se deriva del prefijo COMPLETO: un invitado en /16 no escanea sólo su /24")
igual(motor.red_de_direccion("10.44.1.20/24"), "10.44.1.0/24", "y un /24 da su red, como antes")
igual(motor.red_de_direccion("10.44.1.130/25"), "10.44.1.128/25",
      "y una red más fina (/25) enmascara de verdad: no se escanea media red de más")
igual(motor._red_propia("10.44.1.20/16"), "10.44.0.0/16",
      "`_red_propia` (lo declarado) usa la MISMA regla, para que las dos formas comparen el mismo hecho")
igual(motor.red_de_direccion("sin-prefijo"), "", "y sin prefijo no se inventa una red")
_guion_r16, _banco_r16, _ = _banco_preparador(
    ["10.44.0.0/16 dev eth0 proto kernel scope link src 10.44.1.20"], direccion="10.44.1.20/16")
igual(
    sorted(_corre_preparador(_guion_r16, _banco_r16, "objetivos")[0].split()), ["10.44.0.0/16"],
    "y el guion de verdad deriva `10.44.0.0/16` de una dirección /16 (antes escribía `10.44.1.0/24`)",
)

# 9 y 10. `default`/`0.0.0.0/0` y host-sin-barra/`/32` son el MISMO hecho: se normalizan antes
# de comparar. Sin esto, el motor pedía la ruta en CADA pasada y borraba la que acababa de poner.
igual(
    [o["op"] for o in motor._routes_canonicas(
        [{"dst_address": "0.0.0.0/0", "gateway": "10.44.0.1"}],
        {"estaticas": [{"dst_address": "default", "gateway": "10.44.0.1"}]}, gobierna_por_defecto=False, persistir=False)],
    [],
    "una ruta por defecto declarada `0.0.0.0/0` y leída como `default` son la misma ruta",
)
igual(
    [o["op"] for o in motor._routes_canonicas(
        [{"dst_address": "10.44.1.5/32", "gateway": "10.44.0.12"}],
        {"estaticas": [{"dst_address": "10.44.1.5", "gateway": "10.44.0.12"}]}, gobierna_por_defecto=False, persistir=False)],
    [],
    "y una ruta a un HOST (`/32`) y su forma sin barra también: no se borra la que se acaba de poner "
    "(hallazgos P1, PR #13)",
)
igual(
    [o["op"] for o in motor._routes_canonicas(
        [], {"estaticas": [{"dst_address": "default", "gateway": "10.44.0.1"}]}, gobierna_por_defecto=False, persistir=False)],
    [],
    "y una ruta por defecto NO se quita aunque no se declare: en un Linux la pone la plataforma "
    "al crear el invitado y el motor no la posee -- borrarla lo dejaría sin internet antes de "
    "instalar nada (hallazgo P1, PR #13). El área gobierna las rutas que SÍ declara, no la salida "
    "que le dieron",
)

# 11. La lectura comprueba el `rc` de `ip` ANTES de filtrar: una tabla ilegible no se confunde
# con una tabla sin rutas.
comprobar(
    'ip -4 route show > "$r"' in motor.LECTURAS_LINUX["routes"]["comando"]
    and "exit 1" in motor.LECTURAS_LINUX["routes"]["comando"],
    "el `ip route show` de la lectura COMPRUEBA su código de salida antes de filtrar: antes "
    "`|| true` lo ocultaba y una tabla ilegible se leía como una sin rutas (hallazgo P1, PR #13)",
)
igual(motor.leido_linux([{"area": "routes", "rc": 2, "encontrado": ""}]), {},
     "y una lectura del área `routes` con rc != 0 no se convierte en un estado inventado")
# Y de verdad: si `ip route show` FALLA, el comando de lectura devuelve ESE fallo; si sale bien
# sin rutas, devuelve 0. Antes el `|| true` hacía las dos cosas indistinguibles para el driver.
_lectura_bin = os.path.join(_tempfile.mkdtemp(prefix="netlabs-lectura-"), "bin")
os.makedirs(_lectura_bin)
for _nombre, _cuerpo in (
        ("ip-falla", 'case "$*" in\n  *"route show"*) exit 7 ;;\nesac\nexit 0'),
        ("ip-vacia", 'case "$*" in\n  *"route show"*) exit 0 ;;\nesac\nexit 0')):
    with open(os.path.join(_lectura_bin, _nombre), "w", encoding="utf-8") as _f:
        _f.write("#!/bin/sh\n" + _cuerpo + "\n")
    os.chmod(os.path.join(_lectura_bin, _nombre), 0o755)
os.symlink(os.path.join(_lectura_bin, "ip-falla"), os.path.join(_lectura_bin, "ip"))
_r = _subprocess.run(["sh", "-c", motor.LECTURAS_LINUX["routes"]["comando"]],
                     env=dict(os.environ, PATH=_lectura_bin + ":" + os.environ.get("PATH", "")),
                     capture_output=True, text=True)
comprobar(_r.returncode != 0,
      "y el comando de lectura DEVUELVE el fallo de `ip route show` (rc != 0): una tabla ilegible "
      "no se confunde con una sin rutas (hallazgo P1, PR #13)")
os.remove(os.path.join(_lectura_bin, "ip"))
os.symlink(os.path.join(_lectura_bin, "ip-vacia"), os.path.join(_lectura_bin, "ip"))
_r = _subprocess.run(["sh", "-c", motor.LECTURAS_LINUX["routes"]["comando"]],
                     env=dict(os.environ, PATH=_lectura_bin + ":" + os.environ.get("PATH", "")),
                     capture_output=True, text=True)
igual(_r.returncode, 0,
      "y una tabla SIN rutas estáticas da rc 0: cero coincidencias es legítimo, no una avería")

# 8. Las rutas se dejan ESCRITAS para el próximo arranque: `ip route replace` sólo cambia la
# tabla en marcha, y un reinicio del invitado se llevaba el camino a las zonas.
_persist_rutas = motor.rutas_persistentes([{"dst_address": "10.44.1.0/24", "gateway": "10.44.0.12"}])
comprobar(
    set(_persist_rutas) == {motor.RUTA_RUTAS, f"/etc/systemd/system/{motor.UNIDAD_RUTAS}"}
    and "ip route replace 10.44.1.0/24 via 10.44.0.12 proto static" in _persist_rutas[motor.RUTA_RUTAS]
    and f"ExecStart={motor.RUTA_RUTAS}" in _persist_rutas[f"/etc/systemd/system/{motor.UNIDAD_RUTAS}"],
    "las rutas del área se dejan ESCRITAS (un guion que las repone + una unidad que lo corre al "
    "arrancar): `add_route` sólo cambiaba la tabla en marcha (hallazgo P1, PR #13)",
)
_escrituras_ruta = motor.escrituras_linux(
    [{"op": "add_route", "dst_address": "10.44.1.0/24", "gateway": "10.44.0.12"}],
    _VIGILANTE_CON_RUTAS, DECLARACION, IDENTIDAD, PARAMETROS)
comprobar(
    any(c["area"] == "routes" and motor.RUTA_RUTAS in c["comando"] for c in _escrituras_ruta)
    and any("systemctl enable" in c["comando"] for c in _escrituras_ruta),
    "y cuando el área toca alguna ruta, el ejecutor deja los ficheros y habilita la unidad",
)
comprobar(
    not any(c["area"] == "routes" for c in motor.escrituras_linux(
        [{"op": "add_address", "interface": "eth0", "address": "10.44.0.20/24"}],
        _VIGILANTE_CON_RUTAS, DECLARACION, IDENTIDAD, PARAMETROS)),
    "y sin operaciones de rutas no se reescriben los ficheros: la segunda pasada sigue siendo "
    "`changed=0` (regla 6)",
)

# 12. Las comunidades SNMP ilegibles ya no pasan: se miran los PERMISOS, no sólo el nombre.
igual(
    motor._snmp_canonico({}, {
        "habilitado": True, "comunidades": ["netlabs"],
        "comunidades_detalle": [{"name": "netlabs", "read": True, "comment": "netlabs-snmp", "id": "*1"}]}),
    [], "una comunidad del motor CON lectura no produce trabajo (regla 6)",
)
igual(
    [(o["op"], o.get("id")) for o in motor._snmp_canonico({}, {
        "habilitado": True, "comunidades": ["netlabs"],
        "comunidades_detalle": [{"name": "netlabs", "read": False, "comment": "netlabs-snmp", "id": "*1"}]})],
    [("set_snmp_community", "*1")],
    "una comunidad del motor con la lectura APAGADA se REPARA por su identificador: antes pasaba "
    "por buena y el colector no podía leer el equipo (hallazgo P1, PR #13)",
)
_snmp_conflicto = False
try:
    motor._snmp_canonico({}, {
        "habilitado": True, "comunidades": ["netlabs"],
        "comunidades_detalle": [{"name": "netlabs", "read": False, "comment": "de otro", "id": "*2"}]})
except motor.ErrorMotor:
    _snmp_conflicto = True
comprobar(
    _snmp_conflicto,
    "y una comunidad llamada `netlabs` SIN lectura y SIN la marca del motor INFORMA del conflicto "
    "y NO se toca (regla 17: no es del área)",
)
igual(
    [o["op"] for o in motor._snmp_canonico({}, {
        "habilitado": False, "comunidades": [], "comunidades_detalle": []})],
    ["enable_snmp", "add_snmp_community"],
    "y un equipo sin agente ni comunidad pide encender y añadir la del motor",
)

# 1 y 3. Una CAÍDA de la API (curl `000`) NO debe rehacer la base: se clasifica `no-contesta`
# y el esquema se lee bien, así que no hay DROP. Y si la CONSULTA del esquema falla, se ABORTA.
_guion_caida, _banco_caida, _ = _banco_preparador(
    ["10.44.0.0/24 dev eth0 proto kernel scope link src 10.44.0.10"], codigo_curl="000",
    codigo_api="000")
_corre_preparador(_guion_caida, _banco_caida, "preparar")
with open(os.path.join(_banco_caida, "psql.log"), encoding="utf-8") as _f:
    _log_caida = _f.read().lower()
comprobar(
    "drop database" not in _log_caida,
    "una caída de la API (000) NO rehace la base: el `000000` de antes se tomaba por un rechazo "
    "y un `DROP DATABASE` se llevaba los nodos descubiertos (hallazgo P1, PR #13)",
)
_guion_esq, _banco_esq, _ = _banco_preparador(["10.44.0.0/24 dev eth0 proto kernel scope link src 10.44.0.10"])
with open(os.path.join(_banco_esq, "falla_esquema"), "w", encoding="utf-8") as _f:
    _f.write("x")
_, _rc_esq = _corre_preparador(_guion_esq, _banco_esq, "preparar")
with open(os.path.join(_banco_esq, "psql.log"), encoding="utf-8") as _f:
    _log_esq = _f.read().lower()
comprobar(
    _rc_esq != 0 and "drop database" not in _log_esq,
    "y si la CONSULTA del esquema FALLA se aborta SIN tocar la base: un `no` de una consulta caída "
    "no significa «vacía» (hallazgo P1, PR #13)",
)

# El MÓDULO del API REST: /v1/objects contesta 404 sin él y 401 con él. Es la prueba que
# distingue «lo pedí» de «lo cargó», y la única forma de que `estado` note que falta.
_guion_mod, _banco_mod, _ = _banco_preparador(
    ["10.44.0.0/24 dev eth0 proto kernel scope link src 10.44.0.10"], codigo_api="404")
igual(
    _corre_preparador(_guion_mod, _banco_mod, "estado")[0], "no",
    "sin el módulo del API (404 en `/v1/objects`) el área NO está servida, aunque la base y la "
    "web sí: el API a medias no es el API",
)
igual(_corre_preparador(_guion_mod, _banco_mod, "api")[0], "no",
      "y el verbo `api` lo dice sin tocar nada")
_corre_preparador(_guion_mod, _banco_mod, "preparar")
with open(os.path.join(_banco_mod, "systemctl.log"), encoding="utf-8") as _f:
    _log_mod = _f.read()
comprobar(
    "restart netxms-server" in _log_mod,
    "`preparar` REINICIA el servidor cuando falta el módulo: la configuración se lee al arrancar, "
    "y sin reinicio el módulo no se cargaría NUNCA",
)
_guion_api, _banco_api, _ = _banco_preparador(
    ["10.44.0.0/24 dev eth0 proto kernel scope link src 10.44.0.10"])
igual(_corre_preparador(_guion_api, _banco_api, "api")[0], "si",
      "con 401 en `/v1/objects` el API está cargado y el verbo dice `si`")
_corre_preparador(_guion_api, _banco_api, "preparar")
with open(os.path.join(_banco_api, "systemctl.log"), encoding="utf-8") as _f:
    _log_api = _f.read()
comprobar(
    "restart netxms-server" not in _log_api,
    "y con el módulo ya cargado NO reinicia: un arranque de más es lo que dejaba la clave rota",
)

# 4. El sembrado NO escribe su marca sin confirmar un entero > 0 de equipos vigilados.
for _caso in ("cero", "fallo"):
    _guion_s4, _banco_s4, _marca_s4 = _banco_preparador(
        ["10.44.0.0/24 dev eth0 proto kernel scope link src 10.44.0.10"])
    _fingido = os.path.join(_banco_s4, "nodos" if _caso == "cero" else "falla_nodos")
    with open(_fingido, "w", encoding="utf-8") as _f:
        _f.write("0\n" if _caso == "cero" else "x")
    _, _rc_s4 = _corre_preparador(_guion_s4, _banco_s4, "sembrar")
    comprobar(
        _rc_s4 != 0 and not os.path.exists(_marca_s4),
        f"el sembrado NO escribe su marca con {_caso} equipos vigilados (ni con la consulta "
        "fallida): antes, una consulta fallida dejaba el recuento VACÍO, la cadena vacía no es `0` "
        "y marcaba sin haber confirmado nada (hallazgo P1, PR #13)",
    )

# Y a nivel de DRIVER, que es donde el TIPO DE EQUIPO decide quién posee la ruta por defecto: un
# Linux al que la plataforma le puso su salida no la pierde aunque el lab no la declare. Se prueba
# aquí porque el error cómodo al arreglarlo --equivocar el sitio de llamada-- ninguna prueba de la
# función lo caza: la función recibe el dueño ya decidido (y ya me mordió dos veces, PR #13).
CONTROL_SOLO_RUTAS = dict(CONTROL, config={"linux": {
    "routes": [{"dst_address": "10.44.1.0/24", "gateway": "10.44.0.12"}],
}})
# La lectura del área `routes` de un Linux, tal y como la devuelve el motor: la tabla EN MARCHA
# en el primer bloque y, detrás, los DOS artefactos que la reponen al arrancar y si la unidad
# está habilitada. Construirla aquí es lo que hace que la prueba mire lo que el motor mira.
def _leido_rutas_linux(lineas_rutas, ficheros=None, habilitada=True):
    partes = ["\n".join(lineas_rutas)]
    partes += list(ficheros) if ficheros is not None else ["SIN-FICHERO", "SIN-FICHERO"]
    partes.append("enabled" if habilitada else "disabled")
    return motor.leido_linux([
        {"area": "address", "rc": 0,
         "encontrado": "2: eth0    inet 10.60.0.10/24 brd 10.60.0.255 scope global eth0\n"},
        {"area": "routes", "rc": 0, "encontrado": motor.SEPARADOR.join(partes)},
    ])


_RUTAS_CONTROL = [{"dst_address": "10.44.1.0/24", "gateway": "10.44.0.12"}]
# Los dos artefactos EN EL ORDEN EN QUE LOS DEVUELVE LA LECTURA -- el guion primero, la unidad
# después --, no en el que los tenga dentro `rutas_persistentes`: fiarse de ese orden fue el fallo
# que dejó al `monitor` del 08 sin converger jamás, y esta prueba lo tenía igual de escondido.
_FICHEROS_RUTAS = motor.rutas_persistentes(_RUTAS_CONTROL)
_FICHEROS_RUTAS = [_FICHEROS_RUTAS[motor.RUTA_RUTAS],
                   _FICHEROS_RUTAS["/etc/systemd/system/" + motor.UNIDAD_RUTAS]]
igual(
    motor.pasos_de_convergencia(CONTROL_SOLO_RUTAS, IDENTIDAD, DECLARACION, {
        "alcanzable": True,
        "areas": _leido_rutas_linux(["10.44.1.0/24 via 10.44.0.12 dev eth0",
                                     "default via 10.60.0.1 dev eth0"], _FICHEROS_RUTAS),
    }, PARAMETROS),
    [],
    "un Linux CONVERGIDO no genera ni un paso: ni por la tabla, ni por los ficheros que la "
    "repiten al arrancar, ni por la ruta por defecto que le puso la plataforma",
)
igual(
    [p["parametros"]["operaciones"] for p in motor.pasos_de_convergencia(
        CONTROL_SOLO_RUTAS, IDENTIDAD, DECLARACION, {
            "alcanzable": True,
            "areas": _leido_rutas_linux(["default via 10.60.0.1 dev eth0"]),
        }, PARAMETROS)],
    [[{"op": "add_route", "dst_address": "10.44.1.0/24", "gateway": "10.44.0.12"},
      {"op": "write_routes"}]],
    "y si le faltan la ruta y los ficheros, se pone ESA ruta y se dejan escritos los dos "
    "artefactos: la tabla sola no sobrevive a un reinicio",
)
igual(
    [p["parametros"]["operaciones"] for p in motor.pasos_de_convergencia(
        CONTROL_SOLO_RUTAS, IDENTIDAD, DECLARACION, {
            "alcanzable": True,
            "areas": _leido_rutas_linux(["10.44.1.0/24 via 10.44.0.12 dev eth0"],
                                        _FICHEROS_RUTAS, habilitada=False),
        }, PARAMETROS)],
    [[{"op": "write_routes"}]],
    "y con la tabla PERFECTA y la unidad deshabilitada se repara igual: el fallo que cazó el "
    "revisor era justo ése -- la tabla ya coincidía y el apply no tocaba nada, así que un "
    "reinicio se llevaba el camino a las zonas y el vigilante se quedaba ciego",
)
igual(
    motor._routes_canonicas(
        _RUTAS_CONTROL,
        {"estaticas": _RUTAS_CONTROL, "habilitada": True, "ficheros_leidos": _FICHEROS_RUTAS},
        gobierna_por_defecto=False, persistir=True,
    ),
    [],
    "con la tabla y los ficheros en su sitio, el área de rutas de un Linux no tiene nada que hacer",
)
igual(
    [o["op"] for o in motor._routes_canonicas(
        _RUTAS_CONTROL,
        {"estaticas": _RUTAS_CONTROL, "habilitada": False, "ficheros_leidos": []},
        gobierna_por_defecto=False, persistir=True)],
    ["write_routes"],
    "y con los ficheros perdidos pide reponerlos AUNQUE la tabla ya coincida",
)
igual(
    [o["op"] for o in motor._routes_canonicas(
        _RUTAS_CONTROL,
        {"estaticas": _RUTAS_CONTROL, "habilitada": False, "ficheros_leidos": []},
        gobierna_por_defecto=True, persistir=False)],
    [],
    "y en un ROUTER no: ahí su configuración la guarda el equipo, no el motor",
)

# Y la red del guion, EJECUTADA de verdad. El revisor dijo que el guion «descarta el prefijo y
# siempre peina un /24»: se reprodujo ejecutando su función y era peor -- acertaba sólo cuando el
# trozo de octeto era una potencia de dos -- y aquí queda atada a la del motor, caso por caso.
_GUION_NETXMS = motor._preparador_netxms()
_i_red_de = _GUION_NETXMS.index("red_de() {")
_red_de_guion = _GUION_NETXMS[_i_red_de:_GUION_NETXMS.index("\n}\n", _i_red_de) + 3]
for _caso in ("10.44.1.20/16", "10.44.1.20/24", "10.44.1.130/25", "10.44.1.20/28",
              "10.44.1.20/30", "10.44.1.7/32", "172.16.5.9/12"):
    igual(
        _subprocess.run(["sh", "-c", _red_de_guion + '\nred_de "$1"', "sh", _caso],
                        capture_output=True, text=True).stdout.strip(),
        motor.red_de_direccion(_caso),
        f"el guion del invitado y el motor derivan la MISMA red de {_caso}: la del prefijo de "
        "verdad, no un /24 supuesto (y no `int(o/m)*m`, que sólo acierta si el trozo es potencia "
        "de dos)",
    )

# ---------------------------------------------------------------------------
# Lo que cazó la TERCERA relectura (PR #13): tres cosas que no se ven leyendo la idea,
# sólo mirando cómo viaja el dato.
# ---------------------------------------------------------------------------
_FICHEROS_LATIDO = list(motor.escrituras_latido("2min").values())
igual(
    motor._latido_canonico({"cada": "2min"}, {
        "activo": True, "habilitado": True,
        "ficheros_leidos": [_FICHEROS_LATIDO[0], _FICHEROS_LATIDO[1],
                            _FICHEROS_LATIDO[2].rstrip("\n")],
    }),
    [],
    "un latido ENTERO converge aunque el último fichero llegue sin su salto de línea final: "
    "`ansible.builtin.command` recorta el que cierra el stdout, y el guion va el último",
)
comprobar(
    bool(motor._latido_canonico({"cada": "2min"}, {
        "activo": True, "habilitado": True,
        "ficheros_leidos": [_FICHEROS_LATIDO[0], _FICHEROS_LATIDO[1], "SIN-FICHERO"],
    })),
    "pero un guion BORRADO sigue pidiendo reescribirse: normalizar el salto no afloja el área",
)
igual(
    motor._routes_canonicas(
        [], {"estaticas": [{"dst_address": "default", "gateway": "10.44.0.254"}]},
        gobierna_por_defecto=False, persistir=False),
    [],
    "la ruta POR DEFECTO de un Linux NO se borra: la pone la plataforma al crearlo y no es de "
    "esta área -- si entrara en la comparación, se la quitaría y lo dejaría sin internet",
)
igual(
    motor._routes_canonicas(
        [{"dst_address": "10.44.1.0/24", "gateway": "10.44.0.12"}],
        {"estaticas": [{"dst_address": "10.44.1.0/24", "gateway": "10.44.0.12"},
                       {"dst_address": "default", "gateway": "10.44.0.254"}]},
        gobierna_por_defecto=False, persistir=False),
    [],
    "y con las rutas de las zonas declaradas tampoco sobra nada: el caso del lab 08",
)
igual(
    motor._routes_canonicas(
        [{"dst_address": "0.0.0.0/0", "gateway": "10.60.0.1"}],
        {"estaticas": []},
        gobierna_por_defecto=True, persistir=False),
    [{"op": "add_route", "dst_address": "0.0.0.0/0", "gateway": "10.60.0.1"}],
    "en un ROUTER la ruta por defecto sí se posee: es su salida, y se pone si falta -- la "
    "misma área, dos dueños, y el dueño lo dice el tipo de equipo",
)
igual(
    motor.objetivos_declarados({
        "address": [{"interface": "eth0", "address": "10.44.0.20/24"}],
        "routes": [{"dst_address": "0.0.0.0/0", "gateway": "10.44.0.254"}],
    }),
    ["10.44.0.0/24"],
    "la expectativa del descubrimiento no se inventa una ruta por defecto: el sembrado no la "
    "guarda, así que las dos listas tienen que aplicar la MISMA regla",
)
_i_psql = motor.PLANTILLA_PREPARADOR_NETXMS.find("where id=1")
comprobar(
    _i_psql != -1 and "\\\n" not in motor.PLANTILLA_PREPARADOR_NETXMS[_i_psql:_i_psql + 140],
    "el `psql` de la recuperación y `systemctl start netxms-server` son DOS comandos: un "
    "backslash suelto pegaba el arranque al `psql` y el servidor no arrancaba",
)

# ---------------------------------------------------------------------------
# El área `terminal`: el terminal SSH lo presta un AGENTE, y eso son cuatro hechos
# ---------------------------------------------------------------------------
LAB_TERMINAL = {"guests": [
    {"rol": "control", "tipo": "ctl", "address": "10.60.0.10/24",
     "config": {"linux": {"servicio": "netxms", "terminal": {}}}},
    {"rol": "borde", "tipo": "rt", "address": "10.60.1.1/24", "config": {"routeros": {}}},
    {"rol": "nucleo", "tipo": "rt", "address": "10.60.2.1/24", "config": {"routeros": {}}},
]}
VIGIA = LAB_TERMINAL["guests"][0]
TERMINAL_AL_DIA = {
    "agente": "active", "sshnsm": True, "capacidad": True, "tcpproxy": True,
    "nodos": [{"ip": "10.60.1.1", "login": "admin", "puerto": "22"},
              {"ip": "10.60.2.1", "login": "admin", "puerto": "22"}],
}

igual(motor._terminal_canonica({}, TERMINAL_AL_DIA, LAB_TERMINAL), [],
      "con el agente vivo, ssh.nsm cargado, el proxy TCP en marcha, la capacidad puesta y los "
      "dos routers dados de alta, el área `terminal` NO genera paso (es la idempotencia del área)")

# El proxy TCP es la pieza que faltaba en el primer terminal REAL (medido el 20-nov-2026): el
# agente abría la ventana y la cerraba con «TCP proxy function is disabled», con los otros
# tres hechos en su sitio. Si el estado lo ignora, el área dice «al día» y el terminal no abre.
_sin_proxy = dict(TERMINAL_AL_DIA, tcpproxy=False)
_ops_proxy = motor._terminal_canonica({}, _sin_proxy, LAB_TERMINAL)
comprobar(
    len(_ops_proxy) == 1 and _ops_proxy[0]["op"] == "preparar_terminal"
    and "proxy TCP" in _ops_proxy[0]["motivo"],
    "sin el proxy TCP del agente el área pide preparar el terminal y lo dice con su motivo "
    f"(obtenido {_ops_proxy!r})",
)

_sin_capacidad = dict(TERMINAL_AL_DIA, capacidad=False)
_ops = motor._terminal_canonica({}, _sin_capacidad, LAB_TERMINAL)
comprobar(
    len(_ops) == 1 and _ops[0]["op"] == "preparar_terminal"
    and [e["ip"] for e in _ops[0]["equipos"]] == ["10.60.1.1", "10.60.2.1"],
    "sin la capacidad de agente, el área pide preparar el terminal para LOS DOS routers "
    f"declarados (obtenido {_ops!r})",
)
comprobar("capacidad" in _ops[0]["motivo"],
          "el motivo dice QUÉ falta: «el nodo del vigilante no tiene la capacidad de agente» "
          "es el 502 que se midió, no un «no está» genérico")

# La declaración que el driver recibe está NORMALIZADA: `tipo` es la virtualización y el tipo
# de equipo viene en `equipo`. Filtrar por `tipo` dejaba la lista de equipos vacía y el área
# decía «no hay nada que hacer» con dos routers delante (falló de verdad en el primer ciclo).
igual(
    [e["ip"] for e in motor._terminal_canonica(
        {}, {"agente": "inactive", "sshnsm": False, "capacidad": False, "nodos": []},
        {"guests": [
            {"rol": "borde", "tipo": "qemu", "equipo": "rt", "address": "10.60.3.1/24",
             "config": {"routeros": {}}},
        ]},
    )[0]["equipos"]],
    ["10.60.3.1"],
    "el tipo de equipo se lee de `equipo` en la declaración normalizada: si se mira `tipo` "
    "(que ahí es `qemu`) el área no ve ningún router y no hace nada",
)

igual(motor._terminal_canonica({}, {}, {"guests": [VIGIA]}), [],
      "un lab sin routers no tiene nada que vigilar: el área no inventa equipos ni se queja")

_cmds = motor.escrituras_linux(_ops, VIGIA, LAB_TERMINAL, {"guests": []},
                               {"routeros_usuario": "admin", "routeros_clave": "clave-inventada"})
comprobar(len(_cmds) == 4 and all(c["area"] == "terminal" for c in _cmds),
          "la escritura del terminal son CUATRO comandos, y todos del área (configuración del "
          f"agente, agente vivo, credencial y alta de nodos) — obtenido {len(_cmds)}")
comprobar(
    any(c.get("comando_diario") for c in _cmds)
    and not any("clave-inventada" in (c.get("comando_diario") or "") for c in _cmds),
    "la credencial NO se diariza: el paso que la escribe lleva `comando_diario` y ahí no está "
    "la clave (el diario es sagrado, regla 5)",
)

# La configuración que se escribe lleva la bandera, y el comando la aplica SÓLO si cambió,
# reiniciando el agente en ese mismo instante: el agente lee sus banderas al arrancar, así que
# un fichero nuevo sobre un proceso viejo no arregla nada.
comprobar("EnableTCPProxy = 1" in motor.CONTENIDO_AGENTE,
          "la configuración del agente lleva `EnableTCPProxy = 1`: sin ella la sesión del "
          "terminal no se puede abrir")
comprobar("cmp -s" in _cmds[0]["comando"] and "restart netxms-agent" in _cmds[0]["comando"],
          "la escritura de la configuración compara antes de escribir y reinicia el agente "
          "cuando cambia (si no, el proceso viejo sigue sin leer la bandera)")

# La credencial de los nodos se comprueba DESPUÉS de reiniciar el servidor, que es cuando la
# lee: el servidor vivo puede reescribir la fila que se acaba de tocar, y contar antes del
# reinicio mide lo que va a tirar (medido en un lab recién nacido: el apply siguiente
# «arreglaba» solo lo que la pasada anterior había escrito).
_guion_terminal = motor._ficheros_servicio("netxms")[motor.RUTA_PREPARADOR_NETXMS]
comprobar("restart netxms-server" in _guion_terminal and "terminal-estado" in _guion_terminal,
          "el paso que deja la credencial de los nodos reinicia el servidor y cuenta lo que "
          "lee él, no la tabla cruda")
comprobar('intento_sql" -lt 3' in _guion_terminal,
          "si tras el reinicio el servidor sigue sin ver los nodos, el par escribir+reiniciar "
          "se repite (no se da por hecho con una sola escritura)")

if FALLOS:
    print(f"\nRESULTADO: {len(FALLOS)} fallo(s).")
    sys.exit(1)
print("\nRESULTADO: el driver puro del interior cumple su contrato.")