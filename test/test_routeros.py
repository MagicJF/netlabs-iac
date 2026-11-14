#!/usr/bin/env python3
# PROPÓSITO:   probar la capa PURA de RouterOS: cómo se INTERPRETA lo que contesta su
#              REST y cómo se TRADUCE lo decidido a llamadas REST. Sin RouterOS, sin
#              Proxmox, sin red y sin Ansible: es la prueba de que leer un router y
#              pedirle cambios son dos funciones.
# INVARIANTES: los casos que TIENEN que cumplirse, y que son el contrato del driver de
#              RouterOS:
#              1. se pregunta SÓLO por las áreas declaradas (fuera de ellas el motor no
#                 opina, así que tampoco pregunta);
#              2. las respuestas CRUDAS de un CHR recién nacido se leen bien: el nombre
#                 del equipo, los servicios apagados, el cliente DHCP de fábrica vivo,
#                 su dirección dinámica y su ruta por defecto del DHCP;
#              3. lo decidido se traduce a las rutas REST correctas, con los cuerpos
#                 correctos, y `www` NO aparece en ninguna: es donde vive el REST (el
#                 camino de vuelta del motor);
#              4. la credencial del motor va la ÚLTIMA (identidad al final del plan);
#              5. la contraseña NO se escribe en el diario: `sin_secretos` la tapa;
#              6. con un router ya convergido, CERO operaciones (idempotencia por
#                 construcción); y con el residuo del cliente de fábrica, el reinicio
#                 del invitado declarado en el plan.
# LÍMITES:     no prueba el driver de verdad (eso es el ciclo contra el VPS): aquí no se
#              toca ningún equipo. Las respuestas están COPIADAS de un CHR 7.25.1 real
#              (medido, ver `labs/lab-red-routeros/` y el ADR del interior).
# VER:         docs/decisiones/0006-*.md; filter_plugins/interior.py;
#              tasks/ros_api.yml; tasks/configurar_routeros.yml

# Uso:  python3 test/test_routeros.py     (código de salida != 0 si algo falla)

import os
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(RAIZ, "deployment_engine", "filter_plugins"))

import yaml as _yaml  # noqa: E402
import interior as motor  # noqa: E402
import declaracion as _validador  # noqa: E402

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


# ---------------------------------------------------------------------------
# El lab de ACEPTACIÓN, tal cual está declarado, y una identidad de ejemplo.
# ---------------------------------------------------------------------------
_CRUDA = _yaml.safe_load(
    open(os.path.join(RAIZ, "labs", "lab-red-routeros", "lab-red-routeros.yml"))
)
DECLARACION = _validador.declaracion_normalizar(_CRUDA)
BORDE = [i for i in DECLARACION["invitados"] if i["rol"] == "borde"][0]

# Los vmids son los del pool real cuando esto se escribió; lo que importa es que la MAC
# se DERIVA de ellos (nadie la escribe a mano, regla 14).
IDENTIDAD = {
    "invitados": [
        {"rol": "control", "vmid": 109, "tipo": "lxc", "mac": "BC:24:11:00:00:6D"},
        {"rol": "borde", "vmid": 108, "tipo": "qemu", "mac": "BC:24:11:00:00:6C"},
        {"rol": "nucleo", "vmid": 110, "tipo": "qemu", "mac": "BC:24:11:00:00:6E"},
        {"rol": "servidor", "vmid": 111, "tipo": "lxc", "mac": "BC:24:11:00:00:6F"},
        {"rol": "puesto-1", "vmid": 112, "tipo": "lxc", "mac": "BC:24:11:00:00:70"},
        {"rol": "puesto-2", "vmid": 113, "tipo": "lxc", "mac": "BC:24:11:00:00:71"},
    ]
}
PARAMETROS = {"bridge_gestion": "vmbr1", "camino_puerto_base": 20000, "nodo": "nodo-de-prueba"}
CLAVE_PUBLICA = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAINetlabsCaminoDePrueba netlabs_v4_b"
PARAMETROS_ROUTEROS = {
    "usuario": "admin",
    "clave": "la-contraseña-del-motor",
    "clave_publica": CLAVE_PUBLICA,
}


def respuesta(json_crudo, status=200):
    return {"status": status, "json": json_crudo, "error": ""}


