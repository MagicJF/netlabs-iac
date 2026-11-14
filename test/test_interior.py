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
#              6. en un RouterOS, la `identidad` va la ÚLTIMA en la primera
#                 convergencia (intercambio atómico: si no, un fallo a mitad deja al
#                 equipo con las credenciales viejas y sin camino de vuelta);
#              7. el residuo del cliente DHCP de fábrica se declara como
#                 `reiniciar_invitado` con su motivo, nunca se ignora;
#              8. las reservas DHCP se DERIVAN (MAC del vmid) y del ámbito correcto.
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
    "escalon": 1,
    "bridge": "vmb_gen",
    "direccion": "10.60.0.10/24",
    "config": {
        "linux": {
            "camino": {"salida": {"puerto": 443}},
            "dhcp_servidor": {
                "interfaz": "eth0",
                "rango": "10.60.0.50-10.60.0.99",
                "reservas": "derivadas",
            },
            "reenvio": True,
        }
    },
}

BORDE = {
    "rol": "borde",
    "tipo": "qemu",
    "escalon": 1,
    "bridge": "vmb_gen",
    "direccion": "10.60.0.11/24",
    "imagen": "chr-7.25.1.raw",
    "config": {
        "routeros": {
            "identidad": "rt-borde",
            "servicios": {"deshabilitar": ["telnet", "ftp", "api", "api-ssl"]},
            "cliente_dhcp": {"deshabilitar": True},
            "direcciones": [{"interfaz": "ether2", "direccion": "10.60.1.1/24"}],
            "rutas": [{"destino": "0.0.0.0/0", "pasarela": "10.60.0.1"}],
            "dhcp": [
                {
                    "interfaz": "ether2",
                    "pool": {"rango": "10.60.1.100-10.60.1.200"},
                    "red": {"prefijo": "10.60.1.0/24", "pasarela": "10.60.1.1", "dns": ["10.60.1.1"]},
                    "reservas": "derivadas",
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
    "escalon": 2,
    "bridge": "vmb_lan",
    "direccion": "10.60.1.10/24",
    "config": {"linux": {}},
}

# Un puesto que toma su dirección del router: NO se le reserva nada (no declara una
# dirección estática, no hay nada que proteger).
PUESTO = {
    "rol": "puesto-1",
    "tipo": "lxc",
    "escalon": 3,
    "bridge": "vmb_lan",
    "direccion": "dhcp",
    "config": {"linux": {}},
}

DECLARACION = {
    "lab": "lab-de-prueba",
    "supernet": "10.60.0.0/16",
    "bridges": [
        {"nombre": "vmb_gen", "direccion": "10.60.0.1/24"},
        {"nombre": "vmb_lan", "direccion": "10.60.1.1/24"},
    ],
    "camino": {"tipo": "puesto_control"},
    "invitados": [CONTROL, BORDE, SERVIDOR, PUESTO],
}

IDENTIDAD = {
    "lab": "lab-de-prueba",
    "invitados": [
        {"rol": "control", "vmid": 200, "mac": "BC:24:11:00:00:C8", "nombre": "lab-de-prueba-control"},
        {"rol": "borde", "vmid": 201, "mac": "BC:24:11:00:00:C9", "nombre": "lab-de-prueba-borde"},
        {"rol": "servidor", "vmid": 202, "mac": "BC:24:11:00:00:CA", "nombre": "lab-de-prueba-servidor"},
        {"rol": "puesto-1", "vmid": 203, "mac": "BC:24:11:00:00:CB", "nombre": "lab-de-prueba-puesto-1"},
    ],
}

PARAMETROS = {"bridge_gestion": "vmbr1", "camino_puerto_base": 20000, "nodo": "nodo-de-prueba"}

# El estado del puesto de control LEÍDO dentro del equipo, con todas sus áreas al día.
# El driver lee SIEMPRE todas las áreas declaradas: una lectura recortada no es un
# caso válido (el driver para y lo dice), así que los casos parciales se construyen
# cambiando UNA área de este mapa.
LECTURA_CONTROL_AL_DIA = {
    "direccion": {"direccion": "10.60.0.10/24"},
    "reenvio": {"activo": True},
    "dhcp_servidor": {
        "interfaz": "eth0",
        "rango": "10.60.0.50-10.60.0.99",
        "servicio_activo": True,
        "offload_apagado": True,
        "reservas": [{"mac": "BC:24:11:00:00:C9", "direccion": "10.60.0.11/24"}],
    },
    "camino": {"salida": "puesta"},
}


def lectura(areas_cambiadas=None):
    """La lectura del puesto de control, con las áreas que se quieran cambiar."""
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
igual(motor.tiene_camino(CONTROL), True, "el puesto de control declara el camino")
igual(motor.tiene_camino(BORDE), False, "un router no es el puesto de control")

# Dos tipos a la vez: no se adivina, se dice.
try:
    motor.tipo_de({"config": {"linux": {}, "routeros": {}}})
    comprobar(False, "un `config` con dos tipos da error")
except motor.ErrorMotor:
    comprobar(True, "un `config` con dos tipos da error")

areas_borde = motor.areas_de(BORDE)
igual(
    sorted(areas_borde),
    sorted(["identidad", "servicios", "cliente_dhcp", "direcciones", "rutas", "dhcp"]),
    "las áreas de un RouterOS son las que declara",
)
areas_control = motor.areas_de(CONTROL)
igual(
    sorted(areas_control),
    sorted(["camino", "dhcp_servidor", "reenvio", "direccion"]),
    "las áreas de un Linux son las que declara (más la dirección de su pata)",
)
igual(
    motor.areas_a_leer(CONTROL), list(areas_control.keys()), "se leen exactamente las áreas declaradas"
)

# ---------------------------------------------------------------------------
# La dirección libre de la pata de gestión (derivada: nada se guarda)
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

patas = motor.patas_del_puesto_control(CONTROL, DECLARACION, ESTADO_NODO, PARAMETROS)
igual(len(patas), 3, "el puesto de control tiene una pata por bridge, más la de gestión del nodo")
# El ORDEN es el orden de `eth0, eth1, ...` dentro del invitado: primero las del LAB (la
# declarada la primera, porque es el `eth0` que citan las áreas del lab) y la de gestión
# del nodo la ÚLTIMA, que es la única con puerta.
igual(
    patas[0]["bridge"], "vmb_gen",
    "la primera pata es la declarada: es el `eth0` que el lab cita en sus áreas",
)
igual(
    patas[0]["direccion"], "10.60.0.10/24", "la pata declarada del lab lleva su dirección declarada"
)
igual(patas[0]["puerta"], "", "una pata de un bridge del lab no lleva puerta")
igual(
    patas[1]["direccion"], "10.60.1.254/24",
    "la pata no declarada la deriva el motor por arriba, esquivando lo declarado",
)
igual(patas[2]["bridge"], "vmbr1", "la ÚLTIMA pata es la del bridge de gestión del nodo: la salida")
igual(patas[2]["direccion"], "10.10.10.253/24", "su dirección en el nodo la DERIVA el motor")
igual(patas[2]["puerta"], "10.10.10.1", "y es la única con puerta: la dirección del nodo")
# Y sin bridge de gestión no se inventa nada: un puesto sin salida no se puede converger,
# así que se dice y se para (en vez de crear el invitado y descubrirlo tres pasos después).
try:
    motor.patas_del_puesto_control(
        CONTROL, DECLARACION, ESTADO_NODO, {"camino_puerto_base": 20000}
    )
    comprobar(False, "sin bridge de gestión el motor falla en vez de crear un puesto sin salida")
except motor.ErrorMotor as error:
    comprobar(
        "pve_bridge_gestion" in str(error),
        "sin bridge de gestión el motor falla diciendo la clave que falta",
    )
# Y si ese bridge existe en el nodo pero NO tiene dirección, tampoco hay puerta por la que
# salir: se dice, no se crea una pata muda.
try:
    motor.patas_del_puesto_control(
        CONTROL, DECLARACION, {"bridges_direcciones": {}, "direcciones_usadas": []}, PARAMETROS
    )
    comprobar(False, "un bridge de gestión sin dirección da error, no una pata sin puerta")
except motor.ErrorMotor as error:
    comprobar(
        "vmbr1" in str(error), "el error dice QUÉ bridge de gestión no tiene dirección"
    )

# ---------------------------------------------------------------------------
# El puerto del camino y la línea que se manda por consola
# ---------------------------------------------------------------------------

print("\nEL CAMINO: PUERTO DERIVADO Y LÍNEA DE CONSOLA\n")

igual(motor.puerto_camino(200, PARAMETROS), 20200, "el puerto del camino se deriva del vmid")
igual(motor.puerto_camino(201, PARAMETROS), 20201, "y dos invitados no comparten puerto")

guion = motor.guion_camino("CLAVE-PRIVADA-DE-PRUEBA", "casa.example", 443, "camino", 20200)
comprobar(
    "-R 20200:localhost:22" in guion,
    "el guion deja reenviado el puerto del lab hacia el sshd del invitado",
)
comprobar(
    "-p 443 camino@casa.example" in guion,
    "y sale hacia casa por el host y el puerto que declara el lab",
)
comprobar("/etc/systemd/system/" in guion, "el guion se deja como unidad de systemd")
comprobar("Restart=always" in guion, "y con reinicio automático: el invitado que reinicia, vuelve")
comprobar("CLAVE-PRIVADA-DE-PRUEBA" in guion, "la clave del camino viaja dentro del guion")
comprobar(
    motor.marca_camino() in guion,
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
    [(r["rol"], r["direccion"], r["mac"]) for r in reservas_borde],
    [("servidor", "10.60.1.10/24", "BC:24:11:00:00:CA")],
    "el router reserva la dirección estática del servidor de SU red, con su MAC derivada",
)
comprobar(
    all(r["rol"] != "borde" for r in reservas_borde),
    "el servidor no se reserva a sí mismo",
)
comprobar(
    all(r["rol"] != "puesto-1" for r in reservas_borde),
    "un cliente dinámico no se reserva: no declara dirección que proteger",
)
reservas_control = motor.reservas_derivadas(DECLARACION, IDENTIDAD, CONTROL)
igual(
    [r["rol"] for r in reservas_control],
    ["borde"],
    "el puesto de control reserva, en su bridge, la dirección del router (ámbito por bridge)",
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
    "un puesto con sólo `direccion: dhcp` no pide visita: su dirección se lee del HOST "
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
    motor.pasos_de_convergencia({"rol": "switch", "escalon": 1}, IDENTIDAD, DECLARACION, {}, PARAMETROS),
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
        "identidad": {"nombre": "rt-borde", "usuario_motor": True, "clave_motor": True, "credencial_motor": True},
        "servicios": {"deshabilitados": ["api", "api-ssl", "ftp", "telnet"]},
        "cliente_dhcp": {"habilitado": False},
        "direcciones": {"estaticas": [{"interfaz": "ether1", "direccion": "10.60.0.11/24"}, {"interfaz": "ether2", "direccion": "10.60.1.1/24"}], "dinamicas": []},
        "rutas": {
            "estaticas": [{"destino": "0.0.0.0/0", "pasarela": "10.60.0.1"}],
            "dinamicas": [],
        },
        "dhcp": {
            "servidores": [
                {
                    "interfaz": "ether2",
                    "rango": "10.60.1.100-10.60.1.200",
                    "red": {"prefijo": "10.60.1.0/24", "pasarela": "10.60.1.1", "dns": ["10.60.1.1"]},
                }
            ],
            "reservas": [{"mac": "BC:24:11:00:00:CA", "direccion": "10.60.1.10"}],
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
    "areas": dict(LEIDO_AL_DIA["areas"], rutas={"estaticas": [], "dinamicas": []}),
}
pasos = motor.pasos_de_convergencia(BORDE, IDENTIDAD, DECLARACION, LEIDO_FALTA_UNA_RUTA, PARAMETROS)
igual(len(pasos), 1, "lo que cambia es UNA cosa: un solo paso")
igual(pasos[0]["parametros"]["area"], "rutas", "y es el área de rutas")
igual(
    pasos[0]["parametros"]["operaciones"],
    [{"op": "poner_ruta", "destino": "0.0.0.0/0", "pasarela": "10.60.0.1"}],
    "con la operación concreta que falta",
)

# 3) Lo que está dentro del área y no está declarado, se quita.
LEIDO_CON_SOBRA = {
    "alcanzable": True,
    "areas": dict(
        LEIDO_AL_DIA["areas"],
        servicios={"deshabilitados": ["api", "api-ssl", "ftp", "telnet", "ssh"]},
        direcciones={
            "estaticas": [
                {"interfaz": "ether1", "direccion": "10.60.0.11/24"},
                {"interfaz": "ether2", "direccion": "10.60.1.1/24"},
                {"interfaz": "ether3", "direccion": "10.60.2.1/24"},
            ],
            "dinamicas": [],
        },
    ),
}
pasos_sobra = motor.pasos_de_convergencia(BORDE, IDENTIDAD, DECLARACION, LEIDO_CON_SOBRA, PARAMETROS)
areas_con_paso = {p["parametros"]["area"]: p["parametros"]["operaciones"] for p in pasos_sobra}
igual(
    areas_con_paso.get("servicios"),
    [{"op": "habilitar_servicio", "servicio": "ssh"}],
    "un servicio apagado que el motor gestiona y no está declarado, se vuelve a habilitar",
)
igual(
    areas_con_paso.get("direcciones"),
    [{"op": "quitar_direccion", "interfaz": "ether3", "direccion": "10.60.2.1/24"}],
    "una dirección de más dentro del área, se quita",
)

# 4) El intercambio atómico: en la PRIMERA convergencia la identidad va la última.
LEIDO_SIN_IDENTIDAD = {
    "alcanzable": True,
    "areas": {
        "identidad": {"nombre": "", "usuario_motor": False, "clave_motor": False, "credencial_motor": False},
        "servicios": {"deshabilitados": []},
        "cliente_dhcp": {"habilitado": True},
        "direcciones": {"estaticas": [], "dinamicas": []},
        "rutas": {"estaticas": [], "dinamicas": []},
        "dhcp": {"servidores": [], "reservas": []},
    },
}
pasos_primera = motor.pasos_de_convergencia(
    BORDE, IDENTIDAD, DECLARACION, LEIDO_SIN_IDENTIDAD, PARAMETROS
)
igual(
    pasos_primera[-1]["parametros"]["area"],
    "identidad",
    "la identidad del router va la ÚLTIMA (intercambio atómico)",
)
comprobar(
    {"op": "deshabilitar_cliente_dhcp"}
    in next(
        p for p in pasos_primera if p["parametros"]["area"] == "cliente_dhcp"
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
    [("reiniciar_invitado", "api")],
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
        {"alcanzable": False, "motivo": "el camino está caído"},
        PARAMETROS,
    )
    comprobar(False, "sin camino, converger un interior da error")
except motor.ErrorMotor as error:
    comprobar(
        "el camino está caído" in str(error),
        "sin camino, converger un interior da error diciendo QUÉ falta",
    )

# 7) Linux: la dirección dinámica no se escribe, se comprueba (§6.3).
igual(
    motor.pasos_de_convergencia(
        PUESTO,
        IDENTIDAD,
        DECLARACION,
        {"alcanzable": True, "areas": {"direccion": {"direccion": "10.60.1.77/24"}}},
        PARAMETROS,
    ),
    [],
    "un `direccion: dhcp` no genera escritura: se comprueba, no se escribe",
)
igual(
    operaciones_de(
        motor.pasos_de_convergencia(
            CONTROL,
            IDENTIDAD,
            DECLARACION,
            lectura({"direccion": {"direccion": ""}}),
            PARAMETROS,
        ),
        "direccion",
    ),
    [{"op": "poner_direccion", "interfaz": "eth0", "direccion": "10.60.0.10/24"}],
    "una dirección estática que falta, se escribe (y en eth0: la pata del contenedor)",
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
        {"alcanzable": True, "areas": {"camino": {"salida": "puesta"}}},
        PARAMETROS,
    )
    comprobar(False, "un área declarada que el driver NO leyó da error en vez de escribir a ciegas")
except motor.ErrorMotor as error:
    comprobar(
        "no leyó el área" in str(error)
        and any(area in str(error) for area in ("direccion", "reenvio", "dhcp_servidor")),
        "un área declarada que el driver NO leyó da error diciendo CUÁL falta",
    )
igual(
    operaciones_de(
        motor.pasos_de_convergencia(
            CONTROL,
            IDENTIDAD,
            DECLARACION,
            lectura({"dhcp_servidor": {}}),
            PARAMETROS,
        ),
        "dhcp_servidor",
    ),
    [
        {"op": "escribir_dnsmasq", "interfaz": "eth0", "rango": "10.60.0.50-10.60.0.99"},
        {"op": "apagar_offload", "interfaz": "eth0"},
        {"op": "poner_reserva", "mac": "BC:24:11:00:00:C9", "direccion": "10.60.0.11/24"},
        {"op": "recargar_dnsmasq"},
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
                    "dhcp_servidor": {
                        "interfaz": "eth0",
                        "rango": "10.60.0.50-10.60.0.99",
                        "servicio_activo": True,
                        "offload_apagado": False,
                        "reservas": [{"mac": "BC:24:11:00:00:C9", "direccion": "10.60.0.11/24"}],
                    }
                }
            ),
            PARAMETROS,
        ),
        "dhcp_servidor",
    ),
    [
        {"op": "apagar_offload", "interfaz": "eth0"},
        {"op": "recargar_dnsmasq"},
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
                    "dhcp_servidor": {
                        "interfaz": "eth0",
                        "rango": "10.60.0.50-10.60.0.99",
                        "servicio_activo": True,
                        "offload_apagado": True,
                        "reservas": [],
                    }
                }
            ),
            PARAMETROS,
        ),
        "dhcp_servidor",
    ),
    [
        {"op": "poner_reserva", "mac": "BC:24:11:00:00:C9", "direccion": "10.60.0.11/24"},
        {"op": "recargar_dnsmasq"},
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
            lectura({"reenvio": {"activo": False}}),
            PARAMETROS,
        ),
        "reenvio",
    ),
    [{"op": "activar_reenvio"}],
    "sin reenvío no hay servidor DHCP: se activa",
)

