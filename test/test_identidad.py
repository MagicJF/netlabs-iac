#!/usr/bin/env python3
# PROPÓSITO:   probar el ASIGNADOR DE IDENTIDAD sin Proxmox y sin Ansible. El "estado
#              del mundo" es un fixture escrito a mano: por eso la función pura se
#              puede probar, y por eso se pueden demostrar propiedades que con un
#              Proxmox real dependerían de la suerte del clúster.
# INVARIANTES: cada caso tiene que poder FALLAR de verdad. El caso 4 es un fixture
#              que DEBE ser rechazado: si el validador lo acepta, el test falla.
# LÍMITES:     no prueba nada contra la API real (eso exige credenciales) y no prueba
#              el orden del plan: sólo la identidad y la comparación por conjuntos.
# VER:         README.md §Identidad; AGENTS.md §Identidad
#
# Uso:  python3 test/test_identidad.py     (código de salida != 0 si algo falla)

import json
import os
import sys

import yaml

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURES = os.path.join(RAIZ, "test", "fixtures")
sys.path.insert(0, os.path.join(RAIZ, "deployment_engine", "filter_plugins"))
sys.path.insert(0, os.path.join(RAIZ, "deployment_engine", "tools"))

import declaracion as modulo_declaracion  # noqa: E402
import estado as modulo_estado  # noqa: E402
import identidad as modulo_identidad  # noqa: E402

# Los mismos valores que los defaults del motor: el test no inventa un entorno, usa
# el del repositorio.
PLANTILLA_DESCRIPCION = "lab={lab} rol={rol} gestionado por netlabs_v4_b"
# El nombre dice QUÉ ES, no de qué lab es (ADR 0015): el tipo de equipo y el alias (o el
# rol, si el lab no declara uno). Es la plantilla del motor, copiada a propósito.
PLANTILLA_NOMBRE = "{equipo}-{alias}"
PREFIJO_MAC = "BC:24:11"
VMID_MINIMO = 100
VMID_MAXIMO = 999999

FALLOS = []


def comprobar(condicion, descripcion):
    if condicion:
        print(f"  ok    {descripcion}")
    else:
        print(f"  FALLA {descripcion}")
        FALLOS.append(descripcion)


def fixture_json(nombre):
    with open(os.path.join(FIXTURES, nombre), encoding="utf-8") as fichero:
        return json.load(fichero)


def fixture_yaml(nombre):
    with open(os.path.join(FIXTURES, nombre), encoding="utf-8") as fichero:
        return yaml.safe_load(fichero)


def asignar(declaracion_fichero, estado, maximo=VMID_MAXIMO, carpeta=None):
    cruda = fixture_yaml(declaracion_fichero)
    normalizada = modulo_declaracion.declaracion_normalizar(cruda, carpeta=carpeta)
    return modulo_identidad.identidad_asignar(
        normalizada, estado, PLANTILLA_DESCRIPCION, PLANTILLA_NOMBRE, PREFIJO_MAC, VMID_MINIMO, maximo
    )