# ---------------------------------------------------------------------------
# 1. Un CHR RECIÉN NACIDO, tal como contestó su REST (medido, 7.25.1)
# ---------------------------------------------------------------------------
# Un `admin` sin contraseña, sin claves; `telnet`, `ftp`, `api` y `api-ssl` abiertos;
# `www` abierto (es donde vive REST, y el motor NO lo toca); el cliente DHCP de fábrica
# vivo en ether1 con su dirección dinámica y su ruta por defecto del DHCP; y ninguna
# tabla de DHCP del router todavía.
CRUDO_RECIEN_NACIDO = {
    "/system/identity": respuesta({"name": "CHR"}),
    "/user": respuesta([{"name": "admin", "group": "full", ".id": "*1"}]),
    "/user/ssh-keys": respuesta([]),
    "/ip/service": respuesta([
        {".id": "*0", "name": "telnet", "port": "23", "disabled": "false", "dynamic": "false"},
        {".id": "*1", "name": "ftp", "port": "21", "disabled": "false", "dynamic": "false"},
        {".id": "*2", "name": "www", "port": "80", "disabled": "false", "dynamic": "false"},
        {".id": "*4", "name": "ssh", "port": "22", "disabled": "false", "dynamic": "false"},
        {".id": "*6", "name": "www-ssl", "port": "443", "disabled": "true", "dynamic": "false"},
        {".id": "*7", "name": "api", "port": "8728", "disabled": "false", "dynamic": "false"},
        {".id": "*8", "name": "winbox", "port": "8291", "disabled": "false", "dynamic": "false"},
        {".id": "*9", "name": "api-ssl", "port": "8729", "disabled": "false", "dynamic": "false"},
        # Y las DINÁMICAS, que no son configuración: la conexión viva del propio motor
        # (medida, con `www` repetido) y los servicios que levanta un proceso.
        {".id": "*E", "name": "www", "port": "80", "disabled": "false", "dynamic": "true",
         "connection": "true", "local": "10.40.0.11", "remote": "10.40.0.10:35850"},
        {".id": "*B", "name": "btest", "port": "2000", "disabled": "false", "dynamic": "true"},
    ]),
    "/ip/dhcp-client": respuesta([
        {
            ".id": "*1", "interface": "ether1", "disabled": "false", "dynamic": "false",
            "address": "10.40.0.11/24", "gateway": "10.40.0.10", "add-default-route": "true",
        }
    ]),
    "/ip/address": respuesta([
        {
            ".id": "*1", "address": "10.40.0.11/24", "network": "10.40.0.0",
            "interface": "ether1", "dynamic": "true", "disabled": "false",
        }
    ]),
    "/ip/route": respuesta([
        {
            ".id": "*1", "dst-address": "0.0.0.0/0", "gateway": "10.40.0.10",
            "dynamic": "true", "dhcp": "true", "active": "true",
        },
        {
            ".id": "*2", "dst-address": "10.40.0.0/24", "gateway": "ether1",
            "dynamic": "true", "connect": "true", "active": "true",
        },
    ]),
    "/ip/dhcp-server": respuesta([]),
    "/ip/pool": respuesta([]),
    "/ip/dhcp-server/network": respuesta([]),
    "/ip/dhcp-server/lease": respuesta([]),
}

print("\nLECTURAS: se pregunta SÓLO por lo que el lab declara\n")

for area, rutas_esperadas, en_lab in (
    ("identidad", ["/system/identity", "/user", "/user/ssh-keys"], True),
    ("servicios", ["/ip/service"], True),
    ("cliente_dhcp", ["/ip/dhcp-client"], True),
    ("direcciones", ["/ip/address"], True),
    ("rutas", ["/ip/route"], True),
    ("dhcp", ["/ip/dhcp-server", "/ip/pool", "/ip/dhcp-server/network", "/ip/dhcp-server/lease"], True),
):
    obtenidas = [lectura["ruta"] for lectura in motor.lecturas_routeros(BORDE)]
    igual(
        [r for r in obtenidas if r in rutas_esperadas], rutas_esperadas,
        f"un RouterOS pregunta por las rutas del área '{area}'",
    )

# Un router SIN áreas declaradas sigue teniendo una cosa que leer: su propia dirección de
# gestión. No es un área que el lab declare -- la deriva el motor del `direccion:` del
# invitado -- , y es justo lo que impide dejarlo sin camino de vuelta al apagarle el
# cliente DHCP de fábrica.
SIN_AREAS = dict(BORDE, config={"routeros": {"identidad": "rt-borde"}})
igual(
    motor.areas_a_leer(SIN_AREAS), ["identidad", "direcciones"],
    "un router que sólo declara su identidad lee, además, la dirección de su pata de gestión",
)
igual(
    sorted(motor.areas_a_leer(dict(BORDE, direccion="dhcp"))), sorted(motor.areas_a_leer(BORDE)),
    "y con `direccion: dhcp` esa dirección NO se deriva: no hay nada estático que poner",
)
igual(
    [l["metodo"] for l in motor.lecturas_routeros(BORDE)], ["GET"] * 11,
    "todas las lecturas de un router son GET: leer no cambia nada",
)

print("\nLEER: un CHR recién nacido, con las respuestas CRUDAS de su REST\n")