# El camino: lo pone la consola UNA vez; después sólo se comprueba.
igual(
    motor.pasos_de_convergencia(CONTROL, IDENTIDAD, DECLARACION, lectura(), PARAMETROS),
    [],
    "con la salida ya puesta, el camino no se vuelve a mandar por consola (ni nada más)",
)
igual(
    operaciones_de(
        motor.pasos_de_convergencia(
            CONTROL,
            IDENTIDAD,
            DECLARACION,
            lectura({"camino": {"salida": ""}}),
            PARAMETROS,
        ),
        "camino",
    ),
    [{"op": "mandar_linea_consola"}],
    "sin salida, hay que volver a mandar la línea por consola",
)

# ---------------------------------------------------------------------------
# La sonda de escalón (regla 18)
# ---------------------------------------------------------------------------

print("\nLA SONDA DEL ESCALÓN\n")

sonda_borde = motor.espera_de_servicio(BORDE)
igual(sonda_borde["via"], "sonda", "la sonda no es un `wait_for`: es una petición a lo prometido")
igual(sonda_borde["parametros"]["puerto"], 80, "a un RouterOS se le pregunta por su REST")
igual(
    sonda_borde["parametros"]["direccion"], "10.60.0.11",
    "en la dirección que la declaración promete, sin máscara",
)
igual(motor.espera_de_servicio(CONTROL)["parametros"]["puerto"], 22, "a un Linux, por su sshd")
igual(motor.espera_de_servicio({"rol": "switch"}), None, "un invitado sin interior no se sondea")
comprobar(
    "escalón" in sonda_borde["porque"] and "puerto 80" in sonda_borde["porque"],
    "y el paso explica que el escalón siguiente no se toca hasta que este conteste",
)