def caso_1_dos_labs_disjuntos():
    print("\ncaso 1 — dos labs distintos reciben identidades DISJUNTAS")
    # El mundo se RE-LEE en cada ejecución: por eso la disjunción se demuestra en
    # secuencia, no de golpe. Alfa se despliega contra un clúster vacío; beta se
    # despliega contra el clúster en el que alfa ya está. Si el asignador guardara
    # una lista propia o usara una banda fija por lab, esto se rompería.
    vacio = fixture_json("cluster-vacio.json")
    alfa = asignar("declaracion-alfa.yml", vacio)
    comprobar(not alfa["errores"], "el asignador no da errores para alfa")

    con_alfa = fixture_json("cluster-vacio.json")
    con_alfa["pools"]["lab_alfa"] = {"comment": "alfa"}
    con_alfa["vmids_usados"] = sorted(alfa["mapa_rol_vmid"].values())
    for guest in alfa["guests"]:
        # `pool` es lo que ata el invitado a su lab; el estado real siempre lo trae.
        con_alfa["guests"][str(guest["vmid"])] = {**guest, "pool": "lab_alfa"}

    beta = asignar("declaracion-beta.yml", con_alfa)
    comprobar(not beta["errores"], "el asignador no da errores para beta")
    vmids_alfa = set(alfa["mapa_rol_vmid"].values())
    vmids_beta = set(beta["mapa_rol_vmid"].values())
    comprobar(
        vmids_alfa & vmids_beta == set(),
        f"los vmids no se solapan ({sorted(vmids_alfa)} vs {sorted(vmids_beta)})",
    )
    comprobar(
        min(vmids_beta) > max(vmids_alfa),
        "beta empieza a asignar por encima del mayor vmid que usó alfa",
    )
    nombres_alfa = {i["nombre"] for i in alfa["guests"]}
    nombres_beta = {i["nombre"] for i in beta["guests"]}
    # DESDE EL ADR 0015 los nombres SÍ pueden coincidir: dicen qué es el equipo, no de qué
    # lab es. Los dos labs tienen un `nucleo` de tipo `rt`, así que los dos se llaman
    # `rt-nucleo` -- y no pasa nada, porque lo que dice de quién es cada uno es el pool y
    # la descripción (`lab=… rol=…`), que sí son disjuntos.
    comprobar(
        "rt-nucleo" in nombres_alfa and "rt-nucleo" in nombres_beta,
        "el nombre canónico es <tipo>-<alias>, y se repite entre labs a propósito",
    )
    descripciones_alfa = {i["descripcion"] for i in alfa["guests"]}
    descripciones_beta = {i["descripcion"] for i in beta["guests"]}
    comprobar(
        descripciones_alfa & descripciones_beta == set(),
        "lo que NO se repite es la descripción: `lab=…` dice de quién es cada invitado",
    )
    comprobar(
        modulo_identidad.identidad_mac(100, PREFIJO_MAC) == "BC:24:11:00:00:64",
        "la MAC es función pura del vmid (100 -> BC:24:11:00:00:64)",
    )
    # Un invitado del interior tiene VARIAS interfaces (una por bridge más la de gestión), y
    # cada una lleva su MAC derivada: la 0 es exactamente la de siempre, para que los
    # invitados de una sola interfaz no cambien ni un bit.
    comprobar(
        modulo_identidad.identidad_mac_de_interface(100, 0, PREFIJO_MAC)
        == modulo_identidad.identidad_mac(100, PREFIJO_MAC)
        == "BC:24:11:00:00:64",
        "la interfaz 0 de un invitado conserva la MAC de siempre",
    )
    macs_interfaces = [modulo_identidad.identidad_mac_de_interface(100, i, PREFIJO_MAC) for i in range(4)]
    comprobar(len(set(macs_interfaces)) == 4, f"cada interfaz tiene su MAC, y ninguna se repite: {macs_interfaces}")
    comprobar(
        all(maca.startswith(PREFIJO_MAC + ":") for maca in macs_interfaces),
        "todas las interfaces salen del mismo prefijo (el OUI del motor)",
    )
    # Y la interfaz 1 de un invitado no puede chocar con la interfaz 0 de otro: los vmids de
    # Proxmox no pasan de 999.999 y las interfaces se separan 2**20.
    comprobar(
        modulo_identidad.identidad_mac_de_interface(100, 1, PREFIJO_MAC)
        != modulo_identidad.identidad_mac(100 + modulo_identidad.ESPACIO_DE_INTERFACES - 1, PREFIJO_MAC),
        "la interfaz 1 no choca con la interfaz 0 del vmid de al lado",
    )
    try:
        modulo_identidad.identidad_mac_de_interface(100, -1, PREFIJO_MAC)
        comprobar(False, "una interfaz negativa es un error, no una MAC inventada")
    except Exception as error:
        comprobar("interfaz negativa" in str(error), "una interfaz negativa se dice, no se deriva")


