#!/usr/bin/env python3
# PROPÓSITO:   probar el VALIDADOR de la declaración sin Ansible ni Proxmox: el caso
#              válido es un lab de verdad del repo, y cada prueba rompe ese caso en
#              un sitio para exigir que el validador lo cace y lo diga. Un validador
#              que no se ha visto fallar no es un validador.
# INVARIANTES: ninguna prueba toca la API ni escribe nada. Todas parten de una copia
#              del lab de aceptación (`labs/04_lab-red-routeros`), así que si el lab de
#              aceptación deja de ser coherente, esta batería lo dice en su primera
#              línea en vez de esconderlo.
# LÍMITES:     prueba la coherencia INTERNA de una declaración; NO prueba que la API
#              acepte lo declarado (eso lo dice `plan`/`apply`) ni la disjunción de
#              vmids entre labs (necesita credenciales).
# VER:         labs/04_lab-red-routeros/04_lab-red-routeros.yml; AGENTS.md §Reglas duras;
#              deployment_engine/filter_plugins/declaracion.py

import copy
import os
import sys

import yaml

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(RAIZ, "deployment_engine", "filter_plugins"))

import declaracion as modulo  # noqa: E402

RUTA_LAB = os.path.join(RAIZ, "labs", "04_lab-red-routeros", "04_lab-red-routeros.yml")
CARPETA = "04_lab-red-routeros"

FALLOS = []


def comprobar(condicion, texto):
    if condicion:
        print(f"  OK    {texto}")
    else:
        FALLOS.append(texto)
        print(f"  FALLA {texto}")


def igual(obtenido, esperado, texto):
    comprobar(obtenido == esperado, f"{texto}  (obtenido {obtenido!r}, esperado {esperado!r})")


def errores_de(mutar):
    """Los errores del lab de aceptación con un cambio aplicado encima."""
    declaracion = copy.deepcopy(BASE)
    mutar(declaracion)
    return modulo.declaracion_validar(declaracion, CARPETA)


def dice(errores, fragmento):
    return any(fragmento in error for error in errores)


# ---------------------------------------------------------------------------

print("\nEL CASO VÁLIDO: EL LAB DE ACEPTACIÓN\n")

with open(RUTA_LAB, encoding="utf-8") as fichero:
    BASE = yaml.safe_load(fichero)

BASICOS = modulo.declaracion_validar(BASE, CARPETA)
comprobar(not BASICOS, f"el lab de aceptación es coherente (si no: {BASICOS})")
igual(
    modulo.declaracion_validar(BASE, CARPETA),
    [],
    "validar dos veces da lo mismo: el validador no depende del orden ni del azar",
)
igual(
    modulo.declaracion_validar(BASE, "lab-dos-redes")[:1] != [],
    True,
    "un nombre que no es el de la carpeta se caza (el pool se llama como la carpeta)",
)
comprobar(
    dice(modulo.declaracion_validar(BASE, "otra-carpeta"), "carpeta"),
    "y el error nombra la carpeta, para que se pueda arreglar sin buscar",
)

# ---------------------------------------------------------------------------

print("\nEL ESPACIO DE DIRECCIONES: DENTRO, NO FUERA\n")

comprobar(modulo._ip_en_address_space("10.40.1.5/24", "10.40.0.0/16"), "10.40.1.5/24 cae en 10.40.0.0/16")
comprobar(modulo._ip_en_address_space("10.40.0.11", "10.40.0.0/16"), "sin máscara también")
comprobar(not modulo._ip_en_address_space("10.41.0.11/24", "10.40.0.0/16"), "10.41.0.11/24 NO cae")
comprobar(
    not modulo._ip_en_address_space("10.40.5.5/24", "10.40.0.0/24"),
    "un /24 dentro de otro: coincidir en los tres primeros octetos no basta",
)
comprobar(
    modulo._ip_en_address_space("10.40.0.11/24", "10.40.0.0/24"), "y sí basta cuando coinciden todos"
)
comprobar(
    modulo._ip_en_address_space("10.40.0.11/24", "10.40.0.0/17"),
    "un prefijo que no cae en un octeto no se vigila (no se opina, no se adivina)",
)