# ---------------------------------------------------------------------------
# Los pasos del camino (§5): el plan los emite, el ejecutor los hace
# ---------------------------------------------------------------------------

print("\nLOS PASOS DEL CAMINO\n")

CONTROL_CON_VMID = dict(CONTROL, vmid=200, escalon=1)
pasos_camino = motor.pasos_del_camino(CONTROL_CON_VMID, DECLARACION, ESTADO_NODO, PARAMETROS)
igual(
    [paso["accion"] for paso in pasos_camino],
    ["construir_camino", "comprobar_camino"],
    "sin camino en pie, se construye y se comprueba (en este orden)",
)
igual(pasos_camino[0]["via"], "camino", "los dos pasos del camino van por el camino, no por la API")
igual(
    pasos_camino[0]["parametros"]["puerto"], 20200,
    "el puerto del túnel se DERIVA del vmid del puesto: nada que guardar",
)
comprobar(
    len(pasos_camino[0].get("detalle") or []) >= 4,
    "el paso del camino se explica por piezas (clave, authorized_keys, consola, marca)",
)
igual(
    len(pasos_camino[0]["parametros"]["patas"]), 3,
    "y lleva sus patas: el puesto nace completo, con todas",
)
comprobar(
    "CLAVE-PRIVADA" not in __import__("json").dumps(pasos_camino).upper(),
    "el plan NO lleva secretos: la clave del camino se lee al ejecutar, no viaja en el paso",
)
igual(
    [
        paso["accion"]
        for paso in motor.pasos_del_camino(
            CONTROL_CON_VMID, DECLARACION,
            dict(ESTADO_NODO, camino={"responde": True}), PARAMETROS
        )
    ],
    ["comprobar_camino"],
    "si el camino YA responde no se reconstruye: sólo se comprueba (que es una lectura)",
)
igual(
    motor.pasos_del_camino(BORDE, DECLARACION, {}, PARAMETROS), [],
    "un invitado que no es el puesto de control no genera pasos de camino",
)


