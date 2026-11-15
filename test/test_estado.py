#!/usr/bin/env python3
# PROPÓSITO:   probar la función pura que decide «qué direcciones están YA EN USO» en la
#              red del nodo --*(estado, lecturas) → estado*-- sin Proxmox, sin red y sin
#              Ansible. Es la mitad leída de la pregunta que responde `direccion_libre`;
#              la otra mitad está en `test_interior.py`. Y prueba las DOS formas de
#              lectura que existen, porque de eso depende que el motor elija bien la
#              dirección del puesto de control.
# INVARIANTES: los casos que TIENEN que cumplirse, y que son el contrato:
#              1. la lectura de un CONTENEDOR (`GET /lxc/<vmid>/interfaces`) da una LISTA
#                 con `inet`/`inet6`: se cogen las IPv4, con su máscara;
#              2. la lectura de una VM por su AGENTE (`.../qemu/<vmid>/agent/
#                 network-get-interfaces`) viene envuelta en `result` y trae
#                 `ip-addresses` con `ip-address-type`: se cogen las IPv4, y se dejan
#                 IGUAL que las del contenedor (con máscara) para que el dato signifique
#                 lo mismo venga de donde venga;
#              3. las dos formas a la vez se suman, sin duplicar;
#              4. una lectura VACÍA (`{}`) --la puerta TOLERÓ un fallo: al token le falta
#                 `VM.GuestAgent.Audit`, o la VM no nació con agente-- no aporta nada y NO
#                 borra lo que ya había: el motor se queda como estaba, no finge ver;
#              5. una lectura con basura dentro (una lista de cosas que no son diccionarios,
#                 un `None`) no revienta: se ignora lo que no se entiende;
#              6. y el caso que importa: con lo leído dentro, `direccion_libre` YA NO elige
#                 una dirección ocupada. Eso es la razón de existir de todo lo demás.
# LÍMITES:     no prueba la lectura de verdad (eso es el ciclo contra el VPS): las dos
#              formas están escritas A MANO aquí, tomadas de una respuesta REAL del agente
#              de un CHR (labs/05_research/05_research.md) y de un contenedor del nodo.
# VER:         docs/decisiones/0011-el-agente-de-invitado.md;
#              deployment_engine/tasks/direcciones.yml

# Uso:  python3 test/test_estado.py     (código de salida != 0 si algo falla)

import os
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(RAIZ, "deployment_engine", "filter_plugins"))

import estado as motor_estado  # noqa: E402
import interior as motor_interior  # noqa: E402

FALLOS = []


def comprobar(condicion, descripcion):
    print(("  OK   " if condicion else "  FALLA") + f" {descripcion}")
    if not condicion:
        FALLOS.append(descripcion)


# --- Las dos formas de lectura, tal cual llegan por la puerta ------------------------

# Un contenedor: una LISTA de entradas con `name`, `inet` e `inet6` (medido).
CONTENEDOR = [
    {"name": "eth0", "inet": "10.40.0.10/24", "inet6": "fe80::be24:11ff:fe00:0a/64"},
    {"name": "eth1", "inet": "10.40.1.10/24"},
]

# Una VM por su agente: un OBJETO con `result`, y dentro `ip-addresses` (medido en el CHR
# del lab `research`: ether1, su MAC derivada, y las DOS familias, v6 primero).
VM_AGENTE = {
    "result": [
        {
            "name": "ether1",
            "hardware-address": "bc:24:11:00:00:6d",
            "ip-addresses": [
                {"ip-address": "fe80::be24:11ff:fe00:6d", "ip-address-type": "ipv6", "prefix": 64},
                {"ip-address": "10.41.0.11", "ip-address-type": "ipv4", "prefix": 24},
            ],
        }
    ]
}


def direcciones(estado, lecturas):
    return motor_estado.estado_con_direcciones(estado, lecturas)["direcciones_usadas"]