errores = errores_de(lambda d: d["lab"].__setitem__("address_space", "10.50.0.0/16"))
comprobar(dice(errores, "se sale de la espacio de direcciones"), "un lab fuera de su espacio de direcciones se caza")
comprobar(
    len([error for error in errores if "se sale de la espacio de direcciones" in error]) >= 5,
    "y se caza TODO lo que se sale (bridges, direcciones, rangos y pasarelas), no sólo lo primero",
)
errores = errores_de(lambda d: d["lab"].__setitem__("address_space", "10.40.0.0/24"))
comprobar(
    dice(errores, "se sale de la espacio de direcciones"),
    "una espacio de direcciones que no contiene las LANs que el lab sirve se caza igual: es el error contrario",
)

# ---------------------------------------------------------------------------

print("\nLO QUE NO SE DECLARA NUNCA: MACs Y CREDENCIALES\n")

errores = errores_de(lambda d: d["vms"][0].__setitem__("mac", "BC:24:11:00:00:01"))
comprobar(dice(errores, "MAC"), "una MAC en la declaración es un bug (regla 14)")
errores = errores_de(lambda d: d["vms"][0].__setitem__("mac", "aa-bb-cc-dd-ee-ff"))
comprobar(dice(errores, "MAC"), "también si se escribe en otro formato")
errores = errores_de(lambda d: d["vms"][0].__setitem__("password", "hunter2"))
comprobar(dice(errores, "password"), "una contraseña en la declaración es un bug")
errores = errores_de(lambda d: d["lab"].__setitem__("tunnel_clave", "ssh-ed25519 AAAA"))
comprobar(dice(errores, "clave") or dice(errores, "credencial"), "y una clave privada, también")

# ---------------------------------------------------------------------------

print("\nEL VOCABULARIO ES CERRADO\n")

errores = errores_de(lambda d: d["vms"][0]["config"]["routeros"].__setitem__("bridges", {}))
comprobar(
    dice(errores, "bridges") and (dice(errores, "no") or dice(errores, "pendiente")),
    "un área que el motor todavía no converge se RECHAZA con su motivo: aquí no se finge",
)
errores = errores_de(lambda d: d["vms"][0]["config"]["routeros"].__setitem__("inventado", {}))
comprobar(dice(errores, "inventado"), "un área que no existe se caza con su nombre")

# `uplink` existe, pero es una MARCA: la interfaz de fuera y su dirección las deriva el motor.
# Una opción aquí es el lab inventándose una primitiva por la vía de acceso de atrás (regla 15).
errores = errores_de(
    lambda d: d["vms"][0]["config"]["routeros"].__setitem__("uplink", {"interface": "ether3"})
)
comprobar(
    dice(errores, "uplink") and dice(errores, "opciones"),
    "`uplink` con opciones se caza: es una marca (`uplink: {}`), no un sitio donde el "
    "lab nombre interfaces (no las ha declarado, y por eso no son suyas)",
)
errores = errores_de(lambda d: d["containers"][0]["config"]["linux"].__setitem__("docker", {}))
comprobar(dice(errores, "docker"), "y una primitiva que el lab se inventa, también (regla 15)")

errores = errores_de(lambda d: d["containers"][0]["config"].__setitem__("routeros", {}))
comprobar(dice(errores, "tipo"), "un invitado con dos tipos de interior se caza: el tipo elige driver")
errores = errores_de(lambda d: d["vms"][0].__setitem__("config", {}))
comprobar(dice(errores, "config"), "un `config:` vacío no declara nada y se dice")

errores = errores_de(
    lambda d: d["vms"][0]["config"]["routeros"]["ip_services"].__setitem__("deshabilitar", ["www"])
)
comprobar(
    dice(errores, "www") and dice(errores, "túnel de vuelta"),
    "deshabilitar `www` (donde vive REST) se caza: dejaría el equipo sin poder configurarlo nunca",
)