# ---------------------------------------------------------------------------
# El driver de LINUX: el inventario, la puerta y lo que se midió al conectarlo
# (14-nov-2026). Todo lo de aquí salió de un fallo DE VERDAD al encenderlo.
# ---------------------------------------------------------------------------

print("\nEL DRIVER DE LINUX\n")

import base64 as _base64  # noqa: E402
import yaml as _yaml  # noqa: E402
import declaracion as _validador  # noqa: E402

# La declaración que CIRCULA por el motor está normalizada: sus invitados son una lista
# plana (`invitados`), no `containers`/`vms`. Si el motor la lee como el fichero del lab,
# no encuentra el puesto de control, el inventario se queda sin puerto y el paso muere
# con «No first item, sequence was empty». Pasó: por eso se prueba con esta forma.
_CRUDA = _yaml.safe_load(open(os.path.join(RAIZ, "labs", "lab-red-routeros", "lab-red-routeros.yml")))
_NORMALIZADA = _validador.declaracion_normalizar(_CRUDA)
igual(
    motor.puesto_control(_NORMALIZADA), "control",
    "el puesto de control se saca de la declaración NORMALIZADA (la que circula de verdad)",
)
igual(
    motor.puesto_control({"invitados": [{"rol": "puesto-1", "config": {"linux": {"direccion": "dhcp"}}}]}),
    "",
    "un lab que no declara camino no tiene puesto de control: '' y no un nombre inventado",
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
    [{"ansible_loop_var": "interior_comando", "interior_comando": {"area": "camino"},
      "stdout": "", "rc": 255, "stderr": "root@127.0.0.1: Permission denied (publickey,password)."}],
    {"rol": "control"},
)
igual(_leido_255["alcanzable"], False, "rc 255 = no se pudo entrar: el motor para en vez de seguir a ciegas")
comprobar(
    "Permission denied" in _leido_255["motivo"],
    "y lo que se enseña es el motivo que dijo ssh, no uno inventado",
)
igual(
    motor.leido_de_lecturas([{"ansible_loop_var": "interior_comando", "interior_comando": {"area": "camino"}, "stdout": "", "rc": 1}], {"rol": "control"})["alcanzable"],
    True,
    "rc 1 = el invitado contestó que eso no está: se llegó, y eso se puede decidir",
)

