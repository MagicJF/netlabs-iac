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
    motor.pasos_de_convergencia(PUESTO, IDENTIDAD, DECLARACION, {}, PARAMETROS)[0][
        "parametros"
    ]["operaciones"],
    [],
    "y sin lectura no se puede afirmar que nada coincide: no hay operaciones que enseñar",
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
        "identidad": {"nombre": "rt-borde", "usuario_motor": True, "clave_motor": True},
        "servicios": {"deshabilitados": ["api", "api-ssl", "ftp", "telnet"]},
        "cliente_dhcp": {"habilitado": False},
        "direcciones": {"estaticas": [{"interfaz": "ether2", "direccion": "10.60.1.1/24"}], "dinamicas": []},
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
            "reservas": [{"mac": "BC:24:11:00:00:CA", "direccion": "10.60.1.10/24"}],
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
        "identidad": {"nombre": "", "usuario_motor": False, "clave_motor": False},
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

if FALLOS:
    print(f"\nRESULTADO: {len(FALLOS)} fallo(s).")
    sys.exit(1)
print("\nRESULTADO: el driver puro del interior cumple su contrato.")