BASE = {"direcciones_usadas": ["10.41.0.1/24", "10.41.0.10/24"]}


def main():
    print("== 1) la lectura de un CONTENEDOR: las IPv4, con su máscara ==")
    usadas = direcciones(BASE, {"101": CONTENEDOR})
    comprobar("10.40.0.10/24" in usadas, "entra la IPv4 de eth0, con máscara")
    comprobar("10.40.1.10/24" in usadas, "entra la de eth1")
    comprobar(not any("fe80" in u for u in usadas), "la IPv6 se queda fuera")

    print("== 2) la lectura de una VM por su AGENTE ==")
    usadas = direcciones(BASE, {"109": VM_AGENTE})
    comprobar("10.41.0.11/24" in usadas, "entra la IPv4 de ether1, con su máscara")
    comprobar(not any("fe80" in u for u in usadas), "la IPv6 del agente también se queda fuera")
    comprobar("10.41.0.1/24" in usadas, "lo que ya estaba en el estado no se pierde")
    comprobar(usadas == sorted(usadas), "la lista sale ordenada")

    print("== 3) las dos formas a la vez: se suman, sin duplicar ==")
    usadas = direcciones(BASE, {"101": CONTENEDOR, "109": VM_AGENTE})
    comprobar({"10.40.0.10/24", "10.40.1.10/24", "10.41.0.11/24"}.issubset(set(usadas)),
              "están las tres direcciones leídas")
    comprobar(len(usadas) == len(set(usadas)), "no hay duplicados")
    usadas_otra_vez = direcciones(BASE, {"101": CONTENEDOR, "109": VM_AGENTE})
    comprobar(usadas == usadas_otra_vez, "es una función pura: misma entrada, misma salida")

    print("== 4) una lectura TOLERADA (vació) no aporta y no borra ==")
    usadas = direcciones(BASE, {"109": {}})
    comprobar(usadas == sorted(BASE["direcciones_usadas"]),
              "un {} (403 tolerado, o VM sin agente) deja el estado como estaba")
    comprobar(not any("None" in u for u in usadas), "no se cuela ninguna dirección inventada")

    print("== 5) basura en la lectura: se ignora, no revienta ==")
    for basura in (None, [], [None, 7, "texto"], {"result": None}, {"result": [{"name": "eth0"}]},
                   [{"ip-addresses": [{"ip-address-type": "ipv4"}]}]):
        try:
            usadas = direcciones(BASE, {"300": basura})
            bien = usadas == sorted(BASE["direcciones_usadas"])
        except Exception as e:  # noqa: BLE001
            bien = f"REVENTÓ: {type(e).__name__}: {e}"
        comprobar(bien is True, f"con {basura!r:.40} no se inventa nada ni falla")

    print("== 6) y el caso que importa: la lectura CAMBIA la elección ==")
    # Sin leer nada, el motor cree que la primera de arriba está libre y la elige.
    libre_a_ciegas = motor_interior.direccion_libre("10.41.0.0/24", BASE["direcciones_usadas"])
    comprobar(libre_a_ciegas == "10.41.0.254", "sin la lectura, se elige la primera de arriba")
    # Y una VM que tiene puesta JUSTO ésa: es el caso que el motor no podía ver.
    vm_arriba = {
        "result": [
            {"name": "ether1", "ip-addresses": [
                {"ip-address": "10.41.0.254", "ip-address-type": "ipv4", "prefix": 24}]}
        ]
    }
    usadas = direcciones(BASE, {"300": vm_arriba})
    libre_leyendo = motor_interior.direccion_libre("10.41.0.0/24", usadas)
    comprobar(libre_leyendo == "10.41.0.253",
              "leyendo al invitado, la .254 (que es de una VM) ya no se elige")

    print()
    if FALLOS:
        print(f"FALLOS: {len(FALLOS)}")
        for f in FALLOS:
            print("  -", f)
        return 1
    print("todo OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