# --- El servidor DHCP: el sitio donde la idempotencia se pierde sin querer -----------
CONTROL_CON_DHCP = {
    "rol": "control", "escalon": 1, "tipo": "lxc", "bridge": "vmb_gestion",
    "direccion": "10.40.0.10/24",
    "config": {"linux": {
        "camino": {},
        "reenvio": True,
        "dhcp_servidor": {"interfaz": "eth0", "rango": "10.40.0.50-10.40.0.99", "reservas": "derivadas"},
    }},
}
PUESTO_CON_DHCP = {
    "rol": "puesto-1", "escalon": 1, "tipo": "lxc", "bridge": "vmb_gestion",
    "direccion": "10.40.0.20/24", "config": {"linux": {"camino": {}}},
}
DECLARACION_DHCP = {
    "lab": "prueba", "escalones": [1],
    "bridges": [{"nombre": "vmb_gestion", "supernet": "10.40.0.0/24"}],
    "invitados": [CONTROL_CON_DHCP, PUESTO_CON_DHCP],
    "supernet": "10.40.0.0/24",
    "camino": {"tipo": "puesto_control"},
}
IDENTIDAD_DHCP = {"invitados": [
    # La identidad lleva la MAC de cada pata (la deriva el motor del vmid): es de donde
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
        "camino": {"salida": True},
        "direccion": {"direccion": "10.40.0.10/24"},
        "reenvio": {"activo": True},
        "dhcp_servidor": {
            "interfaz": "eth0",
            "rango": "10.40.0.50-10.40.0.99",
            "reservas": [{"mac": "BC:24:11:00:00:6E", "direccion": "10.40.0.20"}],
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
    [{"ansible_loop_var": "interior_comando", "interior_comando": {"area": "dhcp_servidor"}, "rc": 0, "stdout": (
        "port=0\ninterface=eth0\ndhcp-range=10.40.0.50,10.40.0.99,255.255.255.0,12h\n"
        "---NETLABS---\ntx-checksumming: on\ngeneric-segmentation-offload: off\n"
        "tcp-segmentation-offload: off\n---NETLABS---\ndnsmasq=/usr/sbin/dnsmasq\nethtool=NO\n"
    )}],
    CONTROL_CON_DHCP,
)["areas"]["dhcp_servidor"]
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
        [{"ansible_loop_var": "interior_comando", "interior_comando": {"area": "camino"}, "rc": 0, "stdout": "active"},
         {"ansible_loop_var": "interior_comando", "interior_comando": {"area": "direccion"}, "rc": 0, "stdout":
          "2: eth0    inet 10.40.0.10/24 brd 10.40.0.255 scope global eth0"},
         {"ansible_loop_var": "interior_comando", "interior_comando": {"area": "reenvio"}, "rc": 0, "stdout": "0"},
         {"ansible_loop_var": "interior_comando", "interior_comando": {"area": "dhcp_servidor"}, "rc": 0, "stdout": '---NETLABS---\ntx-checksumming: on\ngeneric-segmentation-offload: on\ntcp-segmentation-offload: on\n---NETLABS---\ndnsmasq=NO\nethtool=NO\n---NETLABS---\ninactive'}],
        CONTROL_CON_DHCP),
    PARAMETROS,
))
_ESCRITURAS = motor.escrituras_linux(
    _OPERACIONES_NUEVO, CONTROL_CON_DHCP, DECLARACION_DHCP, IDENTIDAD_DHCP, PARAMETROS)