LEIDO = motor.leido_routeros(CRUDO_RECIEN_NACIDO, BORDE, "admin", CLAVE_PUBLICA, "fabrica")

igual(LEIDO["alcanzable"], True, "se le pudo preguntar (llegó y contestó)")
igual(
    LEIDO["areas"]["identidad"],
    {"nombre": "CHR", "usuario_motor": True, "credencial_motor": False, "clave_motor": False,
     "usuarios": {"admin": "*1"}},
    "el equipo se llama CHR, su usuario del motor existe y NO tiene todavía ni la credencial ni la clave del motor",
)
igual(
    LEIDO["areas"]["servicios"]["deshabilitados"], ["www-ssl"],
    "sólo las entradas ESTÁTICAS cuentan como configuración: la conexión viva del motor no es un servicio que se apague",
)
igual(
    LEIDO["areas"]["servicios"]["ids"]["www"], "*2",
    "y el `.id` de `www` es el ESTÁTICO, no el de la conexión dinámica (`*E`)",
)
igual(
    LEIDO["areas"]["cliente_dhcp"]["habilitado"], True,
    "el cliente DHCP de fábrica está vivo (es la única forma de que el equipo sea alcanzable)",
)
igual(
    LEIDO["areas"]["direcciones"]["estaticas"], [],
    "su dirección de gestión es DINÁMICA: no cuenta como estática",
)
igual(
    LEIDO["areas"]["direcciones"]["dinamicas"],
    [{"interfaz": "ether1", "direccion": "10.40.0.11/24"}],
    "y se ve como dinámica, que es lo que el motor necesita distinguir",
)
igual(
    LEIDO["areas"]["rutas"]["estaticas"], [],
    "la ruta por defecto que puso el DHCP NO es estática: no la declara el lab",
)
igual(
    LEIDO["areas"]["dhcp"]["servidores"], [],
    "y el router todavía no sirve ninguna red",
)
igual(
    LEIDO["residuo"], {"direccion_dinamica": False, "ruta_dinamica": False},
    "mientras el cliente de fábrica está VIVO no hay residuo que declarar: su dirección dinámica es la forma de ser alcanzable hasta que el motor entre",
)

print("\nDECIDIR: (declarado, leído) -> lo que hay que cambiar\n")

PASOS = motor.pasos_de_convergencia(BORDE, IDENTIDAD, DECLARACION, LEIDO, PARAMETROS)
OPERACIONES = motor.operaciones_de_pasos(PASOS)
OPS = [op["op"] for op in OPERACIONES]

igual(
    OPS,
    ["poner_direccion", "poner_direccion",
     "deshabilitar_servicio", "deshabilitar_servicio", "deshabilitar_servicio",
     "deshabilitar_servicio", "deshabilitar_cliente_dhcp", "poner_ruta",
     "poner_servidor_dhcp", "poner_red_dhcp", "poner_reserva",
     "poner_identidad", "importar_clave_motor", "poner_credencial_motor"],
    "las áreas van en el orden del MOTOR, no en el que las escriba el lab: la dirección "
    "de gestión ANTES de apagar el cliente de fábrica (si no, el router se queda sin "
    "dirección y la escritura sin respuesta: medido), la identidad AL FINAL, y dentro de "
    "la identidad la clave ANTES que la credencial (medido: al revés, la escritura de la "
    "clave se queda sin credencial y contesta 401)",
)
igual(
    [(op["interfaz"], op["direccion"]) for op in OPERACIONES if op["op"] == "poner_direccion"],
    [("ether1", "10.40.0.11/24"), ("ether2", "10.40.1.1/24")],
    "la primera es la de GESTIÓN (derivada del `direccion:` del invitado): sin ella, apagar el cliente de fábrica dejaría al router sin camino de vuelta",
)
igual(
    [op.get("servicio") for op in OPERACIONES if op["op"] == "deshabilitar_servicio"],
    ["api", "api-ssl", "ftp", "telnet"],
    "se apagan los cuatro servicios declarados (en orden alfabético), y `www` NO está entre ellos",
)
igual(
    OPERACIONES[-1]["op"], "poner_credencial_motor",
    "lo último de todo es la CREDENCIAL del motor: la clave se importa antes y la "
    "contraseña de fábrica se cambia al final, porque cambiarla invalida la credencial con "
    "la que se estaba hablando (medido: un 401 en la escritura siguiente, la de la clave)",
)
igual(
    OPERACIONES[-1].get("tolerar_sin_respuesta"), True,
    "y esa escritura tolera perder la respuesta: cambiar la contraseña del usuario con el "
    "que se habla MATA la sesión y RouterOS contesta 400 `Bad Request Session closed` "
    "(medido) aunque el cambio haya surtido efecto -- la convergencia la dice la relectura",
)