errores = errores_de(
    lambda d: d["vms"][0]["config"]["routeros"]["addresses"].append(
        {"interface": "ether3", "address": "10.40.3.1"}
    )
)
comprobar(dice(errores, "address"), "una dirección sin máscara se caza")
errores = errores_de(
    lambda d: d["vms"][0]["config"]["routeros"]["dhcp_server"][0].__setitem__(
        "static_leases", [{"rol": "servidor", "mac": "BC:24:11:00:00:01"}]
    )
)
comprobar(
    dice(errores, "MAC") or dice(errores, "reserva"),
    "una reserva con MAC se caza: las reservas se derivan del vmid",
)
errores = errores_de(
    lambda d: d["vms"][0]["config"]["routeros"]["dhcp_server"][0].__setitem__("static_leases", "derivada")
)
comprobar(dice(errores, "static_leases"), "`static_leases: derivada` (en singular) tampoco es la forma correcta")

# ---------------------------------------------------------------------------

print("\nEL TIPO DE EQUIPO MANDA SOBRE LAS ÁREAS (ADR 0026)\n")

# Un `rt` que filtra: el router con dos trabajos. `firewall` EXISTE en el vocabulario de
# RouterOS -- lo que se caza no es el área, es a quién le toca.
errores = errores_de(
    lambda d: d["vms"][0]["config"]["routeros"].__setitem__(
        "firewall",
        [
            {"chain": "input", "action": "accept", "src_address": "10.40.0.0/24"},
            {"chain": "input", "action": "drop"},
        ],
    )
)
comprobar(
    dice(errores, "firewall") and dice(errores, "fw") and dice(errores, "responsabilidad"),
    "un `rt` que declara `firewall` se caza: filtrar es la responsabilidad de un equipo `fw`",
)


def _como_fw(declaracion):
    """El MISMO equipo declarado `fw`: fuera lo que no le toca, dentro su tabla."""
    routeros = declaracion["vms"][0]["config"]["routeros"]
    declaracion["vms"][0]["tipo"] = "fw"
    routeros.pop("dhcp_server")  # repartir no es filtrar
    routeros["firewall"] = [
        {"chain": "input", "action": "accept", "src_address": "10.40.0.0/24"},
        {"chain": "input", "action": "drop"},
    ]


# Y la mitad que importa: con el tipo `fw`, la MISMA tabla pasa. Si esto no pasara, la
# regla sería «aquí no se filtra», que no es la regla -- es «filtra quien debe».
igual(
    errores_de(_como_fw),
    [],
    "el mismo equipo declarado `fw`, y sin lo que no le toca, filtra sin una sola queja: "
    "la regla es del TIPO, no del área",
)

# Al revés también: un `fw` que traduce (vía de acceso) o reparte, se caza.
errores = errores_de(
    lambda d: (
        d["vms"][0].__setitem__("tipo", "fw"),
        d["vms"][0]["config"]["routeros"].__setitem__("uplink", {}),
    )
)
comprobar(
    dice(errores, "uplink") and dice(errores, "vía de acceso"),
    "un `fw` con `uplink` se caza: traducir y salir no es filtrar (la vía de acceso es un `rt`)",
)
errores = errores_de(lambda d: d["vms"][0].__setitem__("tipo", "fw"))
comprobar(
    dice(errores, "dhcp_server"),
    "y un `fw` que reparte direcciones, también: repartir no es filtrar",
)

# Y el que cierra el otro eje: conmutar no es enrutar. `vms[0]` ya declara `routes`.
errores = errores_de(lambda d: d["vms"][0].__setitem__("tipo", "sw"))
comprobar(
    dice(errores, "routes") and dice(errores, "enruta"),
    "un `sw` que declara `routes` se caza: conmutar no es enrutar",
)

# Y el agujero que Greptile cazó en la primera revisión de este mismo cambio: la tabla tenía
# `rt`, `fw` y `sw`, y **ningún** tipo más -- así que bastaba declarar la misma tabla de
# filtrado en un `srv` para colarla. El tipo que no está en la tabla no tiene ninguna regla.
igual(
    sorted(modulo.AREAS_QUE_NO_LE_TOCAN),
    sorted(modulo.TIPOS_DE_EQUIPO),
    "los SEIS tipos del vocabulario tienen entrada: un tipo fuera de la tabla es una grieta "
    "por la puerta de al lado",
)


