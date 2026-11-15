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
#                 túnel de vuelta del motor);
#              4. la credencial del motor va la ÚLTIMA (identidad al final del plan);
#              5. la contraseña NO se escribe en el diario: `sin_secretos` la tapa;
#              6. con un router ya convergido, CERO operaciones (idempotencia por
#                 construcción); y con el residuo del cliente de fábrica, el reinicio
#                 del invitado declarado en el plan.
# LÍMITES:     no prueba el driver de verdad (eso es el ciclo contra el VPS): aquí no se
#              toca ningún equipo. Las respuestas están COPIADAS de un CHR 7.25.1 real
#              (medido, ver `labs/04_lab-red-routeros/` y el ADR del interior).
# VER:         docs/decisiones/0006-*.md; filter_plugins/interior.py;
#              tasks/ros_api.yml; tasks/configurar_routeros.yml

# Uso:  python3 test/test_routeros.py     (código de salida != 0 si algo falla)

import copy
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
    open(os.path.join(RAIZ, "labs", "04_lab-red-routeros", "04_lab-red-routeros.yml"))
)
DECLARACION = _validador.declaracion_normalizar(_CRUDA)
BORDE = [i for i in DECLARACION["guests"] if i["rol"] == "borde"][0]

# Los vmids son los del pool real cuando esto se escribió; lo que importa es que la MAC
# se DERIVA de ellos (nadie la escribe a mano, regla 14).
IDENTIDAD = {
    "guests": [
        {"rol": "control", "vmid": 109, "tipo": "lxc", "mac": "BC:24:11:00:00:6D"},
        {"rol": "borde", "vmid": 108, "tipo": "qemu", "mac": "BC:24:11:00:00:6C"},
        {"rol": "nucleo", "vmid": 110, "tipo": "qemu", "mac": "BC:24:11:00:00:6E"},
        {"rol": "servidor", "vmid": 111, "tipo": "lxc", "mac": "BC:24:11:00:00:6F"},
        {"rol": "puesto-1", "vmid": 112, "tipo": "lxc", "mac": "BC:24:11:00:00:70"},
        {"rol": "puesto-2", "vmid": 113, "tipo": "lxc", "mac": "BC:24:11:00:00:71"},
    ]
}
PARAMETROS = {"bridge_gestion": "vmbr1", "tunnel_puerto_base": 20000, "nodo": "nodo-de-prueba"}
CLAVE_PUBLICA = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAINetlabsTúnelDePrueba netlabs_v4_b"
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
    ("identity", ["/system/identity", "/user", "/user/ssh-keys"], True),
    ("ip_services", ["/ip/service"], True),
    ("dhcp_client", ["/ip/dhcp-client"], True),
    ("addresses", ["/ip/address"], True),
    ("routes", ["/ip/route"], True),
    ("dhcp", ["/ip/dhcp-server", "/ip/pool", "/ip/dhcp-server/network", "/ip/dhcp-server/lease"], True),
):
    obtenidas = [lectura["ruta"] for lectura in motor.lecturas_routeros(BORDE)]
    igual(
        [r for r in obtenidas if r in rutas_esperadas], rutas_esperadas,
        f"un RouterOS pregunta por las rutas del área '{area}'",
    )

# Un router SIN áreas declaradas sigue teniendo una cosa que leer: su propia dirección de
# gestión. No es un área que el lab declare -- la deriva el motor del `address:` del
# invitado -- , y es justo lo que impide dejarlo sin túnel de vuelta al apagarle el
# cliente DHCP de fábrica.
SIN_AREAS = dict(BORDE, config={"routeros": {"identity": "rt-borde"}})
igual(
    motor.areas_a_leer(SIN_AREAS), ["identity", "addresses"],
    "un router que sólo declara su identidad lee, además, la dirección de su interfaz de gestión",
)
igual(
    sorted(motor.areas_a_leer(dict(BORDE, address="dhcp"))), sorted(motor.areas_a_leer(BORDE)),
    "y con `address: dhcp` esa dirección NO se deriva: no hay nada estático que poner",
)
igual(
    [l["metodo"] for l in motor.lecturas_routeros(BORDE)], ["GET"] * 11,
    "todas las lecturas de un router son GET: leer no cambia nada",
)