print("\nESCRIBIR: lo decidido -> llamadas REST, con sus cuerpos\n")

LLAMADAS = motor.escrituras_routeros(
    OPERACIONES, BORDE, DECLARACION, IDENTIDAD, PARAMETROS_ROUTEROS, LEIDO
)
FIRMAS = [(l["metodo"], l["ruta"]) for l in LLAMADAS if l["accion"] == "escribir"]

igual(
    [l for l in FIRMAS if l[1].endswith("remove")], [],
    "de un router recién nacido no se quita NADA del lab: la única retirada que había era la "
    "dirección prestada del baile, y el baile ya no existe (el intercambio lo hace el router "
    "en un guion, ver la sección 4)",
)
comprobar(
    ("POST", "/ip/service/set") in FIRMAS and ("POST", "/execute") in FIRMAS,
    "se apagan servicios por POST (RouterOS no admite PUT) y el cliente DHCP se quita DENTRO "
    "del guion del intercambio: quitarlo por fuera deja al equipo sin dirección antes de "
    "contestar (medido)",
)
comprobar(
    ("POST", "/ip/address/add") in FIRMAS and ("POST", "/ip/route/add") in FIRMAS,
    "la dirección y la ruta se AÑADEN (medido: un `PUT /rest/ip/route` responde 400)",
)
comprobar(
    [l["ruta"] for l in LLAMADAS][-1] == "/user/set"
    and [l["ruta"] for l in LLAMADAS][-4:-1]
    == ["/system/identity/set", "/user/ssh-keys/add", "/execute"],
    "la credencial es lo ÚLTIMO del lab, y por delante van el nombre, la clave y el guion del "
    "intercambio de la dirección: el guion es la escritura que puede dejar al equipo sin "
    "camino un instante, y cambiando la credencial ninguna escritura posterior encuentra "
    "credencial (medido: un 401 tolerado que deja la pasada a medias, con el equipo ya bueno)",
)
comprobar(
    all("www" not in str(l.get("cuerpo")) for l in LLAMADAS),
    "`www` no aparece en ningún cuerpo: es donde vive REST, o sea el camino de vuelta",
)
igual(
    [l.get("tolerar_sin_respuesta") for l in LLAMADAS if l["ruta"] == "/user/set"], [True],
    "el corte por diseño (400 `Session closed` al cambiar la contraseña del usuario con el "
    "que se habla) llega hasta la llamada de verdad: si no, el driver pararía justo al ir bien",
)


def llamada(ruta):
    return [l for l in LLAMADAS if l.get("ruta") == ruta][0]


igual(
    [l["cuerpo"] for l in LLAMADAS
     if l.get("ruta") == "/ip/address/add"
     and l["cuerpo"].get("address") in ("10.40.0.11/24", "10.40.1.1/24")],
    [
        {"address": "10.40.1.1/24", "interface": "ether2"},
    ],
    "por fuera sólo se pone la pata que NO es la boca de gestión (la LAN del lab en ether2): "
    "la de gestión la pone el router dentro del guion del intercambio, porque su cliente de "
    "fábrica la tiene cogida (ver la sección 4)",
)
igual(
    llamada("/ip/route/add")["cuerpo"],
    {"dst-address": "0.0.0.0/0", "gateway": "10.40.0.1"},
    "y la ruta por defecto sale por la pasarela declarada (el puente de gestión del nodo)",
)
igual(
    [l["ruta"] for l in LLAMADAS if l["ruta"] == "/ip/dhcp-client/set"], [],
    "el cliente de fábrica no se «apaga» por fuera: se QUITA dentro del guion, junto a la "
    "estática que hay que poner en su lugar. Es lo único que no deja al equipo sin dirección "
    "entre las dos cosas (medido)",
)
igual(
    llamada("/ip/pool/add")["cuerpo"],
    {"name": "netlabs-10.40.1.100", "ranges": "10.40.1.100-10.40.1.200"},
    "el rango declarado se declara como pool, con un nombre DERIVADO del rango",
)
igual(
    llamada("/ip/dhcp-server/add")["cuerpo"],
    {"interface": "ether2", "address-pool": "netlabs-10.40.1.100", "disabled": "no",
     "name": "netlabs-ether2"},
    "el servidor DHCP sirve ese rango en esa interfaz",
)
igual(
    llamada("/ip/dhcp-server/network/add")["cuerpo"],
    {"address": "10.40.1.0/24", "gateway": "10.40.1.1", "dns-server": "10.40.1.1"},
    "y anuncia la red declarada con su pasarela y su DNS",
)
igual(
    llamada("/ip/dhcp-server/lease/add")["cuerpo"],
    {"address": "10.40.1.11", "mac-address": "BC:24:11:00:00:6E", "server": "netlabs-ether2"},
    "la reserva va a la MAC DERIVADA del vmid del router de esa red (110 = 0x6E) y al servidor de ESA interfaz",
)