def _con_area(tipo, area, interior="routeros"):
    """El mismo equipo, con otro `tipo` y un área de equipo de red declarada."""
    def mutar(declaracion):
        declaracion["vms"][0]["tipo"] = tipo
        declaracion["vms"][0]["config"][interior][area] = []
    return mutar


# Quien NO es de red no tiene NINGUNA de las cuatro funciones, y `ctl` no se queda fuera.
# (`vms[0]` ya declara `dhcp_server` en el lab de aceptación, así que ese caso sale solo.)
for tipo, area in (
    ("srv", "firewall"), ("srv", "uplink"), ("srv", "dhcp_server"),
    ("ws", "firewall"), ("ws", "routes"), ("ws", "dhcp_server"),
    ("ctl", "firewall"), ("ctl", "uplink"),
):
    comprobar(
        dice(errores_de(_con_area(tipo, area)), "una responsabilidad"),
        f"un `{tipo}` que declara '{area}' con el vocabulario de un equipo de red se caza: "
        "no es un equipo de red",
    )

# Y la precisión que hace falta para no pasarse de frenada: al `ctl` no se le prohíbe
# `dhcp_server` en bloque, sólo con el vocabulario del equipo de red. El bastión REPARTE
# direcciones en la red de gestión con su Linux (ADR 0005), y eso tiene que seguir pasando.
comprobar(
    "dhcp_server" in modulo.AREAS_QUE_NO_LE_TOCAN["ctl"].get("routeros", {})
    and "dhcp_server" not in modulo.AREAS_QUE_NO_LE_TOCAN["ctl"].get("*", {}),
    "la regla del `ctl` está acotada al interior `routeros`: repartir con su Linux es su "
    "trabajo, no una segunda responsabilidad",
)

# ---------------------------------------------------------------------------

print("\nUN INVITADO CON INTERIOR TIENE QUE SER ALCANZABLE\n")

errores = errores_de(lambda d: d["containers"][0].__setitem__("address", None))
comprobar(
    dice(errores, "address"),
    "un invitado con `config:` sin dirección se caza: no se puede converger lo que no se alcanza",
)


# ---------------------------------------------------------------------------

print("\nLAS INTERFACES QUE SE CONFIGURAN TIENEN QUE EXISTIR\n")


def _borde(declaracion):
    return [i for i in declaracion["vms"] if i["rol"] == "borde"][0]


# Un CHR que declara configurar `ether2` necesita DOS interfaces. Sin la segunda, RouterOS
# contesta `400 input does not match any value of interface` A MITAD de la convergencia
# (medido: con la dirección de gestión ya pedida prestada y el equipo a medias), así que
# esto tiene que cazarse ANTES de tocar el VPS.
errores = errores_de(lambda d: _borde(d).__setitem__("bridges", ["vmb_gestion"]))
comprobar(
    dice(errores, "ether2") and dice(errores, "interface"),
    "configurar `ether2` con una sola interfaz declarada se caza: esa interfaz no existiría y "
    "el motor se pararía a mitad de la convergencia",
)

errores = errores_de(lambda d: _borde(d).__setitem__("bridges", ["vmb_gestion", "vmb_lan1"]))
igual(
    [error for error in errores if "ether2" in error], [],
    "con las DOS interfaces declaradas no hay queja: el orden de `bridges` ES la numeración",
)

comprobar(
    dice(
        errores_de(
            lambda d: _borde(d).__setitem__(
                "bridges", ["vmb_gestion", "vmb_que_no_existe"]
            )
        ),
        "vmb_que_no_existe",
    ),
    "y una interfaz que el lab no declara en `lab.bridges` también se caza",
)


# ---------------------------------------------------------------------------

print("\nUN CLIENTE DINÁMICO NO PUEDE PEDIR QUE SE ENTRE EN ÉL\n")


def _control(declaracion):
    return [i for i in declaracion["containers"] if i["rol"] == "control"][0]