comprobar(
    {e["area"] for e in _ESCRITURAS} <= {"dhcp_servidor", "reenvio", "direccion", "camino"},
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
print("\n== un puesto de control declara una dirección por cada bridge del lab ==")
# Medido: sin dirección en la LAN, el CHR que cuelga de ella no contesta al REST y su
# convergencia no se puede ni empezar (10.40.1.11 en 'nucleo'). La forma es `direcciones`
# (lista), y se funde en el área `direccion` para que la convergencia tenga un solo camino.
_PUESTO = {
    "rol": "control",
    "tipo": "lxc",
    "direccion": "10.40.0.10/24",
    "config": {"linux": {"direcciones": [{"interfaz": "eth1", "direccion": "10.40.1.2/24"}]}},
}
comprobar(
    motor.areas_de(_PUESTO)["direccion"]
    == [
        {"interfaz": "eth0", "direccion": "10.40.0.10/24"},
        {"interfaz": "eth1", "direccion": "10.40.1.2/24"},
    ],
    "la de gestión sale del campo `direccion` y va PRIMERO; las otras patas, declaradas una a una",
)
comprobar(
    motor.areas_de(_PUESTO).get("direcciones") is None,
    "`direcciones` no es un área aparte: se funde en `direccion` (una sola forma de converger)",
)
_LEIDO_PUESTO = motor.leido_linux(
    [
        {
            "area": "direccion",
            "rc": 0,
            "encontrado": "2: eth0    inet 10.40.0.10/24 brd 10.40.0.255 scope global eth0\n"
            "3: eth1    inet 10.40.1.2/24 brd 10.40.1.255 scope global eth1\n",
        }
    ]
)
comprobar(
    _LEIDO_PUESTO["direccion"]["direcciones"]
    == [
        {"interfaz": "eth0", "direccion": "10.40.0.10/24"},
        {"interfaz": "eth1", "direccion": "10.40.1.2/24"},
    ],
    "y la lectura saca TODAS las patas con dirección, no sólo eth0",
)
comprobar(
    _LEIDO_PUESTO["direccion"]["direccion"] == "10.40.0.10/24",
    "la de gestión sigue siendo la de eth0: es la que el plan usa para levantar el túnel",
)
comprobar(
    motor._direccion_linux_canonica(
        motor.areas_de(_PUESTO)["direccion"], _LEIDO_PUESTO["direccion"]
    )
    == [],
    "con las dos patas puestas, la segunda pasada no escribe nada (idempotencia)",
)
comprobar(
    motor._direccion_linux_canonica(
        motor.areas_de(_PUESTO)["direccion"],
        {
            "direccion": "10.40.0.10/24",
            "direcciones": [{"interfaz": "eth0", "direccion": "10.40.0.10/24"}],
        },
    )
    == [{"op": "poner_direccion", "interfaz": "eth1", "direccion": "10.40.1.2/24"}],
    "si falta la pata de la LAN, se pone SÓLO esa: lo que ya está no se toca",
)

# ---------------------------------------------------------------------------

if FALLOS:
    print(f"\nRESULTADO: {len(FALLOS)} fallo(s).")
    sys.exit(1)
print("\nRESULTADO: el driver puro del interior cumple su contrato.")