print("\nEL DIARIO: la contraseña nunca se escribe\n")

igual(
    motor.sin_secretos(llamada("/user/set")["cuerpo"]),
    {"numbers": "admin", "password": "···"},
    "la credencial del motor aparece TAPADA en el diario (por nombre de campo, no por confianza)",
)
igual(
    motor.sin_secretos({"a": [{"password": "x", "otra": "visible"}], "clave": "y", "nombre": "z"}),
    {"a": [{"password": "···", "otra": "visible"}], "clave": "···", "nombre": "z"},
    "y se tapa también anidada, dentro de listas y de mapas",
)

# ---------------------------------------------------------------------------
# 2. El MISMO router ya convergido: cero operaciones (la idempotencia)
# ---------------------------------------------------------------------------
# El estado que resulta de aplicar lo de arriba, con las MISMAS formas que contesta el
# REST. Si algo de esto no coincidiera, la segunda ejecución volvería a escribir.
CONVERGIDO = {
    "/system/identity": respuesta({"name": "rt-borde"}),
    "/user": respuesta([{"name": "admin", "group": "full", ".id": "*1"}]),
    "/user/ssh-keys": respuesta([{"user": "admin", "key": CLAVE_PUBLICA, ".id": "*1"}]),
    "/ip/service": respuesta([
        {".id": "*0", "name": "telnet", "disabled": "true", "dynamic": "false"},
        {".id": "*1", "name": "ftp", "disabled": "true", "dynamic": "false"},
        {".id": "*2", "name": "www", "disabled": "false", "dynamic": "false"},
        {".id": "*4", "name": "ssh", "disabled": "false", "dynamic": "false"},
        {".id": "*6", "name": "www-ssl", "disabled": "true", "dynamic": "false"},
        {".id": "*7", "name": "api", "disabled": "true", "dynamic": "false"},
        {".id": "*9", "name": "api-ssl", "disabled": "true", "dynamic": "false"},
        # La conexión viva del motor sigue estando ahí, y no cuenta.
        {".id": "*E", "name": "www", "disabled": "false", "dynamic": "true", "connection": "true"},
    ]),
    # El cliente de fábrica apagado... pero su dirección y su ruta siguen ahí: es el
    # RESIDUO medido (la API no las borra; lo resuelve un reinicio, declarado en el plan).
    "/ip/dhcp-client": respuesta([
        {".id": "*1", "interface": "ether1", "disabled": "true", "address": "10.40.0.11/24"}
    ]),
    "/ip/address": respuesta([
        {".id": "*1", "address": "10.40.0.11/24", "interface": "ether1", "dynamic": "true"},
        {".id": "*2", "address": "10.40.0.11/24", "interface": "ether1", "dynamic": "false"},
        {".id": "*3", "address": "10.40.1.1/24", "interface": "ether2", "dynamic": "false"},
    ]),
    "/ip/route": respuesta([
        {".id": "*1", "dst-address": "0.0.0.0/0", "gateway": "10.40.0.10", "dynamic": "true", "dhcp": "true"},
        {".id": "*2", "dst-address": "10.40.0.0/24", "gateway": "ether1", "dynamic": "true", "connect": "true"},
        {".id": "*3", "dst-address": "0.0.0.0/0", "gateway": "10.40.0.1", "dynamic": "false"},
    ]),
    "/ip/dhcp-server": respuesta([
        {".id": "*7", "interface": "ether2", "address-pool": "netlabs-10.40.1.100", "name": "netlabs-ether2"}
    ]),
    "/ip/pool": respuesta([{".id": "*8", "name": "netlabs-10.40.1.100", "ranges": "10.40.1.100-10.40.1.200"}]),
    "/ip/dhcp-server/network": respuesta([
        {".id": "*9", "address": "10.40.1.0/24", "gateway": "10.40.1.1", "dns-server": "10.40.1.1"}
    ]),
    "/ip/dhcp-server/lease": respuesta([
        {".id": "*10", "address": "10.40.1.11", "mac-address": "BC:24:11:00:00:6E", "server": "netlabs-ether2", "dynamic": "false"}
    ]),
}

print("\nIDEMPOTENCIA: un router ya convergido no genera ni una operación\n")