def caso_2_vmid_ocupado():
    print("\ncaso 2 — un vmid ya ocupado se salta, y sólo se adopta lo del PROPIO pool")
    estado = fixture_json("cluster-con-vecino.json")
    resultado = asignar("declaracion-alfa.yml", estado)
    comprobar(not resultado["errores"], "el asignador no da errores")
    vmids = sorted(resultado["mapa_rol_vmid"].values())
    # 100 y 101 están ocupados por el pool de otro lab, y 500 por un invitado suelto:
    # el primer hueco real es el 102.
    comprobar(vmids == [102, 103, 104], f"usa los tres primeros huecos de verdad: {vmids}")
    comprobar(500 not in vmids, "no reutiliza el vmid 500, que es de otro lab")
    comprobar(101 not in vmids, "no reutiliza el vmid 101, que es de otro pool")

    # Adopción: sólo si el invitado está en el pool DEL LAB. Se le da a alfa un
    # invitado propio (vmid 200) y otro de beta con el MISMO rol declarado.
    estado2 = fixture_json("cluster-vacio.json")
    estado2["pools"] = {"lab_alfa": {}, "lab_beta": {}}
    estado2["guests"] = {
        "200": {
            "vmid": 200,
            "nombre": "alfa-nucleo",
            "tipo": "qemu",
            "descripcion": "lab=alfa rol=nucleo gestionado por netlabs_v4_b",
            "cores": 2, "memory": 512, "bridge": "vmb-alfa",
            "mac": modulo_identidad.identidad_mac(200, PREFIJO_MAC),
            "arrancado": True, "pool": "lab_alfa", "nodo": "pve-simulado",
        },
        "300": {
            "vmid": 300,
            "nombre": "beta-nucleo",
            "tipo": "lxc",
            "descripcion": "lab=beta rol=nucleo gestionado por netlabs_v4_b",
            "cores": 1, "memory": 256, "bridge": "vmb_beta",
            "mac": modulo_identidad.identidad_mac(300, PREFIJO_MAC),
            "arrancado": True, "pool": "lab_beta", "nodo": "pve-simulado",
        },
    }
    resultado2 = asignar("declaracion-alfa.yml", estado2)
    nucleo = [i for i in resultado2["guests"] if i["rol"] == "nucleo"][0]
    comprobar(nucleo["vmid"] == 200, "adopta el invitado propio que ya tiene ese rol (vmid 200)")
    comprobar(nucleo["origen"] == "existente", "y lo marca como existente, no como nuevo")
    comprobar(300 not in resultado2["mapa_rol_vmid"].values(), "NO adopta el invitado homónimo que está en el pool de beta")


def caso_3_cluster_lleno():
    print("\ncaso 3 — clúster lleno: FALLA con un mensaje claro, no reasigna en silencio")
    estado = fixture_json("cluster-sin-hueco.json")
    resultado = asignar("declaracion-alfa.yml", estado, maximo=105)
    comprobar(bool(resultado["errores"]), "el asignador devuelve error")
    mensaje = " ".join(resultado["errores"])
    comprobar("clúster lleno" in mensaje, "el mensaje dice que el clúster está lleno")
    comprobar("105" in mensaje and "100" in mensaje, "el mensaje nombra el rango que se agotó")


def caso_4_declaracion_incoherente():
    print("\ncaso 4 — una declaración incoherente DEBE ser rechazada (fixture negativo)")
    cruda = fixture_yaml("declaracion-incoherente.yml")
    errores = modulo_declaracion.declaracion_validar(cruda, carpeta="otra-carpeta")
    comprobar(len(errores) >= 5, f"el validador da todas las incoherencias de una vez ({len(errores)})")
    texto = " ".join(errores)
    for fragmento, descripcion in (
        ("roles repetidos", "detecta el rol en dos listas"),
        ("vmb-que-no-existe", "detecta el bridge citado que no existe"),
        ("etapa 9", "detecta la etapa no declarado"),
        ("comparten la dirección", "detecta dos roles con la misma dirección"),
        ("vmid", "detecta el vmid declarado a mano"),
        ("carpeta", "detecta que el nombre no coincide con la carpeta"),
        ("no acepta ese nombre de interfaz", "detecta el bridge que Proxmox rechazaría"),
    ):
        comprobar(fragmento in texto, descripcion)
    lanzo = False
    try:
        modulo_declaracion.declaracion_normalizar(cruda, carpeta="otra-carpeta")
    except modulo_declaracion.ErrorMotor:
        lanzo = True
    comprobar(lanzo, "normalizar una declaración incoherente lanza el error del motor")


def caso_5_rol_ya_desplegado_conserva_vmid():
    print("\ncaso 5 — un rol ya desplegado CONSERVA su vmid (si no, apply no sería idempotente)")
    estado = fixture_json("cluster-vacio.json")
    estado["pools"]["lab_alfa"] = {"comment": "alfa"}
    estado["vmids_usados"] = [100]
    estado["guests"] = {
        "100": {
            "vmid": 100,
            "nombre": "alfa-nucleo",
            "tipo": "qemu",
            "descripcion": "lab=alfa rol=nucleo gestionado por netlabs_v4_b",
            "cores": 2,
            "memory": 512,
            "bridge": "vmb_alfa",
            "mac": "BC:24:11:00:00:64",
            "arrancado": True,
            "pool": "lab_alfa",
            "nodo": "pve-simulado",
        }
    }
    resultado = asignar("declaracion-alfa.yml", estado)
    nucleo = [i for i in resultado["guests"] if i["rol"] == "nucleo"][0]
    comprobar(nucleo["vmid"] == 100, "el rol ya desplegado mantiene el vmid 100")
    comprobar(nucleo["origen"] == "existente", "y se marca como existente, no como nuevo")