# El bastión declara `tunnel`, `dhcp_server`...: áreas que EXIGEN entrar. Con
# `address: dhcp` el motor no sabe a dónde conectar, y no se entra a ciegas (regla 16):
# se caza ANTES de tocar el VPS. Un puesto dinámico declara SÓLO el tipo (`linux: {}`) y
# no pide visita, así que ése sí pasa.
errores = errores_de(lambda d: _control(d).__setitem__("address", "dhcp"))
comprobar(
    dice(errores, "dhcp") and dice(errores, "ENTRAR"),
    "un invitado con áreas que piden entrar y `address: dhcp` se caza: no se sabe a dónde conectar",
)


# ---------------------------------------------------------------------------

print("\nLOS CONSEJOS: LO QUE ES LEGAL PERO CASI SIEMPRE ES UN OLVIDO\n")


def consejos_de(mutar):
    """Los consejos del lab de aceptación con un cambio aplicado encima."""
    declaracion = copy.deepcopy(BASE)
    mutar(declaracion)
    return modulo.declaracion_consejos(declaracion, CARPETA)


def aconseja(consejos, codigo):
    return any(consejo["codigo"] == codigo for consejo in consejos)


def _guest(declaracion, rol):
    for seccion in ("vms", "containers"):
        for guest in declaracion.get(seccion) or []:
            if guest.get("rol") == rol:
                return guest
    raise AssertionError(f"el lab de aceptación ya no tiene el rol '{rol}'")


# El caso limpio: un lab que sigue las convenciones del repo no recibe ni un consejo.
# Es la mitad de la prueba: un consejo que salta siempre no enseña nada, sólo hace ruido.
igual(consejos_de(lambda d: None), [], "el lab de aceptación no tiene nada que aconsejar")

# Y cada consejo tiene que poder SALIR de verdad. Se rompe el lab a propósito, uno por
# uno: un consejo que no se ha visto dispararse no es un consejo, es decoración.
CASOS = [
    (
        "stages",
        lambda d: _guest(d, "servidor").__setitem__("stage", 1),
        "un invitado que pide dirección por DHCP en el MISMO etapa que quien se la da "
        "(arrancarían a la vez: carrera, no diseño)",
    ),
    (
        "dhcp",
        lambda d: _control(d)["config"]["linux"]["addresses"][0].__setitem__(
            "address", "10.40.1.150/24"
        ),
        "una dirección estática dentro del rango que reparte el DHCP (un cliente "
        "dinámico puede pedirla antes)",
    ),
    (
        "gateway",
        lambda d: _guest(d, "nucleo")["config"]["routeros"]["routes"][0].__setitem__(
            "gateway", "10.40.1.99"
        ),
        "una pasarela que cae dentro de la espacio de direcciones del lab y no es de nadie",
    ),
    (
        "image",
        lambda d: _guest(d, "borde").pop("image"),
        "una VM que declara `config` y no declara `image` (nacería sin disco)",
    ),
    (
        "bridge-vacio",
        lambda d: d["lab"]["bridges"].append({"nombre": "vmb_vacio", "address": "10.40.3.1/24"}),
        "un bridge por el que no pasa nadie",
    ),
    (
        "dos-dhcp",
        lambda d: _guest(d, "borde")["config"]["routeros"]["dhcp_server"].append(
            {
                "interface": "ether2",
                "pool": {"rango": "10.40.1.100-10.40.1.200"},
                "network": {"address": "10.40.1.0/24", "gateway": "10.40.1.1"},
            }
        ),
        "dos servidores DHCP en el mismo bridge",
    ),
    (
        "sin-quien-la-dirija",
        lambda d: (
            d["lab"]["bridges"].append({"nombre": "vmb_sola", "address": "10.40.4.1/24"}),
            _guest(d, "servidor").__setitem__("bridge", "vmb_sola"),
        ),
        "una dirección dinámica en un bridge del lab donde no hay quien la dé",
    ),
    (
        "uplink-sin-dns",
        lambda d: (
            _guest(d, "borde")["config"]["routeros"].__setitem__("uplink", {}),
            _guest(d, "borde")["config"]["routeros"]["dhcp_server"][0]["network"].pop("dns"),
            _guest(d, "nucleo")["config"]["routeros"]["dhcp_server"][0]["network"].pop("dns"),
        ),
        "un router que es la SALIDA del lab y ningún servidor DHCP que anuncie DNS: "
        "sale a internet y no resuelve un solo nombre",
    ),
    (
        "uplink-con-ruta",
        lambda d: _guest(d, "borde")["config"]["routeros"].__setitem__("uplink", {}),
        "un router que es la salida del lab y además le declaran ruta por defecto: su "
        "la que pone el motor por la pasarela de fuera y la tuya compiten por el mismo destino",
    ),
]