LEIDO_AL_DIA = motor.leido_routeros(CONVERGIDO, BORDE, "admin", CLAVE_PUBLICA, "motor")
PASOS_AL_DIA = motor.pasos_de_convergencia(BORDE, IDENTIDAD, DECLARACION, LEIDO_AL_DIA, PARAMETROS)
igual(
    motor.operaciones_de_pasos(PASOS_AL_DIA), [],
    "cero operaciones: no hay nada que escribir en un router al día",
)
igual(
    [(p["accion"], p["via"]) for p in PASOS_AL_DIA], [("reiniciar_invitado", "api")],
    "y lo único que queda es el REINICIO declarado por el residuo del cliente de fábrica (por la API, no escondido)",
)
igual(
    LEIDO_AL_DIA["residuo"], {"direccion_dinamica": True, "ruta_dinamica": True},
    "el residuo se ve: la dirección y la ruta dinámicas siguen ahí tras apagar el cliente",
)

# Y sin residuo, ni siquiera eso: el router está al día del todo.
SIN_RESIDUO = dict(CONVERGIDO)
SIN_RESIDUO["/ip/address"] = respuesta([
    {".id": "*1", "address": "10.40.0.11/24", "interface": "ether1", "dynamic": "false"},
    {".id": "*3", "address": "10.40.1.1/24", "interface": "ether2", "dynamic": "false"},
])
SIN_RESIDUO["/ip/route"] = respuesta([
    {".id": "*1", "dst-address": "10.40.0.0/24", "gateway": "ether1", "dynamic": "true", "connect": "true"},
    {".id": "*3", "dst-address": "0.0.0.0/0", "gateway": "10.40.0.1", "dynamic": "false"},
])
igual(
    motor.pasos_de_convergencia(
        BORDE, IDENTIDAD, DECLARACION,
        motor.leido_routeros(SIN_RESIDUO, BORDE, "admin", CLAVE_PUBLICA, "motor"), PARAMETROS,
    ),
    [],
    "sin residuo, el router no genera ni un paso: la segunda ejecución es `changed=0`",
)

print("\nQUITAR LO QUE NO SE DECLARA: lo que sobra en un área declarada, se va\n")

DE_MAS = dict(CONVERGIDO)
DE_MAS["/ip/address"] = respuesta([
    {".id": "*1", "address": "10.40.0.11/24", "interface": "ether1", "dynamic": "false"},
    {".id": "*2", "address": "10.40.1.1/24", "interface": "ether2", "dynamic": "false"},
    {".id": "*3", "address": "192.168.99.1/24", "interface": "ether2", "dynamic": "false"},
])
DE_MAS["/ip/dhcp-server/lease"] = respuesta([
    {".id": "*10", "address": "10.40.1.11", "mac-address": "BC:24:11:00:00:6E", "server": "netlabs-ether2", "dynamic": "false"},
    {".id": "*11", "address": "10.40.1.150", "mac-address": "AA:BB:CC:DD:EE:FF", "server": "netlabs-ether2", "dynamic": "false"},
])
LEIDO_DE_MAS = motor.leido_routeros(DE_MAS, BORDE, "admin", CLAVE_PUBLICA, "motor")
OPERACIONES_DE_MAS = motor.operaciones_de_pasos(
    motor.pasos_de_convergencia(BORDE, IDENTIDAD, DECLARACION, LEIDO_DE_MAS, PARAMETROS)
)
igual(
    [op["op"] for op in OPERACIONES_DE_MAS],
    ["quitar_direccion", "quitar_reserva"],
    "una dirección y una reserva que el lab no declara se QUITAN (no se dejan por ahí)",
)
LLAMADAS_DE_MAS = motor.escrituras_routeros(
    OPERACIONES_DE_MAS, BORDE, DECLARACION, IDENTIDAD, PARAMETROS_ROUTEROS, LEIDO_DE_MAS
)
igual(
    [(l["metodo"], l["ruta"], l["cuerpo"]) for l in LLAMADAS_DE_MAS],
    [
        ("POST", "/ip/address/remove", {"numbers": "*3"}),
        ("POST", "/ip/dhcp-server/lease/remove", {"numbers": "*11"}),
    ],
    "y se quitan por su `.id` (el que se leyó), no por descarte",
)

# ---------------------------------------------------------------------------
# 3. Cuando al router NO se le puede preguntar
# ---------------------------------------------------------------------------
print("\nNO SE PUDO PREGUNTAR: -1 no es «eso no está»\n")

SIN_CONTACTO = {
    "/system/identity": {"status": -1, "json": {}, "error": "no se pudo conectar con http://10.40.0.11"},
    "/user": {"status": -1, "json": {}, "error": ""},
}
LEIDO_SIN_CONTACTO = motor.leido_routeros(SIN_CONTACTO, BORDE, "admin", CLAVE_PUBLICA, "fabrica")
igual(LEIDO_SIN_CONTACTO["alcanzable"], False, "el motor sabe que no llegó, y no decide nada")
comprobar(
    "no se pudo conectar" in LEIDO_SIN_CONTACTO["motivo"],
    "y lo dice con el motivo (lo que hay que ir a mirar), no con un «falló»",
)