def caso_6_verificacion_en_los_dos_sentidos():
    print("\ncaso 6 — la verificación mira en los DOS sentidos (sobra algo = fallo)")
    estado = fixture_json("cluster-vacio.json")
    cruda = fixture_yaml("declaracion-alfa.yml")
    normalizada = modulo_declaracion.declaracion_normalizar(cruda)
    identidad = modulo_identidad.identidad_asignar(
        normalizada, estado, PLANTILLA_DESCRIPCION, PLANTILLA_NOMBRE, PREFIJO_MAC, VMID_MINIMO, VMID_MAXIMO
    )
    informe = modulo_estado.estado_verificar(normalizada, estado, identidad)
    comprobar(informe["ok"] is False, "un clúster vacío no verifica")
    comprobar(len(informe["faltan"]) == 3, f"los 3 roles declarados faltan ({len(informe['faltan'])})")

    # Ahora al revés: todo existe... y ADEMÁS sobra un invitado en el pool del lab.
    estado2 = fixture_json("cluster-con-vecino.json")
    estado2["pools"]["lab_alfa"] = {"comment": "alfa"}
    estado2["guests"]["777"] = {
        "vmid": 777,
        "nombre": "copia-a-mano",
        "tipo": "lxc",
        "descripcion": "hecho a mano, sin descripción del motor",
        "cores": 1,
        "memory": 256,
        "bridge": "vmb_alfa",
        "mac": None,
        "arrancado": True,
        "pool": "lab_alfa",
        "nodo": "pve-simulado",
    }
    estado2["vmids_usados"] = sorted(set(estado2["vmids_usados"] + [777]))
    # Los 3 roles de alfa existen y coinciden...
    for rol, vmid in (("nucleo", 100), ("puesto-1", 101), ("puesto-2", 102)):
        estado2["guests"][str(vmid)] = {
            "vmid": vmid,
            "nombre": f"alfa-{rol}",
            "tipo": "qemu" if rol == "nucleo" else "lxc",
            "descripcion": f"lab=alfa rol={rol} gestionado por netlabs_v4_b",
            "cores": 2 if rol == "nucleo" else 1,
            "memory": 512 if rol == "nucleo" else 256,
            "bridge": "vmb_alfa",
            "mac": modulo_identidad.identidad_mac(vmid, PREFIJO_MAC),
            "arrancado": True,
            "pool": "lab_alfa",
            "nodo": "pve-simulado",
        }
    identidad2 = modulo_identidad.identidad_asignar(
        normalizada, estado2, PLANTILLA_DESCRIPCION, PLANTILLA_NOMBRE, PREFIJO_MAC, VMID_MINIMO, VMID_MAXIMO
    )
    informe2 = modulo_estado.estado_verificar(normalizada, estado2, identidad2)
    comprobar(not informe2["faltan"], "ya no falta ningún rol")
    comprobar(len(informe2["sobran"]) == 1, f"y se detecta el que SOBRA ({len(informe2['sobran'])})")
    comprobar(777 == informe2["sobran"][0]["vmid"], "el sobrante es el vmid 777")
    comprobar(not informe2["ok"], "por eso la verificación sigue en rojo")


def caso_7_informe_de_otro_lab():
    print("\ncaso 7 — un invitado con el nombre del rol pero en otro pool se reporta como 'de otro lab'")
    estado = fixture_json("cluster-con-vecino.json")
    cruda = fixture_yaml("declaracion-alfa.yml")
    normalizada = modulo_declaracion.declaracion_normalizar(cruda)
    identidad = modulo_identidad.identidad_asignar(
        normalizada, estado, PLANTILLA_DESCRIPCION, PLANTILLA_NOMBRE, PREFIJO_MAC, VMID_MINIMO, VMID_MAXIMO
    )
    informe = modulo_estado.estado_verificar(normalizada, estado, identidad)
    comprobar(not informe["otros_lab"], "sin invitados ajenos con nuestros nombres, la lista va vacía")
    texto = modulo_estado.estado_informe_texto(informe)
    comprobar("no es verificable por API" in texto, "el informe declara que la dirección IP no es comprobable")