for codigo, mutar, texto in CASOS:
    declaracion = copy.deepcopy(BASE)
    mutar(declaracion)
    consejos = modulo.declaracion_consejos(declaracion, CARPETA)
    comprobar(
        aconseja(consejos, codigo),
        f"el consejo '{codigo}' sale: {texto}",
    )
    # Un consejo es un consejo: el lab mutado sigue siendo COHERENTE (el validador no
    # tiene nada que decirle) y por tanto el plan sale igual. Si esto fallara, el caso
    # no estaría probando un consejo sino un error.
    comprobar(
        not modulo.declaracion_validar(declaracion, CARPETA),
        f"y con el consejo '{codigo}' la declaración sigue siendo coherente: no bloquea",
    )
    # El consejo trae las tres cosas: dónde, qué pasa y qué escribir.
    completo = all(c["donde"] and c["mensaje"] and c["remedio"] for c in consejos)
    comprobar(completo, f"el consejo '{codigo}' dice dónde, qué pasa y qué escribir")

# Ningún consejo puede salir con un código que no esté declarado: un código suelto es
# un consejo que nadie documenta ni prueba.
sueltos = {
    c["codigo"]
    for _, mutar, _ in CASOS
    for c in consejos_de(mutar)
    if c["codigo"] not in modulo.CONSEJOS_CONOCIDOS
}
igual(sueltos, set(), "todos los códigos de consejo están en CONSEJOS_CONOCIDOS")


# ---------------------------------------------------------------------------

print("\nEL CORTAFUEGOS: forma cerrada, y la guarda que evita el tiro en el pie\n")


def con_reglas(reglas):
    """El lab de aceptación con una tabla de filtrado en su PRIMER CHR.

    El CHR se declara `fw` y se le quita el servidor DHCP, porque esta batería prueba la
    FORMA de la tabla y la guarda de supervivencia -- no a quién le toca filtrar, que es lo
    que prueba la sección «EL TIPO DE EQUIPO MANDA SOBRE LAS ÁREAS» (ADR 0026). Sin el
    tipo, cada prueba de aquí saldría además con el motivo del tipo y no se leería nada.
    """
    def mutar(d):
        d["vms"][0]["tipo"] = "fw"
        d["vms"][0]["config"]["routeros"].pop("dhcp_server", None)
        d["vms"][0]["config"]["routeros"]["firewall"] = reglas
    return mutar


igual(
    errores_de(con_reglas([
        {"chain": "input", "action": "accept", "src_address": "10.40.0.0/24"},
        {"chain": "input", "action": "drop"},
        {"chain": "forward", "action": "accept", "connection_state": "established,related"},
    ])),
    [],
    "una tabla de filtrado bien formada pasa: el `accept` de ENTRADA va antes del `drop`",
)
comprobar(
    dice(errores_de(con_reglas([{"chain": "input", "action": "accept", "inventado": 1}])),
         "no están en el vocabulario"),
    "un campo que no está en el vocabulario se caza, y se dice cuáles hay",
)
comprobar(
    dice(errores_de(con_reglas([{"chain": "adelante", "action": "accept"}])), "chain"),
    "una cadena que no es input/forward/output se caza",
)
comprobar(
    dice(errores_de(con_reglas([{"chain": "input", "action": "borrar"}])), "action"),
    "una acción que no es accept/drop/reject se caza",
)
comprobar(
    dice(errores_de(lambda d: d["vms"][0]["config"]["routeros"].__setitem__(
        "firewall", {"chain": "input", "action": "accept"})), "LISTA"),
    "`firewall` tiene que ser una LISTA: el orden es la semántica, y un mapa no lo guarda",
)
comprobar(
    dice(errores_de(con_reglas([{"chain": "input", "action": "drop"}])), "cierra la entrada"),
    "un `drop` de ENTRADA sin un `accept` de entrada ANTES se caza: el motor entra por el "
    "túnel y se quedaría fuera de su propio equipo (habría que ir por consola)",
)
igual(
    errores_de(con_reglas([
        {"chain": "input", "action": "accept", "src_address": "10.40.0.0/24"},
        {"chain": "input", "action": "drop"},
    ])),
    [],
    "y con el `accept` de entrada delante, el `drop` general pasa: la excepción es obligatoria",
)