CREDENCIAL_MALA = dict(CRUDO_RECIEN_NACIDO)
CREDENCIAL_MALA["/system/identity"] = respuesta(
    {"error": 401, "message": "not authorized"}, status=401
)
LEIDO_401 = motor.leido_routeros(CREDENCIAL_MALA, BORDE, "admin", CLAVE_PUBLICA, "fabrica")
igual(
    LEIDO_401["alcanzable"], True,
    "un 401 NO es «no llegué»: se llegó, y lo que no vale es la credencial (eso es lo normal la primera vez)",
)

# ---------------------------------------------------------------------------
# 4. El choque de direcciones: el intercambio va DENTRO del router, en un guion
# ---------------------------------------------------------------------------
print("\nEL CHOQUE DE DIRECCIONES: el intercambio lo hace el router, entero y de una vez\n")

# Esta es la lectura REAL del CHR 108 en el momento de escribir (14-nov-2026, medido): el
# cliente de fábrica seguía VIVO y tenía puesta la dirección declarada (10.40.0.11/24) en
# ether1. Ponerla como estática se comió un 400 «already have such address» (ADR 0006 §5),
# y apagar el cliente primero deja al equipo sin dirección --y a la llamada sin respuesta--:
# es un círculo que NO se rodea a pasos desde fuera. Lo que se hace es mandarle al router,
# en UNA llamada, el trabajo que tiene que hacer él solo y de una vez.
LEIDO_CON_CHOQUE = dict(LEIDO)
LEIDO_CON_CHOQUE["areas"] = dict(LEIDO["areas"])
LEIDO_CON_CHOQUE["areas"]["direcciones"] = {
    "estaticas": [],
    "dinamicas": [{"interfaz": "ether1", "direccion": "10.40.0.11/24"}],
}
LEIDO_CON_CHOQUE["areas"]["cliente_dhcp"] = {
    "habilitado": True, "interfaz": "ether1", "ids": {"ether1": "*1"},
}

OPERACIONES_CHOQUE = motor.operaciones_de_pasos(
    motor.pasos_de_convergencia(BORDE, IDENTIDAD, DECLARACION, LEIDO_CON_CHOQUE, PARAMETROS)
)
LLAMADAS_CHOQUE = motor.escrituras_routeros(
    OPERACIONES_CHOQUE, BORDE, DECLARACION, IDENTIDAD, PARAMETROS_ROUTEROS, LEIDO_CON_CHOQUE
)


def _posicion(condicion):
    """Dónde está la primera llamada que cumple `condicion` (-1 si no está)."""
    for numero, llamada in enumerate(LLAMADAS_CHOQUE):
        if condicion(llamada):
            return numero
    return -1


GUIONES = [l for l in LLAMADAS_CHOQUE if l["ruta"] == "/execute"]
igual(
    [l["metodo"] for l in GUIONES], ["POST"],
    "el intercambio es UNA llamada (`POST /execute`) con el guion dentro: no hay baile de "
    "pasos desde fuera, que es lo que se rompía (medido: un `POST /ip/address/add` de la "
    "prestada se quedó sin respuesta en el CHR del segundo escalón, con el mismo cuerpo que "
    "en el primero contesta 200)",
)
GUION = GUIONES[0]["cuerpo"]["script"] if GUIONES else ""
comprobar(
    "/ip dhcp-client remove [find interface=ether1]" in GUION,
    "y en el guion va lo que tiene que ir junto: quitar el cliente DHCP de la boca de gestión "
    f"(guion: {GUION!r})",
)
comprobar(
    "/ip address add address=10.40.0.11/24 interface=ether1" in GUION,
    "y poner la dirección declarada en la MISMA ejecución: quitando al cliente, el equipo se "
    "queda sin dirección, así que las dos cosas o ninguna",
)
igual(
    [l["cuerpo"] for l in LLAMADAS_CHOQUE
     if l["ruta"] == "/ip/address/add" and l["cuerpo"].get("address") == "10.40.0.11/24"],
    [],
    "y la estática de gestión no se manda ADEMÁS por fuera: el duplicado que RouterOS rechaza "
    "con un 400 es exactamente lo que el guion está resolviendo (trampa ya pagada en v3: las "
    "dos listas se sumaban tal cual y el guion emitía el `add` dos veces)",
)
igual(
    [l["ruta"] for l in LLAMADAS_CHOQUE if l["ruta"] == "/ip/dhcp-client/set"], [],
    "ni el cliente se apaga por fuera: se quita dentro del guion, que es lo único que no deja "
    "al equipo sin dirección entre las dos cosas",
)
igual(
    GUIONES[0].get("tolerar_sin_respuesta") if GUIONES else None, True,
    "el guion DECLARA que puede quedarse sin respuesta: es la llamada que puede dejar al "
    "equipo sin camino un instante, y quien prueba el efecto es la relectura",
)
igual(
    GUIONES[0].get("direccion") if GUIONES else "x", None,
    "y va por la dirección declarada (no estampa ninguna otra): la convergencia no cambia de "
    "dirección a media convergencia -- la cambia el router, él solo y de una vez",
)
_POS_GUION = _posicion(lambda l: l["ruta"] == "/execute")
_POS_CREDENCIAL = _posicion(lambda l: l["ruta"] == "/user/set")
comprobar(
    _POS_GUION >= 0 and (_POS_CREDENCIAL == -1 or _POS_GUION < _POS_CREDENCIAL),
    "el guion va ANTES del cambio de credencial: la credencial es el intercambio que cierra "
    "y deja sin credencial a cualquier escritura posterior (medido: un 401 tolerado que se "
    "queda sin hacer)",
)
igual(
    sorted({l["area"] for l in LLAMADAS_CHOQUE[_POS_GUION + 1:]}), ["identidad"],
    "y detrás del guion sólo queda la identidad: es la ÚLTIMA escritura que puede dejar al "
    "equipo sin camino, así que lo que se pueda dar hecho antes, hecho está",
)
igual(
    [l for l in LLAMADAS_CHOQUE if "www" in str(l["cuerpo"])], [],
    "en ningún momento se toca `www`: es el REST, o sea el camino de vuelta",
)
igual(
    [l.get("direccion") for l in LLAMADAS_CHOQUE
     if l["ruta"] == "/ip/address/add" and l["cuerpo"].get("address") == "10.40.1.1/24"],
    [None],
    "la otra pata del router (ether2) se pone por fuera y por la dirección declarada: del "
    "intercambio sólo se ocupa la boca por la que entra la convergencia",
)