def caso_8_la_frontera_es_el_pool_del_lab():
    print("\ncaso 8 — la frontera de propiedad es el pool DEL LAB (y su nombre lo pone el motor)")
    # Este caso va de punta a punta y es el que faltaba: `cluster_recursos` (la forma
    # CRUDA de /cluster/resources, con el `pool` de cada invitado) -> estado -> identidad.
    # El pool de un lab se llama `lab_<lab>` (prefijo del motor, porque Proxmox exige que
    # un poolid empiece por letra y la carpeta de un lab empieza por su número). Cuando
    # `estado`/`identity` comparaban el pool con el nombre de la CARPETA, ningún invitado
    # propio se reconocía: el plan los veía como de nadie y volvía a crear la topología
    # entera con vmids nuevos en cada pasada.
    estado = modulo_estado.estado_desde_api(
        {
            "lab": "alfa",
            "nodo": "pve-simulado",
            "pools_lista": [
                {"poolid": modulo_identidad.identidad_pool("alfa"), "comment": "alfa"},
                {"poolid": modulo_identidad.identidad_pool("otro-lab"), "comment": "otro"},
            ],
            "red_nodo": [],
            "cluster_recursos": [
                {"vmid": 200, "type": "qemu", "name": "rt-nucleo", "node": "pve-simulado",
                 "status": "running", "pool": modulo_identidad.identidad_pool("alfa")},
                {"vmid": 300, "type": "lxc", "name": "rt-nucleo", "node": "pve-simulado",
                 "status": "running", "pool": modulo_identidad.identidad_pool("otro-lab")},
                {"vmid": 400, "type": "lxc", "name": "suelto", "node": "pve-simulado",
                 "status": "stopped"},
            ],
            "configs": {
                "200": {"name": "rt-nucleo", "cores": 2, "memory": 512,
                        "description": "lab=alfa rol=nucleo gestionado por netlabs_v4_b",
                        "net0": "virtio=BC:24:11:00:00:C8,bridge=vmb_alfa"},
                "300": {"hostname": "rt-nucleo", "cores": 2, "memory": 512,
                        "description": "lab=otro-lab rol=nucleo gestionado por netlabs_v4_b",
                        "net0": "name=eth0,bridge=vmb_otro,hwaddr=BC:24:11:00:01:2C"},
            },
        }
    )
    comprobar("200" in estado["guests"], "el invitado del pool del lab entra como PROPIO")
    comprobar(
        estado["guests"]["200"]["pool"] == modulo_identidad.identidad_pool("alfa"),
        "y guarda el nombre del pool tal cual lo da la API (con el prefijo)",
    )
    # `invitados_otros` va por NOMBRE (es el informe el que lo agrupa así), no por vmid.
    otros_vmids = {i["vmid"] for i in estado["guests_otros"].values()}
    comprobar(200 not in otros_vmids, "el propio no se cuela entre los ajenos")
    comprobar(300 in otros_vmids, "el del pool de otro lab NO se adopta")
    comprobar(400 in otros_vmids, "ni uno sin pool: no es de nadie")

    resultado = asignar("declaracion-alfa.yml", estado)
    nucleo = [i for i in resultado["guests"] if i["rol"] == "nucleo"][0]
    comprobar(nucleo["vmid"] == 200, "y la identidad ADOPTA el invitado propio: conserva su vmid")
    comprobar(nucleo["origen"] == "existente", "lo marca como existente, no como nuevo")
    comprobar(
        300 not in resultado["mapa_rol_vmid"].values(),
        "el homónimo del pool de al lado no se toca",
    )


def main():
    print("=" * 62)
    print("TESTS DEL ASIGNADOR DE IDENTIDAD (fixtures, sin Proxmox)")
    print("=" * 62)
    caso_1_dos_labs_disjuntos()
    caso_2_vmid_ocupado()
    caso_3_cluster_lleno()
    caso_4_declaracion_incoherente()
    caso_5_rol_ya_desplegado_conserva_vmid()
    caso_6_verificacion_en_los_dos_sentidos()
    caso_7_informe_de_otro_lab()
    caso_8_la_frontera_es_el_pool_del_lab()
    print()
    print("=" * 62)
    if FALLOS:
        print(f"RESULTADO: {len(FALLOS)} comprobación(es) en rojo")
        return 1
    print("RESULTADO: todos los casos en verde")
    return 0


# ---------------------------------------------------------------------------
# 6.1 · El IPAM: las direcciones que el lab deja sin escribir (ADR 0020)
# ---------------------------------------------------------------------------