print("\nLEER: un CHR recién nacido, con las respuestas CRUDAS de su REST\n")

LEIDO = motor.leido_routeros(CRUDO_RECIEN_NACIDO, BORDE, "admin", CLAVE_PUBLICA, "fabrica")

igual(LEIDO["alcanzable"], True, "se le pudo preguntar (llegó y contestó)")
igual(
    LEIDO["areas"]["identity"],
    {"nombre": "CHR", "usuario_motor": True, "credencial_motor": False, "clave_motor": False,
     "usuarios": {"admin": "*1"}},
    "el equipo se llama CHR, su usuario del motor existe y NO tiene todavía ni la credencial ni la clave del motor",
)
igual(
    LEIDO["areas"]["ip_services"]["deshabilitados"], ["www-ssl"],
    "sólo las entradas ESTÁTICAS cuentan como configuración: la conexión viva del motor no es un servicio que se apague",
)
igual(
    LEIDO["areas"]["ip_services"]["ids"]["www"], "*2",
    "y el `.id` de `www` es el ESTÁTICO, no el de la conexión dinámica (`*E`)",
)
igual(
    LEIDO["areas"]["dhcp_client"]["habilitado"], True,
    "el cliente DHCP de fábrica está vivo (es la única forma de que el equipo sea alcanzable)",
)
igual(
    LEIDO["areas"]["addresses"]["estaticas"], [],
    "su dirección de gestión es DINÁMICA: no cuenta como estática",
)
igual(
    LEIDO["areas"]["addresses"]["dinamicas"],
    [{"interface": "ether1", "address": "10.40.0.11/24"}],
    "y se ve como dinámica, que es lo que el motor necesita distinguir",
)
igual(
    LEIDO["areas"]["routes"]["estaticas"], [],
    "la ruta por defecto que puso el DHCP NO es estática: no la declara el lab",
)
igual(
    LEIDO["areas"]["dhcp_server"]["servidores"], [],
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
    ["add_address", "add_address",
     "disable_service", "disable_service", "disable_service",
     "disable_service", "disable_dhcp_client", "add_route",
     "add_dhcp_server", "add_dhcp_network", "add_static_lease",
     "set_identity", "import_engine_key", "set_engine_credential"],
    "las áreas van en el orden del MOTOR, no en el que las escriba el lab: la dirección "
    "de gestión ANTES de apagar el cliente de fábrica (si no, el router se queda sin "
    "dirección y la escritura sin respuesta: medido), la identidad AL FINAL, y dentro de "
    "la identidad la clave ANTES que la credencial (medido: al revés, la escritura de la "
    "clave se queda sin credencial y contesta 401)",
)
igual(
    [(op["interface"], op["address"]) for op in OPERACIONES if op["op"] == "add_address"],
    [("ether1", "10.40.0.11/24"), ("ether2", "10.40.1.1/24")],
    "la primera es la de GESTIÓN (derivada del `address:` del invitado): sin ella, apagar el cliente de fábrica dejaría al router sin túnel de vuelta",
)
igual(
    [op.get("servicio") for op in OPERACIONES if op["op"] == "disable_service"],
    ["api", "api-ssl", "ftp", "telnet"],
    "se apagan los cuatro servicios declarados (en orden alfabético), y `www` NO está entre ellos",
)
igual(
    OPERACIONES[-1]["op"], "set_engine_credential",
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
    "túnel un instante, y cambiando la credencial ninguna escritura posterior encuentra "
    "credencial (medido: un 401 tolerado que deja la pasada a medias, con el equipo ya bueno)",
)
comprobar(
    all("www" not in str(l.get("cuerpo")) for l in LLAMADAS),
    "`www` no aparece en ningún cuerpo: es donde vive REST, o sea el túnel de vuelta",
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
    "por fuera sólo se pone la interfaz que NO es la boca de gestión (la LAN del lab en ether2): "
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
    [(p["accion"], p["via"]) for p in PASOS_AL_DIA], [("reiniciar_guest", "api")],
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
    ["remove_address", "remove_static_lease"],
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
# 2.b UN ROUTER CON DOS ÁMBITOS DHCP: cada servidor compara SÓLO sus reservas
# ---------------------------------------------------------------------------
# Medido con `07_dunder-mifflin`, el primer lab con dos LANs en un mismo router: el
# ámbito de la segunda red pedía QUITAR la reserva de la primera -- que no es suya, y
# que el otro ámbito está declarando en la misma pasada -- así que el router no
# convergía nunca (la pasada moría con `[dhcp] remove_static_lease` pendiente). Un router de
# una empresa pequeña con dos áreas es un caso legítimo, no un lab raro: lo que estaba
# mal era comparar las concesiones de todas las redes contra las de una.
print("\nDOS ÁMBITOS EN UN ROUTER: las reservas de una LAN no son de la otra\n")

BORDE_DOS_AMBITOS = copy.deepcopy(BORDE)
BORDE_DOS_AMBITOS["bridges"] = ["vmb_gestion", "vmb_lan1", "vmb_lan2"]
BORDE_DOS_AMBITOS["config"]["routeros"]["addresses"] = [
    {"interface": "ether2", "address": "10.40.1.1/24"},
    {"interface": "ether3", "address": "10.40.2.1/24"},
]
BORDE_DOS_AMBITOS["config"]["routeros"]["dhcp_server"] = [
    {
        "interface": "ether2",
        "pool": {"rango": "10.40.1.100-10.40.1.200"},
        "network": {"address": "10.40.1.0/24", "gateway": "10.40.1.1", "dns": ["10.40.1.1"]},
        "static_leases": "derived",
    },
    {
        "interface": "ether3",
        "pool": {"rango": "10.40.2.100-10.40.2.200"},
        "network": {"address": "10.40.2.0/24", "gateway": "10.40.2.1", "dns": ["10.40.2.1"]},
        "static_leases": "derived",
    },
]
igual(
    [
        r["rol"] for r in motor.reservas_derivadas(
            DECLARACION, IDENTIDAD, BORDE_DOS_AMBITOS, en_red="10.40.1.0/24"
        )
    ],
    ["nucleo"],
    "el ámbito de la LAN 1 reserva a quien tiene dirección declarada DENTRO de su red (el nucleo)",
)
igual(
    motor.reservas_derivadas(DECLARACION, IDENTIDAD, BORDE_DOS_AMBITOS, en_red="10.40.2.0/24"), [],
    "y el de la LAN 2 no reserva nada: allí no hay nada con dirección fija",
)

DOS_AMBITOS = dict(CONVERGIDO)
DOS_AMBITOS["/ip/address"] = respuesta([
    {".id": "*1", "address": "10.40.0.11/24", "interface": "ether1", "dynamic": "false"},
    {".id": "*2", "address": "10.40.1.1/24", "interface": "ether2", "dynamic": "false"},
    {".id": "*3", "address": "10.40.2.1/24", "interface": "ether3", "dynamic": "false"},
])
DOS_AMBITOS["/ip/route"] = respuesta([
    {".id": "*1", "dst-address": "10.40.0.0/24", "gateway": "ether1", "dynamic": "true", "connect": "true"},
    {".id": "*3", "dst-address": "0.0.0.0/0", "gateway": "10.40.0.1", "dynamic": "false"},
])
DOS_AMBITOS["/ip/dhcp-server"] = respuesta([
    {".id": "*7", "interface": "ether2", "address-pool": "netlabs-10.40.1.100", "name": "netlabs-ether2"},
    {".id": "*8", "interface": "ether3", "address-pool": "netlabs-10.40.2.100", "name": "netlabs-ether3"},
])
DOS_AMBITOS["/ip/pool"] = respuesta([
    {".id": "*8", "name": "netlabs-10.40.1.100", "ranges": "10.40.1.100-10.40.1.200"},
    {".id": "*9", "name": "netlabs-10.40.2.100", "ranges": "10.40.2.100-10.40.2.200"},
])
DOS_AMBITOS["/ip/dhcp-server/network"] = respuesta([
    {".id": "*9", "address": "10.40.1.0/24", "gateway": "10.40.1.1", "dns-server": "10.40.1.1"},
    {".id": "*A", "address": "10.40.2.0/24", "gateway": "10.40.2.1", "dns-server": "10.40.2.1"},
])
# La reserva de la LAN 1, atada a SU servidor: la LAN 2 no tiene por qué tocarla.
DOS_AMBITOS["/ip/dhcp-server/lease"] = respuesta([
    {".id": "*10", "address": "10.40.1.11", "mac-address": "BC:24:11:00:00:6E",
     "server": "netlabs-ether2", "dynamic": "false"},
])
LEIDO_DOS_AMBITOS = motor.leido_routeros(
    DOS_AMBITOS, BORDE_DOS_AMBITOS, "admin", CLAVE_PUBLICA, "motor"
)
igual(
    motor.operaciones_de_pasos(
        motor.pasos_de_convergencia(
            BORDE_DOS_AMBITOS, IDENTIDAD, DECLARACION, LEIDO_DOS_AMBITOS, PARAMETROS
        )
    ),
    [],
    "con las dos LANs servidas y sus reservas puestas, CERO operaciones: el segundo ámbito "
    "no le quita la reserva al primero (era el fallo: no convergía nunca)",
)
igual(
    [
        (s["interface"], s["nombre"]) for s in LEIDO_DOS_AMBITOS["areas"]["dhcp_server"]["servidores"]
    ],
    [("ether2", "netlabs-ether2"), ("ether3", "netlabs-ether3")],
    "y se leen los DOS servidores, cada uno con su nombre derivado de su interfaz",
)

# Lo que sí sobra en el SEGUNDO ámbito también se quita: la reserva que no declara
# ningún ámbito del lab es de nadie, y ahí no se deja.
DE_MAS_DOS_AMBITOS = dict(DOS_AMBITOS)
DE_MAS_DOS_AMBITOS["/ip/dhcp-server/lease"] = respuesta([
    {".id": "*10", "address": "10.40.1.11", "mac-address": "BC:24:11:00:00:6E",
     "server": "netlabs-ether2", "dynamic": "false"},
    {".id": "*11", "address": "10.40.2.150", "mac-address": "AA:BB:CC:DD:EE:FF",
     "server": "netlabs-ether3", "dynamic": "false"},
])
LEIDO_DE_MAS_DOS_AMBITOS = motor.leido_routeros(
    DE_MAS_DOS_AMBITOS, BORDE_DOS_AMBITOS, "admin", CLAVE_PUBLICA, "motor"
)
OPERACIONES_DE_MAS_DOS_AMBITOS = motor.operaciones_de_pasos(
    motor.pasos_de_convergencia(
        BORDE_DOS_AMBITOS, IDENTIDAD, DECLARACION, LEIDO_DE_MAS_DOS_AMBITOS, PARAMETROS
    )
)
igual(
    [(op["op"], op.get("mac")) for op in OPERACIONES_DE_MAS_DOS_AMBITOS],
    [("remove_static_lease", "AA:BB:CC:DD:EE:FF")],
    "una reserva del segundo ámbito que el lab no declara SÍ se quita: se compara por "
    "servidor, no se ignora lo que hay en él",
)

# Y una concesión que no dice a quién sirve (sin `server`, o `all`) se atribuye a la red
# en la que CAE su dirección: es lo que la deja a la vista de SU ámbito -- y no de los
# dos -- sin cambiar nada en un router de una sola LAN, donde no hay duda posible.
SIN_SERVIDOR = dict(DOS_AMBITOS)
SIN_SERVIDOR["/ip/dhcp-server/lease"] = respuesta([
    {".id": "*10", "address": "10.40.1.11", "mac-address": "BC:24:11:00:00:6E", "dynamic": "false"},
    {".id": "*11", "address": "10.40.2.150", "mac-address": "AA:BB:CC:DD:EE:FF", "dynamic": "false"},
])
LEIDO_SIN_SERVIDOR = motor.leido_routeros(
    SIN_SERVIDOR, BORDE_DOS_AMBITOS, "admin", CLAVE_PUBLICA, "motor"
)
igual(
    [
        (op["op"], op.get("mac"))
        for op in motor.operaciones_de_pasos(
            motor.pasos_de_convergencia(
                BORDE_DOS_AMBITOS, IDENTIDAD, DECLARACION, LEIDO_SIN_SERVIDOR, PARAMETROS
            )
        )
    ],
    [("remove_static_lease", "AA:BB:CC:DD:EE:FF")],
    "la que cae en la red del ámbito declarado se respeta, y la que cae en la otra se "
    "quita: el ámbito se decide por dónde cae la dirección cuando la concesión no lo dice",
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
# 4. El choque de addresses: el intercambio va DENTRO del router, en un guion
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
LEIDO_CON_CHOQUE["areas"]["addresses"] = {
    "estaticas": [],
    "dinamicas": [{"interface": "ether1", "address": "10.40.0.11/24"}],
}
LEIDO_CON_CHOQUE["areas"]["dhcp_client"] = {
    "habilitado": True, "interface": "ether1", "ids": {"ether1": "*1"},
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
    "prestada se quedó sin respuesta en el CHR del segundo etapa, con el mismo cuerpo que "
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
    "equipo sin túnel un instante, y quien prueba el efecto es la relectura",
)
igual(
    GUIONES[0].get("address") if GUIONES else "x", None,
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
    sorted({l["area"] for l in LLAMADAS_CHOQUE[_POS_GUION + 1:]}), ["identity"],
    "y detrás del guion sólo queda la identity: es la ÚLTIMA escritura que puede dejar al "
    "equipo sin túnel, así que lo que se pueda dar hecho antes, hecho está",
)
igual(
    [l for l in LLAMADAS_CHOQUE if "www" in str(l["cuerpo"])], [],
    "en ningún momento se toca `www`: es el REST, o sea el túnel de vuelta",
)
igual(
    [l.get("address") for l in LLAMADAS_CHOQUE
     if l["ruta"] == "/ip/address/add" and l["cuerpo"].get("address") == "10.40.1.1/24"],
    [None],
    "la otra interfaz del router (ether2) se pone por fuera y por la dirección declarada: del "
    "intercambio sólo se ocupa la boca por la que entra la convergencia",
)

# El RESIDUO: el cliente ya no está, pero la entrada dinámica que dejó sigue puesta (RouterOS
# no la borra al irse el cliente, medido). Aquí no hay cliente que quitar: lo que hay que
# soltar es la entrada, y por eso el guion la suelta y espera antes de poner la estática.
LEIDO_CON_RESIDUO = dict(LEIDO_CON_CHOQUE)
LEIDO_CON_RESIDUO["areas"] = dict(LEIDO_CON_CHOQUE["areas"])
LEIDO_CON_RESIDUO["areas"]["dhcp_client"] = {"habilitado": False}
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


# ---------------------------------------------------------------------------
# 5. La SALIDA del lab: un router que declara `uplink`
# ---------------------------------------------------------------------------
# Un router con `uplink` es la pasarela del lab hacia fuera. Su interfaz de fuera la añade el
# PLAN (una más, sobre el bridge del nodo que tiene salida), y el número y la vía de acceso los
# DERIVA el motor del estado: el lab declara la salida, no la red de casa. Aquí se prueba la
# mitad del driver: que la interfaz y la numeración se derivan, que lo que falta se pide, que
# lo que está no se vuelve a pedir, y que la dirección/ruta de fuera NO se confunden con los
# residuos de fábrica (si se confundieran, el lab se quedaría sin salida en la primera pasada
# y la segunda pediría un reinicio del router: la idempotencia se rompe justo por ahí).
print("\nLA SALIDA DEL LAB: dirección derivada, masquerade y resolutor\n")

BORDE_SALIDA = copy.deepcopy(BORDE)
BORDE_SALIDA["config"]["routeros"]["uplink"] = {}
# Y NO declara ruta por defecto: la pone el motor por la pasarela de fuera. Declararla además
# son dos compitiendo por el mismo destino (para eso está el consejo `exterior-con-ruta`), y
# obligaría al lab a saberse la pasarela de la red de casa -- justo lo que `uplink` evita.
BORDE_SALIDA["config"]["routeros"].pop("routes", None)
igual(
    motor.interfaz_exterior(BORDE_SALIDA), "ether3",
    "la interfaz de fuera se DERIVA: es la siguiente a las dos que declaró (el lab no la "
    "nombra, porque no está entre sus interfaces y la validación la rechazaría)",
)
igual(motor.interfaz_exterior(BORDE), "", "un router sin `uplink` no tiene interfaz de fuera")

# Y la NUMERACIÓN también se deriva del estado: la vía de acceso es la dirección del bridge por el
# que sale el nodo, y la dirección del invitado se cuenta por ARRIBA entre las libres (así no
# cae dentro de un pool que reparta un router del lab). Sin nada declarado en el lab.
ESTADO_SALIDA = {
    "bridges_direcciones": {"vmbr1": "192.0.2.1/24"},
    "direcciones_usadas": ["192.0.2.252"],
}
PARAMETROS_SALIDA = {
    **PARAMETROS,
    **motor.salida_derivada(ESTADO_SALIDA, {**PARAMETROS, "bridge_gestion": "vmbr1"}),
}
igual(
    {clave: PARAMETROS_SALIDA[clave] for clave in ("salida_acceso", "salida_direccion")},
    {"salida_acceso": "192.0.2.1", "salida_direccion": "192.0.2.254/24"},
    "la vía de acceso es la dirección del bridge y la dirección es la libre de más arriba: las dos "
    "DERIVADAS del estado, ninguna declarada por el lab",
)
igual(
    motor.salida_derivada(
        {"bridges_direcciones": {"vmbr1": "192.0.2.1/24"},
         "direcciones_usadas": ["192.0.2.254/24"]},
        {**PARAMETROS, "bridge_gestion": "vmbr1"},
    )["salida_direccion"],
    "192.0.2.253/24",
    "y la que ya está en uso se esquiva: cuenta hacia abajo hasta la primera libre",
)

# a) La interfaz de fuera recién tendida: no tiene dirección, ni ruta por defecto, ni NAT, ni
#    resolutor. Sólo las dos interfaces del lab tienen dirección.
CRUDO_SALIDA = copy.deepcopy(CRUDO_RECIEN_NACIDO)
CRUDO_SALIDA["/ip/address"] = respuesta([
    {".id": "*1", "address": "10.40.0.1/24", "interface": "ether1", "dynamic": "false"},
    {".id": "*2", "address": "10.40.1.1/24", "interface": "ether2", "dynamic": "false"},
])
CRUDO_SALIDA["/ip/route"] = respuesta([
    {".id": "*1", "dst-address": "10.40.0.0/24", "gateway": "ether1", "dynamic": "true",
     "connect": "true", "active": "true"},
])
CRUDO_SALIDA["/ip/firewall/nat"] = respuesta([])
CRUDO_SALIDA["/ip/dns"] = respuesta({"allow-remote-requests": "false", "servers": ""})
LEIDO_SALIDA = motor.leido_routeros(CRUDO_SALIDA, BORDE_SALIDA, "admin", CLAVE_PUBLICA, "motor")
igual(
    {clave: LEIDO_SALIDA["areas"]["uplink"][clave]
     for clave in ("interface", "address", "por_defecto", "masquerade", "resolutor")},
    {"interface": "ether3", "address": "", "por_defecto": "", "masquerade": False,
     "resolutor": False},
    "se lee que a la interfaz de fuera le falta todo (y la interfaz, derivada, es ether3)",
)
OPERACIONES_SALIDA = motor.operaciones_de_pasos(
    motor.pasos_de_convergencia(
        BORDE_SALIDA, IDENTIDAD, DECLARACION, LEIDO_SALIDA, PARAMETROS_SALIDA
    )
)
DE_FUERA = [op for op in OPERACIONES_SALIDA if op.get("area") == "uplink"]
igual(
    [(op["op"], op.get("address") or op.get("gateway") or op.get("servidores")) for op in DE_FUERA],
    [
        ("add_address", "192.0.2.254/24"),
        ("add_route", "192.0.2.1"),
        ("add_masquerade", None),
        ("enable_dns_resolver", ["192.0.2.1"]),
    ],
    "y se decide lo mínimo: numerar la interfaz (con la dirección DERIVADA), mandar lo que no es "
    "suyo por la pasarela de fuera, traducir lo que sale y encender el resolutor apuntando a esa "
    "misma vía de acceso",
)
LLAMADAS_SALIDA = motor.escrituras_routeros(
    OPERACIONES_SALIDA, BORDE_SALIDA, DECLARACION, IDENTIDAD, PARAMETROS_ROUTEROS, LEIDO_SALIDA
)
igual(
    [(l["metodo"], l["ruta"], l["cuerpo"]) for l in LLAMADAS_SALIDA
     if l.get("area") == "uplink"],
    [
        ("POST", "/ip/address/add",
         {"address": "192.0.2.254/24", "interface": "ether3"}),
        ("POST", "/ip/route/add",
         {"dst-address": "0.0.0.0/0", "gateway": "192.0.2.1"}),
        ("POST", "/ip/firewall/nat/add",
         {"chain": "srcnat", "out-interface": "ether3", "action": "masquerade",
          "comment": motor.MARCA_EXTERIOR}),
        ("POST", "/ip/dns/set", {"allow-remote-requests": "yes", "servers": "192.0.2.1"}),
    ],
    "y se escribe por la vía de acceso del REST: dirección, ruta por defecto por la pasarela de fuera, "
    "masquerade y resolutor apuntando a esa pasarela -- el motor no necesita conocer ninguna "
    "dirección de casa porque las DERIVA del estado",
)
comprobar(
    all("www" not in str(l.get("cuerpo")) for l in LLAMADAS_SALIDA),
    "y por la interfaz de fuera tampoco se toca `www`: es donde vive REST, o sea la vuelta",
)

# b) Al día: la dirección derivada está puesta, la ruta por defecto está, la regla está, el
#    resolutor está apuntando a la vía de acceso. CERO pasos.
AL_DIA_SALIDA = copy.deepcopy(SIN_RESIDUO)
AL_DIA_SALIDA["/ip/address"] = respuesta([
    {".id": "*3", "address": "192.0.2.254/24", "interface": "ether3", "dynamic": "false"},
])
AL_DIA_SALIDA["/ip/firewall/nat"] = respuesta([
    {".id": "*2", "chain": "srcnat", "action": "masquerade", "out-interface": "ether3",
     "comment": motor.MARCA_EXTERIOR},
])
AL_DIA_SALIDA["/ip/dns"] = respuesta({"allow-remote-requests": "true", "servers": "192.0.2.1"})
AL_DIA_SALIDA["/ip/route"] = respuesta([
    {".id": "*1", "dst-address": "10.40.0.0/24", "gateway": "ether1", "dynamic": "true",
     "connect": "true", "active": "true"},
    {".id": "*2", "dst-address": "0.0.0.0/0", "gateway": "192.0.2.1", "dynamic": "false",
     "active": "true"},
])
LEIDO_AL_DIA_SALIDA = motor.leido_routeros(
    AL_DIA_SALIDA, BORDE_SALIDA, "admin", CLAVE_PUBLICA, "motor"
)
igual(
    {clave: LEIDO_AL_DIA_SALIDA["areas"]["uplink"][clave]
     for clave in ("address", "por_defecto", "masquerade", "resolutor", "servidores")},
    {"address": "192.0.2.254/24", "por_defecto": "192.0.2.1", "masquerade": True,
     "resolutor": True, "servidores": "192.0.2.1"},
    "se lee la dirección, la ruta y el resolutor tal cual están: la salida no se supone, "
    "se comprueba",
)
igual(
    LEIDO_AL_DIA_SALIDA["areas"]["dhcp_client"]["habilitado"], False,
    "y la interfaz de FUERA no cuenta como cliente de fábrica: el de fábrica es el que coge "
    "dirección en una interfaz DEL LAB, y esta es la salida",
)
OPERACIONES_AL_DIA_SALIDA = motor.operaciones_de_pasos(
    motor.pasos_de_convergencia(
        BORDE_SALIDA, IDENTIDAD, DECLARACION, LEIDO_AL_DIA_SALIDA, PARAMETROS_SALIDA
    )
)
igual(
    [op for op in OPERACIONES_AL_DIA_SALIDA if op.get("area") == "uplink"],
    [],
    "cero operaciones en la salida: ni renumera la interfaz, ni añade otra ruta, ni vuelve a tocar "
    "el NAT o el resolutor (idempotencia por construcción: se compara contra lo que el motor "
    "DERIVA)",
)
# La trampa que se probó al implementarlo: en RouterOS la ruta por defecto de fuera es DINÁMICA,
# que es exactamente la forma del residuo del cliente de fábrica. Si contara como residuo, este
# router pediría un reinicio en CADA pasada.
igual(
    [op for op in OPERACIONES_AL_DIA_SALIDA
     if "reinicio" in str(op.get("parametros") or {})],
    [],
    "y una ruta por defecto que no declaró el lab no se toma por un residuo del cliente de "
    "fábrica: en un router que es la salida es justo lo que tiene que haber",
)
# Y la pelea que se vio de verdad al aplicarlo: el área `addresses` quitaba la dirección
# que el área `uplink` acababa de poner (regla 17: "lo no declarado, fuera"), y `rutas`
# hacía lo propio con la ruta por defecto. La interfaz de fuera no es una interfaz del lab.
igual(
    LEIDO_AL_DIA_SALIDA["areas"]["addresses"]["estaticas"], [],
    "la dirección de la interfaz de fuera NO se lee como una dirección del lab: si se leyera, "
    "esta área la quitaría en cada pasada",
)
igual(
    LEIDO_AL_DIA_SALIDA["areas"]["routes"]["estaticas"], [],
    "ni la ruta por defecto se lee como una ruta declarada del lab: la manda `uplink`",
)

# c) La pasada que se vio de verdad: la interfaz con DOS direcciones (una por pasada, cuando el
#    motor la renumeraba). Se adopta la primera y se quita la otra: una sola, y estable.
DOS_SALIDA = copy.deepcopy(AL_DIA_SALIDA)
DOS_SALIDA["/ip/address"] = respuesta([
    {".id": "*5", "address": "192.0.2.250/24", "interface": "ether3", "dynamic": "false"},
    {".id": "*6", "address": "192.0.2.253/24", "interface": "ether3", "dynamic": "false"},
])
LEIDO_DOS_SALIDA = motor.leido_routeros(DOS_SALIDA, BORDE_SALIDA, "admin", CLAVE_PUBLICA, "motor")
igual(
    {clave: LEIDO_DOS_SALIDA["areas"]["uplink"][clave]
     for clave in ("address", "de_la_red", "todas")},
    {"address": "192.0.2.250/24", "de_la_red": "192.0.2.250",
     "todas": ["192.0.2.250/24", "192.0.2.253/24"]},
    "se leen TODAS las de la interfaz, con su `.id` (es lo único con lo que se puede quitar una)",
)
OPERACIONES_DOS = [
    op for op in motor.operaciones_de_pasos(
        motor.pasos_de_convergencia(
            BORDE_SALIDA, IDENTIDAD, DECLARACION, LEIDO_DOS_SALIDA, PARAMETROS_SALIDA
        )
    ) if op.get("area") == "uplink"
]
igual(
    [(op["op"], op.get("address"), op.get("id")) for op in OPERACIONES_DOS],
    [("remove_address", "192.0.2.253/24", "*6")],
    "y la que sobra se quita, con su identificador: la interfaz se queda con UNA -- la que ya "
    "tenía -- en vez de ir dejando una nueva por pasada",
)

print("\n" + "=" * 62)
if FALLOS:
    print(f"RESULTADO: {len(FALLOS)} fallo(s).")
    sys.exit(1)
print("RESULTADO: todos los casos en verde")