print("\n6.4 · SE MIDE DONDE SE PISA\n")


def con_captura_en(puente):
    """El lab de aceptación con una captura pedida en `puente` (que se añade si no está)."""
    def mutar(d):
        d["capture"] = {"bridge": puente, "filtro": "icmp", "segundos": 15}
        if puente not in [b["nombre"] for b in d["lab"]["bridges"]]:
            d["lab"]["bridges"].append({"nombre": puente, "address": "10.40.9.1/24"})
    return mutar


# El bastión NO pisa todos los bridges del lab (su dotación es el de gestión más los que
# declara en `bridges:`), y una captura pedida donde no tiene pata se puede declarar pero
# no se puede montar. Se caza al LEER, no al ejecutar el verbo con el lab desplegado.
comprobar(
    dice(errores_de(con_captura_en("vmb_sin_pata")), "no tiene una interfaz ahí"),
    "6.4 · una captura en un bridge del lab donde el bastión NO tiene pata se caza al leer la declaración",
)

# ---------------------------------------------------------------------------

print("\nEL ÁREA `servicio`: VOCABULARIO CERRADO (ADR 0027)\n")

# El único miembro del vocabulario hoy (`caddy`) pasa: el motor sabe instalarlo y servirlo.
igual(
    errores_de(lambda d: d["containers"][0]["config"]["linux"].__setitem__("servicio", "caddy")),
    [],
    "`servicio: caddy` es vocabulario del motor y pasa sin una queja",
)
# Un servicio que el motor NO sabe instalar se RECHAZA con su nombre y los que hay, en vez de
# aceptarse y no hacer nada con él. El vocabulario es cerrado (regla 15, ADR 0027).
comprobar(
    dice(errores_de(lambda d: d["containers"][0]["config"]["linux"].__setitem__("servicio", "nginx")), "nginx")
    and dice(
        errores_de(lambda d: d["containers"][0]["config"]["linux"].__setitem__("servicio", "nginx")),
        "caddy",
    ),
    "un servicio que no está en el vocabulario cerrado se caza con su nombre y con los que hay",
)
# Y una forma que no es un nombre no cuela: `servicio` es un NOMBRE (una cadena), no un mapa.
comprobar(
    dice(
        errores_de(
            lambda d: d["containers"][0]["config"]["linux"].__setitem__(
                "servicio", {"nombre": "caddy"}
            )
        ),
        "servicio",
    ),
    "un `servicio` que no es un nombre (un mapa) se caza: no se acepta una forma a medias",
)
# Y una clave PRESENTE pero VACÍA tampoco pasa en silencio (hallazgo del revisor): `servicio:`
# sin nada declara el área, y tomarla por «no declarada» dejaba al motor sin hacer nada y sin
# decir nada. Un valor vacío no está en el vocabulario cerrado, así que se caza con su motivo.
comprobar(
    dice(
        errores_de(lambda d: d["containers"][0]["config"]["linux"].__setitem__("servicio", None)),
        "servicio",
    ),
    "un `servicio:` SIN valor se caza: declarar el área y no decir qué servicio no puede pasar en silencio",
)
comprobar(
    dice(
        errores_de(lambda d: d["containers"][0]["config"]["linux"].__setitem__("servicio", "  ")),
        "servicio",
    ),
    "un `servicio` en blanco se caza igual: el espacio no es un nombre del vocabulario",
)

if FALLOS:
    print(f"\nRESULTADO: {len(FALLOS)} fallo(s).")
    sys.exit(1)
print("\nRESULTADO: el validador caza lo que tiene que cazar y deja pasar el lab de aceptación.")