_DECL_DERIVADA = {
    "lab": {
        "nombre": "p0_ipam",
        "address_space": "198.51.0.0/16",
        "bridges": [
            {"nombre": "vmb_gestion", "address": "derived"},
            {"nombre": "vmb_lan", "address": "derived"},
        ],
    },
    "vms": [
        {
            "rol": "rt-1",
            "tipo": "rt",
            "nombre": 1,
            "address": "derived",
            "bridges": ["vmb_gestion", "vmb_lan"],
            "config": {
                "routeros": {
                    "addresses": [{"interface": "ether2", "address": "derived"}],
                    "dhcp_server": [
                        {
                            "interface": "ether2",
                            "pool": {"rango": "derived"},
                            "network": {
                                "address": "derived",
                                "gateway": "derived",
                                "dns": "derived",
                            },
                        }
                    ],
                }
            },
        }
    ],
    "containers": [
        {
            "rol": "control",
            "tipo": "ctl",
            "nombre": 1,
            "address": "derived",
            "bridge": "vmb_gestion",
        }
    ],
}
_resuelto = modulo_identidad.direcciones_resolver(_DECL_DERIVADA)

comprobar(
    _DECL_DERIVADA["lab"]["bridges"][0]["address"] == "derived"
    and _resuelto["lab"]["bridges"][0]["address"] != "derived",
    "el IPAM devuelve una COPIA: la declaración que le llega se queda como estaba",
)
comprobar(
    _resuelto["lab"]["bridges"][0]["address"] == "198.51.0.1/24"
    and _resuelto["lab"]["bridges"][1]["address"] == "198.51.1.1/24",
    "cada bridge deriva la subred /24 siguiente del espacio, y la .1 de esa subred",
)
comprobar(
    _resuelto["vms"][0]["config"]["routeros"]["addresses"][0]["address"] == "198.51.1.1/24",
    "la LAN que sirve el router sale del bridge que le toca por el ORDEN de sus patas (ether2 -> la 2a)",
)
comprobar(
    _resuelto["vms"][0]["config"]["routeros"]["dhcp_server"][0]["pool"]["rango"]
    == "198.51.1.100-198.51.1.200",
    "el rango del DHCP derivado es la .100-.200 de su subred (fuera del reparto de huéspedes fijos)",
)
comprobar(
    _resuelto["vms"][0]["config"]["routeros"]["dhcp_server"][0]["network"]
    == {"address": "198.51.1.0/24", "gateway": "198.51.1.1", "dns": ["198.51.1.1"]},
    "la red del DHCP derivada: su subred, su puerta (la .1 del bridge) y esa puerta como resolutor",
)
comprobar(
    _resuelto["vms"][0]["address"] != _resuelto["containers"][0]["address"],
    "dos invitados derivados en la MISMA subred no se pisan (el reparto es estable)",
)
comprobar(
    modulo_identidad.direcciones_resolver(_resuelto) == _resuelto,
    "el IPAM es IDEMPOTENTE: sin marcas que resolver no cambia nada (la 2a pasada deriva lo mismo)",
)
comprobar(
    modulo_identidad.direcciones_resolver(
        {
            "lab": {
                "nombre": "p0_escape",
                "address_space": "198.51.0.0/16",
                "bridges": [{"nombre": "vmb_uno", "address": "198.51.99.1/24"}],
            },
            "containers": [],
        }
    )["lab"]["bridges"][0]["address"]
    == "198.51.99.1/24",
    "una dirección EXPLÍCITA gana: el IPAM no toca lo que el lab escribe (el escape de la recomendación)",
)
comprobar(
    modulo_identidad.direcciones_resolver(
        {
            "lab": {"nombre": "p0_sin_espacio", "bridges": [{"nombre": "vmb_uno", "address": "derived"}]},
            "containers": [],
        }
    )["lab"]["bridges"][0]["address"]
    == "derived",
    "sin `address_space` NO se deriva nada: se queda en `derived` y lo dice el validador (no se inventa)",
)
comprobar(
    modulo_identidad.direcciones_resolver(
        {
            "lab": {
                "nombre": "p0_estrecho",
                "address_space": "198.51.100.0/24",
                "bridges": [
                    {"nombre": "vmb_uno", "address": "derived"},
                    {"nombre": "vmb_dos", "address": "derived"},
                ],
            },
            "containers": [],
        }
    )["lab"]["bridges"][1]["address"]
    == "derived",
    "un /24 no da para dos bridges: el segundo se queda sin derivar en vez de salirse del espacio",
)


if __name__ == "__main__":
    sys.exit(main())