# El RESIDUO: el cliente ya no está, pero la entrada dinámica que dejó sigue puesta (RouterOS
# no la borra al irse el cliente, medido). Aquí no hay cliente que quitar: lo que hay que
# soltar es la entrada, y por eso el guion la suelta y espera antes de poner la estática.
LEIDO_CON_RESIDUO = dict(LEIDO_CON_CHOQUE)
LEIDO_CON_RESIDUO["areas"] = dict(LEIDO_CON_CHOQUE["areas"])
LEIDO_CON_RESIDUO["areas"]["cliente_dhcp"] = {"habilitado": False}
LLAMADAS_RESIDUO = motor.escrituras_routeros(
    motor.operaciones_de_pasos(
        motor.pasos_de_convergencia(BORDE, IDENTIDAD, DECLARACION, LEIDO_CON_RESIDUO, PARAMETROS)
    ),
    BORDE, DECLARACION, IDENTIDAD, PARAMETROS_ROUTEROS, LEIDO_CON_RESIDUO,
)
_GUIONES_RESIDUO = [l for l in LLAMADAS_RESIDUO if l["ruta"] == "/execute"]
_RESIDUO = _GUIONES_RESIDUO[0]["cuerpo"]["script"] if _GUIONES_RESIDUO else ""
comprobar(
    "/ip address remove [find address=10.40.0.11 interface=ether1 dynamic=yes]" in _RESIDUO,
    "con el cliente ya retirado, el guion suelta la entrada dinámica que dejó: sin soltarla, "
    "el `add` de la estática choca con el mismo 400 de siempre",
)
comprobar(
    ":delay 2s" in _RESIDUO and "/ip address add address=10.40.0.11/24 interface=ether1" in _RESIDUO,
    "y le da un respiro antes de poner la declarada: el guion corre ENTERO dentro del equipo, "
    "así que ese respiro no abre ninguna ventana hacia fuera",
)
igual(
    [l["ruta"] for l in LLAMADAS_RESIDUO if l["ruta"] == "/ip/dhcp-client/set"], [],
    "y sin cliente vivo no se manda apagar ninguno: al guion se le pide lo que hay, no lo "
    "que hubo",
)

# Y sin choque ni residuo no hay guion: con el router ya convergido (cliente apagado,
# dirección estática, nada dinámico) no se manda ni eso.
LLAMADAS_AL_DIA = motor.escrituras_routeros(
    motor.operaciones_de_pasos(PASOS_AL_DIA), BORDE, DECLARACION, IDENTIDAD,
    PARAMETROS_ROUTEROS, LEIDO_AL_DIA,
)
igual(
    LLAMADAS_AL_DIA, [],
    "un router ya convergido no genera NINGUNA llamada, ni el guion ni nada (idempotencia)",
)


print("\n" + "=" * 62)
if FALLOS:
    print(f"RESULTADO: {len(FALLOS)} fallo(s).")
    sys.exit(1)
print("RESULTADO: todos los casos en verde")
